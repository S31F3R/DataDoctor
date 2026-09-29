# Plotter dictionary legends and HDB SQL fallback selection. No network.
# Run from the repo root: .venv/bin/python tests/testPlotterLegend.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import Config
from core.Query import (
    buildDataDictionaryIndex,
    dictionaryLegendLabel,
    mergeUsbrApiAndSql,
    plotterSqlFallbackIds,
)
from core.Utils import usbrOracleDatabase
from ui.uiPlotter import displayLabels

TSID = "a" * 32


class Cell:
    def __init__(self, text):
        self._text = "" if text is None else str(text)

    def text(self):
        return self._text


class DictTable:
    def __init__(self, headers, rows):
        self.headers = list(headers)
        self.rows = list(rows)

    def columnCount(self):
        return len(self.headers)

    def rowCount(self):
        return len(self.rows)

    def horizontalHeaderItem(self, col):
        return Cell(self.headers[col])

    def item(self, row, col):
        value = self.rows[row][col]
        if value is None:
            return None
        return Cell(value)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def legend(table, index, dataId, database):
    return dictionaryLegendLabel(table, dataId, database, idIndex=index)


def main():
    errors = 0
    saved = (
        Config.labelDataTypeUSBR,
        Config.labelDataTypeAquarius,
        Config.labelDataTypeUSGS,
    )
    headers = ["dataID", "commonName", "datatype"]
    rows = [
        ["1863", "Boise", "Flow"],
        ["1001", "Parker", ""],
        [TSID, "Green River", "Stage"],
        ["aq-1", "Canal", "Discharge"],
        ["9999", "", "Flow"],
    ]
    table = DictTable(headers, rows)
    index = buildDataDictionaryIndex(table)

    try:
        Config.labelDataTypeUSBR = True
        Config.labelDataTypeAquarius = False
        Config.labelDataTypeUSGS = True

        if not usbrOracleDatabase("USBR-LCHDB"):
            errors += fail("oracle lchdb", "LCHDB should be an Oracle HDB")
        if not usbrOracleDatabase("USBR-UCHDB2"):
            errors += fail("oracle uchdb2", "UCHDB2 should be an Oracle HDB")
        if not usbrOracleDatabase("kbohdb"):
            errors += fail("oracle alias", "kbohdb should match USBR-KBOHDB")
        if usbrOracleDatabase("USBR-PNHYD") or usbrOracleDatabase("USBR-GPHYD"):
            errors += fail("hydromet", "PNHYD and GPHYD stay on the public API")
        if usbrOracleDatabase("USGS-NWIS") or usbrOracleDatabase("AQUARIUS"):
            errors += fail("other sources", "only Oracle HDBs fall back to SQL")

        got = legend(table, index, "1863-0", "USBR-LCHDB")
        if got != "Boise-Flow":
            errors += fail("usbr datatype on", got)
        Config.labelDataTypeUSBR = False
        got = legend(table, index, "1863", "USBR-YAOHDB")
        if got != "Boise":
            errors += fail("usbr datatype off", got)
        Config.labelDataTypeUSBR = True
        got = legend(table, index, "1001-12", "USBR-LCHDB")
        if got != "Parker":
            errors += fail("blank datatype", got)

        got = legend(table, index, f"09380000-{TSID}-00060", "USGS-NWIS")
        if got != "Green River-Stage":
            errors += fail("usgs", got)
        Config.labelDataTypeUSGS = False
        got = legend(table, index, TSID, "USGS-NWIS")
        if got != "Green River":
            errors += fail("usgs off", got)

        got = legend(table, index, "aq-1", "AQUARIUS")
        if got != "Canal":
            errors += fail("aquarius off", got)
        Config.labelDataTypeAquarius = True
        got = legend(table, index, "aq-1", "AQUARIUS")
        if got != "Canal-Discharge":
            errors += fail("aquarius on", got)

        if legend(table, index, "missing", "USBR-LCHDB") is not None:
            errors += fail("missing id", "unknown ids keep the API label")
        if legend(table, index, "9999", "USBR-LCHDB") is not None:
            errors += fail("blank name", "a blank commonName keeps the API label")
        if legend(None, None, "1863", "USBR-LCHDB") is not None:
            errors += fail("no table", "no dictionary returns None")

        api = {"1863": ["01/01/26 00:00:00,1.2"], "1001": []}
        missing = plotterSqlFallbackIds("USBR-LCHDB", ["1863", "1001", "2002"], api)
        if missing != ["2002"]:
            errors += fail("fallback ids", missing)
        if plotterSqlFallbackIds("USBR-PNHYD", ["9"], {}) != []:
            errors += fail("pnhyd fallback", "hydromet must not use SQL")
        if plotterSqlFallbackIds("USGS-NWIS", ["9"], {}) != []:
            errors += fail("usgs fallback", "USGS must not use SQL")
        if plotterSqlFallbackIds("USBR-LCHDB", ["9", "8"], None) != ["9", "8"]:
            errors += fail("api threw", "a failed API call retries every SDID")

        merged = mergeUsbrApiAndSql(
            api,
            {"2002": {"data": ["01/01/26 00:00:00,4"], "rawResponse": []}},
            ["2002"],
        )
        if merged.get("1863") != api["1863"] or "2002" not in merged or "1001" not in merged:
            errors += fail("merge", merged)
        untouched = mergeUsbrApiAndSql(api, {"1863": {"data": ["nope"]}}, ["2002"])
        if untouched.get("1863") != api["1863"]:
            errors += fail("merge keeps api", untouched)

        shown = displayLabels([
            {"label": "Boise-Flow", "dataId": "1863"},
            {"label": "1864", "dataId": "1864"},
            {"label": "Boise-Flow", "dataId": "1865"},
        ])
        if shown != ["Boise-Flow (1863)", "1864", "Boise-Flow (1865)"]:
            errors += fail("display", shown)
    finally:
        (
            Config.labelDataTypeUSBR,
            Config.labelDataTypeAquarius,
            Config.labelDataTypeUSGS,
        ) = saved

    if errors:
        print(f"{errors} plotter legend check(s) failed")
        return 1
    print("plotter legend checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
