"""Tokenizer for MiniLang source code."""

from __future__ import annotations
from src.parser.tokens import Token, TokenType, KEYWORDS


class LexerError(Exception):
    """Raised when the lexer encounters an invalid character sequence."""
    def __init__(self, message: str, line: int, column: int):
        self.line = line
        self.column = column
        super().__init__(f"Lexer error at L{line}:{column}: {message}")


class Lexer:
    """Scans MiniLang source code into a stream of tokens."""

    def __init__(self, source: str, filename: str = "source.mini") -> None:
        self.source = source
        self.filename = filename
        self.position = 0
        self.line = 1
        self.column = 1
        self.length = len(source)

    def _advance(self) -> str:
        if self._is_at_end():
            return ""
        char = self.source[self.position]
        self.position += 1
        if char == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def _peek(self) -> str:
        if self._is_at_end():
            return ""
        return self.source[self.position]

    def _peek_next(self) -> str:
        if self.position + 1 >= self.length:
            return ""
        return self.source[self.position + 1]

    def _is_at_end(self) -> bool:
        return self.position >= self.length

    def _skip_whitespace_and_comments(self) -> None:
        while not self._is_at_end():
            char = self._peek()
            if char in [' ', '\r', '\t', '\n']:
                self._advance()
            elif char == '/' and self._peek_next() == '/':
                # Line comment
                while not self._is_at_end() and self._peek() != '\n':
                    self._advance()
            else:
                break

    def _read_number(self) -> Token:
        start_column = self.column
        num_str = ""
        while not self._is_at_end() and (self._peek().isdigit() or self._peek() == '.'):
            num_str += self._advance()
            
        if '.' in num_str:
            if num_str.count('.') > 1:
                raise LexerError(f"Invalid numeric literal: {num_str}", self.line, start_column)
            return Token(TokenType.FLOAT_LITERAL, float(num_str), self.line, start_column)
        return Token(TokenType.INT_LITERAL, int(num_str), self.line, start_column)

    def _read_string(self) -> Token:
        start_column = self.column
        self._advance()  # Skip opening quote
        val = ""
        while not self._is_at_end() and self._peek() != '"':
            char = self._advance()
            if char == '\\':
                next_char = self._advance()
                if next_char == 'n':
                    val += '\n'
                elif next_char == 't':
                    val += '\t'
                elif next_char == '"':
                    val += '"'
                elif next_char == '\\':
                    val += '\\'
                else:
                    val += '\\' + next_char
            else:
                val += char
                
        if self._is_at_end():
            raise LexerError("Unterminated string literal", self.line, start_column)
            
        self._advance()  # Skip closing quote
        return Token(TokenType.STRING_LITERAL, val, self.line, start_column)

    def _read_identifier_or_keyword(self) -> Token:
        start_column = self.column
        ident = ""
        while not self._is_at_end() and (self._peek().isalnum() or self._peek() == '_'):
            ident += self._advance()
            
        t_type = KEYWORDS.get(ident, TokenType.IDENTIFIER)
        # Handle boolean keywords specifically as values
        if t_type == TokenType.TRUE:
            return Token(TokenType.TRUE, True, self.line, start_column)
        elif t_type == TokenType.FALSE:
            return Token(TokenType.FALSE, False, self.line, start_column)
            
        return Token(t_type, ident, self.line, start_column)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while not self._is_at_end():
            self._skip_whitespace_and_comments()
            if self._is_at_end():
                break
                
            char = self._peek()
            start_column = self.column
            
            if char.isdigit():
                tokens.append(self._read_number())
            elif char == '"':
                tokens.append(self._read_string())
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            else:
                # Delimiters and operators
                self._advance()
                if char == '+':
                    tokens.append(Token(TokenType.PLUS, "+", self.line, start_column))
                elif char == '-':
                    if self._peek() == '>':
                        self._advance()
                        tokens.append(Token(TokenType.ARROW, "->", self.line, start_column))
                    else:
                        tokens.append(Token(TokenType.MINUS, "-", self.line, start_column))
                elif char == '*':
                    tokens.append(Token(TokenType.STAR, "*", self.line, start_column))
                elif char == '/':
                    tokens.append(Token(TokenType.SLASH, "/", self.line, start_column))
                elif char == '%':
                    tokens.append(Token(TokenType.PERCENT, "%", self.line, start_column))
                elif char == '=':
                    if self._peek() == '=':
                        self._advance()
                        tokens.append(Token(TokenType.EQ, "==", self.line, start_column))
                    else:
                        tokens.append(Token(TokenType.ASSIGN, "=", self.line, start_column))
                elif char == '!':
                    if self._peek() == '=':
                        self._advance()
                        tokens.append(Token(TokenType.NEQ, "!=", self.line, start_column))
                    else:
                        tokens.append(Token(TokenType.NOT, "!", self.line, start_column))
                elif char == '<':
                    if self._peek() == '=':
                        self._advance()
                        tokens.append(Token(TokenType.LTE, "<=", self.line, start_column))
                    else:
                        tokens.append(Token(TokenType.LT, "<", self.line, start_column))
                elif char == '>':
                    if self._peek() == '=':
                        self._advance()
                        tokens.append(Token(TokenType.GTE, ">=", self.line, start_column))
                    else:
                        tokens.append(Token(TokenType.GT, ">", self.line, start_column))
                elif char == '&' and self._peek() == '&':
                    self._advance()
                    tokens.append(Token(TokenType.AND, "&&", self.line, start_column))
                elif char == '|' and self._peek() == '|':
                    self._advance()
                    tokens.append(Token(TokenType.OR, "||", self.line, start_column))
                elif char == '(':
                    tokens.append(Token(TokenType.LPAREN, "(", self.line, start_column))
                elif char == ')':
                    tokens.append(Token(TokenType.RPAREN, ")", self.line, start_column))
                elif char == '{':
                    tokens.append(Token(TokenType.LBRACE, "{", self.line, start_column))
                elif char == '}':
                    tokens.append(Token(TokenType.RBRACE, "}", self.line, start_column))
                elif char == '[':
                    tokens.append(Token(TokenType.LBRACKET, "[", self.line, start_column))
                elif char == ']':
                    tokens.append(Token(TokenType.RBRACKET, "]", self.line, start_column))
                elif char == ',':
                    tokens.append(Token(TokenType.COMMA, ",", self.line, start_column))
                elif char == ':':
                    tokens.append(Token(TokenType.COLON, ":", self.line, start_column))
                elif char == ';':
                    tokens.append(Token(TokenType.SEMICOLON, ";", self.line, start_column))
                else:
                    raise LexerError(f"Unexpected character: {char!r}", self.line, start_column)
                    
        tokens.append(Token(TokenType.EOF, None, self.line, self.column))
        return tokens
