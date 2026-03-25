"""TypeExprParser — pure-Python parser for Coq type expression strings.

Converts textual type signatures (as returned by coq-lsp Search output)
into ConstrNode trees for structural indexing and query-time parsing.

Specification: specification/type-expr-parser.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from Poule.normalization.constr_node import (
    App,
    Const,
    Lambda,
    LetIn,
    Prod,
    Rel,
    Sort,
)
from Poule.pipeline.parser import ParseError


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------


class TokenKind(Enum):
    IDENT = auto()
    NUMBER = auto()
    SORT = auto()
    FORALL = auto()
    EXISTS = auto()
    FUN = auto()
    ARROW = auto()
    DARROW = auto()
    COLON = auto()
    COLONEQ = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LRECORD = auto()
    RRECORD = auto()
    PIPE = auto()
    UNDERSCORE = auto()
    INFIX_OP = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    pos: int


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_SORTS = frozenset({"Prop", "Set", "Type"})

# Infix binding powers: (left_bp, right_bp)
# Higher bp = tighter binding.
# Left-associative: right_bp = left_bp + 1
# Right-associative: right_bp = left_bp - 1
_INFIX_BP: dict[str, tuple[int, int]] = {
    "->": (10, 9),
    "=": (30, 31),
    "<>": (30, 31),
    "&": (40, 41),
    "+": (50, 51),
    "-": (50, 51),
    "++": (55, 54),
    "::": (55, 54),
    "*": (60, 61),
    "^": (65, 66),
    "\\/": (65, 66),
    "/\\": (65, 66),
    "<->": (20, 21),
    "==>": (15, 16),
    "||": (35, 36),
    "&&": (40, 41),
    "==": (30, 31),
    "=?": (30, 31),
    "?=": (30, 31),
    "<": (70, 71),
    "<=": (70, 71),
    ">": (70, 71),
    ">=": (70, 71),
}

# Tokens that can start a primary expression (for application parsing).
_PRIMARY_STARTS = frozenset({
    TokenKind.IDENT,
    TokenKind.NUMBER,
    TokenKind.SORT,
    TokenKind.UNDERSCORE,
    TokenKind.LPAREN,
    TokenKind.LBRACE,
    TokenKind.LBRACKET,
    TokenKind.LRECORD,
    TokenKind.FORALL,
    TokenKind.EXISTS,
    TokenKind.FUN,
})

# Regex for scope annotations: )%ident or trailing %ident
_re = __import__("re")
_SCOPE_RE = _re.compile(r"%[a-zA-Z_][a-zA-Z0-9_]*")

# Unicode math symbol → ASCII equivalent mapping
_UNICODE_MAP: dict[str, str] = {
    "\u2200": "forall ",   # ∀
    "\u2203": "exists ",   # ∃
    "\u2192": "-> ",       # →
    "\u21d2": "=> ",       # ⇒
    "\u2194": "<-> ",      # ↔
    "\u2227": "/\\ ",      # ∧
    "\u2228": "\\/ ",      # ∨
    "\u00ac": "~ ",        # ¬
    "\u03bb": "fun ",      # λ
    "\u2264": "<= ",       # ≤
    "\u2265": ">= ",       # ≥
    "\u2260": "<> ",       # ≠
}
_UNICODE_RE = _re.compile(
    "[" + "".join(_re.escape(k) for k in _UNICODE_MAP) + "]"
)


def tokenize(text: str) -> list[Token]:
    """Tokenize a Coq type expression string into a list of Tokens."""
    # Pre-process: normalize Unicode math symbols to ASCII equivalents
    text = _UNICODE_RE.sub(lambda m: _UNICODE_MAP[m.group()], text)
    # Pre-process: strip Coq scope annotations (%nat_scope, %bool, etc.)
    text = _SCOPE_RE.sub("", text)
    tokens: list[Token] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # Skip whitespace
        if ch.isspace():
            i += 1
            continue

        pos = i

        # Three-character operators (check before two-char)
        if i + 2 < n:
            three = text[i : i + 3]
            if three == "<->":
                tokens.append(Token(TokenKind.INFIX_OP, "<->", pos))
                i += 3
                continue
            if three == "==>":
                tokens.append(Token(TokenKind.INFIX_OP, "==>", pos))
                i += 3
                continue
            if three in ("<=?", "=?b", "<?b"):
                # Decidable comparison notations — treat as identifiers
                tokens.append(Token(TokenKind.IDENT, three, pos))
                i += 3
                continue

        # Two-character operators (check before single-char)
        if i + 1 < n:
            two = text[i : i + 2]
            if two == "->":
                tokens.append(Token(TokenKind.ARROW, "->", pos))
                i += 2
                continue
            if two == "=>":
                tokens.append(Token(TokenKind.DARROW, "=>", pos))
                i += 2
                continue
            if two == ":=":
                tokens.append(Token(TokenKind.COLONEQ, ":=", pos))
                i += 2
                continue
            if two == "::":
                tokens.append(Token(TokenKind.INFIX_OP, "::", pos))
                i += 2
                continue
            if two == "++":
                tokens.append(Token(TokenKind.INFIX_OP, "++", pos))
                i += 2
                continue
            if two == "==":
                tokens.append(Token(TokenKind.INFIX_OP, "==", pos))
                i += 2
                continue
            if two == "{|":
                tokens.append(Token(TokenKind.LRECORD, "{|", pos))
                i += 2
                continue
            if two == "|}":
                tokens.append(Token(TokenKind.RRECORD, "|}", pos))
                i += 2
                continue
            if two in ("<=", ">=", "<>"):
                tokens.append(Token(TokenKind.INFIX_OP, two, pos))
                i += 2
                continue
            # Decidable operators: =?, <=?, ?=
            if two in ("=?", "?="):
                tokens.append(Token(TokenKind.INFIX_OP, two, pos))
                i += 2
                continue
            # Boolean operators: || and &&
            if two == "||":
                tokens.append(Token(TokenKind.INFIX_OP, "||", pos))
                i += 2
                continue
            if two == "&&":
                tokens.append(Token(TokenKind.INFIX_OP, "&&", pos))
                i += 2
                continue

        # Disjunction: \/ (backslash + forward slash)
        if ch == "\\" and i + 1 < n and text[i + 1] == "/":
            tokens.append(Token(TokenKind.INFIX_OP, "\\/", pos))
            i += 2
            continue

        # Conjunction: /\ (forward slash + backslash)
        if ch == "/" and i + 1 < n and text[i + 1] == "\\":
            tokens.append(Token(TokenKind.INFIX_OP, "/\\", pos))
            i += 2
            continue

        # Single-character punctuation
        if ch == "(":
            tokens.append(Token(TokenKind.LPAREN, "(", pos))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenKind.RPAREN, ")", pos))
            i += 1
            continue
        if ch == "{":
            tokens.append(Token(TokenKind.LBRACE, "{", pos))
            i += 1
            continue
        if ch == "}":
            tokens.append(Token(TokenKind.RBRACE, "}", pos))
            i += 1
            continue
        if ch == "[":
            tokens.append(Token(TokenKind.LBRACKET, "[", pos))
            i += 1
            continue
        if ch == "]":
            tokens.append(Token(TokenKind.RBRACKET, "]", pos))
            i += 1
            continue
        if ch == ":":
            tokens.append(Token(TokenKind.COLON, ":", pos))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenKind.COMMA, ",", pos))
            i += 1
            continue
        if ch == "|":
            tokens.append(Token(TokenKind.PIPE, "|", pos))
            i += 1
            continue

        # Single-character infix operators
        if ch in ("+", "*", "^", "&"):
            tokens.append(Token(TokenKind.INFIX_OP, ch, pos))
            i += 1
            continue
        if ch == "=":
            tokens.append(Token(TokenKind.INFIX_OP, "=", pos))
            i += 1
            continue
        if ch == "<":
            tokens.append(Token(TokenKind.INFIX_OP, "<", pos))
            i += 1
            continue
        if ch == ">":
            tokens.append(Token(TokenKind.INFIX_OP, ">", pos))
            i += 1
            continue
        if ch == "-":
            tokens.append(Token(TokenKind.INFIX_OP, "-", pos))
            i += 1
            continue

        # @ (explicit application marker) — skip it
        if ch == "@":
            i += 1
            continue

        # ? followed by identifier (existential variable) — treat as identifier
        if ch == "?" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in ("_", "'", ".")):
                j += 1
            tokens.append(Token(TokenKind.IDENT, text[i:j], pos))
            i = j
            continue

        # Standalone ?, !, ~, `, #, ;, ., $, % — skip
        # %: is a MathComp notation prefix (e.g., x%:M) — skip both chars
        if ch == "%" and i + 1 < n and text[i + 1] == ":":
            i += 2
            continue
        if ch in ("?", "!", "`", "#", "~", ";", ".", "$", "%"):
            i += 1
            continue

        # String literals "..." — skip entire quoted string
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 1
            if i < n:
                i += 1  # consume closing quote
            continue

        # Standalone / or \ not part of /\ or \/ — skip
        if ch in ("/", "\\"):
            i += 1
            continue

        # Numbers
        if ch.isdigit():
            j = i
            while j < n and text[j].isdigit():
                j += 1
            tokens.append(Token(TokenKind.NUMBER, text[i:j], pos))
            i = j
            continue

        # Identifiers, keywords, sorts
        # Allow ' as identifier start for MathComp notation (e.g. 'M_)
        if ch.isalpha() or ch == "_" or ch == "'":
            j = i
            while j < n and (text[j].isalnum() or text[j] in ("_", "'", ".")):
                j += 1
            # Strip trailing dots (not part of identifiers)
            while j > i + 1 and text[j - 1] == ".":
                j -= 1
            word = text[i:j]
            if word == "_":
                tokens.append(Token(TokenKind.UNDERSCORE, "_", pos))
            elif word in _SORTS:
                tokens.append(Token(TokenKind.SORT, word, pos))
            elif word == "forall":
                tokens.append(Token(TokenKind.FORALL, word, pos))
            elif word == "exists":
                tokens.append(Token(TokenKind.EXISTS, word, pos))
            elif word == "fun":
                tokens.append(Token(TokenKind.FUN, word, pos))
            elif word in ("if", "then", "else", "let", "in",
                          "match", "with", "end", "return",
                          "as", "fix", "cofix"):
                # Control-flow keywords — treat as identifiers for indexing
                tokens.append(Token(TokenKind.IDENT, word, pos))
            else:
                tokens.append(Token(TokenKind.IDENT, word, pos))
            i = j
            continue

        # Skip unknown non-ASCII characters (Unicode math symbols not
        # handled by the pre-processing map, e.g. ∈, ⊆, ⊤, ⊥, ·)
        if ord(ch) > 127:
            i += 1
            continue

        raise ParseError(f"Unexpected character {ch!r} at position {pos}")

    tokens.append(Token(TokenKind.EOF, "", len(text)))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TypeExprParser:
    """Pure-Python parser for Coq type expression strings.

    Implements the ``CoqParser`` protocol. Converts type signature text
    into ``ConstrNode`` trees using a Pratt (top-down operator precedence)
    parser.
    """

    def parse(self, expression: str) -> Any:
        """Parse a Coq type expression string into a ConstrNode.

        Raises ``ParseError`` on failure.
        """
        if not expression or not expression.strip():
            raise ParseError("Empty expression")

        tokens = tokenize(expression)
        pos, node = self._expr(tokens, 0, [], 0)

        if tokens[pos].kind != TokenKind.EOF:
            tok = tokens[pos]
            raise ParseError(
                f"Unexpected token {tok.value!r} at position {tok.pos}"
            )
        return node

    # ----- Pratt parser core -----

    def _expr(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
        min_bp: int,
    ) -> tuple[int, Any]:
        """Parse an expression with minimum binding power *min_bp*."""
        pos, lhs = self._atom(tokens, pos, binders)

        while True:
            tok = tokens[pos]

            # Determine if the current token is an infix operator
            if tok.kind == TokenKind.ARROW:
                op = "->"
            elif tok.kind == TokenKind.INFIX_OP:
                op = tok.value
            else:
                break

            bp = _INFIX_BP.get(op)
            if bp is None:
                break

            left_bp, right_bp = bp
            if left_bp < min_bp:
                break

            pos += 1  # consume the operator

            if op == "->":
                # Non-dependent arrow: A -> B ≡ Prod("_", A, B)
                # Push "_" binder for correct de Bruijn offsets
                new_binders = binders + ["_"]
                pos, rhs = self._expr(tokens, pos, new_binders, right_bp)
                lhs = Prod("_", lhs, rhs)
            else:
                # Infix desugared to App: n + m ≡ App(Const("+"), [n, m])
                pos, rhs = self._expr(tokens, pos, binders, right_bp)
                lhs = App(Const(op), [lhs, rhs])

        return pos, lhs

    def _atom(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse a primary expression and optional application arguments."""
        pos, node = self._primary(tokens, pos, binders)

        # Greedy application: collect arguments while next token starts a primary
        # Also consume stray infix operators as identifier arguments (handles
        # scope-stripped function references like -%R → bare -, +%R → bare +)
        args: list[Any] = []
        while True:
            if tokens[pos].kind in _PRIMARY_STARTS:
                pos, arg = self._primary(tokens, pos, binders)
                args.append(arg)
            elif (tokens[pos].kind == TokenKind.INFIX_OP
                  and pos + 1 < len(tokens)
                  and tokens[pos + 1].kind not in _PRIMARY_STARTS
                  and tokens[pos + 1].kind != TokenKind.INFIX_OP):
                # Trailing operator with no right operand — treat as identifier
                args.append(Const(tokens[pos].value))
                pos += 1
            else:
                break

        if args:
            return pos, App(node, args)
        return pos, node

    def _primary(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse a single primary expression (no application)."""
        tok = tokens[pos]

        if tok.kind == TokenKind.IDENT:
            # Handle 'let ... := ... in ...' expressions
            if tok.value == "let":
                return self._parse_let(tokens, pos, binders)
            # Handle 'match ... with ... end' — skip to 'end', return body
            if tok.value == "match":
                return self._skip_match(tokens, pos, binders)
            return pos + 1, self._resolve(tok.value, binders)

        if tok.kind == TokenKind.SORT:
            return pos + 1, Sort(tok.value)

        if tok.kind == TokenKind.UNDERSCORE:
            return pos + 1, Sort("Type")

        if tok.kind == TokenKind.NUMBER:
            return pos + 1, Const(tok.value)

        if tok.kind == TokenKind.LPAREN:
            pos += 1
            # Empty parens () — unit type
            if tokens[pos].kind == TokenKind.RPAREN:
                return pos + 1, Const("_unit_")
            pos, inner = self._expr(tokens, pos, binders, 0)
            # Named argument: (name := value) — keep just the value
            if tokens[pos].kind == TokenKind.COLONEQ:
                pos += 1  # consume :=
                pos, inner = self._expr(tokens, pos, binders, 0)
            # Tuple-like: (a, b, ...) — skip remaining comma-separated items
            while tokens[pos].kind == TokenKind.COMMA:
                pos += 1
                pos, _ = self._expr(tokens, pos, binders, 0)
            # Type annotation: (expr : Type) — keep the type for indexing
            if tokens[pos].kind == TokenKind.COLON:
                pos += 1  # consume ':'
                pos, inner = self._expr(tokens, pos, binders, 0)
            if tokens[pos].kind == TokenKind.RPAREN:
                return pos + 1, inner
            # Paren content couldn't be fully parsed (e.g., MathComp
            # colon-infix notation :&:) — skip to matching )
            depth = 1
            while depth > 0 and tokens[pos].kind != TokenKind.EOF:
                if tokens[pos].kind == TokenKind.LPAREN:
                    depth += 1
                elif tokens[pos].kind == TokenKind.RPAREN:
                    depth -= 1
                pos += 1
            if depth > 0:
                raise ParseError(
                    f"Expected ')' at position {tokens[pos].pos}"
                )
            return pos, inner

        if tok.kind == TokenKind.LBRACE:
            pos += 1
            pos, inner = self._expr(tokens, pos, binders, 0)
            if tokens[pos].kind == TokenKind.PIPE:
                # Sig type {x : T | P} — parse the proposition after |
                pos += 1  # consume |
                pos, prop = self._expr(tokens, pos, binders, 0)
                # For indexing purposes, treat as Prod("_", inner, prop)
                inner = Prod("_", inner, prop)
            if tokens[pos].kind == TokenKind.RBRACE:
                return pos + 1, inner
            # Brace content couldn't be fully parsed (e.g., {morphism >->})
            # — skip to matching }
            depth = 1
            while depth > 0 and tokens[pos].kind != TokenKind.EOF:
                if tokens[pos].kind == TokenKind.LBRACE:
                    depth += 1
                elif tokens[pos].kind == TokenKind.RBRACE:
                    depth -= 1
                pos += 1
            if depth > 0:
                raise ParseError(
                    f"Expected '}}' at position {tokens[pos].pos}"
                )
            return pos, inner

        if tok.kind == TokenKind.LRECORD:
            # Record syntax {| field := val ; ... |} — skip to matching |}
            depth = 1
            pos += 1
            while depth > 0 and tokens[pos].kind != TokenKind.EOF:
                if tokens[pos].kind == TokenKind.LRECORD:
                    depth += 1
                elif tokens[pos].kind == TokenKind.RRECORD:
                    depth -= 1
                pos += 1
            return pos, Const("_record_")

        if tok.kind == TokenKind.LBRACKET:
            pos += 1
            # Empty brackets [] — nil/empty list
            if tokens[pos].kind == TokenKind.RBRACKET:
                return pos + 1, Const("_nil_")
            pos, inner = self._expr(tokens, pos, binders, 0)
            if tokens[pos].kind == TokenKind.RBRACKET:
                return pos + 1, inner
            # Bracket content couldn't be fully parsed (e.g., custom
            # notation <[k:=v]>) — skip to matching ]
            depth = 1
            while depth > 0 and tokens[pos].kind != TokenKind.EOF:
                if tokens[pos].kind == TokenKind.LBRACKET:
                    depth += 1
                elif tokens[pos].kind == TokenKind.RBRACKET:
                    depth -= 1
                pos += 1
            if depth > 0:
                raise ParseError(
                    f"Expected ']' at position {tokens[pos].pos}"
                )
            return pos, inner

        if tok.kind == TokenKind.FORALL:
            return self._parse_forall(tokens, pos, binders)

        if tok.kind == TokenKind.EXISTS:
            return self._parse_exists(tokens, pos, binders)

        if tok.kind == TokenKind.FUN:
            return self._parse_fun(tokens, pos, binders)

        # Leading/unary infix operator — treat as identifier (handles
        # scope-stripped function references and unary operators)
        if tok.kind == TokenKind.INFIX_OP:
            return pos + 1, Const(tok.value)

        # Stray ARROW in expression position — treat as identifier
        if tok.kind == TokenKind.ARROW:
            return pos + 1, Const("->")

        # Stray PIPE — skip (e.g., match arms, absolute value notation)
        if tok.kind == TokenKind.PIPE:
            pos += 1
            return self._primary(tokens, pos, binders)

        # COLONEQ in unexpected position — skip
        if tok.kind == TokenKind.COLONEQ:
            pos += 1
            return self._primary(tokens, pos, binders)

        # COLON in unexpected position — skip
        if tok.kind == TokenKind.COLON:
            pos += 1
            return self._primary(tokens, pos, binders)

        raise ParseError(
            f"Expected expression at position {tok.pos}, got {tok.value!r}"
        )

    # ----- Binder parsing -----

    def _parse_binder_groups(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
        separator: TokenKind,
    ) -> tuple[int, list[tuple[str, Any]]]:
        """Parse binder groups until *separator* (COMMA for forall, DARROW for fun).

        Returns (new_pos, list of (name, type) pairs).
        """
        all_pairs: list[tuple[str, Any]] = []
        current_binders = list(binders)

        while True:
            tok = tokens[pos]

            if tok.kind == TokenKind.LPAREN:
                # Parenthesized group: (x y ... : T)
                pos += 1
                names: list[str] = []
                while tokens[pos].kind in (TokenKind.IDENT, TokenKind.UNDERSCORE):
                    names.append(tokens[pos].value)
                    pos += 1
                if not names:
                    raise ParseError(
                        f"Expected variable name at position {tokens[pos].pos}"
                    )
                if tokens[pos].kind != TokenKind.COLON:
                    raise ParseError(
                        f"Expected ':' at position {tokens[pos].pos}"
                    )
                pos += 1
                pos, ty = self._expr(tokens, pos, current_binders, 0)
                if tokens[pos].kind != TokenKind.RPAREN:
                    raise ParseError(
                        f"Expected ')' at position {tokens[pos].pos}"
                    )
                pos += 1
                for name in names:
                    all_pairs.append((name, ty))
                    current_binders.append(name)
                continue

            if tok.kind == TokenKind.LBRACE:
                # Implicit group: {x y ... : T}
                pos += 1
                names = []
                while tokens[pos].kind in (TokenKind.IDENT, TokenKind.UNDERSCORE):
                    names.append(tokens[pos].value)
                    pos += 1
                if not names:
                    raise ParseError(
                        f"Expected variable name at position {tokens[pos].pos}"
                    )
                if tokens[pos].kind != TokenKind.COLON:
                    raise ParseError(
                        f"Expected ':' at position {tokens[pos].pos}"
                    )
                pos += 1
                pos, ty = self._expr(tokens, pos, current_binders, 0)
                if tokens[pos].kind != TokenKind.RBRACE:
                    raise ParseError(
                        f"Expected '}}' at position {tokens[pos].pos}"
                    )
                pos += 1
                for name in names:
                    all_pairs.append((name, ty))
                    current_binders.append(name)
                continue

            if tok.kind == TokenKind.LBRACKET:
                # Maximal implicit group: [x y ... : T]
                pos += 1
                names = []
                while tokens[pos].kind in (TokenKind.IDENT, TokenKind.UNDERSCORE):
                    names.append(tokens[pos].value)
                    pos += 1
                if not names:
                    raise ParseError(
                        f"Expected variable name at position {tokens[pos].pos}"
                    )
                if tokens[pos].kind != TokenKind.COLON:
                    raise ParseError(
                        f"Expected ':' at position {tokens[pos].pos}"
                    )
                pos += 1
                pos, ty = self._expr(tokens, pos, current_binders, 0)
                if tokens[pos].kind != TokenKind.RBRACKET:
                    raise ParseError(
                        f"Expected ']' at position {tokens[pos].pos}"
                    )
                pos += 1
                for name in names:
                    all_pairs.append((name, ty))
                    current_binders.append(name)
                continue

            if tok.kind in (TokenKind.IDENT, TokenKind.UNDERSCORE):
                # Unparenthesized binder(s): x y ... : T  (or untyped for fun)
                names = []
                while tokens[pos].kind in (TokenKind.IDENT, TokenKind.UNDERSCORE):
                    names.append(tokens[pos].value)
                    pos += 1
                if tokens[pos].kind == TokenKind.COLON:
                    pos += 1
                    pos, ty = self._expr(tokens, pos, current_binders, 0)
                    for name in names:
                        all_pairs.append((name, ty))
                        current_binders.append(name)
                else:
                    # Untyped binders (fun x => ...) — default type Sort("Type")
                    for name in names:
                        all_pairs.append((name, Sort("Type")))
                        current_binders.append(name)
                break  # unparenthesized group ends binder list

            # No more binder groups
            break

        return pos, all_pairs

    def _parse_forall(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse ``forall (binders), body``."""
        pos += 1  # consume 'forall'

        pos, pairs = self._parse_binder_groups(
            tokens, pos, binders, TokenKind.COMMA
        )
        if not pairs:
            raise ParseError(
                f"Expected binder after 'forall' at position {tokens[pos].pos}"
            )

        if tokens[pos].kind != TokenKind.COMMA:
            raise ParseError(
                f"Expected ',' at position {tokens[pos].pos}"
            )
        pos += 1  # consume ','

        # Build binder stack for body
        body_binders = binders + [name for name, _ in pairs]
        pos, body = self._expr(tokens, pos, body_binders, 0)

        # Build nested Prod from right to left
        result = body
        for name, ty in reversed(pairs):
            result = Prod(name, ty, result)

        return pos, result

    def _parse_fun(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse ``fun (binders) => body``."""
        pos += 1  # consume 'fun'

        pos, pairs = self._parse_binder_groups(
            tokens, pos, binders, TokenKind.DARROW
        )
        if not pairs:
            raise ParseError(
                f"Expected binder after 'fun' at position {tokens[pos].pos}"
            )

        if tokens[pos].kind not in (TokenKind.DARROW, TokenKind.COMMA):
            raise ParseError(
                f"Expected '=>' or ',' at position {tokens[pos].pos}"
            )
        pos += 1  # consume '=>' or ','

        # Build binder stack for body
        body_binders = binders + [name for name, _ in pairs]
        pos, body = self._expr(tokens, pos, body_binders, 0)

        # Build nested Lambda from right to left
        result = body
        for name, ty in reversed(pairs):
            result = Lambda(name, ty, result)

        return pos, result

    def _parse_exists(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse ``exists (binders), body`` — treated as Prod for indexing."""
        pos += 1  # consume 'exists'

        pos, pairs = self._parse_binder_groups(
            tokens, pos, binders, TokenKind.COMMA
        )
        if not pairs:
            raise ParseError(
                f"Expected binder after 'exists' at position {tokens[pos].pos}"
            )

        if tokens[pos].kind != TokenKind.COMMA:
            raise ParseError(
                f"Expected ',' at position {tokens[pos].pos}"
            )
        pos += 1  # consume ','

        # Build binder stack for body
        body_binders = binders + [name for name, _ in pairs]
        pos, body = self._expr(tokens, pos, body_binders, 0)

        # Build nested Prod from right to left (structurally same as forall)
        result = body
        for name, ty in reversed(pairs):
            result = Prod(name, ty, result)

        return pos, result

    def _parse_let(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Parse ``let name := value in body``.

        Since 'in' is tokenized as IDENT and the expression parser
        would greedily consume it, we scan ahead for the 'in' token
        at depth 0 and parse only the body (the structurally important
        part for indexing).
        """
        # Skip 'let' and everything up to 'in', then parse body
        return self._skip_let_to_in(tokens, pos + 1, binders)

    def _skip_match(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Skip ``match ... with ... end`` and return a placeholder."""
        depth = 1
        pos += 1  # consume 'match'
        while tokens[pos].kind != TokenKind.EOF:
            if (tokens[pos].kind == TokenKind.IDENT
                    and tokens[pos].value == "match"):
                depth += 1
            elif (tokens[pos].kind == TokenKind.IDENT
                  and tokens[pos].value == "end"):
                depth -= 1
                if depth == 0:
                    pos += 1  # consume 'end'
                    return pos, Const("_match_")
            pos += 1
        return pos, Const("_match_")

    def _skip_let_to_in(
        self,
        tokens: list[Token],
        pos: int,
        binders: list[str],
    ) -> tuple[int, Any]:
        """Skip a destructuring let to the 'in' keyword and parse body."""
        depth = 0
        while tokens[pos].kind != TokenKind.EOF:
            if tokens[pos].kind in (TokenKind.LPAREN, TokenKind.LBRACE):
                depth += 1
            elif tokens[pos].kind in (TokenKind.RPAREN, TokenKind.RBRACE):
                depth -= 1
            elif (depth == 0
                  and tokens[pos].kind == TokenKind.IDENT
                  and tokens[pos].value == "in"):
                pos += 1  # consume 'in'
                return self._expr(tokens, pos, binders, 0)
            pos += 1
        # Couldn't find 'in' — return a placeholder
        return pos, Const("_let_")

    # ----- Name resolution -----

    @staticmethod
    def _resolve(name: str, binders: list[str]) -> Any:
        """Resolve a name against the binder stack.

        Returns ``Rel(n)`` for bound names (1-based de Bruijn index)
        or ``Const(name)`` for unbound names.
        """
        for i, binder_name in enumerate(reversed(binders)):
            if binder_name == name:
                return Rel(i + 1)
        return Const(name)
