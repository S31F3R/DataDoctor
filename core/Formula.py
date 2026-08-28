# Formula.py
# Excel-style formulas for the Data Query table.
#
# Stored on the cell (user dict 'formula'). The table text is the computed
# value (upload / graph / CSV use that). Edit shows the formula.

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

FORMULA_KEY = "formula"

# Displayed when evaluation fails (Excel-ish). Not uploaded as HDB values.
ERR_VALUE = "#VALUE!"
ERR_REF = "#REF!"
ERR_DIV = "#DIV/0!"
ERR_NAME = "#NAME?"
ERR_CYCLE = "#CYCLE!"

_ERROR_VALUES = (ERR_VALUE, ERR_REF, ERR_DIV, ERR_NAME, ERR_CYCLE)

_COL_RE = re.compile(r"^\$?[A-Za-z]+\$?\d+$")
_NUM_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")


def colToLetters(index: int) -> str:
    """0-based column index → A, B, … Z, AA, …"""
    if index < 0:
        return "A"
    n = index + 1
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def lettersToCol(letters: str) -> int:
    """A → 0, B → 1, AA → 26. Case-insensitive."""
    n = 0
    for ch in (letters or "").upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(letters)
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def parseCellRef(token: str):
    """
    'A1', '$A$1', 'A$1', '$A1' → (col, row, absCol, absRow) 0-based.
    None if not a cell ref.
    """
    raw = (token or "").strip()
    if not raw or not _COL_RE.match(raw):
        return None
    absCol = raw.startswith("$")
    body = raw[1:] if absCol else raw
    i = 0
    while i < len(body) and body[i].isalpha():
        i += 1
    if i == 0 or i >= len(body):
        return None
    letters = body[:i]
    rest = body[i:]
    absRow = rest.startswith("$")
    digits = rest[1:] if absRow else rest
    if not digits.isdigit():
        return None
    row = int(digits) - 1
    if row < 0:
        return None
    try:
        col = lettersToCol(letters)
    except ValueError:
        return None
    return col, row, absCol, absRow


def formatCellRef(col: int, row: int, absCol=False, absRow=False) -> str:
    colPart = f"${colToLetters(col)}" if absCol else colToLetters(col)
    rowPart = f"${row + 1}" if absRow else str(row + 1)
    return colPart + rowPart


def isErrorValue(text) -> bool:
    s = str(text or "").strip()
    return s in _ERROR_VALUES


def looksLikeFormula(text) -> bool:
    s = (text or "").strip()
    return s.startswith("=") and len(s) > 1


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_OPS = {
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "^": "^",
    "%": "%",
    "(": "(",
    ")": ")",
    ",": ",",
    ":": ":",
    "=": "=",
    "<": "<",
    ">": ">",
}


def tokenize(formula: str):
    s = (formula or "").strip()
    if s.startswith("="):
        s = s[1:]
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "<>":
            if i + 1 < n and s[i + 1] in "=>":
                tokens.append(("OP", s[i : i + 2]))
                i += 2
                continue
            tokens.append(("OP", ch))
            i += 1
            continue
        if ch == "=":
            tokens.append(("OP", "="))
            i += 1
            continue
        if ch in _OPS:
            tokens.append(("OP", ch))
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and s[i + 1].isdigit()):
            j = i
            while j < n and (s[j].isdigit() or s[j] in ".eE+-"):
                if s[j] in "eE" and j + 1 < n and s[j + 1] in "+-":
                    j += 2
                    continue
                if s[j] in "+-" and not (j > i and s[j - 1] in "eE"):
                    break
                j += 1
            num = s[i:j]
            if not _NUM_RE.match(num):
                raise ValueError(ERR_VALUE)
            tokens.append(("NUM", num))
            i = j
            continue
        if ch == "$" or ch.isalpha() or ch == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] in "$_"):
                j += 1
            word = s[i:j]
            if parseCellRef(word) is not None:
                tokens.append(("REF", word))
            else:
                tokens.append(("NAME", word))
            i = j
            continue
        if ch in ('"', "'"):
            quote = ch
            j = i + 1
            buf = []
            while j < n and s[j] != quote:
                buf.append(s[j])
                j += 1
            if j >= n:
                raise ValueError(ERR_VALUE)
            tokens.append(("STR", "".join(buf)))
            i = j + 1
            continue
        raise ValueError(ERR_VALUE)
    return tokens


# ---------------------------------------------------------------------------
# Parser / evaluator
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens, getCell, evaluating, origin):
        self.tokens = tokens
        self.i = 0
        self.getCell = getCell
        self.evaluating = evaluating
        self.origin = origin  # (col, row) of the formula cell

    def peek(self):
        if self.i >= len(self.tokens):
            return None
        return self.tokens[self.i]

    def take(self, kind=None, value=None):
        tok = self.peek()
        if tok is None:
            return None
        if kind is not None and tok[0] != kind:
            return None
        if value is not None and tok[1] != value:
            return None
        self.i += 1
        return tok

    def parse(self):
        if not self.tokens:
            raise ValueError(ERR_VALUE)
        val = self.parseCompare()
        if self.peek() is not None:
            raise ValueError(ERR_VALUE)
        return val

    def parseCompare(self):
        left = self.parseAdd()
        while True:
            tok = self.peek()
            if tok is None or tok[0] != "OP" or tok[1] not in (
                "=", "<>", "<", ">", "<=", ">=",
            ):
                return left
            op = self.take()[1]
            right = self.parseAdd()
            ln, rn = _asNumber(left), _asNumber(right)
            if op == "=":
                if ln is not None and rn is not None:
                    left = abs(ln - rn) < 1e-12
                else:
                    left = str(left).strip() == str(right).strip()
            elif op == "<>":
                if ln is not None and rn is not None:
                    left = abs(ln - rn) >= 1e-12
                else:
                    left = str(left).strip() != str(right).strip()
            else:
                if ln is None or rn is None:
                    raise ValueError(ERR_VALUE)
                if op == "<":
                    left = ln < rn
                elif op == ">":
                    left = ln > rn
                elif op == "<=":
                    left = ln <= rn
                else:
                    left = ln >= rn
        return left

    def parseAdd(self):
        left = self.parseMul()
        while True:
            tok = self.peek()
            if tok is None or tok[0] != "OP" or tok[1] not in ("+", "-"):
                return left
            op = self.take()[1]
            right = self.parseMul()
            ln, rn = _needNumber(left), _needNumber(right)
            left = ln + rn if op == "+" else ln - rn

    def parseMul(self):
        left = self.parsePower()
        while True:
            tok = self.peek()
            if tok is None or tok[0] != "OP" or tok[1] not in ("*", "/", "%"):
                return left
            op = self.take()[1]
            right = self.parsePower()
            ln, rn = _needNumber(left), _needNumber(right)
            if op == "*":
                left = ln * rn
            elif op == "%":
                if rn == 0:
                    raise ValueError(ERR_DIV)
                left = ln % rn
            else:
                if rn == 0:
                    raise ValueError(ERR_DIV)
                left = ln / rn

    def parsePower(self):
        left = self.parseUnary()
        tok = self.peek()
        if tok is not None and tok[0] == "OP" and tok[1] == "^":
            self.take()
            right = self.parsePower()
            return _needNumber(left) ** _needNumber(right)
        return left

    def parseUnary(self):
        tok = self.peek()
        if tok is not None and tok[0] == "OP" and tok[1] == "-":
            self.take()
            return -_needNumber(self.parseUnary())
        if tok is not None and tok[0] == "OP" and tok[1] == "+":
            self.take()
            return self.parseUnary()
        return self.parsePrimary()

    def parsePrimary(self):
        tok = self.peek()
        if tok is None:
            raise ValueError(ERR_VALUE)
        if tok[0] == "NUM":
            self.take()
            return float(tok[1])
        if tok[0] == "STR":
            self.take()
            return tok[1]
        if tok[0] == "REF":
            self.take()
            start = parseCellRef(tok[1])
            if start is None:
                raise ValueError(ERR_REF)
            nxt = self.peek()
            if nxt is not None and nxt[0] == "OP" and nxt[1] == ":":
                self.take()
                endTok = self.take("REF")
                if endTok is None:
                    raise ValueError(ERR_REF)
                end = parseCellRef(endTok[1])
                if end is None:
                    raise ValueError(ERR_REF)
                return self._rangeValues(start, end)
            return self._cellValue(start[0], start[1])
        if tok[0] == "NAME":
            name = tok[1].upper()
            self.take()
            if name == "PI" and (self.peek() is None or self.peek() != ("OP", "(")):
                return math.pi
            if not self.take("OP", "("):
                raise ValueError(ERR_NAME)
            args = []
            if not (self.peek() and self.peek() == ("OP", ")")):
                args.append(self.parseCompare())
                while self.take("OP", ","):
                    args.append(self.parseCompare())
            if not self.take("OP", ")"):
                raise ValueError(ERR_VALUE)
            return _callFunc(name, args)
        if tok[0] == "OP" and tok[1] == "(":
            self.take()
            val = self.parseCompare()
            if not self.take("OP", ")"):
                raise ValueError(ERR_VALUE)
            return val
        raise ValueError(ERR_VALUE)

    def _cellValue(self, col, row):
        key = (col, row)
        if key == self.origin or key in self.evaluating:
            raise ValueError(ERR_CYCLE)
        self.evaluating.add(key)
        try:
            return self.getCell(col, row)
        finally:
            self.evaluating.discard(key)

    def _rangeValues(self, start, end):
        c0, r0 = start[0], start[1]
        c1, r1 = end[0], end[1]
        if c0 > c1:
            c0, c1 = c1, c0
        if r0 > r1:
            r0, r1 = r1, r0
        out = []
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                out.append(self._cellValue(c, r))
        return out


def _asNumber(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        if isinstance(val, float) and not math.isfinite(val):
            raise ValueError(ERR_VALUE)
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, list):
        return None
    s = str(val).strip()
    if not s or isErrorValue(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _needNumber(val):
    n = _asNumber(val)
    if n is None:
        raise ValueError(ERR_VALUE)
    return n


def _flatten(args):
    out = []
    for a in args:
        if isinstance(a, list):
            out.extend(_flatten(a))
        else:
            out.append(a)
    return out


def _nums(args, skipBlank=True):
    nums = []
    for a in _flatten(args):
        if a is None or a == "":
            if not skipBlank:
                nums.append(0.0)
            continue
        if isErrorValue(a):
            raise ValueError(str(a))
        n = _asNumber(a)
        if n is None:
            continue
        nums.append(n)
    return nums


def _truthy(val):
    if isinstance(val, bool):
        return val
    n = _asNumber(val)
    if n is not None:
        return n != 0
    return bool(str(val or "").strip())


def _callFunc(name, args):
    fn = FUNCTIONS.get(name)
    if fn is None:
        raise ValueError(ERR_NAME)
    return fn(args)


def _fnSum(args):
    return sum(_nums(args))


def _fnAverage(args):
    ns = _nums(args)
    if not ns:
        raise ValueError(ERR_DIV)
    return sum(ns) / len(ns)


def _fnMin(args):
    ns = _nums(args)
    if not ns:
        raise ValueError(ERR_VALUE)
    return min(ns)


def _fnMax(args):
    ns = _nums(args)
    if not ns:
        raise ValueError(ERR_VALUE)
    return max(ns)


def _fnCount(args):
    return float(len(_nums(args)))


def _fnCountA(args):
    n = 0
    for a in _flatten(args):
        if a is None or a == "":
            continue
        n += 1
    return float(n)


def _fnAbs(args):
    if len(args) != 1:
        raise ValueError(ERR_VALUE)
    return abs(_needNumber(args[0]))


def _fnRound(args):
    if not args:
        raise ValueError(ERR_VALUE)
    val = _needNumber(args[0])
    digits = int(_needNumber(args[1])) if len(args) > 1 else 0
    q = Decimal("1").scaleb(-digits) if digits >= 0 else Decimal(10) ** (-digits)
    try:
        d = Decimal(str(val)).quantize(q, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, ValueError):
        raise ValueError(ERR_VALUE)
    return float(d)


def _fnSqrt(args):
    if len(args) != 1:
        raise ValueError(ERR_VALUE)
    n = _needNumber(args[0])
    if n < 0:
        raise ValueError(ERR_VALUE)
    return math.sqrt(n)


def _fnIf(args):
    if len(args) < 2 or len(args) > 3:
        raise ValueError(ERR_VALUE)
    if _truthy(args[0]):
        return args[1]
    return args[2] if len(args) > 2 else False


def _fnAnd(args):
    return all(_truthy(a) for a in _flatten(args))


def _fnOr(args):
    return any(_truthy(a) for a in _flatten(args))


def _fnNot(args):
    if len(args) != 1:
        raise ValueError(ERR_VALUE)
    return not _truthy(args[0])


def _fnPower(args):
    if len(args) != 2:
        raise ValueError(ERR_VALUE)
    return _needNumber(args[0]) ** _needNumber(args[1])


def _fnMod(args):
    if len(args) != 2:
        raise ValueError(ERR_VALUE)
    b = _needNumber(args[1])
    if b == 0:
        raise ValueError(ERR_DIV)
    return _needNumber(args[0]) % b


def _fnSign(args):
    if len(args) != 1:
        raise ValueError(ERR_VALUE)
    n = _needNumber(args[0])
    if n > 0:
        return 1.0
    if n < 0:
        return -1.0
    return 0.0


def _fnInt(args):
    if len(args) != 1:
        raise ValueError(ERR_VALUE)
    return float(math.floor(_needNumber(args[0])))


def _fnPi(args):
    if args:
        raise ValueError(ERR_VALUE)
    return math.pi


FUNCTIONS = {
    "SUM": _fnSum,
    "AVERAGE": _fnAverage,
    "AVG": _fnAverage,
    "MIN": _fnMin,
    "MAX": _fnMax,
    "COUNT": _fnCount,
    "COUNTA": _fnCountA,
    "ABS": _fnAbs,
    "ROUND": _fnRound,
    "SQRT": _fnSqrt,
    "IF": _fnIf,
    "AND": _fnAnd,
    "OR": _fnOr,
    "NOT": _fnNot,
    "POWER": _fnPower,
    "MOD": _fnMod,
    "SIGN": _fnSign,
    "INT": _fnInt,
    "PI": _fnPi,
}

FUNCTION_HELP = (
    ("SUM(range)", "Add numbers (skips blanks/text)"),
    ("AVERAGE(range) / AVG(range)", "Mean of numbers"),
    ("MIN(range)", "Smallest number"),
    ("MAX(range)", "Largest number"),
    ("COUNT(range)", "Count of numeric cells"),
    ("COUNTA(range)", "Count of non-blank cells"),
    ("ABS(n)", "Absolute value"),
    ("ROUND(n, digits)", "Bankers rounding (half to even); digits optional"),
    ("SQRT(n)", "Square root"),
    ("IF(test, then, else)", "else is optional (FALSE if omitted)"),
    ("AND(a, b, …)", "TRUE if every argument is true / non-zero"),
    ("OR(a, b, …)", "TRUE if any argument is true / non-zero"),
    ("NOT(a)", "Invert a boolean"),
    ("POWER(n, exp) or n^exp", "Exponent"),
    ("MOD(n, d)", "Remainder"),
    ("SIGN(n)", "−1, 0, or 1"),
    ("INT(n)", "Floor toward −∞"),
    ("PI()", "3.14159…"),
)


def evaluateFormula(formula: str, getCell, originCol: int, originRow: int):
    """
    Evaluate '=…' using getCell(col, row) → display value / nested formula result.
    Returns a number, bool, str, or raises ValueError with an ERR_* string.
    """
    try:
        tokens = tokenize(formula)
    except ValueError as e:
        raise ValueError(str(e) or ERR_VALUE)
    parser = _Parser(tokens, getCell, {(originCol, originRow)}, (originCol, originRow))
    try:
        return parser.parse()
    except ValueError:
        raise
    except ZeroDivisionError:
        raise ValueError(ERR_DIV)
    except RecursionError:
        raise ValueError(ERR_CYCLE)


def formatFormulaResult(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ERR_VALUE
        if abs(value) >= 1e12 or (0 < abs(value) < 1e-8):
            return format(value, ".10g")
        # Trim binary noise for display; upload still uses this string
        asDec = Decimal(str(value)).normalize()
        text = format(asDec, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


# ---------------------------------------------------------------------------
# Fill: adjust relative refs
# ---------------------------------------------------------------------------

_REF_IN_FORMULA = re.compile(
    r"(\$?[A-Za-z]+\$?\d+)",
)


def adjustFormula(formula: str, dCol: int, dRow: int) -> str:
    """
    Shift relative refs by dCol / dRow. $A1 keeps the column; A$1 keeps the row.
    Out-of-range refs become #REF!.
    """
    if not looksLikeFormula(formula):
        return formula

    def repl(m):
        token = m.group(1)
        parsed = parseCellRef(token)
        if parsed is None:
            return token
        col, row, absCol, absRow = parsed
        newCol = col if absCol else col + dCol
        newRow = row if absRow else row + dRow
        if newCol < 0 or newRow < 0:
            return ERR_REF
        return formatCellRef(newCol, newRow, absCol, absRow)

    body = formula.strip()
    prefix = ""
    if body.startswith("="):
        prefix = "="
        body = body[1:]
    return prefix + _REF_IN_FORMULA.sub(repl, body)
