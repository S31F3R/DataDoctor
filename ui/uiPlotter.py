# uiPlotter.py
# Plotter window and tab. API-only fetch, then Line / Scatter / Time Lag.
# The Data Query table and its right-click Graph are not used here.

import json
import os
from datetime import datetime

import numpy as np
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDateTimeEdit, QDialog,
    QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton,
    QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
from PyQt6 import uic

from core import Config, Logic, Query, QueryFlags, QuickLookDates, Utils
from core.plotLag import (
    chainLag, lagClockText, maxLagSteps, overlapCount, shiftByLag, viewPairScores,
)
from core.regression.equation import formatNumber
from ui.uiGraph import GraphPanel, parseNumeric
from ui.uiQuery import ALL_INTERVALS, USGS_DEFAULT_INTERVAL, USGS_INTERVALS
from ui.uiSearch import uiSearch

PLOT_TITLES = {
    "line": "Plotter-Line",
    "scatter": "Plotter-Scatter",
    "timeLag": "Plotter-Time Lag",
}


def valueTexts(values):
    out = []
    for value in values or []:
        if value is None:
            out.append("")
        else:
            out.append(str(value).strip())
    return out


def shiftedTexts(texts, lag):
    texts = list(texts or [])
    lag = int(lag or 0)
    if lag <= 0:
        return texts
    if lag >= len(texts):
        return [""] * len(texts)
    return list(texts[lag:]) + [""] * lag


def displayLabels(series):
    labels = []
    for item in series or []:
        site = str(item.get("label") or "").strip()
        dataId = str(item.get("dataId") or "").strip()
        if site and site != dataId:
            labels.append(site)
        else:
            labels.append(dataId or site or "Series")
    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    out = []
    for item, label in zip(series or [], labels):
        dataId = str(item.get("dataId") or "").strip()
        if counts.get(label, 0) > 1 and dataId and dataId not in label:
            out.append(f"{label} ({dataId})")
        else:
            out.append(label)
    return out


def numericColumns(fetched):
    stamps = list((fetched or {}).get("timestamps") or [])
    n = len(stamps)
    columns = []
    for item in (fetched or {}).get("series") or []:
        vals = [parseNumeric(v) for v in (item.get("values") or [])]
        if len(vals) < n:
            vals.extend([np.nan] * (n - len(vals)))
        columns.append(np.asarray(vals[:n] if n else vals, dtype=float))
    return columns


def parsedTimes(fetched):
    stamps = list((fetched or {}).get("timestamps") or [])
    times = [Query.parseDisplayTimestamp(s) for s in stamps]
    texts = ["" if s is None else str(s) for s in stamps]
    return times, texts


class PlotterPanel(GraphPanel):
    """One plot surface. Line and Time Lag share the graph tools; Scatter is points."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tabPlotter")
        if self._placeholder is not None:
            self._placeholder.setText("Run a plot from the Plotter window.")
        self.plotKind = ""
        self.lagState = None
        self.lastLagInfo = None
        self.onViewChanged = self.refreshViewStats

        self.lagHost = QWidget(self)
        self.lagHostLayout = QVBoxLayout(self.lagHost)
        self.lagHostLayout.setContentsMargins(8, 0, 8, 6)
        self.lagHostLayout.setSpacing(2)
        self.lagRows = []
        self.lagStats = QLabel("", self)
        self.lagStats.setContentsMargins(8, 2, 8, 2)
        self.lagStats.setWordWrap(True)
        self._layout.addWidget(self.lagStats)
        self._layout.addWidget(self.lagHost)
        self.lagStats.hide()
        self.lagHost.hide()

    def pinLagBar(self):
        if self.lagStats is not None:
            self._layout.removeWidget(self.lagStats)
            self._layout.addWidget(self.lagStats)
        if self.lagHost is not None:
            self._layout.removeWidget(self.lagHost)
            self._layout.addWidget(self.lagHost)

    def hideLagChrome(self):
        if self.lagStats is not None:
            self.lagStats.hide()
        if self.lagHost is not None:
            self.lagHost.hide()

    def sliderStyle(self, color):
        return (
            "QSlider::groove:horizontal { height: 4px; background: rgba(128,128,128,90); border-radius: 2px; }"
            "QSlider::handle:horizontal {"
            f" background: {color}; width: 16px; margin: -6px 0; border-radius: 8px;"
            "}"
        )

    def clearLagRows(self):
        for row in self.lagRows:
            widget = row.get("widget")
            slider = row.get("slider")
            if slider is not None:
                slider.blockSignals(True)
            if widget is not None:
                self.lagHostLayout.removeWidget(widget)
                widget.deleteLater()
        self.lagRows = []

    def colorForSeries(self, seriesId):
        entry = self.entryById(seriesId)
        color = entry.get("color") if entry else None
        return str(color) if color else "#1f77b4"

    def rebuildLagRows(self, lags, limit, interval):
        """One slider per series after the first. Handle and step text use that line's color."""
        self.clearLagRows()
        for i in range(1, len(lags)):
            color = self.colorForSeries(f"lag{i}")
            wrap = QWidget(self.lagHost)
            layout = QHBoxLayout(wrap)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            slider = QSlider(Qt.Orientation.Horizontal, wrap)
            slider.setMinimum(0)
            slider.setMaximum(max(0, int(limit)))
            slider.setValue(int(lags[i]))
            slider.setEnabled(int(limit) > 0)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            slider.setStyleSheet(self.sliderStyle(color))
            readout = QLabel("", wrap)
            readout.setMinimumWidth(220)
            readout.setStyleSheet(f"color: {color};")
            layout.addWidget(slider, stretch=1)
            layout.addWidget(readout)
            self.lagHostLayout.addWidget(wrap)
            slider.valueChanged.connect(lambda value, index=i: self.onLagSlider(index, value))
            self.lagRows.append({
                "index": i,
                "slider": slider,
                "readout": readout,
                "widget": wrap,
            })
        self.refreshLagReadouts()

    def showLine(self, fetched):
        self.plotKind = "line"
        self.lagState = None
        self.lastLagInfo = None
        self.hideLagChrome()
        times, texts, columns, labels, rawTexts = self.bundle(fetched)
        series = []
        for i, col in enumerate(columns):
            if not np.any(np.isfinite(col)):
                continue
            series.append((labels[i], col, rawTexts[i], col))
        if not series:
            return False, "No numeric values to plot."
        ok, note = self.plotPrepared(times, texts, series)
        self.pinLagBar()
        return ok, note

    def showScatter(self, fetched):
        self.plotKind = "scatter"
        self.lagState = None
        self.lastLagInfo = None
        self.hideLagChrome()
        _times, _texts, columns, labels, rawTexts = self.bundle(fetched)
        if len(columns) != 2:
            return False, "Scatter needs exactly two Data IDs. The first is X and the second is Y."
        x = columns[0]
        y = columns[1]
        mask = np.isfinite(x) & np.isfinite(y)
        if int(np.sum(mask)) < 2:
            return False, "Scatter needs overlapping numeric values on both Data IDs."
        xs = x[mask]
        ys = y[mask]
        texts = [rawTexts[1][i] for i in np.flatnonzero(mask)]
        series = [(labels[1], ys, texts, ys)]
        ok, note = self.plotPrepared([], [], series, xValues=xs, markersOnly=True)
        if ok and self._ax is not None:
            self._ax.set_xlabel(labels[0])
            self._ax.set_ylabel(labels[1])
            try:
                self._applyChartFonts(self._ax, list(self._yAxes[1:]) if self._yAxes else [])
            except Exception:
                pass
            if self.canvas is not None:
                self.canvas.draw_idle()
        self.pinLagBar()
        return ok, note

    def showTimeLag(self, fetched, restoreLag=None, restoreLags=None):
        self.plotKind = "timeLag"
        self.lagState = None
        times, texts, columns, labels, rawTexts = self.bundle(fetched)
        if len(columns) < 2:
            self.hideLagChrome()
            return False, (
                "Time Lag needs at least two Data IDs. "
                "Put the upstream series first and the downstream series last."
            )
        if not np.any(np.isfinite(columns[0])) or not np.any(np.isfinite(columns[-1])):
            self.hideLagChrome()
            return False, "Time Lag needs numeric values on the first and last Data IDs."
        n = int(columns[0].size)
        window = max(0, n - 1)
        limit = maxLagSteps(overlapCount(columns[0], columns[-1]), window)
        recommended, _pairs, lagVsFirst, _direct = chainLag(columns, limit)
        lags = [int(min(max(int(v), 0), limit)) for v in lagVsFirst]
        if not lags:
            lags = [0]
        lags[0] = 0
        if isinstance(restoreLags, (list, tuple)) and restoreLags:
            for offset, raw in enumerate(restoreLags):
                index = offset + 1
                if index >= len(lags):
                    break
                try:
                    lags[index] = int(min(max(int(raw), 0), limit))
                except (TypeError, ValueError):
                    pass
        elif restoreLag is not None and len(lags) > 1:
            try:
                lags[-1] = int(min(max(int(restoreLag), 0), limit))
            except (TypeError, ValueError):
                pass
        series = []
        for i, col in enumerate(columns):
            if i not in (0, len(columns) - 1) and not np.any(np.isfinite(col)):
                continue
            lag = lags[i] if i < len(lags) else 0
            shifted = shiftByLag(col, lag)
            series.append((
                labels[i], shifted, shiftedTexts(rawTexts[i], lag), shifted, f"lag{i}",
            ))
        ok, note = self.plotPrepared(times, texts, series)
        self.pinLagBar()
        if not ok:
            self.hideLagChrome()
            return ok, note
        refEntry = self.entryById("lag0")
        x = None
        if refEntry is not None and refEntry.get("line") is not None:
            x = np.asarray(refEntry["line"].get_xdata(), dtype=float)
        self.lagState = {
            "x": x,
            "columns": columns,
            "texts": rawTexts,
            "lags": lags,
            "interval": (fetched or {}).get("interval") or "",
            "maxLag": limit,
            "recommended": recommended,
        }
        self.rememberLagInfo()
        self.rebuildLagRows(lags, limit, self.lagState["interval"])
        self.lagStats.show()
        self.lagHost.show()
        self.refreshViewStats()
        return True, note

    def rememberLagInfo(self):
        state = self.lagState or {}
        lags = list(state.get("lags") or [])
        self.lastLagInfo = {
            "recommended": state.get("recommended"),
            "slider": lags[-1] if len(lags) > 1 else 0,
            "sliderLags": [int(v) for v in lags[1:]],
            "maxLag": state.get("maxLag"),
        }

    def bundle(self, fetched):
        times, texts = parsedTimes(fetched)
        columns = numericColumns(fetched)
        labels = displayLabels((fetched or {}).get("series"))
        raw = []
        for item, col in zip((fetched or {}).get("series") or [], columns):
            textsFor = valueTexts(item.get("values"))
            if len(textsFor) < col.size:
                textsFor.extend([""] * (col.size - len(textsFor)))
            raw.append(textsFor[: col.size])
        return times, texts, columns, labels, raw

    def entryById(self, seriesId):
        for entry in self._lineData or []:
            if entry.get("seriesId") == seriesId:
                return entry
        return None

    def onLagSlider(self, index, value):
        if self.plotKind != "timeLag" or not self.lagState:
            return
        self.applySeriesLag(int(index), int(value))

    def applySeriesLag(self, index, lag):
        state = self.lagState
        if not state:
            return
        columns = state.get("columns") or []
        lags = state.get("lags") or []
        if index <= 0 or index >= len(columns) or index >= len(lags):
            return
        limit = int(state.get("maxLag") or 0)
        lag = int(min(max(lag, 0), limit))
        entry = self.entryById(f"lag{index}")
        line = entry.get("line") if entry else None
        if line is None:
            return
        y = shiftByLag(columns[index], lag)
        try:
            line.set_ydata(y)
        except Exception as e:
            Logic.logException("applySeriesLag set_ydata failed", e)
            return
        x = np.asarray(line.get_xdata(), dtype=float)
        mask = np.isfinite(x) & np.isfinite(y)
        entry["xs"] = np.asarray(x[mask], dtype=float)
        entry["ys"] = np.asarray(y[mask], dtype=float)
        entry["yRounded"] = np.asarray(y[mask], dtype=float)
        texts = (state.get("texts") or [])
        raw = texts[index] if index < len(texts) else []
        moved = shiftedTexts(raw, lag)
        if len(moved) == y.size:
            entry["yTexts"] = [moved[i] for i, keep in enumerate(mask) if keep]
        lags[index] = lag
        self.rememberLagInfo()
        self.expandStoredYLimits()
        self._autoscaleYToXView()
        self._refreshMarkerDensity(draw=False)
        if self.canvas is not None:
            self.canvas.draw_idle()
        self.refreshViewStats()

    def expandStoredYLimits(self):
        axes = self._yAxes or []
        if not axes:
            return
        buckets = [[] for _ in axes]
        for entry in self._lineData or []:
            ys = entry.get("ys")
            if ys is None or len(ys) == 0:
                continue
            ai = self._axisIndexForEntry(entry)
            if 0 <= ai < len(buckets):
                buckets[ai].append(np.asarray(ys, dtype=float))
        if len(self._yDataLims) < len(axes):
            self._yDataLims = list(self._yDataLims) + [None] * (len(axes) - len(self._yDataLims))
        for i, bucket in enumerate(buckets):
            lim = self._padLimits(bucket)
            if lim is not None:
                self._yDataLims[i] = lim
        if self._yDataLims:
            self._yDataLim = self._yDataLims[0]
            if len(self._yDataLims) > 1:
                self._y2DataLim = self._yDataLims[1]

    def refreshLagReadouts(self):
        state = self.lagState or {}
        lags = state.get("lags") or []
        interval = state.get("interval") or ""
        limit = int(state.get("maxLag") or 0)
        for row in self.lagRows:
            index = row["index"]
            lag = int(lags[index]) if index < len(lags) else 0
            readout = row.get("readout")
            if readout is None:
                continue
            if limit <= 0:
                readout.setText("Not enough overlap to estimate a lag.")
            else:
                readout.setText(lagClockText(lag, interval))

    def refreshViewStats(self):
        if self.plotKind != "timeLag" or not self.lagState:
            return
        self.refreshLagReadouts()
        state = self.lagState
        if self._ax is None or self.lagStats is None:
            return
        try:
            x0, x1 = self._ax.get_xlim()
        except Exception:
            return
        x = state.get("x")
        if x is None:
            ref = self.entryById("lag0")
            if ref is not None and ref.get("line") is not None:
                x = np.asarray(ref["line"].get_xdata(), dtype=float)
                state["x"] = x
        columns = state.get("columns") or []
        lags = state.get("lags") or []
        if x is None or len(columns) < 2 or len(lags) < 2:
            return
        shifted = shiftByLag(columns[-1], int(lags[-1]))
        scores = viewPairScores(x, columns[0], shifted, x0, x1)
        self.lagStats.setText(self.statsLine(scores))

    def statsLine(self, scores):
        """Same block Regression uses, plus NSE, for the points in view."""
        count = int((scores or {}).get("n") or 0)
        if count < 3:
            return "Not enough overlap in view"
        def piece(name, key):
            value = scores.get(key)
            shown = "—" if value is None else formatNumber(value)
            return f"{name} = {shown}"
        return (
            f"{piece('r²', 'r2')}   {piece('NSE', 'nse')}   "
            f"{piece('ME', 'me')}   {piece('RMSE', 'rmse')}   N = {count}"
        )


class uiPlotter(QMainWindow):
    """Plot query window. Same dates and Data ID list as Public Query, API fetch only."""

    def __init__(self, winMain=None):
        super().__init__(None)
        uiPath = Logic.resourcePath("ui/winPlotter.ui")
        uic.loadUi(uiPath, self)
        self.queryType = "plotter"
        self.winMain = winMain
        self.editingQueryIndex = None
        self.quickLookDateRule = None
        self.restoreLag = None
        self.restoreLags = None
        self._shownOnce = False
        self.uiSearch = None

        self.btnQuery = self.findChild(QPushButton, "btnQuery")
        self.qleDataID = self.findChild(QLineEdit, "qleDataID")
        self.cbDatabase = self.findChild(QComboBox, "cbDatabase")
        self.cbInterval = self.findChild(QComboBox, "cbInterval")
        self.dteStartDate = self.findChild(QDateTimeEdit, "dteStartDate")
        self.dteEndDate = self.findChild(QDateTimeEdit, "dteEndDate")
        self.listQueryList = self.findChild(QListWidget, "listQueryList")
        self.btnAddQuery = self.findChild(QPushButton, "btnAddQuery")
        self.btnRemoveQuery = self.findChild(QPushButton, "btnRemoveQuery")
        self.btnSaveQuickLook = self.findChild(QPushButton, "btnSaveQuickLook")
        self.cbQuickLook = self.findChild(QComboBox, "cbQuickLook")
        self.btnLoadQuickLook = self.findChild(QPushButton, "btnLoadQuickLook")
        self.btnDeleteQuickLook = self.findChild(QPushButton, "btnDeleteQuickLook")
        self.btnClearQuery = self.findChild(QPushButton, "btnClearQuery")
        self.btnDataIdInfo = self.findChild(QPushButton, "btnDataIdInfo")
        self.btnIntervalInfo = self.findChild(QPushButton, "btnIntervalInfo")
        self.btnQueryOptionsInfo = self.findChild(QPushButton, "btnQueryOptionsInfo")
        self.btnSearch = self.findChild(QPushButton, "btnSearch")
        self.rbCustomDateTime = self.findChild(QRadioButton, "rbCustomDateTime")
        self.rbPrevDayToCurrent = self.findChild(QRadioButton, "rbPrevDayToCurrent")
        self.rbPrevWeekToCurrent = self.findChild(QRadioButton, "rbPrevWeekToCurrent")
        self.rbPlotLine = self.findChild(QRadioButton, "rbPlotLine")
        self.rbPlotScatter = self.findChild(QRadioButton, "rbPlotScatter")
        self.rbPlotTimeLag = self.findChild(QRadioButton, "rbPlotTimeLag")
        self.btnUpMax = self.findChild(QPushButton, "btnUpMax")
        self.btnUp15 = self.findChild(QPushButton, "btnUp15")
        self.btnUp5 = self.findChild(QPushButton, "btnUp5")
        self.btnUp1 = self.findChild(QPushButton, "btnUp1")
        self.btnDownMax = self.findChild(QPushButton, "btnDownMax")
        self.btnDown15 = self.findChild(QPushButton, "btnDown15")
        self.btnDown5 = self.findChild(QPushButton, "btnDown5")
        self.btnDown1 = self.findChild(QPushButton, "btnDown1")

        self.dateRadios = QButtonGroup(self)
        self.dateRadios.addButton(self.rbCustomDateTime)
        self.dateRadios.addButton(self.rbPrevDayToCurrent)
        self.dateRadios.addButton(self.rbPrevWeekToCurrent)
        self.plotRadios = QButtonGroup(self)
        self.plotRadios.addButton(self.rbPlotLine)
        self.plotRadios.addButton(self.rbPlotScatter)
        self.plotRadios.addButton(self.rbPlotTimeLag)
        if self.rbPlotLine is not None:
            self.rbPlotLine.setChecked(True)

        self.populateIntervalCombo(ALL_INTERVALS)
        # Empty QComboBox is falsy; loadDatabase skips it unless something is already there.
        if self.cbDatabase is not None:
            self.cbDatabase.addItem("")
        buttonIcons = [
            (self.btnDataIdInfo, "Info", 24),
            (self.btnIntervalInfo, "Info", 24),
            (self.btnQueryOptionsInfo, "Info", 24),
            (self.btnUpMax, "Up-MAX", 24),
            (self.btnUp15, "Up-15", 24),
            (self.btnUp5, "Up-5", 24),
            (self.btnUp1, "Up-1", 24),
            (self.btnDownMax, "Down-MAX", 24),
            (self.btnDown15, "Down-15", 24),
            (self.btnRemoveQuery, "Delete", 24),
            (self.btnDown5, "Down-5", 24),
            (self.btnDown1, "Down-1", 24),
            (self.btnSearch, "Search", 24),
        ]
        for btn, iconName, iconSize in buttonIcons:
            if btn is not None:
                Utils.buttonStyle(btn, iconName, iconSize=iconSize)
        if self.btnSearch is not None:
            self.btnSearch.setToolTip("Data ID Search")

        self.btnQuery.clicked.connect(self.btnPlotPressed)
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed)
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed)
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)
        self.btnDeleteQuickLook.clicked.connect(self.btnDeleteQuickLookPressed)
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)
        self.btnQueryOptionsInfo.clicked.connect(self.btnPlotTypesInfoPressed)
        self.dateRadios.buttonClicked.connect(self.onDateRadioClicked)
        self.cbDatabase.currentTextChanged.connect(self.onDatabaseChanged)
        if self.btnSearch is not None:
            self.btnSearch.clicked.connect(self.showSearch)
        if self.listQueryList is not None:
            self.listQueryList.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.listQueryList.itemDoubleClicked.connect(self.onQueryListDoubleClicked)
            self.listQueryList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.listQueryList.customContextMenuRequested.connect(self.showQueryListContextMenu)
        for btn, slot in (
            (self.btnUpMax, self.btnUpMaxPressed),
            (self.btnUp15, self.btnUp15Pressed),
            (self.btnUp5, self.btnUp5Pressed),
            (self.btnUp1, self.btnUp1Pressed),
            (self.btnDownMax, self.btnDownMaxPressed),
            (self.btnDown15, self.btnDown15Pressed),
            (self.btnDown5, self.btnDown5Pressed),
            (self.btnDown1, self.btnDown1Pressed),
        ):
            if btn is not None:
                btn.clicked.connect(slot)

        self.qleDataID.installEventFilter(self)
        self.qleDataID.textChanged.connect(self.onDataIdTextChanged)
        self.installEventFilter(self)
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        Utils.bindIndependentWindow(self, owner=winMain, allowMaximize=False)
        Utils.loadQuickLooks(self.cbQuickLook, Utils.getPlotQuickLookDir())

    def showEvent(self, event):
        Utils.centerWindowToParent(self)
        Utils.applyRoleFonts(root=self)
        Utils.applyModeControlLayouts(root=self)
        self.setWindowIcon(QIcon(Logic.resourcePath("ui/icons/Plotter.png")))
        self.setWindowTitle("Plotter")
        prevDb = self.cbDatabase.currentText() if self.cbDatabase is not None else ""
        prevInterval = self.cbInterval.currentText() if self.cbInterval is not None else ""
        Utils.loadDatabase(self.cbDatabase, "plotter")
        if prevDb and self.cbDatabase is not None:
            idx = self.cbDatabase.findText(prevDb)
            if idx >= 0:
                self.cbDatabase.setCurrentIndex(idx)
        self.updateIntervalForDatabase()
        if prevInterval and self.cbInterval is not None:
            idx = self.cbInterval.findText(prevInterval)
            if idx >= 0:
                self.cbInterval.setCurrentIndex(idx)
        if not self._shownOnce:
            Logic.loadLastQuickLook(self.cbQuickLook, "lastPlotQuickLook")
            self._shownOnce = True
        self.refreshRelativeQueryTimes()
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        super().showEvent(event)

    def plotTypeKey(self):
        if self.rbPlotScatter is not None and self.rbPlotScatter.isChecked():
            return "scatter"
        if self.rbPlotTimeLag is not None and self.rbPlotTimeLag.isChecked():
            return "timeLag"
        return "line"

    def applyPlotType(self, key):
        target = {
            "scatter": self.rbPlotScatter,
            "timeLag": self.rbPlotTimeLag,
        }.get(key, self.rbPlotLine)
        if target is not None:
            target.setChecked(True)

    def populateIntervalCombo(self, intervals, preferred=None):
        if self.cbInterval is None:
            return
        prev = self.cbInterval.currentText()
        self.cbInterval.blockSignals(True)
        try:
            self.cbInterval.clear()
            for name in intervals:
                self.cbInterval.addItem(name)
            idx = self.cbInterval.findText(prev)
            if idx >= 0:
                self.cbInterval.setCurrentIndex(idx)
            elif preferred:
                prefIdx = self.cbInterval.findText(preferred)
                self.cbInterval.setCurrentIndex(prefIdx if prefIdx >= 0 else 0)
            elif self.cbInterval.count() > 0:
                self.cbInterval.setCurrentIndex(0)
        finally:
            self.cbInterval.blockSignals(False)

    def updateIntervalForDatabase(self, database=None):
        if self.cbDatabase is None:
            return
        db = self.cbDatabase.currentText() if database is None else database
        if db == "USGS-NWIS":
            self.populateIntervalCombo(USGS_INTERVALS, preferred=USGS_DEFAULT_INTERVAL)
        else:
            self.populateIntervalCombo(ALL_INTERVALS)

    def onDatabaseChanged(self, text):
        self.updateIntervalForDatabase(text)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery)
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.qleDataID.hasFocus():
                self.btnAddQueryPressed()
            elif self.btnQuery.isDefault():
                self.btnPlotPressed()
            return True
        return super().eventFilter(obj, event)

    def btnPlotPressed(self):
        try:
            self.refreshRelativeQueryTimes()
            kind = self.plotTypeKey()
            items = self.collectQueryItems()
            if items is None:
                return
            if not items:
                QMessageBox.warning(self, "Plotter", "Add at least one Data ID.")
                return
            if kind == "scatter" and len(items) != 2:
                QMessageBox.warning(
                    self, "Plotter",
                    "Scatter needs exactly two Data IDs.\n\nThe first list row is X and the second is Y.",
                )
                return
            if kind == "timeLag" and len(items) < 2:
                QMessageBox.warning(
                    self, "Plotter",
                    "Time Lag needs at least two Data IDs.\n\n"
                    "Put the upstream series first and the downstream series last.",
                )
                return
            startDate = self.dteStartDate.dateTime().toString("yyyy-MM-dd hh:mm")
            endDate = self.dteEndDate.dateTime().toString("yyyy-MM-dd hh:mm")
            bucket = []
            host = self.winMain if self.winMain is not None else self
            # Same as Query: hide this window, progress stays on the main window,
            # then close so Plot is not left sitting over the tab.
            self.hide()
            Query.executeQuery(
                host, items, startDate, endDate,
                False, None,
                apiOnly=True, seriesSink=bucket,
            )
            if bucket and self.winMain is not None:
                panel = self.winMain.ensurePlotterPanel()
                seed = self.restoreLag
                seeds = self.restoreLags
                self.restoreLag = None
                self.restoreLags = None
                if kind == "timeLag" and seeds is None and seed is None:
                    info = getattr(panel, "lastLagInfo", None)
                    if isinstance(info, dict):
                        seeds = info.get("sliderLags")
                        seed = info.get("slider")
                if kind == "line":
                    ok, message = panel.showLine(bucket[0])
                elif kind == "scatter":
                    ok, message = panel.showScatter(bucket[0])
                else:
                    ok, message = panel.showTimeLag(
                        bucket[0], restoreLag=seed, restoreLags=seeds,
                    )
                if not ok:
                    QMessageBox.warning(host, "Plotter", message or "Could not build the plot.")
                else:
                    self.winMain.showPlotterInMainTabs(PLOT_TITLES.get(kind, "Plotter"), select=True)
            self.close()
        except Exception as e:
            Logic.logException("btnPlotPressed failed", e)
            QMessageBox.warning(self, "Plotter", f"Failed to plot:\n{e}")

    def collectQueryItems(self):
        items = []
        if self.listQueryList is None:
            return items
        for i in range(self.listQueryList.count()):
            listItem = self.listQueryList.item(i)
            text = listItem.text().strip() if listItem is not None else ""
            parsed = QueryFlags.parseListText(text)
            if parsed is None:
                Logic.logMessage("WARN", f"Plotter skipped invalid item: {text}")
                continue
            kind, dataId, interval, database = parsed
            if kind == QueryFlags.KIND_EQUATION:
                QMessageBox.warning(self, "Plotter", "Plotter does not plot formula columns.")
                return None
            if database == "USGS-NWIS":
                resolved = self.resolveUsgs(dataId)
                if resolved is None:
                    return None
                if resolved != dataId:
                    dataId = resolved
                    listItem.setText(f"{dataId}|{interval}|{database}")
            mrid = "0"
            if database.startswith("USBR-") and "-" in dataId:
                _sdid, mrid = dataId.rsplit("-", 1)
            items.append((dataId, interval, database, mrid, i))
        if items or not (self.qleDataID.text() or "").strip():
            return items
        text = self.buildQueryListItemText()
        if not text:
            return None
        parsed = QueryFlags.parseListText(text)
        if parsed is None or parsed[0] != QueryFlags.KIND_SERIES:
            return items
        _k, dataId, interval, database = parsed
        mrid = "0"
        if database.startswith("USBR-") and "-" in dataId:
            _sdid, mrid = dataId.rsplit("-", 1)
        return [(dataId, interval, database, mrid, 0)]

    def resolveUsgs(self, dataId):
        try:
            from core import USGS
            resolved = USGS.resolveUsgsDataId(dataId, parent=self)
        except Exception as e:
            Logic.logException("Plotter USGS resolve failed", e)
            return dataId
        if resolved is None:
            QMessageBox.warning(
                self, "USGS Data ID",
                f"Could not resolve USGS Data ID '{dataId}'.\n"
                "Include time_series_id, or pick a series when prompted.",
            )
            return None
        return resolved

    def buildQueryListItemText(self):
        dataId = self.qleDataID.text().strip() if self.qleDataID is not None else ""
        interval = self.cbInterval.currentText() if self.cbInterval is not None else ""
        database = self.cbDatabase.currentText() if self.cbDatabase is not None else ""
        if not dataId:
            return None
        if database == "USGS-NWIS":
            resolved = self.resolveUsgs(dataId)
            if resolved is None:
                return None
            dataId = resolved
        return f"{dataId}|{interval}|{database}"

    def makeItem(self, text):
        return QueryFlags.makeListItem(text, flags=QueryFlags.emptyFlags())

    def btnAddQueryPressed(self):
        editIdx = self.editingQueryIndex
        itemText = self.buildQueryListItemText()
        if not itemText:
            return
        if (
            editIdx is not None
            and self.listQueryList is not None
            and 0 <= editIdx < self.listQueryList.count()
        ):
            self.listQueryList.item(editIdx).setText(itemText)
            self.listQueryList.setCurrentRow(editIdx)
        else:
            self.listQueryList.addItem(self.makeItem(itemText))
            self.listQueryList.scrollToBottom()
        self.editingQueryIndex = None
        self.setQueryAddMode(False)
        self.qleDataID.clear()
        self.qleDataID.setFocus()

    def setQueryAddMode(self, updating):
        if self.btnAddQuery is None:
            return
        self.btnAddQuery.setText("Update Query" if updating else "Add Query")

    def onDataIdTextChanged(self, text):
        if self.editingQueryIndex is None:
            return
        if str(text or "").strip():
            return
        self.editingQueryIndex = None
        self.setQueryAddMode(False)

    def btnRemoveQueryPressed(self):
        selected = self.listQueryList.selectedItems()
        if not selected:
            return
        removed = {self.listQueryList.row(item) for item in selected}
        if self.editingQueryIndex is not None and self.editingQueryIndex in removed:
            self.editingQueryIndex = None
            self.setQueryAddMode(False)
            self.qleDataID.clear()
        for item in selected:
            self.listQueryList.takeItem(self.listQueryList.row(item))
        if self.editingQueryIndex is not None:
            below = sum(1 for row in removed if row < self.editingQueryIndex)
            self.editingQueryIndex -= below
            if self.editingQueryIndex < 0 or self.editingQueryIndex >= self.listQueryList.count():
                self.editingQueryIndex = None
                self.setQueryAddMode(False)

    def btnClearQueryPressed(self):
        self.listQueryList.clear()
        self.editingQueryIndex = None
        self.setQueryAddMode(False)
        if self.qleDataID is not None:
            self.qleDataID.clear()

    def onQueryListDoubleClicked(self, item):
        if item is None or self.listQueryList is None:
            return
        parts = item.text().strip().split("|", 2)
        if len(parts) != 3:
            return
        dataId, interval, database = parts
        self.editingQueryIndex = self.listQueryList.row(item)
        self.setQueryAddMode(True)
        self.qleDataID.setText(dataId)
        self.qleDataID.setFocus()
        self.qleDataID.selectAll()
        if self.cbDatabase is not None:
            idx = self.cbDatabase.findText(database)
            if idx >= 0:
                self.cbDatabase.setCurrentIndex(idx)
        if self.cbInterval is not None and interval:
            idx = self.cbInterval.findText(interval)
            if idx >= 0:
                self.cbInterval.setCurrentIndex(idx)

    def showQueryListContextMenu(self, pos):
        if self.listQueryList is None:
            return
        item = self.listQueryList.itemAt(pos)
        if item is None:
            return
        row = self.listQueryList.row(item)
        selected = self.listQueryList.selectedItems()
        if item not in selected:
            self.listQueryList.clearSelection()
            item.setSelected(True)
            self.listQueryList.setCurrentItem(item)
        dataId = self.qleDataID.text().strip() if self.qleDataID is not None else ""
        nSel = len(self.listQueryList.selectedItems())
        menu = QMenu(self)
        actAbove = menu.addAction("Insert Above")
        actBelow = menu.addAction("Insert Below")
        canInsert = bool(dataId) and nSel <= 1
        actAbove.setEnabled(canInsert)
        actBelow.setEnabled(canInsert)
        menu.addSeparator()
        actDelete = menu.addAction("Delete" if nSel <= 1 else f"Delete ({nSel})")
        chosen = menu.exec(self.listQueryList.mapToGlobal(pos))
        if chosen == actAbove:
            self.insertQueryAt(row, below=False)
        elif chosen == actBelow:
            self.insertQueryAt(row, below=True)
        elif chosen == actDelete:
            self.btnRemoveQueryPressed()

    def insertQueryAt(self, anchorRow, below=False):
        itemText = self.buildQueryListItemText()
        if not itemText or self.listQueryList is None:
            return
        insertAt = anchorRow + 1 if below else anchorRow
        insertAt = max(0, min(insertAt, self.listQueryList.count()))
        self.listQueryList.insertItem(insertAt, self.makeItem(itemText))
        self.listQueryList.setCurrentRow(insertAt)
        self.editingQueryIndex = None
        self.setQueryAddMode(False)
        self.qleDataID.clear()
        self.qleDataID.setFocus()

    def moveSelectedRows(self, delta, toEnd=False):
        lst = self.listQueryList
        if lst is None:
            return
        selected = lst.selectedItems()
        if not selected:
            return
        senderBtn = self.sender()
        try:
            n = lst.count()
            if n <= 0:
                return
            rows = sorted({lst.row(it) for it in selected})
            if toEnd:
                if delta < 0:
                    newRows = list(range(len(rows)))
                else:
                    start = n - len(rows)
                    newRows = list(range(start, n))
            elif delta < 0:
                newRows = []
                ceiling = -1
                for r in rows:
                    dest = max(ceiling + 1, r + delta)
                    newRows.append(dest)
                    ceiling = dest
            else:
                newRows = [0] * len(rows)
                floor = n
                for i in range(len(rows) - 1, -1, -1):
                    dest = min(floor - 1, rows[i] + delta)
                    newRows[i] = dest
                    floor = dest
            if newRows == rows:
                return
            original = [lst.item(i) for i in range(n)]
            moving = set(rows)
            destOf = {old: new for old, new in zip(rows, newRows)}
            result = [None] * n
            for old, new in destOf.items():
                result[new] = original[old]
            remaining = [original[i] for i in range(n) if i not in moving]
            ri = 0
            for i in range(n):
                if result[i] is None:
                    result[i] = remaining[ri]
                    ri += 1
            selectedIds = {id(original[r]) for r in rows}
            bar = lst.verticalScrollBar()
            oldScroll = bar.value() if bar is not None else 0
            lst.blockSignals(True)
            try:
                for i in range(n - 1, -1, -1):
                    lst.takeItem(i)
                for it in result:
                    lst.addItem(it)
                    it.setSelected(id(it) in selectedIds)
                if result and rows:
                    current = original[rows[0]]
                    if id(current) in selectedIds:
                        lst.setCurrentItem(current)
            finally:
                lst.blockSignals(False)
            if bar is not None:
                bar.setValue(oldScroll)
        finally:
            Utils.resetStyledButtonHover(senderBtn)

    def btnUpMaxPressed(self):
        self.moveSelectedRows(-1, toEnd=True)

    def btnUp15Pressed(self):
        self.moveSelectedRows(-15)

    def btnUp5Pressed(self):
        self.moveSelectedRows(-5)

    def btnUp1Pressed(self):
        self.moveSelectedRows(-1)

    def btnDownMaxPressed(self):
        self.moveSelectedRows(1, toEnd=True)

    def btnDown15Pressed(self):
        self.moveSelectedRows(15)

    def btnDown5Pressed(self):
        self.moveSelectedRows(5)

    def btnDown1Pressed(self):
        self.moveSelectedRows(1)

    def queryDateMode(self):
        if self.rbPrevDayToCurrent is not None and self.rbPrevDayToCurrent.isChecked():
            return "prevDay"
        if self.rbPrevWeekToCurrent is not None and self.rbPrevWeekToCurrent.isChecked():
            return "prevWeek"
        return "custom"

    def onDateRadioClicked(self, btn):
        Logic.setQueryDateRange(self, btn, self.dteStartDate, self.dteEndDate)
        if btn is not self.rbCustomDateTime:
            self.quickLookDateRule = None

    def queryListTexts(self):
        if self.listQueryList is None:
            return []
        return [
            self.listQueryList.item(i).text()
            for i in range(self.listQueryList.count())
            if self.listQueryList.item(i) is not None
        ]

    def refreshRelativeQueryTimes(self):
        try:
            if self.rbPrevDayToCurrent is not None and self.rbPrevDayToCurrent.isChecked():
                Logic.setQueryDateRange(self, self.rbPrevDayToCurrent, self.dteStartDate, self.dteEndDate)
            elif self.rbPrevWeekToCurrent is not None and self.rbPrevWeekToCurrent.isChecked():
                Logic.setQueryDateRange(self, self.rbPrevWeekToCurrent, self.dteStartDate, self.dteEndDate)
            elif self.queryDateMode() == "custom":
                rule = self.quickLookDateRule
                if isinstance(rule, dict) and rule.get("kind") not in (None, "fixed", "omit"):
                    result = QuickLookDates.applyRule(rule, datetime.now())
                    if isinstance(result, tuple) and len(result) == 2:
                        self.dteStartDate.setDateTime(result[0])
                        self.dteEndDate.setDateTime(result[1])
        except Exception as e:
            Logic.logException("Plotter refreshRelativeQueryTimes failed", e)

    def pickCustomDateRule(self, startStr, endStr):
        start = QuickLookDates.parseStamp(startStr)
        end = QuickLookDates.parseStamp(endStr)
        now = datetime.now()
        fallback = self.cbInterval.currentText() if self.cbInterval is not None else "HOUR"
        intervalMin = QuickLookDates.finestIntervalMinutes(self.queryListTexts(), fallback)
        choices = QuickLookDates.propose(start or now, end or now, now, intervalMin)
        dlg = QDialog(self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setWindowTitle("Quick Look Date Range")
        dlg.setModal(True)
        dlg.setMinimumWidth(560)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(20 if Config.retroMode else 10)
        layout.setContentsMargins(12, 12, 12, 12)
        intro = QLabel(
            "Custom dates can mean a rolling window. Pick how this Quick Look "
            "should set start and end when you load it (and when you Plot)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        listing = QListWidget(dlg)
        listing.setObjectName("quickLookDateList")
        listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listing.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for choice in choices:
            row = QListWidgetItem(choice["label"])
            row.setData(Qt.ItemDataRole.UserRole, choice)
            listing.addItem(row)
        Utils.applyRetroFont(dlg)
        rowH = listing.sizeHintForRow(0) if listing.count() else 0
        fmH = listing.fontMetrics().height() + listing.fontMetrics().leading()
        if Config.retroMode:
            rowH = max(rowH, fmH + 16, 28)
        else:
            rowH = max(rowH, fmH + 8, 22)
        visible = min(7, max(listing.count(), 1))
        listing.setFixedHeight(rowH * visible + 2 * listing.frameWidth() + 8)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        okBtn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        okBtn.setText("Use this")
        okBtn.setEnabled(False)
        listing.itemSelectionChanged.connect(
            lambda: okBtn.setEnabled(len(listing.selectedItems()) == 1)
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.adjustSize()
        extra = 36 if Config.retroMode else 12
        dlg.resize(max(dlg.width(), 560), dlg.height() + extra)
        dlg.setMinimumHeight(dlg.height())
        Utils.centerWindowToParent(dlg)
        self.raise_()
        dlg.raise_()
        dlg.activateWindow()
        try:
            accepted = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            self.raise_()
            self.activateWindow()
        if not accepted:
            return False
        selected = listing.currentItem()
        if selected is None:
            return False
        choice = selected.data(Qt.ItemDataRole.UserRole) or {}
        if choice.get("id") == "cancelAdjust":
            hint = QuickLookDates.evenIntervalSuggestion(end or now, intervalMin)
            QMessageBox.information(self, "Adjust the dates", "None of the rolling options matched what you want.\n\n" + hint)
            return False
        return choice.get("rule")

    def plotQuickLookExtra(self):
        extra = {"plotType": self.plotTypeKey()}
        panel = getattr(self.winMain, "tabPlotter", None) if self.winMain is not None else None
        info = getattr(panel, "lastLagInfo", None) if panel is not None else None
        if self.plotTypeKey() == "timeLag" and isinstance(info, dict):
            if info.get("recommended") is not None:
                extra["recommendedLag"] = info.get("recommended")
            if info.get("slider") is not None:
                extra["sliderLag"] = info.get("slider")
            if info.get("sliderLags"):
                extra["sliderLags"] = list(info.get("sliderLags"))
        return extra

    def btnSaveQuickLookPressed(self):
        if self.listQueryList is None or self.listQueryList.count() == 0:
            QMessageBox.warning(self, "Empty Query List", "Cannot save Quick Look: No items in the query list.")
            return
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Save Quick Look")
        dlg.setLabelText("Quick Look name:")
        dlg.setInputMode(QInputDialog.InputMode.TextInput)
        dlg.setOkButtonText("Save")
        existing = (self.cbQuickLook.currentText() or "").strip() if self.cbQuickLook is not None else ""
        if existing:
            dlg.setTextValue(existing)
        hint = dlg.sizeHint()
        dlg.resize(max(hint.width(), 280) + 60, hint.height())
        ok = dlg.exec() == dlg.DialogCode.Accepted
        name = dlg.textValue().strip() if ok else ""
        if not ok or not name:
            return
        directory = Utils.getPlotQuickLookDir()
        if Logic.quickLookExists(name, directory):
            reply = QMessageBox.question(
                self, "Overwrite Quick Look",
                f"A Quick Look named '{name}' already exists.\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        dateMode = self.queryDateMode()
        startStr = endStr = None
        dateRule = None
        if dateMode == "custom":
            if self.dteStartDate is not None:
                startStr = self.dteStartDate.dateTime().toString("yyyy-MM-dd HH:mm")
            if self.dteEndDate is not None:
                endStr = self.dteEndDate.dateTime().toString("yyyy-MM-dd HH:mm")
            dateRule = self.pickCustomDateRule(startStr, endStr)
            if dateRule is False:
                return
            if isinstance(dateRule, dict) and dateRule.get("kind") == "omit":
                startStr = endStr = None
            self.quickLookDateRule = dateRule
        else:
            self.quickLookDateRule = None
        Logic.saveQuickLook(
            name, self.listQueryList,
            dateMode=dateMode, startDate=startStr, endDate=endStr, dateRule=dateRule,
            directory=directory, extra=self.plotQuickLookExtra(),
        )
        Utils.loadQuickLooks(self.cbQuickLook, directory)
        if self.cbQuickLook is not None:
            idx = self.cbQuickLook.findText(name)
            if idx >= 0:
                self.cbQuickLook.setCurrentIndex(idx)
        self.rememberQuickLook(name)

    def btnLoadQuickLookPressed(self):
        directory = Utils.getPlotQuickLookDir()
        meta = Logic.loadQuickLook(
            self.cbQuickLook, self.listQueryList,
            dateRadios={
                "custom": self.rbCustomDateTime,
                "prevDay": self.rbPrevDayToCurrent,
                "prevWeek": self.rbPrevWeekToCurrent,
            },
            dteStartDate=self.dteStartDate,
            dteEndDate=self.dteEndDate,
            directory=directory,
        )
        if not isinstance(meta, dict):
            return
        self.applyPlotType(meta.get("plotType") or "line")
        self.quickLookDateRule = meta.get("dateRule") if isinstance(meta.get("dateRule"), dict) else None
        if meta.get("plotType") == "timeLag":
            self.restoreLags = meta.get("sliderLags")
            self.restoreLag = meta.get("sliderLag")
        else:
            self.restoreLags = None
            self.restoreLag = None
        self.refreshRelativeQueryTimes()
        name = self.cbQuickLook.currentText() if self.cbQuickLook is not None else ""
        self.rememberQuickLook(name)

    def btnDeleteQuickLookPressed(self):
        name = self.cbQuickLook.currentText() if self.cbQuickLook is not None else ""
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Quick Look",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not Logic.deleteQuickLook(name, Utils.getPlotQuickLookDir()):
            QMessageBox.warning(self, "Cannot Delete", "That Quick Look could not be deleted.")
            return
        idx = self.cbQuickLook.currentIndex()
        self.cbQuickLook.removeItem(idx)
        self.cbQuickLook.setCurrentIndex(-1)

    def rememberQuickLook(self, name):
        path = Utils.getConfigPath()
        config = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    config = json.load(handle)
            except Exception as e:
                Logic.logMessage("ERROR", f"Failed to load user.config: {e}")
                config = {}
        if not isinstance(config, dict):
            config = {}
        config["lastPlotQuickLook"] = name
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)

    def btnDataIdInfoPressed(self):
        try:
            QMessageBox.information(
                self, "DataID Formats",
                "AQUARIUS Format:\nUID\n\n"
                "USBR Format:\nSDID\nSDID-MRID\n\n"
                "USGS Format:\n"
                "  Site-time_series_id[-parameter]  (OGC; parameter optional)\n"
                "  Site-parameter  (looks up time_series_id; picker if multiple)\n"
                "  Site-methodID-parameter  (legacy)",
            )
        finally:
            Utils.resetStyledButtonHover(self.sender() or self.btnDataIdInfo)

    def btnIntervalInfoPressed(self):
        try:
            QMessageBox.information(
                self, "Interval Info",
                "Interval determines the timestamp grid and, for USBR, which table is read.\n\n"
                "INSTANT:1 / :15 / :30 / :60 are 1-, 15-, 30-, and 60-minute grids. "
                "The grid follows the first Data ID in the list.\n\n"
                "Time Lag counts one slider step as one of those intervals.",
            )
        finally:
            Utils.resetStyledButtonHover(self.sender() or self.btnIntervalInfo)

    def btnPlotTypesInfoPressed(self):
        try:
            QMessageBox.information(
                self, "Plot Types",
                "Line: time on X. Each Data ID is its own series.\n\n"
                "Scatter: exactly two Data IDs. The first list row is X and the second is Y.\n\n"
                "Time Lag: two or more Data IDs, upstream first and downstream last. "
                "Stations in between are queried. Each step to the next station is estimated "
                "and summed as the starting lag from the first series to the last. "
                "The slider on the plot moves only the last series. "
                "The correlation uses the time window currently on screen.",
            )
        finally:
            Utils.resetStyledButtonHover(self.sender() or self.btnQueryOptionsInfo)

    def showSearch(self):
        if self.uiSearch is None:
            self.uiSearch = uiSearch(self)
        self.uiSearch.show()
