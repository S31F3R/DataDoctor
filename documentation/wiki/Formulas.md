# Formulas

Internal **Data Query** cells can hold Excel-style formulas. Type `=` then an expression. The cell **shows the result**; upload / graph / CSV use that number. Double-click (or F2) to see and edit the formula.

Public Query tables stay read-only (no formulas). **Delta** columns stay locked. On **Overlay** columns the formula writes the **primary** value (the number you see), not the secondary series. Blank columns inserted from the header menu are normal formula cells; they stay on **Refresh** and re-evaluate.

**Ctrl+Z** / **Ctrl+Y** undo and redo table edits (no extra menu). SQL Query Builder uses the same shortcuts.

## Cell references

Columns are `A`, `B`, … (leftmost data column is `A`). Rows are `1` at the top of the table.

| Form | Meaning | Fill handle |
|------|---------|-------------|
| `A1` | relative | both letter and number move |
| `$A1` | absolute column | row moves, column stays |
| `A$1` | absolute row | column moves, row stays |
| `$A$1` | both locked | neither moves |
| `A1:B10` | rectangle (for SUM / AVERAGE / …) | each corner follows the same `$` rules |

While the editor is open and the text starts with `=`, **click another cell** to insert its A1 name at the cursor.

## Fill handle

Select a cell (or a block). The small square at the **bottom-right** of the selection is the fill handle. Drag down or right (or up / left) to copy.

- A formula is copied with relative refs shifted (`=A1` in B1 → `=A2` one row down).
- `$` stops that axis from shifting (same as Excel).
- A plain number is copied as a number.

## Operators

`+` `-` `*` `/` `^` `%`   parentheses   comparisons `=` `<>` `<` `>` `<=` `>=`

Unary minus works (`=-A1`). Text in quotes is allowed (`"ok"`).

## Functions

| Function | Result |
|----------|--------|
| `SUM(range)` | Add numbers (skips blanks / text) |
| `AVERAGE(range)` / `AVG(range)` | Mean of numbers |
| `MIN(range)` | Smallest number |
| `MAX(range)` | Largest number |
| `COUNT(range)` | Count of numeric cells |
| `COUNTA(range)` | Count of non-blank cells |
| `ABS(n)` | Absolute value |
| `ROUND(n, digits)` | Bankers rounding (half to even); `digits` optional |
| `SQRT(n)` | Square root |
| `IF(test, then, else)` | `else` optional (FALSE if omitted) |
| `AND(a, b, …)` | TRUE if every argument is true / non-zero |
| `OR(a, b, …)` | TRUE if any argument is true / non-zero |
| `NOT(a)` | Invert a boolean |
| `POWER(n, exp)` or `n^exp` | Exponent |
| `MOD(n, d)` | Remainder |
| `SIGN(n)` | −1, 0, or 1 |
| `INT(n)` | Floor toward −∞ |
| `PI()` | π |

Examples: `=A1-B1`  `=SUM(A1:A24)`  `=IF(A1>0, A1, 0)`  `=ROUND(A1/B1, 2)`

## Errors

| Display | Meaning |
|---------|---------|
| `#VALUE!` | Wrong type / bad syntax |
| `#REF!` | Cell is off the table (often after a fill) |
| `#DIV/0!` | Divide by zero |
| `#NAME?` | Unknown function |
| `#CYCLE!` | Formula refers to itself (directly or through others) |

Error cells are **not** uploaded to HDB. Fix the formula (or clear the cell) first.

## Upload

A formula result that is a normal number is a regular edit (magenta until you upload). Clearing the cell deletes the formula too.

Paste from Excel: a clipboard cell that starts with `=` is treated as a formula (refs are **not** rewritten on paste — they keep the letters/numbers you pasted).
