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
    renameEquationRow,
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
    parsed = parseListText("ROW|Total")
    if parsed is None or parsed[0] != KIND_EQUATION_ROW or parsed[3] != "Total":
        return fail("parse", parsed)
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
    if not saved.get("cells") or saved["cells"][0].get("formula") != "=SUM(A1:A3)":
        return fail("savedCells", saved)
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
    if lst.count() != 1 or lst.item(0).text() != "ROW|Total":
        return fail("list", [lst.item(i).text() for i in range(lst.count())])
    item = makeListItem(
        "ROW|Total", kind=KIND_EQUATION_ROW,
        extra={"rowId": "row1", "rowName": "Total", "cells": cells, "id": "row1"},
    )
    packed = serializeItem(item)
    if packed.get("kind") != KIND_EQUATION_ROW or packed.get("q") != "ROW|Total":
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


def main():
    errors = testCoverRowsAbove() + testParseRow() + testTable()
    if errors:
        print(f"{errors} failed")
        return 1
    print("equation row checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
