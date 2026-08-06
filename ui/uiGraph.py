# uiGraph.py
# Graph tab: plot mainTable series with zoom toolbar and dual Y-axis when scales differ.

from __future__ import annotations

import re
from datetime import datetime

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QSizePolicy, QLabel

from core import Config, Logic

# Lazy matplotlib imports so startup still works if the package is missing
_mplReady = False
Figure = None
FigureCanvasQTAgg = None
NavigationToolbar2QT = None
mdates = None


def _ensureMatplotlib():
    global _mplReady, Figure, FigureCanvasQTAgg, NavigationToolbar2QT, mdates
    if _mplReady:
        return True
    try:
        from matplotlib.figure import Figure as _Figure
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg as _Canvas,
            NavigationToolbar2QT as _Toolbar,
        )
        import matplotlib.dates as _mdates

        Figure = _Figure
        FigureCanvasQTAgg = _Canvas
        NavigationToolbar2QT = _Toolbar
        mdates = _mdates
        _mplReady = True
        return True
    except Exception as e:
        Logic.logException("uiGraph: matplotlib import failed", e)
        return False


# Timestamp formats used by Data Query vertical headers
_TS_FORMATS = (
    '%m/%d/%y %H:%M:00',
    '%m/%d/%y %H:%M:%S',
    '%m/%d/%y %H:%M',
    '%m/%d/%y',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
    '%m/%d/%Y %H:%M:%S',
    '%m/%d/%Y %H:%M',
    '%m/%d/%Y',
)


def parseTimestamp(text):
    """Parse a table timestamp string to datetime, or None."""
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Last resort: dateutil-free ISO-ish cleanup
    try:
        cleaned = s.replace('T', ' ').split('.')[0]
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


def parseNumeric(text):
    """Parse a cell value to float; blank / non-numeric → nan."""
    if text is None:
        return np.nan
    s = str(text).strip()
    if not s or s in ('-', '—', 'N/A', 'n/a', 'null', 'None'):
        return np.nan
    # Strip thousands separators and trailing units-ish junk
    s = s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        m = re.match(r'^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)', s)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return np.nan


def seriesScale(values):
    """
    Characteristic magnitude for dual-axis decisions.
    Prefer data span; fall back to max abs.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 1.0
    span = float(np.nanmax(finite) - np.nanmin(finite))
    peak = float(np.nanmax(np.abs(finite)))
    if span > 1e-12:
        return max(span, peak * 0.1, 1e-12)
    return max(peak, 1e-12)


def assignAxes(seriesList, ratioThreshold=10.0):
    """
    Split series into left / right Y-axis groups when scales differ a lot.

    seriesList: list of (label, values ndarray)
    Returns (leftList, rightList) — each same shape as input items.
    """
    if not seriesList:
        return [], []
    if len(seriesList) == 1:
        return list(seriesList), []

    scales = [seriesScale(vals) for _, vals in seriesList]
    # Use median scale as reference so one outlier does not force everything right
    ref = float(np.median(scales)) if scales else 1.0
    ref = max(ref, 1e-12)

    left, right = [], []
    for item, scale in zip(seriesList, scales):
        ratio = max(scale, ref) / min(scale, ref)
        if ratio >= ratioThreshold:
            right.append(item)
        else:
            left.append(item)

    # Never leave left empty
    if not left and right:
        left = [right.pop(0)]
    return left, right


def headerLabel(table, col):
    """Single-line legend label from multi-line table header."""
    item = table.horizontalHeaderItem(col) if table is not None else None
    if item is None:
        return f"Col {col + 1}"
    text = (item.text() or '').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text or f"Col {col + 1}"


def selectedDataColumns(table):
    """
    Column indices to graph from selection.
    - Selected columns (cells or full columns) → those indices
    - No selection → all columns
    """
    if table is None or table.columnCount() <= 0:
        return []

    cols = set()
    # Cell / range selection
    for idx in table.selectedIndexes():
        cols.add(idx.column())
    # Full column selection via ranges
    for r in table.selectedRanges():
        for c in range(r.leftColumn(), r.rightColumn() + 1):
            cols.add(c)

    if cols:
        return sorted(cols)
    return list(range(table.columnCount()))


def extractSeries(table, columns=None):
    """
    Read timestamps + numeric series from mainTable.

    Returns (timestamps list[datetime|None], series list[(label, values)], warnings)
    """
    warnings = []
    if table is None or table.rowCount() <= 0 or table.columnCount() <= 0:
        return [], [], ["No data in the Data Query table to graph."]

    if columns is None:
        columns = selectedDataColumns(table)
    if not columns:
        return [], [], ["No columns available to graph."]

    nRows = table.rowCount()
    timestamps = []
    for r in range(nRows):
        vh = table.verticalHeaderItem(r)
        tsText = vh.text() if vh is not None else ''
        timestamps.append(parseTimestamp(tsText))

    # If almost no timestamps parsed, use row index as X
    parsedCount = sum(1 for t in timestamps if t is not None)
    useDatetime = parsedCount >= max(2, int(nRows * 0.5))
    if not useDatetime:
        warnings.append("Could not parse most timestamps; using row index on the X axis.")

    series = []
    for c in columns:
        label = headerLabel(table, c)
        vals = np.empty(nRows, dtype=float)
        for r in range(nRows):
            item = table.item(r, c)
            vals[r] = parseNumeric(item.text() if item is not None else '')
        if not np.any(np.isfinite(vals)):
            warnings.append(f"Skipped '{label}' (no numeric values).")
            continue
        series.append((label, vals))

    if not series:
        return timestamps, [], ["No numeric series found to graph."]
    return timestamps, series, warnings


class GraphPanel(QWidget):
    """
    Graph content: matplotlib canvas + NavigationToolbar (zoom / pan / home).
    Fills parent so maximize / resize scales the plot.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('tabGraph')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._placeholder = QLabel("Press Graph to plot the Data Query table.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)

        self.figure = None
        self.canvas = None
        self.toolbar = None
        self._ax = None
        self._ax2 = None

    def clearPlot(self):
        if self.canvas is not None:
            self._layout.removeWidget(self.toolbar)
            self._layout.removeWidget(self.canvas)
            if self.toolbar is not None:
                self.toolbar.setParent(None)
                self.toolbar.deleteLater()
            self.canvas.setParent(None)
            self.canvas.deleteLater()
            self.toolbar = None
            self.canvas = None
            self.figure = None
            self._ax = None
            self._ax2 = None
        if self._placeholder is not None:
            self._placeholder.show()

    def plotFromTable(self, table, columns=None):
        """
        Build/rebuild the graph from mainTable.
        Returns (ok: bool, message: str).
        """
        if not _ensureMatplotlib():
            return False, (
                "matplotlib is not installed.\n\n"
                "Install it with:\n  pip install matplotlib\n"
                "Then restart Data Doctor."
            )

        timestamps, series, warnings = extractSeries(table, columns)
        if not series:
            msg = warnings[0] if warnings else "Nothing to graph."
            return False, msg

        # Tear down previous figure
        self.clearPlot()
        if self._placeholder is not None:
            self._placeholder.hide()

        retro = bool(Config.retroMode)
        fig = Figure(figsize=(8, 5), tight_layout=True)
        if retro:
            fig.patch.set_facecolor('#1a1a1a')
        self.figure = fig
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setObjectName('graphToolbar')

        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.canvas, stretch=1)

        ax = fig.add_subplot(111)
        self._ax = ax
        self._ax2 = None

        if retro:
            ax.set_facecolor('#101010')
            ax.tick_params(colors='#00FF00')
            ax.xaxis.label.set_color('#00FF00')
            ax.yaxis.label.set_color('#00FF00')
            for spine in ax.spines.values():
                spine.set_color('#00FF00')
            ax.title.set_color('#00FF00')

        n = len(series[0][1])
        useDatetime = (
            timestamps
            and sum(1 for t in timestamps if t is not None) >= max(2, int(n * 0.5))
        )
        if useDatetime:
            x = mdates.date2num([
                t if t is not None else np.nan for t in timestamps
            ])
        else:
            x = np.arange(n, dtype=float)

        leftSeries, rightSeries = assignAxes(series)
        colorCycle = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        ]
        if retro:
            colorCycle = [
                '#00FF00', '#00FFFF', '#FF00FF', '#FFFF00', '#FF8800',
                '#88FF00', '#00FF88', '#FF0088', '#8888FF', '#FFFFFF',
            ]

        lines = []
        colorIdx = 0

        def plotGroup(axTarget, group, isRight=False):
            nonlocal colorIdx
            for label, vals in group:
                color = colorCycle[colorIdx % len(colorCycle)]
                colorIdx += 1
                # Mask NaNs so lines break on gaps
                y = np.array(vals, dtype=float)
                mask = np.isfinite(x) & np.isfinite(y)
                if not np.any(mask):
                    continue
                (line,) = axTarget.plot(
                    x[mask], y[mask],
                    label=label,
                    color=color,
                    linewidth=1.4,
                    marker='o' if mask.sum() <= 80 else None,
                    markersize=3,
                )
                lines.append(line)
            axTarget.set_ylabel(
                'Value' + (' (right)' if isRight else ''),
                color=colorCycle[0] if not isRight else colorCycle[1 % len(colorCycle)],
            )
            if isRight and retro:
                axTarget.tick_params(colors='#00FFFF')
                axTarget.yaxis.label.set_color('#00FFFF')

        plotGroup(ax, leftSeries, isRight=False)

        if rightSeries:
            ax2 = ax.twinx()
            self._ax2 = ax2
            if retro:
                ax2.set_facecolor('#101010')
                for spine in ax2.spines.values():
                    spine.set_color('#00FFFF')
            plotGroup(ax2, rightSeries, isRight=True)

        if useDatetime:
            ax.xaxis_date()
            fig.autofmt_xdate()
            ax.set_xlabel('Timestamp')
        else:
            ax.set_xlabel('Row')

        titleBits = []
        if len(series) == 1:
            titleBits.append(series[0][0])
        else:
            titleBits.append(f"{len(series)} series")
        if rightSeries:
            titleBits.append("dual axis")
        ax.set_title(" · ".join(titleBits))

        # Combined legend
        labels = [ln.get_label() for ln in lines]
        if lines:
            ax.legend(lines, labels, loc='best', fontsize=8)

        ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()

        note = ''
        if warnings:
            note = ' '.join(warnings)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"GraphPanel.plotFromTable: {len(leftSeries)} left, "
                f"{len(rightSeries)} right, rows={n}, datetime={useDatetime}",
            )
        return True, note
