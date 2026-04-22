#!/usr/bin/env python3
"""
Logo Language Interpreter
Implements a substantial subset of UCBLogo/MSWLogo.
"""
import math
import re
import random
from typing import Any, Callable, Dict, List, Optional, Tuple


# ─── 256-colour palette (xterm standard) ─────────────────────────────────────

def _build_palette() -> List[str]:
    """
    Build the standard xterm 256-colour palette as Tk '#rrggbb' strings.

      0-15   : system colours (traditional Logo / MSWLogo names kept for 0-15)
     16-231  : 6x6x6 RGB cube
    232-255  : 24-step greyscale ramp
    """
    # 0-15: traditional Logo/MSWLogo-compatible system colours
    system = [
        (  0,   0,   0),   #  0  black
        (  0,   0, 128),   #  1  navy / dark blue
        (  0, 128,   0),   #  2  green
        (  0, 128, 128),   #  3  teal / cyan
        (128,   0,   0),   #  4  maroon / dark red
        (128,   0, 128),   #  5  purple / magenta
        (128, 128,   0),   #  6  olive / brown-yellow
        (192, 192, 192),   #  7  silver / light grey
        (128, 128, 128),   #  8  grey
        (  0,   0, 255),   #  9  blue
        (  0, 255,   0),   # 10  lime / bright green
        (  0, 255, 255),   # 11  cyan / aqua
        (255,   0,   0),   # 12  red
        (255,   0, 255),   # 13  magenta / fuchsia
        (255, 255,   0),   # 14  yellow
        (255, 255, 255),   # 15  white
    ]
    palette = ['#{:02x}{:02x}{:02x}'.format(*rgb) for rgb in system]

    # 16-231: 6x6x6 colour cube
    _levels = [0, 95, 135, 175, 215, 255]
    for r in range(6):
        for g in range(6):
            for b in range(6):
                palette.append('#{:02x}{:02x}{:02x}'.format(
                    _levels[r], _levels[g], _levels[b]))

    # 232-255: 24-step greyscale ramp (8..238 in steps of 10)
    for i in range(24):
        v = 8 + i * 10
        palette.append('#{:02x}{:02x}{:02x}'.format(v, v, v))

    return palette


LOGO_PALETTE: List[str] = _build_palette()   # 256 entries, module-level constant


# ─── Signals ──────────────────────────────────────────────────────────────────

class LogoError(Exception):
    """Runtime error in Logo code."""

class StopSignal(Exception):
    """Raised by STOP to exit a procedure."""

class OutputSignal(Exception):
    """Raised by OUTPUT to return a value from a procedure."""
    def __init__(self, value: Any):
        self.value = value


# ─── Token types ──────────────────────────────────────────────────────────────

T_NUMBER  = 'NUMBER'   # 42  3.14
T_WORD    = 'WORD'     # "hello  (quoted)
T_VAR     = 'VAR'      # :x  :count
T_NAME    = 'NAME'     # FORWARD  TO  user_proc
T_LBRACK  = '['
T_RBRACK  = ']'
T_LPAREN  = '('
T_RPAREN  = ')'
T_OP      = 'OP'       # + - * / = < > <= >= <>
T_EOF     = 'EOF'


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, type_: str, value: Any, line: int = 0):
        self.type = type_
        self.value = value
        self.line = line

    def __repr__(self) -> str:
        return f'Token({self.type}, {self.value!r})'


# ─── Lexer ────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r'(?P<COMMENT>;[^\n]*)'
    r'|(?P<WS>[ \t\r\n]+)'
    r'|(?P<LINE_CONT>~[ \t]*\n)'
    r'|(?P<LBRACK>\[)'
    r'|(?P<RBRACK>\])'
    r'|(?P<LPAREN>\()'
    r'|(?P<RPAREN>\))'
    r'|(?P<WORD>"[^ \t\r\n\[\]()]*)'
    r'|(?P<VAR>:[A-Za-z_][A-Za-z0-9_.]*)'
    r'|(?P<NUMBER>-?\d+\.?\d*(?:[eE][+-]?\d+)?)'
    r'|(?P<OP><=|>=|<>|[+\-*/=<>])'
    r'|(?P<NAME>[A-Za-z_][A-Za-z0-9_?!.]*)'
    r'|(?P<UNKNOWN>.)'
)


def tokenize(source: str) -> List[Token]:
    tokens: List[Token] = []
    line = 1
    for m in _TOKEN_RE.finditer(source):
        kind = m.lastgroup
        val = m.group()

        if kind in ('COMMENT', 'WS', 'LINE_CONT'):
            line += val.count('\n')
            continue

        if kind == 'NUMBER':
            tokens.append(Token(T_NUMBER,
                float(val) if ('.' in val or 'e' in val.lower()) else int(val),
                line))
        elif kind == 'WORD':
            tokens.append(Token(T_WORD, val[1:], line))   # strip leading "
        elif kind == 'VAR':
            tokens.append(Token(T_VAR, val[1:].lower(), line))  # strip :
        elif kind == 'NAME':
            tokens.append(Token(T_NAME, val.upper(), line))
        elif kind == 'LBRACK':
            tokens.append(Token(T_LBRACK, val, line))
        elif kind == 'RBRACK':
            tokens.append(Token(T_RBRACK, val, line))
        elif kind == 'LPAREN':
            tokens.append(Token(T_LPAREN, val, line))
        elif kind == 'RPAREN':
            tokens.append(Token(T_RPAREN, val, line))
        elif kind == 'OP':
            tokens.append(Token(T_OP, val, line))
        elif kind == 'UNKNOWN':
            raise LogoError(f"Unknown character: {val!r} at line {line}")

    tokens.append(Token(T_EOF, None, line))
    return tokens


# ─── Turtle state ─────────────────────────────────────────────────────────────

class TurtleState:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0    # 0=North, 90=East, clockwise
        self.pen_down = True
        self.pen_color = 'black'
        self.pen_size = 1
        self.visible = True
        self.fill_color = 'black'
        self.bg_color = 'white'

    def forward(self, dist: float) -> Tuple[float, float, float, float]:
        rad = math.radians(self.heading)
        ox, oy = self.x, self.y
        self.x += math.sin(rad) * dist
        self.y += math.cos(rad) * dist
        return ox, oy, self.x, self.y

    def right(self, deg: float):
        self.heading = (self.heading + deg) % 360

    def left(self, deg: float):
        self.heading = (self.heading - deg) % 360


# ─── Interpreter ─────────────────────────────────────────────────────────────

# Sentinel: this built-in name was not found
_NOT_FOUND = object()


class LogoInterpreter:
    """
    Full Logo interpreter.

    draw_callback(cmd, *args)  – called for every drawing operation
    print_callback(text)       – called for PRINT / SHOW / TYPE output
    """

    def __init__(self,
                 draw_callback: Optional[Callable] = None,
                 print_callback: Optional[Callable] = None):
        self.draw_cb   = draw_callback  or (lambda *a: None)
        self.print_cb  = print_callback or print

        self.turtle    = TurtleState()
        self.globals: Dict[str, Any]  = {}
        self.procs:   Dict[str, dict] = {}   # user-defined procedures
        self.call_stack: List[Dict[str, Any]] = []

        self._stop_requested = False
        self._running        = False

    # ── Public API ──────────────────────────────────────────────────────────

    def reset(self):
        self.turtle    = TurtleState()
        self.globals   = {}
        self.procs     = {}
        self.call_stack = []
        self._stop_requested = False
        self.draw_cb('CLEARSCREEN', 'white')

    def reset_turtle_only(self):
        """Clear the screen but keep procedures/variables."""
        self.turtle = TurtleState()
        self._stop_requested = False
        self.draw_cb('CLEARSCREEN', self.turtle.bg_color)

    def stop(self):
        self._stop_requested = True

    def run(self, source: str) -> Optional[str]:
        """Execute Logo source. Returns error string or None."""
        self._stop_requested = False
        self._running = True
        try:
            tokens = tokenize(source)
            pos = 0
            while tokens[pos].type != T_EOF:
                if self._stop_requested:
                    return "Execution stopped."
                _, pos = self._run_stmt(tokens, pos, self.globals)
            return None
        except LogoError as e:
            return str(e)
        except StopSignal:
            return None
        except OutputSignal:
            return "OUTPUT used outside a procedure."
        except Exception as e:
            return f"Internal error: {e}"
        finally:
            self._running = False

    # ── Statement runner ────────────────────────────────────────────────────

    def _run_stmt(self, tokens: List[Token], pos: int, env: Dict
                  ) -> Tuple[Any, int]:
        """Execute one statement, return (value, new_pos)."""
        if self._stop_requested:
            raise StopSignal()

        tok = tokens[pos]

        if tok.type == T_NAME:
            name = tok.value
            pos += 1
            if name == 'TO':
                return self._define_proc(tokens, pos)
            return self._call_cmd(name, tokens, pos, env)

        if tok.type in (T_NUMBER, T_VAR, T_WORD, T_LBRACK, T_LPAREN):
            # Expression at top level – evaluate and discard
            val, pos = self._eval_expr(tokens, pos, env)
            return val, pos

        if tok.type == T_OP:
            val, pos = self._eval_expr(tokens, pos, env)
            return val, pos

        if tok.type == T_EOF:
            return None, pos

        raise LogoError(f"Unexpected token {tok.value!r} at line {tok.line}")

    def _run_block(self, tokens: List[Token], pos: int, env: Dict
                   ) -> Tuple[Any, int]:
        """Run statements until ] or EOF, return (last_value, new_pos)."""
        last = None
        while pos < len(tokens) and tokens[pos].type not in (T_RBRACK, T_EOF):
            if self._stop_requested:
                raise StopSignal()
            last, pos = self._run_stmt(tokens, pos, env)
        return last, pos

    # ── List reading ────────────────────────────────────────────────────────

    def _read_list_tokens(self, tokens: List[Token], pos: int
                          ) -> Tuple[List[Token], int]:
        """Consume [...] and return the inner token list (with EOF appended)."""
        assert tokens[pos].type == T_LBRACK
        pos += 1  # skip [
        depth = 1
        result: List[Token] = []
        while pos < len(tokens):
            t = tokens[pos]
            if t.type == T_LBRACK:
                depth += 1
                result.append(t)
                pos += 1
            elif t.type == T_RBRACK:
                depth -= 1
                if depth == 0:
                    result.append(Token(T_EOF, None, t.line))
                    return result, pos + 1
                result.append(t)
                pos += 1
            elif t.type == T_EOF:
                raise LogoError("Unexpected end of input inside [ ]")
            else:
                result.append(t)
                pos += 1
        raise LogoError("Unterminated [ ]")

    # ── Expression evaluation ───────────────────────────────────────────────

    def _eval_expr(self, tokens: List[Token], pos: int, env: Dict
                   ) -> Tuple[Any, int]:
        return self._parse_cmp(tokens, pos, env)

    def _parse_cmp(self, tokens, pos, env):
        left, pos = self._parse_add(tokens, pos, env)
        while (pos < len(tokens)
               and tokens[pos].type == T_OP
               and tokens[pos].value in ('=', '<', '>', '<=', '>=', '<>')):
            op = tokens[pos].value
            pos += 1
            right, pos = self._parse_add(tokens, pos, env)
            left = self._apply_op(op, left, right)
        return left, pos

    def _parse_add(self, tokens, pos, env):
        left, pos = self._parse_mul(tokens, pos, env)
        while (pos < len(tokens)
               and tokens[pos].type == T_OP
               and tokens[pos].value in ('+', '-')):
            op = tokens[pos].value
            pos += 1
            right, pos = self._parse_mul(tokens, pos, env)
            left = self._apply_op(op, left, right)
        return left, pos

    def _parse_mul(self, tokens, pos, env):
        left, pos = self._parse_unary(tokens, pos, env)
        while (pos < len(tokens)
               and tokens[pos].type == T_OP
               and tokens[pos].value in ('*', '/')):
            op = tokens[pos].value
            pos += 1
            right, pos = self._parse_unary(tokens, pos, env)
            left = self._apply_op(op, left, right)
        return left, pos

    def _parse_unary(self, tokens, pos, env):
        if tokens[pos].type == T_OP and tokens[pos].value == '-':
            pos += 1
            val, pos = self._parse_primary(tokens, pos, env)
            return -self._to_num(val), pos
        return self._parse_primary(tokens, pos, env)

    def _parse_primary(self, tokens, pos, env):
        tok = tokens[pos]

        if tok.type == T_NUMBER:
            return tok.value, pos + 1

        if tok.type == T_WORD:
            return tok.value, pos + 1

        if tok.type == T_VAR:
            return self._get_var(tok.value, env), pos + 1

        if tok.type == T_LBRACK:
            lst, pos = self._read_list_tokens(tokens, pos)
            return lst, pos

        if tok.type == T_LPAREN:
            pos += 1  # skip (
            val, pos = self._eval_expr(tokens, pos, env)
            if tokens[pos].type != T_RPAREN:
                raise LogoError(
                    f"Expected ')' at line {tokens[pos].line}")
            return val, pos + 1

        if tok.type == T_NAME:
            # Reporter (function that returns a value)
            name = tok.value
            pos += 1
            val, pos, handled = self._try_builtin(name, tokens, pos, env)
            if handled:
                if val is None:
                    raise LogoError(f"{name} is a command, not a reporter")
                return val, pos
            if name in self.procs:
                val, pos = self._call_user_proc(name, tokens, pos, env)
                if val is None:
                    raise LogoError(f"Procedure {name} didn't OUTPUT a value")
                return val, pos
            raise LogoError(f"Unknown function: {name}")

        raise LogoError(
            f"Expected value, got {tok.type}={tok.value!r} at line {tok.line}")

    def _apply_op(self, op: str, left: Any, right: Any) -> Any:
        if op == '+':
            if isinstance(left, str) or isinstance(right, str):
                return str(left) + str(right)
            return self._to_num(left) + self._to_num(right)
        if op == '-':  return self._to_num(left) - self._to_num(right)
        if op == '*':  return self._to_num(left) * self._to_num(right)
        if op == '/':
            r = self._to_num(right)
            if r == 0:
                raise LogoError("Division by zero")
            return self._to_num(left) / r
        if op == '=':  return left == right
        if op == '<':  return self._to_num(left) < self._to_num(right)
        if op == '>':  return self._to_num(left) > self._to_num(right)
        if op == '<=': return self._to_num(left) <= self._to_num(right)
        if op == '>=': return self._to_num(left) >= self._to_num(right)
        if op == '<>': return left != right
        raise LogoError(f"Unknown operator: {op}")

    # ── Variables ────────────────────────────────────────────────────────────

    def _get_var(self, name: str, env: Dict) -> Any:
        name = name.lower()
        if name in env:
            return env[name]
        for frame in reversed(self.call_stack):
            if name in frame:
                return frame[name]
        if name in self.globals:
            return self.globals[name]
        raise LogoError(f"Variable :{name} has no value")

    def _set_var(self, name: str, value: Any, local: bool = False):
        name = name.lower()
        if local and self.call_stack:
            self.call_stack[-1][name] = value
            return
        # Find existing binding
        for frame in reversed(self.call_stack):
            if name in frame:
                frame[name] = value
                return
        self.globals[name] = value

    # ── Type helpers ─────────────────────────────────────────────────────────

    def _to_num(self, val: Any) -> float:
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass
        raise LogoError(f"Expected a number, got {val!r}")

    def _to_bool(self, val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.upper() not in ('FALSE', '0', '')
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)

    def _to_display(self, val: Any) -> str:
        if isinstance(val, bool):
            return 'true' if val else 'false'
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        if isinstance(val, list):
            items = self._list_items(val)
            return '[' + ' '.join(self._to_display(v) for v in items) + ']'
        return str(val)

    # ── Procedure definition ─────────────────────────────────────────────────

    def _define_proc(self, tokens: List[Token], pos: int) -> Tuple[None, int]:
        if tokens[pos].type != T_NAME:
            raise LogoError("Expected procedure name after TO")
        name = tokens[pos].value
        pos += 1
        params: List[str] = []
        while tokens[pos].type == T_VAR:
            params.append(tokens[pos].value.lower())
            pos += 1
        body: List[Token] = []
        while tokens[pos].type != T_EOF:
            t = tokens[pos]
            if t.type == T_NAME and t.value == 'END':
                pos += 1
                break
            body.append(t)
            pos += 1
        else:
            raise LogoError(f"Missing END for procedure {name}")
        body.append(Token(T_EOF, None))
        self.procs[name] = {'params': params, 'body': body}
        return None, pos

    # ── Procedure call ───────────────────────────────────────────────────────

    def _call_cmd(self, name: str, tokens: List[Token], pos: int, env: Dict
                  ) -> Tuple[Any, int]:
        val, pos, handled = self._try_builtin(name, tokens, pos, env)
        if handled:
            return val, pos
        if name in self.procs:
            val, pos = self._call_user_proc(name, tokens, pos, env)
            return val, pos
        raise LogoError(f"Unknown command: {name}")

    def _call_user_proc(self, name: str, tokens: List[Token], pos: int,
                        env: Dict) -> Tuple[Any, int]:
        proc = self.procs[name]
        args: List[Any] = []
        for _ in proc['params']:
            arg, pos = self._eval_expr(tokens, pos, env)
            args.append(arg)
        local_env: Dict[str, Any] = {}
        for pname, pval in zip(proc['params'], args):
            local_env[pname] = pval
        self.call_stack.append(local_env)
        try:
            self._run_block(proc['body'], 0, local_env)
            return None, pos
        except StopSignal:
            return None, pos
        except OutputSignal as sig:
            return sig.value, pos
        finally:
            self.call_stack.pop()

    # ── List helpers ─────────────────────────────────────────────────────────

    def _list_items(self, token_list: List[Token]) -> List[Any]:
        """Parse a token list into Logo values (for FIRST, LAST, etc.)."""
        items: List[Any] = []
        pos = 0
        while pos < len(token_list) and token_list[pos].type != T_EOF:
            tok = token_list[pos]
            if tok.type == T_LBRACK:
                sub, pos = self._read_list_tokens(token_list, pos)
                items.append(sub)
            elif tok.type == T_NUMBER:
                items.append(tok.value)
                pos += 1
            elif tok.type == T_WORD:
                items.append(tok.value)
                pos += 1
            elif tok.type == T_NAME:
                items.append(tok.value)
                pos += 1
            elif tok.type == T_VAR:
                items.append(':' + tok.value)
                pos += 1
            else:
                pos += 1
        return items

    def _items_to_tokens(self, items: List[Any]) -> List[Token]:
        """Convert Logo values back to tokens (for FPUT, LPUT, etc.)."""
        result: List[Token] = []
        for item in items:
            if isinstance(item, list):
                result.append(Token(T_LBRACK, '['))
                result.extend(item[:-1])  # exclude EOF
                result.append(Token(T_RBRACK, ']'))
            elif isinstance(item, (int, float)):
                result.append(Token(T_NUMBER, item))
            elif isinstance(item, str):
                result.append(Token(T_NAME, item))
            elif isinstance(item, bool):
                result.append(Token(T_NAME, 'TRUE' if item else 'FALSE'))
        result.append(Token(T_EOF, None))
        return result

    def _parse_color(self, val: Any) -> str:
        """
        Convert a Logo colour value to a Tk '#rrggbb' string.

        Accepted forms:
          integer 0-255   -> LOGO_PALETTE entry
          string "red     -> passed straight to Tk (named colour)
          list [r g b]    -> r/g/b each 0-255
        """
        if isinstance(val, (int, float)):
            idx = int(val) % 256          # wrap so e.g. 256 -> 0
            return LOGO_PALETTE[idx]
        if isinstance(val, str):
            return val.lower()
        if isinstance(val, list):
            items = self._list_items(val)
            if len(items) >= 3:
                r = min(255, max(0, int(self._to_num(items[0]))))
                g = min(255, max(0, int(self._to_num(items[1]))))
                b = min(255, max(0, int(self._to_num(items[2]))))
                return f'#{r:02x}{g:02x}{b:02x}'
        return '#000000'

    # ── Built-in dispatch ────────────────────────────────────────────────────

    def _try_builtin(self, name: str, tokens: List[Token], pos: int, env: Dict
                     ) -> Tuple[Any, int, bool]:
        """
        Try to execute a built-in command or reporter.
        Returns (result, new_pos, handled).
        """
        t = self.turtle

        def e1():
            nonlocal pos
            v, pos = self._eval_expr(tokens, pos, env)
            return v

        def e2():
            nonlocal pos
            a, pos = self._eval_expr(tokens, pos, env)
            b, pos = self._eval_expr(tokens, pos, env)
            return a, b

        def elist():
            nonlocal pos
            v, pos = self._eval_expr(tokens, pos, env)
            if not isinstance(v, list):
                raise LogoError("Expected a [ ] list")
            return v

        def draw_line(ox, oy, nx, ny):
            if t.pen_down:
                self.draw_cb('LINE', ox, oy, nx, ny, t.pen_color, t.pen_size)
            self.draw_cb('TURTLE', nx, ny, t.heading, t.visible)

        # ── Turtle motion ─────────────────────────────────────────────────────

        if name in ('FORWARD', 'FD'):
            dist = self._to_num(e1())
            ox, oy, nx, ny = t.forward(dist)
            draw_line(ox, oy, nx, ny)
            return None, pos, True

        if name in ('BACKWARD', 'BACK', 'BK'):
            dist = self._to_num(e1())
            ox, oy, nx, ny = t.forward(-dist)
            draw_line(ox, oy, nx, ny)
            return None, pos, True

        if name in ('RIGHT', 'RT'):
            t.right(self._to_num(e1()))
            self.draw_cb('TURTLE', t.x, t.y, t.heading, t.visible)
            return None, pos, True

        if name in ('LEFT', 'LT'):
            t.left(self._to_num(e1()))
            self.draw_cb('TURTLE', t.x, t.y, t.heading, t.visible)
            return None, pos, True

        if name in ('SETHEADING', 'SETH'):
            t.heading = self._to_num(e1()) % 360
            self.draw_cb('TURTLE', t.x, t.y, t.heading, t.visible)
            return None, pos, True

        if name == 'HOME':
            ox, oy = t.x, t.y
            t.x = t.y = t.heading = 0.0
            draw_line(ox, oy, 0.0, 0.0)
            return None, pos, True

        if name == 'SETXY':
            nx, ny = e2()
            ox, oy = t.x, t.y
            t.x, t.y = self._to_num(nx), self._to_num(ny)
            draw_line(ox, oy, t.x, t.y)
            return None, pos, True

        if name == 'SETX':
            nx = self._to_num(e1())
            ox, oy = t.x, t.y
            t.x = nx
            draw_line(ox, oy, t.x, t.y)
            return None, pos, True

        if name == 'SETY':
            ny = self._to_num(e1())
            ox, oy = t.x, t.y
            t.y = ny
            draw_line(ox, oy, t.x, t.y)
            return None, pos, True

        if name == 'ARC':
            angle, radius = e2()
            self.draw_cb('ARC', t.x, t.y, t.heading,
                         self._to_num(angle), self._to_num(radius),
                         t.pen_color if t.pen_down else None, t.pen_size)
            return None, pos, True

        # ── Pen control ───────────────────────────────────────────────────────

        if name in ('PENUP', 'PU'):
            t.pen_down = False
            return None, pos, True

        if name in ('PENDOWN', 'PD'):
            t.pen_down = True
            return None, pos, True

        if name in ('PENSIZE', 'SETPENSIZE'):
            t.pen_size = max(1, int(self._to_num(e1())))
            return None, pos, True

        if name in ('SETPENCOLOR', 'SETPC', 'PC'):
            t.pen_color = self._parse_color(e1())
            return None, pos, True

        if name in ('SETFILLCOLOR', 'SETFC'):
            t.fill_color = self._parse_color(e1())
            return None, pos, True

        if name in ('SETBACKGROUND', 'SETBG', 'BG', 'SETBGCOLOR'):
            t.bg_color = self._parse_color(e1())
            self.draw_cb('BACKGROUND', t.bg_color)
            return None, pos, True

        if name == 'FILL':
            self.draw_cb('FILL', t.x, t.y, t.fill_color)
            return None, pos, True

        # ── Screen control ────────────────────────────────────────────────────

        if name in ('CLEARSCREEN', 'CS'):
            t.x = t.y = 0.0
            t.heading = 0.0
            self.draw_cb('CLEARSCREEN', t.bg_color)
            self.draw_cb('TURTLE', 0, 0, 0, t.visible)
            return None, pos, True

        if name == 'CLEAN':
            self.draw_cb('CLEAN', t.bg_color)
            self.draw_cb('TURTLE', t.x, t.y, t.heading, t.visible)
            return None, pos, True

        if name in ('HIDETURTLE', 'HT'):
            t.visible = False
            self.draw_cb('TURTLE', t.x, t.y, t.heading, False)
            return None, pos, True

        if name in ('SHOWTURTLE', 'ST'):
            t.visible = True
            self.draw_cb('TURTLE', t.x, t.y, t.heading, True)
            return None, pos, True

        # ── Reporters: turtle position ────────────────────────────────────────

        if name == 'XCOR':
            return t.x, pos, True

        if name == 'YCOR':
            return t.y, pos, True

        if name == 'HEADING':
            return t.heading, pos, True

        if name == 'PENDOWNP':
            return t.pen_down, pos, True

        # ── Variables ─────────────────────────────────────────────────────────

        if name == 'MAKE':
            varname = e1()
            if not isinstance(varname, str):
                raise LogoError("MAKE: first arg must be a quoted word")
            value = e1()
            self._set_var(varname.lower(), value)
            return None, pos, True

        if name == 'LOCAL':
            varname = e1()
            if not isinstance(varname, str):
                raise LogoError("LOCAL: expected a quoted word")
            if self.call_stack:
                self.call_stack[-1][varname.lower()] = 0
            return None, pos, True

        if name == 'LOCALMAKE':
            varname = e1()
            value = e1()
            if not isinstance(varname, str):
                raise LogoError("LOCALMAKE: first arg must be a quoted word")
            self._set_var(varname.lower(), value, local=True)
            return None, pos, True

        if name == 'THING':
            varname = e1()
            return self._get_var(str(varname).lower(), env), pos, True

        # ── Control flow ──────────────────────────────────────────────────────

        if name == 'REPEAT':
            count = int(self._to_num(e1()))
            block = elist()
            loop_env = dict(env)
            for i in range(count):
                if self._stop_requested:
                    break
                loop_env['repcount'] = i + 1
                try:
                    self._run_block(block, 0, loop_env)
                except StopSignal:
                    break
            return None, pos, True

        if name == 'FOREVER':
            block = elist()
            while not self._stop_requested:
                try:
                    self._run_block(block, 0, dict(env))
                except StopSignal:
                    break
            return None, pos, True

        if name in ('IF', 'IFTRUE', 'IFT'):
            cond = self._to_bool(e1())
            block = elist()
            if cond:
                self._run_block(block, 0, dict(env))
            return None, pos, True

        if name in ('IFFALSE', 'IFF'):
            cond = self._to_bool(e1())
            block = elist()
            if not cond:
                self._run_block(block, 0, dict(env))
            return None, pos, True

        if name == 'IFELSE':
            cond = self._to_bool(e1())
            true_block  = elist()
            false_block = elist()
            if cond:
                self._run_block(true_block, 0, dict(env))
            else:
                self._run_block(false_block, 0, dict(env))
            return None, pos, True

        if name == 'WHILE':
            cond_block = elist()
            body_block = elist()
            while not self._stop_requested:
                cond_val, _ = self._run_block(cond_block, 0, dict(env))
                if not self._to_bool(cond_val):
                    break
                try:
                    self._run_block(body_block, 0, dict(env))
                except StopSignal:
                    break
            return None, pos, True

        if name == 'UNTIL':
            cond_block = elist()
            body_block = elist()
            while not self._stop_requested:
                try:
                    self._run_block(body_block, 0, dict(env))
                except StopSignal:
                    break
                cond_val, _ = self._run_block(cond_block, 0, dict(env))
                if self._to_bool(cond_val):
                    break
            return None, pos, True

        if name == 'FOR':
            # FOR [var start end] body  or  FOR [var start end step] body
            for_list = elist()
            body_block = elist()
            items = self._list_items(for_list)
            if len(items) < 3:
                raise LogoError("FOR: needs [var start end] or [var start end step]")
            varname = str(items[0]).lower()
            start = self._to_num(items[1])
            end   = self._to_num(items[2])
            step  = self._to_num(items[3]) if len(items) > 3 else (1 if start <= end else -1)
            i = start
            while not self._stop_requested:
                if step > 0 and i > end: break
                if step < 0 and i < end: break
                loop_env = dict(env)
                loop_env[varname] = i
                try:
                    self._run_block(body_block, 0, loop_env)
                except StopSignal:
                    break
                i += step
            return None, pos, True

        if name == 'RUN':
            block = elist()
            self._run_block(block, 0, dict(env))
            return None, pos, True

        # ── Procedure control ─────────────────────────────────────────────────

        if name == 'STOP':
            raise StopSignal()

        if name in ('OUTPUT', 'OP'):
            raise OutputSignal(e1())

        # ── Output ────────────────────────────────────────────────────────────

        if name in ('PRINT', 'PR'):
            val = e1()
            self.print_cb(self._to_display(val) + '\n')
            return None, pos, True

        if name == 'SHOW':
            val = e1()
            self.print_cb(self._to_display(val) + '\n')
            return None, pos, True

        if name == 'TYPE':
            val = e1()
            self.print_cb(self._to_display(val))
            return None, pos, True

        if name == 'NEWLINE':
            self.print_cb('\n')
            return None, pos, True

        # ── Math reporters ────────────────────────────────────────────────────

        if name == 'SUM':
            a, b = e2()
            return self._to_num(a) + self._to_num(b), pos, True

        if name == 'DIFFERENCE':
            a, b = e2()
            return self._to_num(a) - self._to_num(b), pos, True

        if name == 'PRODUCT':
            a, b = e2()
            return self._to_num(a) * self._to_num(b), pos, True

        if name == 'QUOTIENT':
            a, b = e2()
            b = self._to_num(b)
            if b == 0: raise LogoError("Division by zero")
            return self._to_num(a) / b, pos, True

        if name in ('REMAINDER', 'MODULO'):
            a, b = e2()
            return self._to_num(a) % self._to_num(b), pos, True

        if name == 'POWER':
            a, b = e2()
            return self._to_num(a) ** self._to_num(b), pos, True

        if name == 'MINUS':
            return -self._to_num(e1()), pos, True

        if name == 'ABS':
            return abs(self._to_num(e1())), pos, True

        if name in ('INT', 'TRUNCATE'):
            return int(self._to_num(e1())), pos, True

        if name == 'ROUND':
            return round(self._to_num(e1())), pos, True

        if name == 'FLOOR':
            return math.floor(self._to_num(e1())), pos, True

        if name == 'CEILING':
            return math.ceil(self._to_num(e1())), pos, True

        if name == 'SQRT':
            v = self._to_num(e1())
            if v < 0: raise LogoError("SQRT of negative number")
            return math.sqrt(v), pos, True

        if name == 'SIN':
            return math.sin(math.radians(self._to_num(e1()))), pos, True

        if name == 'COS':
            return math.cos(math.radians(self._to_num(e1()))), pos, True

        if name == 'TAN':
            return math.tan(math.radians(self._to_num(e1()))), pos, True

        if name == 'ARCTAN':
            return math.degrees(math.atan(self._to_num(e1()))), pos, True

        if name == 'ARCTAN2':
            a, b = e2()
            return math.degrees(math.atan2(self._to_num(a), self._to_num(b))), pos, True

        if name == 'ARCSIN':
            v = self._to_num(e1())
            if not -1 <= v <= 1: raise LogoError("ARCSIN: value out of range [-1,1]")
            return math.degrees(math.asin(v)), pos, True

        if name == 'ARCCOS':
            v = self._to_num(e1())
            if not -1 <= v <= 1: raise LogoError("ARCCOS: value out of range [-1,1]")
            return math.degrees(math.acos(v)), pos, True

        if name == 'EXP':
            return math.exp(self._to_num(e1())), pos, True

        if name == 'LOG':
            v = self._to_num(e1())
            if v <= 0: raise LogoError("LOG of non-positive number")
            return math.log(v), pos, True

        if name == 'LOG10':
            v = self._to_num(e1())
            return math.log10(v), pos, True

        if name == 'PI':
            return math.pi, pos, True

        if name == 'RANDOM':
            n = int(self._to_num(e1()))
            return random.randint(0, max(0, n - 1)), pos, True

        if name == 'RERANDOM':
            seed = int(self._to_num(e1()))
            random.seed(seed)
            return None, pos, True

        if name == 'MAX':
            a, b = e2()
            return max(self._to_num(a), self._to_num(b)), pos, True

        if name == 'MIN':
            a, b = e2()
            return min(self._to_num(a), self._to_num(b)), pos, True

        # ── Comparison / logic ────────────────────────────────────────────────

        if name in ('EQUALP', 'EQUAL?'):
            a, b = e2()
            return a == b, pos, True

        if name in ('LESSP', 'LESS?'):
            a, b = e2()
            return self._to_num(a) < self._to_num(b), pos, True

        if name in ('GREATERP', 'GREATER?'):
            a, b = e2()
            return self._to_num(a) > self._to_num(b), pos, True

        if name == 'AND':
            a, b = e2()
            return self._to_bool(a) and self._to_bool(b), pos, True

        if name == 'OR':
            a, b = e2()
            return self._to_bool(a) or self._to_bool(b), pos, True

        if name == 'NOT':
            return not self._to_bool(e1()), pos, True

        if name == 'TRUE':
            return True, pos, True

        if name == 'FALSE':
            return False, pos, True

        # ── Type predicates ───────────────────────────────────────────────────

        if name in ('NUMBERP', 'NUMBER?'):
            v = e1()
            return isinstance(v, (int, float)) and not isinstance(v, bool), pos, True

        if name in ('WORDP', 'WORD?'):
            v = e1()
            return isinstance(v, str), pos, True

        if name in ('LISTP', 'LIST?'):
            v = e1()
            return isinstance(v, list), pos, True

        if name in ('EMPTYP', 'EMPTY?'):
            v = e1()
            if isinstance(v, list):
                return len(self._list_items(v)) == 0, pos, True
            if isinstance(v, str):
                return len(v) == 0, pos, True
            return False, pos, True

        if name in ('ZEROP', 'ZERO?'):
            return self._to_num(e1()) == 0, pos, True

        if name in ('NEGATIVEP', 'NEGATIVE?'):
            return self._to_num(e1()) < 0, pos, True

        if name in ('POSITIVEP', 'POSITIVE?'):
            return self._to_num(e1()) > 0, pos, True

        # ── List / word operations ────────────────────────────────────────────

        if name == 'WORD':
            a, b = e2()
            return str(a) + str(b), pos, True

        if name in ('SENTENCE', 'SE'):
            a, b = e2()
            al = self._list_items(a) if isinstance(a, list) else [a]
            bl = self._list_items(b) if isinstance(b, list) else [b]
            return self._items_to_tokens(al + bl), pos, True

        if name == 'LIST':
            a, b = e2()
            return self._items_to_tokens([a, b]), pos, True

        if name == 'FPUT':
            item = e1()
            lst  = elist()
            existing = self._list_items(lst)
            return self._items_to_tokens([item] + existing), pos, True

        if name == 'LPUT':
            item = e1()
            lst  = elist()
            existing = self._list_items(lst)
            return self._items_to_tokens(existing + [item]), pos, True

        if name == 'FIRST':
            v = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                if not items: raise LogoError("FIRST of empty list")
                return items[0], pos, True
            if isinstance(v, str):
                if not v: raise LogoError("FIRST of empty word")
                return v[0], pos, True
            raise LogoError(f"FIRST: expected list or word")

        if name == 'LAST':
            v = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                if not items: raise LogoError("LAST of empty list")
                return items[-1], pos, True
            if isinstance(v, str):
                if not v: raise LogoError("LAST of empty word")
                return v[-1], pos, True
            raise LogoError("LAST: expected list or word")

        if name in ('BUTFIRST', 'BF'):
            v = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                return self._items_to_tokens(items[1:]), pos, True
            if isinstance(v, str):
                return v[1:], pos, True
            raise LogoError("BUTFIRST: expected list or word")

        if name in ('BUTLAST', 'BL'):
            v = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                return self._items_to_tokens(items[:-1]), pos, True
            if isinstance(v, str):
                return v[:-1], pos, True
            raise LogoError("BUTLAST: expected list or word")

        if name == 'COUNT':
            v = e1()
            if isinstance(v, list):
                return len(self._list_items(v)), pos, True
            if isinstance(v, str):
                return len(v), pos, True
            raise LogoError("COUNT: expected list or word")

        if name == 'ITEM':
            idx = int(self._to_num(e1()))
            v   = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                if idx < 1 or idx > len(items):
                    raise LogoError(f"ITEM: index {idx} out of range (1..{len(items)})")
                return items[idx - 1], pos, True
            if isinstance(v, str):
                if idx < 1 or idx > len(v):
                    raise LogoError(f"ITEM: index {idx} out of range")
                return v[idx - 1], pos, True
            raise LogoError("ITEM: expected list or word")

        if name == 'MEMBER':
            item = e1()
            v    = e1()
            if isinstance(v, list):
                items = self._list_items(v)
                try:
                    i = items.index(item)
                    return self._items_to_tokens(items[i:]), pos, True
                except ValueError:
                    return self._items_to_tokens([]), pos, True
            if isinstance(v, str):
                idx = v.find(str(item))
                return v[idx:] if idx >= 0 else '', pos, True
            raise LogoError("MEMBER: expected list or word")

        # Not a known built-in
        return None, pos, False
