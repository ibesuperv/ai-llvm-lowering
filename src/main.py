"""AI-LLVM Lowering Pipeline — Main CLI Entry Point.

Provides a command-line interface for:
- compile: Translate a single MiniLang file to LLVM IR
- evaluate: Batch process a directory of tests and generate a report
- demo: Run a quick built-in test case
"""

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

from src.config import load_config
from src.evaluator import Evaluator
from src.llm import ModelRegistry, PromptEngine
from src.parser import Lexer, Parser, ParseError, LexerError
from src.repair import RepairOrchestrator
from src.validator import IRValidator

# Setup Rich console for pretty output
console = Console()

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger("ai_llvm")


@click.group()
def cli():
    """AI-Assisted Lowering from MiniLang to LLVM IR."""
    pass


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option("--model", default="gemini-2.0-flash", help="Model ID to use")
@click.option("--no-cache", is_flag=True, default=False, help="Disable response cache")
def compile(file_path: Path, model: str, no_cache: bool):
    """Compile a single MiniLang file to LLVM IR.

    Validates the generated IR using llvm-as (structural check: SSA form, types,
    CFG) and optionally via lli execution against a .expected output file.
    """
    try:
        source_code = file_path.read_text(encoding="utf-8")

        console.print(Panel(
            Syntax(source_code, "c", theme="monokai", line_numbers=True),
            title=f"[bold cyan]Source: {file_path.name}[/]",
        ))

        # ── 1. Parse ──────────────────────────────────────────────────
        with console.status("[bold cyan]Parsing source code..."):
            tokens = Lexer(source_code, filename=file_path.name).tokenize()
            ast = Parser(tokens).parse()
        console.print(f"[green]✓[/] Parsed — Tier detected: [bold]{ast.tier.name}[/]")

        # ── 2. Load expected output (if present) ─────────────────────
        expected_output = None
        expected_path = file_path.with_suffix(".expected")
        if expected_path.exists():
            expected_output = expected_path.read_text(encoding="utf-8")
            console.print(
                f"[green]✓[/] Expected output loaded from "
                f"[dim]{expected_path.name}[/]: [yellow]{repr(expected_output.strip()[:60])}[/]"
            )
        else:
            console.print(
                f"[dim]ℹ  No .expected file found — skipping output correctness check[/]"
            )

        # ── 3. Setup Pipeline ─────────────────────────────────────────
        config = load_config()
        if no_cache:
            config.no_cache = True
        registry = ModelRegistry(config)
        client = registry.get_client(model)

        if not client:
            console.print(
                f"[bold red]Error:[/] Model [cyan]{model}[/] not found or API key missing.\n"
                f"Available models: {registry.get_model_ids()}"
            )
            sys.exit(1)

        validator = IRValidator(
            llvm_as_path=config.llvm_as_path,
            lli_path=config.lli_path,
        )
        prompt_engine = PromptEngine()
        orchestrator = RepairOrchestrator(config, validator, prompt_engine)

        # ── 4. Generate & Repair ──────────────────────────────────────
        console.print(Rule(f"[bold yellow]Generating via {client.get_model_name()}"))
        with console.status(f"[bold yellow]Calling {client.get_model_name()}..."):
            result = orchestrator.run_task(
                client, source_code, ast, expected_output=expected_output
            )

        # ── 5. Show Repair History ────────────────────────────────────
        if len(result.repair_attempts) > 1:
            console.print(Rule("[dim]Repair History"))
            for attempt in result.repair_attempts:
                is_last = attempt.attempt_number == len(result.repair_attempts) - 1
                status = "✅" if attempt.validation.is_valid else "❌"
                label = (
                    "Initial Generation" if attempt.attempt_number == 0
                    else f"Repair Attempt {attempt.attempt_number}"
                )
                console.print(f"\n{status} [bold]{label}[/]")

                if not attempt.validation.is_valid and attempt.validation.errors:
                    console.print("[red]  llvm-as Errors:[/]")
                    for err in attempt.validation.errors:
                        console.print(
                            f"    [yellow]{err.category.name}[/]: {err.message}"
                        )
                    # Show the invalid IR for analysis
                    if hasattr(attempt.response, "ir_code") and attempt.response.ir_code:
                        console.print(
                            Panel(
                                Syntax(attempt.response.ir_code[:2000], "llvm", theme="monokai"),
                                title=f"[red]Generated IR (Attempt {attempt.attempt_number}) — Invalid[/]",
                                border_style="red",
                            )
                        )

        # ── 6. Final Result ───────────────────────────────────────────
        console.print(Rule("[bold]Result"))

        if result.success:
            console.print("[bold green]✅ PASS — Valid LLVM IR generated![/]")
            console.print(
                f"   [dim]Passed:[/] llvm-as (IR structure) "
                + ("[dim]+[/] lli output check" if expected_output else "")
            )
            console.print(
                Panel(
                    Syntax(result.final_ir, "llvm", theme="monokai", line_numbers=True),
                    title="[green]Final LLVM IR[/]",
                    border_style="green",
                )
            )

            # Save output
            out_path = Path(config.output_dir) / "generated_ir" / f"{file_path.stem}.ll"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(result.final_ir)
            console.print(f"   Saved to: [cyan]{out_path}[/]")

        else:
            console.print("[bold red]❌ FAIL — Could not generate valid IR after all repair attempts.[/]")
            console.print(
                f"   Attempts: {len(result.repair_attempts)} / {config.max_retries + 1}"
            )

            # Show final validation errors in a table
            if result.repair_attempts:
                last = result.repair_attempts[-1]
                if last.validation.errors:
                    table = Table(title="Final Validation Errors", show_lines=True)
                    table.add_column("Category", style="yellow")
                    table.add_column("Line", style="dim")
                    table.add_column("Message")
                    for err in last.validation.errors:
                        table.add_row(
                            err.category.name,
                            str(err.line) if err.line else "—",
                            err.message,
                        )
                    console.print(table)

            console.print(
                Panel(
                    Syntax(result.final_ir or "(no IR generated)", "llvm", theme="monokai"),
                    title="[red]Final IR (Invalid)[/]",
                    border_style="red",
                )
            )
            sys.exit(1)

    except (LexerError, ParseError) as e:
        console.print(f"[bold red]Parse Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Pipeline failed")
        sys.exit(1)


@cli.command()
@click.argument("test_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--no-cache", is_flag=True, default=False, help="Disable response cache")
def evaluate(test_dir: Path, no_cache: bool):
    """Run batch evaluation on a directory of tests.

    Runs every .mini file against all configured LLM models and produces
    a Markdown report with correctness %, repair success rate, and error distribution.
    """
    console.print(f"[bold cyan]Batch evaluation on: {test_dir}[/]")

    config = load_config()
    if no_cache:
        config.no_cache = True

    registry = ModelRegistry(config)

    if not registry.get_all_clients():
        console.print(
            "[bold red]No LLM models available.[/] "
            "Set GEMINI_API_KEY or GROQ_API_KEY in your .env file."
        )
        sys.exit(1)

    validator = IRValidator(
        llvm_as_path=config.llvm_as_path,
        lli_path=config.lli_path,
    )
    prompt_engine = PromptEngine()
    orchestrator = RepairOrchestrator(config, validator, prompt_engine)
    evaluator = Evaluator(config, registry, orchestrator)

    with console.status("[bold magenta]Evaluating (this may take several minutes)..."):
        evaluator.run_evaluation(test_dir)

    console.print("[bold green]Evaluation complete![/] Report saved to results/reports/")


@cli.command()
@click.option("--model", default="gemini-2.0-flash", help="Model ID to use")
def demo(model: str):
    """Run a built-in demo case (recursive factorial).

    Shows the full pipeline: source → parse → LLM generation → llvm-as validation
    → repair loop if needed → final IR output.
    """
    demo_code = """\
fn factorial(n: int): int {
    if (n <= 1) {
        return 1;
    }
    return n * factorial(n - 1);
}

fn main(): int {
    let result: int = factorial(5);
    print(result);
    return 0;
}
"""
    # factorial(5) = 120
    demo_expected = "120\n"

    console.print("[bold cyan]Demo: Recursive Factorial[/]")
    console.print(Panel(
        Syntax(demo_code, "c", theme="monokai", line_numbers=True),
        title="[cyan]MiniLang Source[/]",
    ))
    console.print(f"[dim]Expected output:[/] [yellow]{repr(demo_expected.strip())}[/]")

    try:
        with console.status("[bold cyan]Parsing..."):
            tokens = Lexer(demo_code, filename="demo.mini").tokenize()
            ast = Parser(tokens).parse()
        console.print(f"[green]✓[/] Parsed — Tier: [bold]{ast.tier.name}[/]")

        config = load_config()
        registry = ModelRegistry(config)
        client = registry.get_client(model)

        if not client:
            console.print(
                f"[bold red]Error:[/] Model '{model}' not found or API key missing."
            )
            sys.exit(1)

        validator = IRValidator(
            llvm_as_path=config.llvm_as_path,
            lli_path=config.lli_path,
        )
        prompt_engine = PromptEngine()
        orchestrator = RepairOrchestrator(config, validator, prompt_engine)

        console.print(Rule(f"[bold yellow]Calling {client.get_model_name()}"))
        with console.status(f"[bold yellow]Generating IR..."):
            result = orchestrator.run_task(
                client, demo_code, ast, expected_output=demo_expected
            )

        if result.success:
            console.print("[bold green]✅ PASS — factorial(5) = 120[/]")
            console.print(Panel(
                Syntax(result.final_ir, "llvm", theme="monokai", line_numbers=True),
                title="[green]Generated LLVM IR — Validated by llvm-as + lli[/]",
                border_style="green",
            ))
            out_path = Path(config.output_dir) / "generated_ir" / "demo.ll"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(result.final_ir)
            console.print(f"   Saved to: [cyan]{out_path}[/]")
        else:
            console.print("[bold red]❌ FAIL — LLM could not generate valid IR.[/]")
            if result.repair_attempts:
                last = result.repair_attempts[-1]
                for err in last.validation.errors:
                    console.print(f"  [yellow]{err.category.name}[/]: {err.message}")
                console.print(Panel(
                    Syntax(result.final_ir or "(no IR)", "llvm", theme="monokai"),
                    title="[red]Final IR (Invalid)[/]",
                    border_style="red",
                ))
            sys.exit(1)

    except (LexerError, ParseError) as e:
        console.print(f"[bold red]Parse Error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Demo failed")
        sys.exit(1)


if __name__ == "__main__":
    cli()
