"""Abstract base class for LLM clients with rate limiting and IR extraction.

This module provides:
- LLMResponse: Structured response from any LLM call
- RateLimiter: Sliding-window rate limiter with exponential backoff
- LLMClient: Abstract base class that all providers must implement
- extract_ir_from_response(): Robust LLVM IR extraction from LLM text

Design decisions:
- Synchronous API (not async) — simpler, and we call models sequentially anyway
- Rate limiter is per-client instance, not global — each model has its own RPM limit
- IR extraction tries multiple formats (fenced code, markers, raw IR) for robustness
"""

from __future__ import annotations

import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from src.config import RateLimitConfig

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LLM Response
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class LLMResponse:
    """Structured response from an LLM API call.

    Attributes:
        content: Raw response text from the LLM.
        ir_code: Extracted LLVM IR code (parsed from content).
        model: Model identifier that generated this response.
        temperature: Sampling temperature used for generation.
        prompt_tokens: Number of tokens in the input prompt.
        completion_tokens: Number of tokens in the output.
        duration_ms: Wall-clock time for the API call in milliseconds.
        cached: True if this response was served from the file cache.
        error: Error message if the call failed, None otherwise.
    """
    content: str = ""
    ir_code: str = ""
    model: str = ""
    temperature: float = 0.2
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0.0
    cached: bool = False
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True if the call succeeded and produced IR code."""
        return self.error is None and bool(self.ir_code.strip())

    def to_cache_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON caching."""
        return {
            "content": self.content,
            "ir_code": self.ir_code,
            "model": self.model,
            "temperature": self.temperature,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> LLMResponse:
        """Deserialize from a cached dict."""
        return cls(
            content=data.get("content", ""),
            ir_code=data.get("ir_code", ""),
            model=data.get("model", ""),
            temperature=data.get("temperature", 0.2),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            duration_ms=data.get("duration_ms", 0.0),
            cached=True,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Rate Limiter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RateLimiter:
    """Sliding-window rate limiter for LLM API calls.

    Tracks request timestamps within a 60-second window and blocks
    when the RPM limit would be exceeded. Thread-safe.

    Also provides exponential backoff for rate-limit error responses
    (HTTP 429 or equivalent).
    """

    def __init__(self, rpm: int, config: RateLimitConfig) -> None:
        """Initialize the rate limiter.

        Args:
            rpm: Maximum requests per minute.
            config: Backoff configuration for retry delays.
        """
        self._rpm: int = rpm
        self._config: RateLimitConfig = config
        self._timestamps: list[float] = []
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        """Block until it's safe to make another API request.

        Uses a sliding 60-second window. If we've made RPM requests
        in the last 60 seconds, sleeps until the oldest request falls
        out of the window.
        """
        with self._lock:
            now = time.time()

            # Prune timestamps older than 60 seconds
            self._timestamps = [
                t for t in self._timestamps if now - t < 60.0
            ]

            if len(self._timestamps) >= self._rpm:
                # Window is full — sleep until the oldest timestamp expires
                oldest = self._timestamps[0]
                sleep_time = 60.0 - (now - oldest) + 0.5  # +0.5s safety margin
                if sleep_time > 0:
                    logger.warning(
                        "Rate limit reached (%d/%d RPM). Sleeping %.1fs...",
                        len(self._timestamps), self._rpm, sleep_time,
                    )
                    time.sleep(sleep_time)

            # Record this request
            self._timestamps.append(time.time())

    def backoff(self, attempt: int) -> None:
        """Execute exponential backoff after a rate-limit error.

        Args:
            attempt: Zero-indexed retry attempt number.
        """
        delay = self._config.get_backoff_delay(attempt)
        logger.warning(
            "Rate limit error from API. Backing off %.1fs (attempt %d/%d)...",
            delay, attempt + 1, self._config.max_retries,
        )
        time.sleep(delay)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Abstract LLM Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LLMClient(ABC):
    """Abstract interface for LLM providers.

    All LLM clients must implement this interface, enabling the pipeline
    to be provider-agnostic and support multi-model comparison.

    Subclasses: GeminiClient, GroqClient
    """

    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        """Send a prompt to the LLM and return a structured response.

        Args:
            prompt: The complete prompt string.
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).

        Returns:
            LLMResponse with content, extracted IR, and metadata.
            On error, LLMResponse.error will contain the error message.
        """
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return a human-readable model identifier for reports."""
        ...

    @abstractmethod
    def get_model_id(self) -> str:
        """Return the provider-specific model ID (e.g., 'gemini-2.0-flash')."""
        ...


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LLVM IR Extraction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_ir_from_response(response_text: str) -> str:
    """Extract LLVM IR code from an LLM response.

    LLMs return IR in various formats depending on the prompt and model.
    This function tries multiple extraction strategies in priority order:

    1. Custom markers: ===LLVM_IR_START=== ... ===LLVM_IR_END===
    2. Fenced code blocks: ```llvm ... ``` or ```ir ... ``` or ``` ... ```
    3. Raw IR detection: lines starting with LLVM IR keywords
    4. Fallback: return the entire text (let the validator handle it)

    Args:
        response_text: Raw text output from the LLM.

    Returns:
        Extracted LLVM IR code string (may be invalid — validation is separate).
    """
    text = response_text.strip()
    if not text:
        return ""

    # ── Strategy 1: Custom markers ────────────────────────────────
    marker_pattern = r"===LLVM_IR_START===\s*\n(.*?)===LLVM_IR_END==="
    match = re.search(marker_pattern, text, re.DOTALL)
    if match:
        return normalize_ir_header(match.group(1).strip())

    # ── Strategy 2: Fenced code blocks ────────────────────────────
    fence_patterns = [
        r"```llvm\s*\n(.*?)```",      # ```llvm
        r"```ir\s*\n(.*?)```",         # ```ir
        r"```ll\s*\n(.*?)```",         # ```ll
        r"```assembly\s*\n(.*?)```",   # ```assembly
        r"```\s*\n(.*?)```",           # plain ```
    ]
    for pattern in fence_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            # Verify it looks like IR (not some other code block)
            if _looks_like_ir(extracted):
                return normalize_ir_header(extracted)

    # ── Strategy 3: Raw IR detection ──────────────────────────────
    # Look for lines that start with common LLVM IR patterns
    ir_start_patterns = (
        "; ModuleID",
        "source_filename",
        "target datalayout",
        "target triple",
        "define ",
        "declare ",
        "@",
        "%struct.",
    )

    lines = text.split("\n")
    ir_start_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped.startswith(p) for p in ir_start_patterns):
            ir_start_idx = i
            break

    if ir_start_idx >= 0:
        # Take everything from the first IR line to the end
        ir_lines = lines[ir_start_idx:]

        # Trim trailing non-IR lines (explanations after the code)
        while ir_lines and not ir_lines[-1].strip():
            ir_lines.pop()
        while ir_lines and _is_explanation_line(ir_lines[-1]):
            ir_lines.pop()

        result = "\n".join(ir_lines).strip()
        if result:
            return normalize_ir_header(result)

    # ── Strategy 4: Fallback — return everything ──────────────────
    # The validator will report it as invalid if it's not valid IR
    logger.warning(
        "Could not extract LLVM IR from response (length=%d). "
        "Returning raw text for validation.",
        len(text),
    )
    return normalize_ir_header(text)


# Correct target datalayout and triple for x86_64 Linux (LLVM 18)
_CORRECT_DATALAYOUT = (
    'target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-'
    'i64:64-i128:128-f80:128-n8:16:32:64-S128"'
)
_CORRECT_TRIPLE = 'target triple = "x86_64-pc-linux-gnu"'

# Regex to match any target datalayout or triple line
_DATALAYOUT_RE = re.compile(r'^target datalayout\s*=\s*"[^"]*"', re.MULTILINE)
_TRIPLE_RE = re.compile(r'^target triple\s*=\s*"[^"]*"', re.MULTILINE)


def normalize_ir_header(ir_code: str) -> str:
    """Normalize target datalayout and triple to x86_64 Linux LLVM 18 values.

    LLMs frequently generate wrong datalayout strings (e.g., 32-bit pointer
    layouts like 'p:32:32') that cause SIGSEGV crashes in lli on 64-bit systems
    even when llvm-as accepts the IR. This function replaces any datalayout and
    triple with the known-correct values.

    Also replaces common LLVM 14 typed pointer syntax that llvm-as 18 may accept
    in compatibility mode but causes runtime crashes:
    - 'i8*'  → 'ptr'
    - 'i32*' → 'ptr'
    - 'i64*' → 'ptr'

    Args:
        ir_code: Raw LLVM IR string from LLM extraction.

    Returns:
        IR string with normalized header.
    """
    if not ir_code.strip():
        return ir_code

    # Replace or insert target datalayout
    if _DATALAYOUT_RE.search(ir_code):
        ir_code = _DATALAYOUT_RE.sub(_CORRECT_DATALAYOUT, ir_code)
    else:
        # Insert after ModuleID / source_filename or at top
        ir_code = _CORRECT_DATALAYOUT + "\n" + ir_code

    # Replace or insert target triple
    if _TRIPLE_RE.search(ir_code):
        ir_code = _TRIPLE_RE.sub(_CORRECT_TRIPLE, ir_code)
    else:
        ir_code = _CORRECT_TRIPLE + "\n" + ir_code

    # Fix common typed pointer remnants that survive llvm-as in compat mode
    # but crash lli — replace typed GEP calls to printf with opaque-pointer style
    # e.g.: call i32 (i8*, ...) @printf(i8* getelementptr ...)
    # →      call i32 (ptr, ...) @printf(ptr @.fmt.int, ...)
    # We do a targeted fix: just replace i8* / i32* / i64* in call arguments
    ir_code = re.sub(r'\bi8\*', 'ptr', ir_code)
    ir_code = re.sub(r'\bi32\*', 'ptr', ir_code)
    ir_code = re.sub(r'\bi64\*', 'ptr', ir_code)

    # Fix typed GEP: getelementptr inbounds ([N x i8], [N x i8]* @x, i32 0, i32 0)
    # → getelementptr inbounds ([N x i8], ptr @x, i64 0, i64 0)
    ir_code = re.sub(
        r'getelementptr inbounds \(\[([^\]]+)\],\s*\[[^\]]+\]\*\s*(@[\w.]+),\s*i32 0,\s*i32 0\)',
        r'getelementptr inbounds ([\1], ptr \2, i64 0, i64 0)',
        ir_code,
    )

    # Fix call with typed i8* pointer: call i32 (i8*, ...) @printf(i8* ...
    # → call i32 (ptr, ...) @printf(ptr ...
    ir_code = re.sub(r'call\s+i32\s+\(i8\*,\s*\.\.\.\)', 'call i32 (ptr, ...)', ir_code)

    return ir_code


def _looks_like_ir(text: str) -> bool:
    """Heuristic check: does this text look like LLVM IR?

    Checks for common LLVM IR patterns. Used to filter false positives
    when extracting from generic ``` code blocks.
    """
    ir_indicators = [
        "define ", "declare ", "alloca ", "store ", "load ",
        "ret ", "br ", "icmp ", "add ", "sub ", "mul ",
        "i32", "i64", "i1", "double", "ptr", "label",
        "entry:", "@", "%",
    ]
    text_lower = text.lower()
    matches = sum(1 for indicator in ir_indicators if indicator in text_lower)
    return matches >= 3


def _is_explanation_line(line: str) -> bool:
    """Check if a line is likely an explanation (not IR code).

    Used to trim trailing explanations that the LLM appends after the IR.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # IR lines typically start with these characters
    ir_prefixes = (
        ";", "define", "declare", "@", "%", "}", "{",
        "entry:", "if.", "while.", "for.", "else",
        "ret ", "br ", "store ", "load ", "alloca ",
        "call ", "add ", "sub ", "mul ", "sdiv ", "srem ",
        "fadd ", "fsub ", "fmul ", "fdiv ", "frem ",
        "icmp ", "fcmp ", "phi ", "getelementptr ",
        "source_filename", "target ",
        "sext ", "zext ", "trunc ", "sitofp ", "fptosi ",
    )
    # If it doesn't start with an IR prefix, it's likely explanation
    return not any(stripped.startswith(p) or stripped.startswith(p.upper())
                    for p in ir_prefixes)
