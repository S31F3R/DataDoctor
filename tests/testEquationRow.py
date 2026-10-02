# Equation rows appended from the date column.
# Run from the repo root: python tests/testEquationRow.py

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication, QListWidget, QTableWidget, QTableWidgetItem

from core.Formula import coverRowsAbove
from core.FormulaUi import _itemFormula, applyCellInput
from core.Query import captureTableRows, sortWorker, updateTableAfterSort
from core.QueryFlags import (
    KIND_EQUATION_ROW, makeListItem, parseListText, parseSavedEntry, serializeItem,
)
from core.QueryUtils import isEquationRow
from core.TableOps import (
    appendEquationRow, applyEquationRowItems, equationRowMenu, moveColumnSet,
    renameEquationRow, restoreCustomColumns,
)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def testCoverRowsAbove():
    if coverRowsAbove("=SUM(A1:A3)", 5) != "=SUM(A1:A5)":
        return fail("cover", coverRowsAbove("=SUM(A1:A3)", 5))
    if coverRowsAbove("=AVERAGE($A$1:$A$3)", 5) != "=AVERAGE($A$1:$A$5)":
        return fail("coverAbs", coverRowsAbove("=AVERAGE($A$1:$A$3)", 5))
    if coverRowsAbove("=A1", 8) != "=A1":
        return fail("coverCell", coverRowsAbove("=A1", 8))
    both = coverRowsAbove("=SUM(A1:A3)+MAX(C1:C2)", 4)
    if both != "=SUM(A1:A4)+MAX(C1:C4)":
        return fail("coverBoth", both)
    return 0


def testParseRow():
    parsed = parseListText("ROW EQUATION|Total")
    if parsed is None or parsed[0] != KIND_EQUATION_ROW or parsed[3] != "Total":
        return fail("parse", parsed)
    legacy = parseListText("ROW|Total")
    if legacy is None or legacy[0] != KIND_EQUATION_ROW or legacy[3] != "Total":
        return fail("legacyRow", legacy)
    column = parseListText("COLUMN EQUATION|Stage")
    if column is None or column[0] != "equation" or column[3] != "Stage":
        return fail("column", column)
    oldColumn = parseListText("EQUATION|Stage")
    if oldColumn is None or oldColumn[0] != "equation" or oldColumn[3] != "Stage":
        return fail("legacyColumn", oldColumn)
    saved = parseSavedEntry({
        "kind": KIND_EQUATION_ROW,
        "q": "ROW|Total",
        "rowId": "row1",
        "rowName": "Total",
        "cells": [{
            "formula": "=SUM(A1:A3)",
            "columnId": "aaa",
            "header": "Stage",
        }],
    })
    if saved is None or saved.get("rowName") != "Total":
        return fail("savedName", saved)
    if saved.get("text") != "ROW EQUATION|Total":
        return fail("savedText", saved)
    if not saved.get("cells") or saved["cells"][0].get("formula") != "=SUM(A1:A3)":
        return fail("savedCells", saved)
    oldSaved = parseSavedEntry("EQUATION|Stage")
    if oldSaved is None or oldSaved.get("text") != "COLUMN EQUATION|Stage":
        return fail("oldColumnText", oldSaved)
    if parseListText("111|HOUR|USGS-NWIS")[0] != "series":
        return fail("series", "row prefix ate a series")
    return 0


class Host:
    def __init__(self, rows, cols):
        self.mainTable = QTableWidget(rows, cols)
        self.columnMetadata = [
            {
                "type": "normal",
                "dataIds": ["111"],
                "itemId": "aaa",
                "dbs": ["USGS-NWIS"],
                "queryInfos": ["111|HOUR|USGS-NWIS"],
            },
            {
                "type": "normal",
                "dataIds": ["222"],
                "itemId": "bbb",
                "dbs": ["USGS-NWIS"],
                "queryInfos": ["222|HOUR|USGS-NWIS"],
            },
        ]
        self.lastQueryItems = []
        self.lastQueryType = "internal"
        self.winQuery = type("Q", (), {})()
        self.winQuery.listQueryList = QListWidget()
        self.winQuery.loadedQuickLookName = ""
        self.winQuery.markQuickLookDirtyFromTable = lambda: None
        self.mainTable.setHorizontalHeaderItem(0, QTableWidgetItem("Stage"))
        self.mainTable.setHorizontalHeaderItem(1, QTableWidgetItem("Flow"))
        for r in range(rows):
            self.mainTable.setVerticalHeaderItem(r, QTableWidgetItem(f"01/0{r + 1}/24 00:00:00"))
            self.mainTable.setItem(r, 0, QTableWidgetItem(str([1, 5, 2, 4, 3][r])))
            self.mainTable.setItem(r, 1, QTableWidgetItem(str(r + 1)))


def _menuLabels(menu):
    return [a.text() for a in menu.actions()]


def testTable():
    app = QApplication.instance() or QApplication([])
    host = Host(3, 2)
    table = host.mainTable
    dateMenu = _menuLabels(equationRowMenu(host, 0))
    if dateMenu != ["Append New Row"]:
        return fail("dateMenu", dateMenu)
    row = appendEquationRow(host)
    if row != 3 or not isEquationRow(table, 3):
        return fail("append", row)
    if isEquationRow(table, 0):
        return fail("dateMarked", "timestamp became an equation row")
    eqMenu = _menuLabels(equationRowMenu(host, 3))
    if eqMenu != ["Append New Row", "Rename", "Remove"]:
        return fail("eqMenu", eqMenu)
    if renameEquationRow(host, 0, "Nope"):
        return fail("renameDate", "date row accepted a name")
    if not renameEquationRow(host, 3, "Total"):
        return fail("rename", "equation row did not rename")
    if table.verticalHeaderItem(3).text() != "Total":
        return fail("renameText", table.verticalHeaderItem(3).text())
    applyCellInput(host, 3, 0, "=SUM(A1:A3)")
    if _itemFormula(table.item(3, 1)):
        return fail("otherCell", _itemFormula(table.item(3, 1)))
    applyCellInput(host, 3, 1, "42")
    specs = [it for it in host.lastQueryItems if it.get("kind") == KIND_EQUATION_ROW]
    if len(specs) != 1 or specs[0].get("rowName") != "Total":
        return fail("specName", specs)
    cells = specs[0].get("cells") or []
    if len(cells) != 1 or cells[0].get("formula") != "=SUM(A1:A3)":
        return fail("specCells", cells)
    if cells[0].get("columnId") != "aaa":
        return fail("specCol", cells[0])
    lst = host.winQuery.listQueryList
    if lst.count() != 1 or lst.item(0).text() != "ROW EQUATION|Total":
        return fail("list", [lst.item(i).text() for i in range(lst.count())])
    item = makeListItem(
        "ROW|Total", kind=KIND_EQUATION_ROW,
        extra={"rowId": "row1", "rowName": "Total", "cells": cells, "id": "row1"},
    )
    packed = serializeItem(item)
    if packed.get("kind") != KIND_EQUATION_ROW or packed.get("q") != "ROW EQUATION|Total":
        return fail("serialize", packed)
    if not moveColumnSet(host, [0], 2):
        return fail("move", "column did not move")
    if _itemFormula(table.item(3, 1)) != "=SUM(B1:B3)":
        return fail("followed", _itemFormula(table.item(3, 1)))
    if _itemFormula(table.item(3, 0)):
        return fail("stayed", _itemFormula(table.item(3, 0)))
    rows = captureTableRows(table)
    worker = sortWorker(rows, 0, False, byTimestamp=False)
    worker.run()
    if not worker.rows[-1].get("equationRow"):
        return fail("sort", [r.get("ts") for r in worker.rows])
    updateTableAfterSort(table, worker.rows, False, None, 0)
    if table.verticalHeaderItem(table.rowCount() - 1).text() != "Total":
        return fail("sortHeader", table.verticalHeaderItem(table.rowCount() - 1).text())
    if not isEquationRow(table, table.rowCount() - 1):
        return fail("sortRole", "equation marker dropped after sort")

    replay = Host(5, 2)
    applyEquationRowItems(replay, [{
        "kind": KIND_EQUATION_ROW,
        "rowId": "row9",
        "rowName": "Total",
        "cells": [{
            "formula": "=SUM(A1:A3)",
            "columnId": "aaa",
            "header": "Stage",
        }],
    }])
    replayTable = replay.mainTable
    if replayTable.rowCount() != 6:
        return fail("replayRows", replayTable.rowCount())
    if replayTable.verticalHeaderItem(5).text() != "Total":
        return fail("replayName", replayTable.verticalHeaderItem(5).text())
    if _itemFormula(replayTable.item(5, 0)) != "=SUM(A1:A5)":
        return fail("replayFormula", _itemFormula(replayTable.item(5, 0)))
    if _itemFormula(replayTable.item(5, 1)):
        return fail("replayOther", _itemFormula(replayTable.item(5, 1)))
    if replayTable.item(5, 1) is not None and replayTable.item(5, 1).text() not in ("", None):
        return fail("replayBlank", replayTable.item(5, 1).text())
    _ = app
    return 0


def seriesHost(cols, rows=3):
    host = type("H", (), {})()
    host.mainTable = QTableWidget(rows, cols)
    host.columnMetadata = []
    host.lastQueryItems = []
    host.lastQueryType = "internal"
    host.winQuery = type("Q", (), {})()
    host.winQuery.listQueryList = QListWidget()
    host.winQuery.loadedQuickLookName = ""
    host.winQuery.markQuickLookDirtyFromTable = lambda: None
    for c in range(cols):
        host.columnMetadata.append({
            "type": "normal",
            "dataIds": [str(100 + c)],
            "itemId": f"s{c}",
            "dbs": ["USGS-NWIS"],
            "queryInfos": [f"{100 + c}|HOUR|USGS-NWIS"],
            "name": f"S{c}",
        })
        host.mainTable.setHorizontalHeaderItem(c, QTableWidgetItem(f"S{c}"))
    for r in range(rows):
        host.mainTable.setVerticalHeaderItem(r, QTableWidgetItem(f"01/0{r + 1}/24 00:00:00"))
        for c in range(cols):
            host.mainTable.setItem(r, c, QTableWidgetItem(str((c + 1) * 10)))
    return host


def _customNames(host):
    return [(m or {}).get("name") for m in host.columnMetadata]


def testRefreshKeepsEquationColumns():
    """Three series, equation at B, equation at C, then a series-only refresh."""
    app = QApplication.instance() or QApplication([])
    host = seriesHost(3)
    host.customColumns = [
        {
            "id": "eq1", "name": "EqB", "indexHint": 1, "cells": {},
            "formulaTemplate": "=A1", "formulaAnchorRow": 0,
        },
        {
            "id": "eq2", "name": "EqC", "indexHint": 2, "cells": {},
            "formulaTemplate": "=D1", "formulaAnchorRow": 0,
        },
    ]
    restoreCustomColumns(host)
    table = host.mainTable
    names = _customNames(host)
    if table.columnCount() != 5 or names[1] != "EqB" or names[2] != "EqC":
        return fail("places", (table.columnCount(), names))
    if _itemFormula(table.item(0, 1)) != "=A1":
        return fail("eqb", _itemFormula(table.item(0, 1)))
    if _itemFormula(table.item(0, 2)) != "=D1":
        return fail("eqc", _itemFormula(table.item(0, 2)))
    if table.item(0, 2).text() == "#CYCLE!" or table.item(0, 1).text() == "#CYCLE!":
        return fail("cycle", (table.item(0, 1).text(), table.item(0, 2).text()))

    start = seriesHost(3)
    start.customColumns = [
        {
            "id": "a", "name": "Left", "indexHint": 0, "cells": {},
            "formulaTemplate": "=C1", "formulaAnchorRow": 0,
        },
        {
            "id": "b", "name": "Next", "indexHint": 1, "cells": {},
            "formulaTemplate": "=C1", "formulaAnchorRow": 0,
        },
    ]
    restoreCustomColumns(start)
    if _customNames(start)[:2] != ["Left", "Next"]:
        return fail("start", _customNames(start))

    end = seriesHost(3)
    end.customColumns = [
        {
            "id": "e1", "name": "End1", "indexHint": 3, "cells": {},
            "formulaTemplate": "=A1", "formulaAnchorRow": 0,
        },
        {
            "id": "e2", "name": "End2", "indexHint": 4, "cells": {},
            "formulaTemplate": "=A1", "formulaAnchorRow": 0,
        },
    ]
    restoreCustomColumns(end)
    if _customNames(end)[-2:] != ["End1", "End2"]:
        return fail("end", _customNames(end))
    _ = app
    return 0


def main():
    errors = testCoverRowsAbove() + testParseRow() + testTable() + testRefreshKeepsEquationColumns()
    if errors:
        print(f"{errors} failed")
        return 1
    print("equation row checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
