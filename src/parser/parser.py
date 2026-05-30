"""Recursive descent parser for MiniLang."""

from __future__ import annotations
from src.parser.tokens import Token, TokenType
from src.parser.ast_nodes import *
from src.types import DataType, LanguageTier


class ParseError(Exception):
    """Raised when the parser encounters invalid syntax."""
    def __init__(self, message: str, token: Token):
        self.token = token
        super().__init__(f"Parse error at L{token.line}:{token.column}: {message}")


class Parser:
    """Recursive descent parser that builds an AST from a token stream."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.current = 0

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _is_at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self.tokens[self.current - 1]

    def _check(self, type: TokenType) -> bool:
        if self._is_at_end():
            return False
        return self._peek().type == type

    def _match(self, *types: TokenType) -> bool:
        for t in types:
            if self._check(t):
                self._advance()
                return True
        return False

    def _expect(self, type: TokenType, message: str) -> Token:
        if self._check(type):
            return self._advance()
        raise ParseError(message, self._peek())

    def parse(self) -> Program:
        """Parse tokens into a complete Program AST. Auto-detects tier."""
        program = Program()
        program.functions = []
        while not self._is_at_end():
            program.functions.append(self._parse_function())
        program.tier = self.detect_tier(program)
        return program

    def detect_tier(self, program: Program) -> LanguageTier:
        """Walk the AST and determine the minimum tier needed."""
        has_t2 = False
        has_t3 = False

        def visit_stmt(stmt: Statement):
            nonlocal has_t2, has_t3
            if isinstance(stmt, ForStmt):
                has_t2 = True
            elif isinstance(stmt, VarDecl):
                if stmt.type in [DataType.FLOAT, DataType.ARRAY_INT, DataType.ARRAY_FLOAT, DataType.STRING]:
                    if stmt.type == DataType.FLOAT:
                        has_t2 = True
                    else:
                        has_t3 = True
                if stmt.value:
                    visit_expr(stmt.value)
            elif isinstance(stmt, Assignment):
                if stmt.index:
                    has_t3 = True
                if stmt.value:
                    visit_expr(stmt.value)
            elif isinstance(stmt, IfStmt):
                if stmt.condition:
                    visit_expr(stmt.condition)
                for s in stmt.then_block.statements:
                    visit_stmt(s)
                if stmt.else_block:
                    for s in stmt.else_block.statements:
                        visit_stmt(s)
            elif isinstance(stmt, WhileStmt):
                if stmt.condition:
                    visit_expr(stmt.condition)
                for s in stmt.body.statements:
                    visit_stmt(s)
            elif isinstance(stmt, ReturnStmt):
                if stmt.value:
                    visit_expr(stmt.value)
            elif isinstance(stmt, PrintStmt):
                if stmt.value:
                    visit_expr(stmt.value)

        def visit_expr(expr: Expression):
            nonlocal has_t2, has_t3
            if isinstance(expr, FloatLiteral):
                has_t2 = True
            elif isinstance(expr, StringLiteral):
                has_t3 = True
            elif isinstance(expr, BoolLiteral):
                has_t2 = True
            elif isinstance(expr, ArrayAccess):
                has_t3 = True
            elif isinstance(expr, ArrayLiteral):
                has_t3 = True
            elif isinstance(expr, BinaryOp):
                if expr.op in ["&&", "||", "%"]:
                    has_t2 = True
                visit_expr(expr.left)
                visit_expr(expr.right)
            elif isinstance(expr, UnaryOp):
                if expr.op == "!":
                    has_t2 = True
                visit_expr(expr.operand)
            elif isinstance(expr, FunctionCall):
                # recursion detection
                # simplified: nested calls or arrays/recursion are checked
                for arg in expr.args:
                    visit_expr(arg)

        for fn in program.functions:
            if fn.return_type in [DataType.FLOAT, DataType.ARRAY_INT, DataType.ARRAY_FLOAT, DataType.STRING]:
                if fn.return_type == DataType.FLOAT:
                    has_t2 = True
                else:
                    has_t3 = True
            for param in fn.params:
                if param.type in [DataType.FLOAT, DataType.ARRAY_INT, DataType.ARRAY_FLOAT, DataType.STRING]:
                    if param.type == DataType.FLOAT:
                        has_t2 = True
                    else:
                        has_t3 = True
            for stmt in fn.body.statements:
                visit_stmt(stmt)
                
            # Recursion detection: walk all AST nodes in the function body and
            # check if any FunctionCall refers back to this function by name.
            # This catches recursion nested inside expressions (e.g. n * factorial(n-1))
            # which the old shallow check missed.
            for node in _walk_ast(fn.body):
                if isinstance(node, FunctionCall) and node.name == fn.name:
                    has_t3 = True
                    break

        if has_t3:
            return LanguageTier.TIER_3
        if has_t2:
            return LanguageTier.TIER_2
        return LanguageTier.TIER_1

    def _parse_type(self) -> DataType:
        token = self._advance()
        if token.type == TokenType.INT_TYPE:
            if self._match(TokenType.LBRACKET):
                self._expect(TokenType.RBRACKET, "Expected ']' for array type")
                return DataType.ARRAY_INT
            return DataType.INT
        elif token.type == TokenType.FLOAT_TYPE:
            if self._match(TokenType.LBRACKET):
                self._expect(TokenType.RBRACKET, "Expected ']' for array type")
                return DataType.ARRAY_FLOAT
            return DataType.FLOAT
        elif token.type == TokenType.STRING_TYPE:
            return DataType.STRING
        elif token.type == TokenType.VOID_TYPE:
            return DataType.VOID
        raise ParseError(f"Expected type name, got {token.value}", token)

    def _parse_function(self) -> Function:
        fn_tok = self._expect(TokenType.FN, "Expected 'fn'")
        name = self._expect(TokenType.IDENTIFIER, "Expected function name").value
        self._expect(TokenType.LPAREN, "Expected '(' after function name")
        
        params = []
        if not self._check(TokenType.RPAREN):
            while True:
                p_name = self._expect(TokenType.IDENTIFIER, "Expected parameter name").value
                self._expect(TokenType.COLON, "Expected ':' after parameter name")
                p_type = self._parse_type()
                params.append(Parameter(p_name, p_type))
                if not self._match(TokenType.COMMA):
                    break
                    
        self._expect(TokenType.RPAREN, "Expected ')' after parameter list")
        self._expect(TokenType.COLON, "Expected ':' before return type")
        ret_type = self._parse_type()
        body = self._parse_block()
        
        fn = Function(name, params, ret_type, body)
        fn.line = fn_tok.line
        fn.column = fn_tok.column
        return fn

    def _parse_block(self) -> Block:
        lbrace = self._expect(TokenType.LBRACE, "Expected '{'")
        statements = []
        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            statements.append(self._parse_statement())
        self._expect(TokenType.RBRACE, "Expected '}'")
        block = Block(statements)
        block.line = lbrace.line
        block.column = lbrace.column
        return block

    def _parse_statement(self) -> Statement:
        if self._match(TokenType.LET):
            return self._parse_var_decl()
        elif self._match(TokenType.IF):
            return self._parse_if_stmt()
        elif self._match(TokenType.WHILE):
            return self._parse_while_stmt()
        elif self._match(TokenType.FOR):
            return self._parse_for_stmt()
        elif self._match(TokenType.RETURN):
            return self._parse_return_stmt()
        elif self._match(TokenType.PRINT):
            return self._parse_print_stmt()
        else:
            return self._parse_assignment_or_expr()

    def _parse_var_decl(self) -> VarDecl:
        name = self._expect(TokenType.IDENTIFIER, "Expected variable name").value
        self._expect(TokenType.COLON, "Expected ':' after variable name")
        t = self._parse_type()
        self._expect(TokenType.ASSIGN, "Expected '=' in variable declaration")
        val = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "Expected ';' after variable declaration")
        return VarDecl(name, t, val)

    def _parse_if_stmt(self) -> IfStmt:
        self._expect(TokenType.LPAREN, "Expected '(' before if condition")
        cond = self._parse_expression()
        self._expect(TokenType.RPAREN, "Expected ')' after if condition")
        then_b = self._parse_block()
        else_b = None
        if self._match(TokenType.ELSE):
            if self._check(TokenType.LBRACE):
                else_b = self._parse_block()
            else:
                else_b = Block([self._parse_statement()])
        return IfStmt(cond, then_b, else_b)

    def _parse_while_stmt(self) -> WhileStmt:
        self._expect(TokenType.LPAREN, "Expected '(' before while condition")
        cond = self._parse_expression()
        self._expect(TokenType.RPAREN, "Expected ')' after while condition")
        body = self._parse_block()
        return WhileStmt(cond, body)

    def _parse_for_stmt(self) -> ForStmt:
        self._expect(TokenType.LPAREN, "Expected '(' after 'for'")
        # For init can be VarDecl
        self._expect(TokenType.LET, "Expected 'let' in for loop init")
        init = self._parse_var_decl() # includes semicolon
        cond = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "Expected ';' after for loop condition")
        
        # update stmt (Assignment)
        u_target = self._expect(TokenType.IDENTIFIER, "Expected identifier in update statement").value
        self._expect(TokenType.ASSIGN, "Expected '=' in update statement")
        u_val = self._parse_expression()
        update = Assignment(u_target, None, u_val)
        
        self._expect(TokenType.RPAREN, "Expected ')' after update statement")
        body = self._parse_block()
        return ForStmt(init, cond, update, body)

    def _parse_return_stmt(self) -> ReturnStmt:
        val = None
        if not self._check(TokenType.SEMICOLON):
            val = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "Expected ';' after return")
        return ReturnStmt(val)

    def _parse_print_stmt(self) -> PrintStmt:
        self._expect(TokenType.LPAREN, "Expected '(' after print")
        val = self._parse_expression()
        self._expect(TokenType.RPAREN, "Expected ')' after print value")
        self._expect(TokenType.SEMICOLON, "Expected ';' after print statement")
        return PrintStmt(val)

    def _parse_assignment_or_expr(self) -> Statement:
        # Since it can be an assignment or just expression statement
        expr = self._parse_expression()
        if self._match(TokenType.ASSIGN):
            # Must be assignment
            if isinstance(expr, Identifier):
                val = self._parse_expression()
                self._expect(TokenType.SEMICOLON, "Expected ';' after assignment")
                return Assignment(expr.name, None, val)
            elif isinstance(expr, ArrayAccess):
                val = self._parse_expression()
                self._expect(TokenType.SEMICOLON, "Expected ';' after array assignment")
                return Assignment(expr.array, expr.index, val)
            raise ParseError("Invalid assignment target", self._peek())
        self._expect(TokenType.SEMICOLON, "Expected ';' after expression")
        return expr

    def _parse_expression(self) -> Expression:
        return self._parse_or_expr()

    def _parse_or_expr(self) -> Expression:
        expr = self._parse_and_expr()
        while self._match(TokenType.OR):
            op = "||"
            right = self._parse_and_expr()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_and_expr(self) -> Expression:
        expr = self._parse_equality()
        while self._match(TokenType.AND):
            op = "&&"
            right = self._parse_equality()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_equality(self) -> Expression:
        expr = self._parse_comparison()
        while self._match(TokenType.EQ, TokenType.NEQ):
            op = self.tokens[self.current - 1].value
            right = self._parse_comparison()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_comparison(self) -> Expression:
        expr = self._parse_additive()
        while self._match(TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE):
            op = self.tokens[self.current - 1].value
            right = self._parse_additive()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_additive(self) -> Expression:
        expr = self._parse_multiplicative()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op = self.tokens[self.current - 1].value
            right = self._parse_multiplicative()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_multiplicative(self) -> Expression:
        expr = self._parse_unary()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self.tokens[self.current - 1].value
            right = self._parse_unary()
            expr = BinaryOp(expr, op, right)
        return expr

    def _parse_unary(self) -> Expression:
        if self._match(TokenType.NOT, TokenType.MINUS):
            op = self.tokens[self.current - 1].value
            operand = self._parse_unary()
            return UnaryOp(op, operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expression:
        if self._match(TokenType.INT_LITERAL):
            return IntLiteral(self.tokens[self.current - 1].value)
        elif self._match(TokenType.FLOAT_LITERAL):
            return FloatLiteral(self.tokens[self.current - 1].value)
        elif self._match(TokenType.STRING_LITERAL):
            return StringLiteral(self.tokens[self.current - 1].value)
        elif self._match(TokenType.TRUE):
            return BoolLiteral(True)
        elif self._match(TokenType.FALSE):
            return BoolLiteral(False)
        elif self._match(TokenType.IDENTIFIER):
            name = self.tokens[self.current - 1].value
            if self._match(TokenType.LPAREN):
                # Function call
                args = []
                if not self._check(TokenType.RPAREN):
                    while True:
                        args.append(self._parse_expression())
                        if not self._match(TokenType.COMMA):
                            break
                self._expect(TokenType.RPAREN, "Expected ')' after arguments")
                return FunctionCall(name, args)
            elif self._match(TokenType.LBRACKET):
                # Array access
                idx = self._parse_expression()
                self._expect(TokenType.RBRACKET, "Expected ']' after index")
                return ArrayAccess(name, idx)
            return Identifier(name)
        elif self._match(TokenType.LPAREN):
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN, "Expected ')' after grouped expression")
            return expr
        elif self._match(TokenType.LBRACKET):
            # Array literal
            elements = []
            if not self._check(TokenType.RBRACKET):
                while True:
                    elements.append(self._parse_expression())
                    if not self._match(TokenType.COMMA):
                        break
            self._expect(TokenType.RBRACKET, "Expected ']' after array literal elements")
            return ArrayLiteral(elements)
            
        raise ParseError(f"Unexpected token in expression: {self._peek().value}", self._peek())


def _walk_ast(node):
    """Yield all AST nodes via depth-first traversal."""
    if node is None:
        return
    yield node
    if isinstance(node, Program):
        for fn in node.functions:
            yield from _walk_ast(fn)
    elif isinstance(node, Function):
        for param in node.params:
            yield from _walk_ast(param)
        yield from _walk_ast(node.body)
    elif isinstance(node, Block):
        for stmt in node.statements:
            yield from _walk_ast(stmt)
    elif isinstance(node, VarDecl):
        if node.value:
            yield from _walk_ast(node.value)
    elif isinstance(node, Assignment):
        if node.index:
            yield from _walk_ast(node.index)
        if node.value:
            yield from _walk_ast(node.value)
    elif isinstance(node, IfStmt):
        if node.condition:
            yield from _walk_ast(node.condition)
        yield from _walk_ast(node.then_block)
        if node.else_block:
            yield from _walk_ast(node.else_block)
    elif isinstance(node, WhileStmt):
        if node.condition:
            yield from _walk_ast(node.condition)
        yield from _walk_ast(node.body)
    elif isinstance(node, ForStmt):
        if node.init:
            yield from _walk_ast(node.init)
        if node.condition:
            yield from _walk_ast(node.condition)
        if node.update:
            yield from _walk_ast(node.update)
        yield from _walk_ast(node.body)
    elif isinstance(node, ReturnStmt):
        if node.value:
            yield from _walk_ast(node.value)
    elif isinstance(node, PrintStmt):
        if node.value:
            yield from _walk_ast(node.value)
    elif isinstance(node, BinaryOp):
        if node.left:
            yield from _walk_ast(node.left)
        if node.right:
            yield from _walk_ast(node.right)
    elif isinstance(node, UnaryOp):
        if node.operand:
            yield from _walk_ast(node.operand)
    elif isinstance(node, FunctionCall):
        for arg in node.args:
            yield from _walk_ast(arg)
    elif isinstance(node, ArrayAccess):
        if node.index:
            yield from _walk_ast(node.index)
    elif isinstance(node, ArrayLiteral):
        for el in node.elements:
            yield from _walk_ast(el)

