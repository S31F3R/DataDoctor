# uiRegression.py
# Right-click Regression: one lagged fit, two views (Relationship / Aligned).
# Does not write the query table. The user copies the equation into Formulas.

from __future__ import annotations

import json
import os

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import Config, Logic, QueryUtils, Utils
from core.Formula import colToLetters
from core.plotLag import viewPairScores
from core.regression.equation import formatClock, formatNumber, formatSteps
from core.regression.fitRegression import SeriesColumn, fitColumns
from ui.uiGraph import (
    _LEGEND_OFF,
    _LEGEND_ON,
    detectTimestampDisplayFormat,
    headerLabel,
    isSystemDarkMode,
    parseNumeric,
    parseTimestamp,
    selectedDataColumns,
    selectedDataRows,
)

_mplReady = False
Figure = None
FigureCanvasQTAgg = None
NavigationToolbar2QT = None
mdates = None
Line2D = None


def _ensureMatplotlib():
    global _mplReady, Figure, FigureCanvasQTAgg, NavigationToolbar2QT, mdates, Line2D
    if _mplReady:
        return True
    try:
        from matplotlib.figure import Figure as _Figure
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg as _Canvas,
            NavigationToolbar2QT as _Toolbar,
        )
        from matplotlib.lines import Line2D as _Line2D
        import matplotlib.dates as _mdates

        Figure = _Figure
        FigureCanvasQTAgg = _Canvas
        NavigationToolbar2QT = _Toolbar
        mdates = _mdates
        Line2D = _Line2D
        _mplReady = True
        return True
    except Exception as e:
        Logic.logException("uiRegression: matplotlib import failed", e)
        return False


def noteStatus(window, text):
    """Non-modal status line. Hides again once the message expires."""
    if window is None or not text:
        return
    try:
        bar = window.statusBar()
        bar.show()
        bar.showMessage(text, 10000)

        def _hide():
            try:
                if not bar.currentMessage():
                    bar.hide()
            except Exception:
                pass

        QTimer.singleShot(10500, _hide)
    except Exception:
        pass
    try:
        Logic.logMessage("INFO", text)
    except Exception:
        pass


def _columnType(columnMetadata, col):
    if not columnMetadata or col < 0 or col >= len(columnMetadata):
        return ""
    meta = columnMetadata[col]
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("type") or "")


def _cellRaw(item):
    """Displayed primary for an overlay cell; otherwise the raw cell value."""
    if item is None:
        return ""
    role = item.data(Qt.ItemDataRole.UserRole)
    if isinstance(role, dict) and role.get("overlay"):
        raw = role.get("primaryNative")
        if raw in (None, ""):
            raw = role.get("primaryVal")
        if raw not in (None, ""):
            return str(raw).strip()
    return QueryUtils.itemNativeText(item)


def gatherColumns(table, columns=None, rows=None, columnMetadata=None):
    """
    Numeric columns for a regression snapshot.

    Delta columns are skipped (derived). Overlay columns contribute the
    displayed primary, not the secondary series.
    """
    if table is None:
        return [], []
    if columns is None:
        columns = selectedDataColumns(table)
    if rows is None:
        rows = selectedDataRows(table)
    tsTexts = []
    for r in rows or []:
        vh = table.verticalHeaderItem(r)
        tsTexts.append(vh.text() if vh is not None else "")

    kept = []
    for c in columns or []:
        if _columnType(columnMetadata, c) == "delta":
            continue
        times = []
        values = []
        for r in rows or []:
            vh = table.verticalHeaderItem(r)
            tsText = vh.text() if vh is not None else ""
            dt, _fmt = parseTimestamp(tsText)
            item = table.item(r, c)
            val = parseNumeric(_cellRaw(item))
            if dt is None or not np.isfinite(val):
                continue
            times.append(dt)
            values.append(val)
        if len(values) < 2:
            continue
        kept.append(SeriesColumn(
            colToLetters(c),
            headerLabel(table, c),
            c,
            times,
            values,
        ))
    return kept, tsTexts


def askTarget(parent, columns):
    """Small modal: which series to predict. Returns an index, or None."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Regression")
    layout = QVBoxLayout(dlg)
    label = QLabel("Which series to predict?")
    layout.addWidget(label)
    combo = QComboBox()
    for i, col in enumerate(columns):
        combo.addItem(f"{col.key}  {col.label}", i)
    layout.addWidget(combo)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    Utils.applyRetroFont(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return combo.currentData()


def runRegression(window, columns=None, rows=None):
    """Right-click entry. Refuses in a dialog and does not open a tab."""
    table = getattr(window, "mainTable", None)
    if table is None or table.rowCount() <= 0 or table.columnCount() <= 0:
        QMessageBox.information(window, "Regression", "No data to regress. Run a Data Query first.")
        return
    if not _ensureMatplotlib():
        QMessageBox.warning(
            window,
            "Regression",
            "matplotlib is not installed.\n\nInstall it with:\n  pip install matplotlib\n"
            "Then restart Data Doctor.",
        )
        return

    meta = getattr(window, "columnMetadata", None)
    cols, tsTexts = gatherColumns(table, columns=columns, rows=rows, columnMetadata=meta)
    if len(cols) < 2:
        QMessageBox.information(
            window, "Regression", "Regression needs at least two numeric columns.",
        )
        return
    targetIndex = askTarget(window, cols)
    if targetIndex is None:
        return
    result, err = fitColumns(cols, int(targetIndex))
    if err or result is None:
        QMessageBox.warning(window, "Regression", err or "Regression did not fit.")
        return

    panel = window.ensureRegressionPanel()
    fmt = detectTimestampDisplayFormat(tsTexts) or "%m/%d/%y %H:%M"
    panel.showFit(result, fmt)
    window.showRegressionInMainTabs(select=True)


class EquationLabel(QLabel):
    """Copy target. Double-click copies the formula line, not the commentary."""

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setToolTip("Double-click to copy the equation.")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def mouseDoubleClickEvent(self, event):
        self._panel.copyEquation()
        event.accept()

    def _menu(self, pos):
        menu = QMenu(self)
        act = menu.addAction("Copy")
        if menu.exec(self.mapToGlobal(pos)) == act:
            self._panel.copyEquation()


_ToolbarCls = None


def _makeToolbarClass():
    global _ToolbarCls
    if _ToolbarCls is not None:
        return _ToolbarCls
    if not _ensureMatplotlib():
        return None

    class RegressionToolbar(NavigationToolbar2QT):
        """Zoom-default toolbar. Saves remember lastRegressionSavePath."""

        def __init__(self, canvas, parent=None):
            super().__init__(canvas, parent)
            try:
                mode = str(getattr(self, "mode", "") or "").lower()
                if "zoom" not in mode:
                    self.zoom()
            except Exception:
                pass

        def save_figure(self, *args):
            try:
                filetypes = self.canvas.get_supported_filetypes_grouped()
                sortedTypes = sorted(filetypes.items())
                defaultType = self.canvas.get_default_filetype()
                config = Utils.loadConfig()
                startpath = (config.get("lastRegressionSavePath") or "").strip()
                if not startpath or not os.path.isdir(startpath):
                    startpath = (config.get("lastGraphSavePath") or "").strip()
                if not startpath or not os.path.isdir(startpath):
                    startpath = (config.get("lastExportPath") or "").strip()
                if not startpath or not os.path.isdir(startpath):
                    startpath = os.path.expanduser("~/Documents")
                startpath = os.path.normpath(os.path.abspath(startpath))
                start = os.path.join(startpath, self.canvas.get_default_filename())
                filters = []
                selected = None
                for name, exts in sortedTypes:
                    extsList = " ".join(f"*.{ext}" for ext in exts)
                    filt = f"{name} ({extsList})"
                    if defaultType in exts:
                        selected = filt
                    filters.append(filt)
                fname, _filt = QFileDialog.getSaveFileName(
                    self.canvas.parent() or self,
                    "Save regression",
                    start,
                    ";;".join(filters),
                    selected,
                )
                if not fname:
                    return fname
                fig = self.canvas.figure
                panel = self.parent()
                result = getattr(panel, "_result", None) if panel is not None else None
                if panel is not None and hasattr(panel, "currentLabelText"):
                    label = panel.currentLabelText() or ""
                else:
                    label = (result.labelText if result is not None else "") or ""
                footerAx = None
                oldBottom = fig.subplotpars.bottom
                if label:
                    # Own axes under the plot so the equation is not drawn on the points.
                    lines = label.count("\n") + 1
                    footerH = min(0.46, 0.032 * lines + 0.04)
                    fig.subplots_adjust(bottom=footerH + 0.08)
                    color = "#222222"
                    try:
                        from ui.uiGraph import isSystemDarkMode
                        if Config.retroMode and isSystemDarkMode():
                            color = "#00FF00"
                        elif isSystemDarkMode():
                            color = "#e0e0e0"
                    except Exception:
                        pass
                    footerAx = fig.add_axes([0.02, 0.006, 0.96, footerH])
                    footerAx.set_axis_off()
                    footerAx.text(
                        0.0, 0.0, label,
                        va="bottom", ha="left", fontsize=8, color=color,
                        transform=footerAx.transAxes, clip_on=False,
                    )
                try:
                    fig.set_tight_layout(False)
                    fig.savefig(fname)
                finally:
                    if footerAx is not None:
                        fig.delaxes(footerAx)
                    fig.subplots_adjust(bottom=oldBottom)
                    self.canvas.draw_idle()
                saveDir = os.path.dirname(os.path.abspath(fname))
                config = Utils.loadConfig()
                config["lastRegressionSavePath"] = saveDir
                with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                return fname
            except Exception as e:
                Logic.logException("RegressionToolbar.save_figure failed", e)
                return None

    _ToolbarCls = RegressionToolbar
    return _ToolbarCls


class RegressionPanel(QWidget):
    """
    Relationship scatter or lag-shifted time plot. Legend is a radio for the
    view, then per-series show/hide on the aligned plot.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tabRegression")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._placeholder = QLabel("Right-click columns and choose Regression.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder, stretch=1)

        self._equation = EquationLabel(self)
        self._equation.hide()
        self._layout.addWidget(self._equation)

        self.figure = None
        self.canvas = None
        self.toolbar = None
        self._ax = None
        self._legend = None
        self._pressCid = None
        self._hoverCid = None
        self._result = None
        self._tsFormat = "%m/%d/%y %H:%M"
        self._view = "relationship"
        self._visible = []
        self._lineData = []
        self._theme = "light"
        self._axBg = "#ffffff"
        self._toolbarOrigIcons = None
        self._lastTipKey = None

    def showFit(self, result, tsFormat):
        """Draw a finished fit. View starts on Relationship."""
        if not _ensureMatplotlib():
            return
        self._result = result
        self._tsFormat = tsFormat or self._tsFormat
        self._view = "relationship"
        self._visible = [True] * len(result.aligned or [])
        self._buildCanvas()
        self._drawCurrent()

    def copyEquation(self):
        result = self._result
        text = (result.copyText if result is not None else "") or ""
        if not text:
            return
        QApplication.clipboard().setText(text)
        host = self.window()
        main = getattr(host, "mainWindow", None) or host
        noteStatus(main, "Copied regression equation.")

    def reapplyTheme(self):
        """Restyle after light/dark/retro change. Same fit, same view."""
        self._styleEquation()
        self._applyToolbarTheme()
        if self._result is None or self.figure is None:
            return
        self._drawCurrent()

    def _buildCanvas(self):
        if self.figure is not None:
            return
        if self._placeholder is not None:
            self._placeholder.hide()
        fig = Figure(figsize=(8, 5), tight_layout=False)
        fig.subplots_adjust(left=0.08, right=0.97, top=0.96, bottom=0.16)
        self.figure = fig
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        ToolbarCls = _makeToolbarClass() or NavigationToolbar2QT
        self.toolbar = ToolbarCls(self.canvas, self)
        self.toolbar.setObjectName("regressionToolbar")
        self._toolbarOrigIcons = None
        self._applyToolbarTheme()
        # Equation label stays last (under the plot).
        self._layout.insertWidget(0, self.toolbar)
        self._layout.insertWidget(1, self.canvas, stretch=1)
        self._ax = fig.add_subplot(111)
        self._pressCid = self.canvas.mpl_connect("button_press_event", self._onPress)
        self._hoverCid = self.canvas.mpl_connect("motion_notify_event", self._onHover)

    def _drawCurrent(self):
        result = self._result
        if result is None or self._ax is None:
            return
        ax = self._ax
        ax.clear()
        self._legend = None
        self._lineData = []
        theme = self._applyTheme(self.figure, ax)
        self._theme = theme
        colors = self._colorCycle(theme)
        if self._view == "aligned":
            self._drawAligned(ax, colors, theme)
        else:
            self._drawRelationship(ax, colors, theme)
        self._annotate(ax, theme)
        self._buildLegend(theme)
        self._styleEquation()
        self._equation.setText(self.currentLabelText())
        self._equation.show()
        try:
            ax.ticklabel_format(axis="y", useOffset=False)
        except Exception:
            pass
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _drawRelationship(self, ax, colors, theme):
        result = self._result
        pointColor = colors[0]
        lineColor = "#00FF00" if theme == "retro" else ("#e0e0e0" if theme == "dark" else "#222222")
        xs = np.asarray(result.scatterX, dtype=float)
        ys = np.asarray(result.scatterY, dtype=float)
        ax.plot(xs, ys, linestyle="none", marker="o", color=pointColor, markersize=3.5)
        ax.plot(result.lineX, result.lineY, color=lineColor, linewidth=1.4)
        ax.set_xlabel(result.xLabel or "")
        ax.set_ylabel(result.yLabel or "")
        self._applyChartFonts(ax)
        self._lineData.append({
            "xs": xs,
            "ys": ys,
            "times": None,
            "label": result.yLabel or result.targetLabel or "Observed",
            "xLabel": result.xLabel or "",
            "mode": result.scatterMode,
            "line": None,
        })
        self._grid(ax, theme)

    def _drawAligned(self, ax, colors, theme):
        result = self._result
        for i, series in enumerate(result.aligned or []):
            color = colors[i % len(colors)]
            times = list(series.times or [])
            values = np.asarray(series.values, dtype=float)
            if times and mdates is not None:
                x = mdates.date2num(times)
            else:
                x = np.arange(values.size, dtype=float)
            nFinite = int(np.count_nonzero(np.isfinite(values)))
            markEvery = 1 if nFinite <= 5000 else max(1, nFinite // 4000)
            (line,) = ax.plot(
                x,
                values,
                color=color,
                linewidth=1.4,
                marker="o",
                markersize=2.8 if nFinite <= 5000 else 2.0,
                markevery=markEvery,
            )
            visible = True if i >= len(self._visible) else bool(self._visible[i])
            line.set_visible(visible)
            self._lineData.append({
                "xs": np.asarray(x, dtype=float),
                "ys": values,
                "times": times,
                "label": series.legend or series.label or series.key,
                "xLabel": "",
                "mode": "aligned",
                "line": line,
                "seriesIndex": i,
            })
        if mdates is not None:
            try:
                ax.xaxis_date()
                ax.xaxis.set_major_formatter(mdates.DateFormatter(self._tsFormat))
                for tick in ax.get_xticklabels():
                    tick.set_rotation(30)
                    tick.set_horizontalalignment("right")
            except Exception:
                pass
        ax.set_xlabel("")
        ax.set_ylabel("")
        self._applyChartFonts(ax)
        self._grid(ax, theme)

    def _grid(self, ax, theme):
        if theme in ("dark", "retro"):
            ax.grid(True, alpha=0.3, color="#666666")
        else:
            ax.grid(True, alpha=0.3)

    def currentLabelText(self):
        """Relationship keeps the fit. Aligned scores the shifted hydrographs, including NSE."""
        result = self._result
        if result is None:
            return ""
        if self._view != "aligned":
            return result.labelText or ""
        lines = []
        if result.equationText:
            lines.append(result.equationText)
        bits = []
        for pred in result.predictors or []:
            clock = formatClock(float(pred.lagSteps) * float(result.stepSeconds or 0))
            bits.append(f"lag {pred.key} = {formatSteps(pred.lagSteps)} ({clock})")
        if bits:
            lines.append("   ".join(bits))
        lines.extend(self._alignedScoreLines())
        if result.stepLabel:
            lines.append(f"dt = {result.stepLabel}")
        for warning in result.warnings or []:
            text = str(warning).strip()
            if text:
                lines.append(f"Warning: {text}")
        return "\n".join(lines)

    def _alignedScoreLines(self):
        result = self._result
        series = list(result.aligned or []) if result is not None else []
        if len(series) < 2:
            return ["Not enough overlap"]
        target = np.asarray(series[0].values, dtype=float)
        x = np.arange(target.size, dtype=float)
        lines = []
        for i, pred in enumerate(series[1:], start=1):
            if i < len(self._visible) and not self._visible[i]:
                continue
            scores = viewPairScores(
                x, target, np.asarray(pred.values, dtype=float), -1.0, float(target.size) + 1.0,
            )
            name = pred.key or pred.label or "Series"
            lines.append(self._alignedStatLine(name, scores))
        if not lines:
            return ["No shifted series is shown"]
        return lines

    def _alignedStatLine(self, name, scores):
        count = int((scores or {}).get("n") or 0)
        if count < 3:
            return f"{name}: not enough overlap"
        def piece(label, key):
            value = scores.get(key)
            shown = "—" if value is None else formatNumber(value)
            return f"{label} = {shown}"
        return (
            f"{name}: {piece('r²', 'r2')}   {piece('NSE', 'nse')}   "
            f"{piece('ME', 'me')}   {piece('RMSE', 'rmse')}   N = {count}"
        )

    def _annotate(self, ax, theme):
        if self._view == "aligned":
            text = "\n".join(self._alignedScoreLines())
        else:
            text = (self._result.figureText if self._result is not None else "") or ""
        if not text:
            return
        if theme == "retro":
            color = "#00FF00"
        elif theme == "dark":
            color = "#e0e0e0"
        else:
            color = "#222222"
        prop = self._chartFont(8)
        kwargs = dict(
            transform=ax.transAxes,
            va="top",
            ha="left",
            color=color,
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=self._axBg, edgecolor="none", alpha=0.8),
        )
        if prop is not None:
            kwargs["fontproperties"] = prop
        try:
            ax.text(0.02, 0.98, text, **kwargs)
        except Exception:
            pass

    def _legendBases(self):
        bases = ["Relationship", "Aligned"]
        for series in (self._result.aligned if self._result is not None else []) or []:
            bases.append(series.legend or series.label or series.key)
        return bases

    def _mark(self, index, base):
        if index == 0:
            on = self._view == "relationship"
        elif index == 1:
            on = self._view == "aligned"
        else:
            seriesIdx = index - 2
            on = True if seriesIdx >= len(self._visible) else bool(self._visible[seriesIdx])
        mark = _LEGEND_ON if on else _LEGEND_OFF
        return f"{mark} {base}"

    def _buildLegend(self, theme):
        if self._ax is None or Line2D is None:
            self._legend = None
            return
        bases = self._legendBases()
        colors = self._colorCycle(theme)
        handles = []
        labels = []
        for i, base in enumerate(bases):
            if i < 2:
                handle = Line2D([], [], linestyle="none", marker="None")
            else:
                color = colors[(i - 2) % len(colors)]
                handle = Line2D([], [], color=color, linewidth=2, marker="o", markersize=4)
            handles.append(handle)
            labels.append(self._mark(i, base))
        prop = self._chartFont(9)
        if prop is not None:
            legend = self._ax.legend(handles, labels, loc="best", prop=prop)
        else:
            legend = self._ax.legend(handles, labels, loc="best", fontsize=9)
        if theme == "dark":
            legend.get_frame().set_facecolor("#2b2b2b")
            legend.get_frame().set_edgecolor("#888888")
            for text in legend.get_texts():
                text.set_color("#e0e0e0")
        elif theme == "retro":
            legend.get_frame().set_facecolor("#1a1a1a")
            legend.get_frame().set_edgecolor("#00FF00")
            for text in legend.get_texts():
                text.set_color("#00FF00")
        self._legend = legend

    def _onPress(self, event):
        if event is None or event.button != 1:
            return
        idx = self._legendHitIndex(event)
        if idx is None:
            if self._isOverLegend(event):
                self._cancelToolbarInteraction()
            return
        self._cancelToolbarInteraction()
        if idx == 0:
            if self._view != "relationship":
                self._view = "relationship"
                self._drawCurrent()
            return
        if idx == 1:
            if self._view != "aligned":
                self._view = "aligned"
                self._drawCurrent()
            return
        seriesIdx = idx - 2
        if seriesIdx < 0 or seriesIdx >= len(self._visible):
            return
        self._visible[seriesIdx] = not self._visible[seriesIdx]
        if self._view == "aligned":
            self._drawCurrent()
        else:
            self._buildLegend(self._theme)
            if self.canvas is not None:
                self.canvas.draw_idle()

    def _hideTip(self):
        if self._lastTipKey is None:
            return
        self._lastTipKey = None
        try:
            from PyQt6.QtWidgets import QToolTip
            QToolTip.hideText()
        except Exception:
            pass

    def _onHover(self, event):
        if self.canvas is None or not self._lineData:
            return
        if event.inaxes is None or event.x is None or event.y is None:
            self._hideTip()
            return
        best = None
        for entry in self._lineData:
            line = entry.get("line")
            if line is not None and not line.get_visible():
                continue
            xs = entry.get("xs")
            ys = entry.get("ys")
            if xs is None or ys is None or len(xs) == 0:
                continue
            try:
                pts = self._ax.transData.transform(np.column_stack([xs, ys]))
                mouse = np.array([event.x, event.y], dtype=float)
                d2 = (pts[:, 0] - mouse[0]) ** 2 + (pts[:, 1] - mouse[1]) ** 2
                # Ignore NaN distances from gapped points.
                if not np.any(np.isfinite(d2)):
                    continue
                i = int(np.nanargmin(d2))
                dist2 = float(d2[i])
                if dist2 < 196 and (best is None or dist2 < best[0]):
                    best = (dist2, i, entry)
            except Exception:
                continue
        if best is None:
            self._hideTip()
            return
        _dist, i, entry = best
        tip = self._hoverText(entry, i)
        if not tip:
            return
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QToolTip
        if tip != self._lastTipKey:
            self._lastTipKey = tip
            QToolTip.showText(QCursor.pos(), tip, self.canvas)

    def _hoverText(self, entry, index):
        ys = entry.get("ys")
        xs = entry.get("xs")
        try:
            y = float(ys[index])
        except Exception:
            return ""
        if not np.isfinite(y):
            return ""
        try:
            val = Logic.valuePrecision(y)
        except Exception:
            val = str(y)
        mode = entry.get("mode")
        if mode == "aligned":
            times = entry.get("times") or []
            when = ""
            if 0 <= index < len(times) and times[index] is not None:
                try:
                    when = times[index].strftime(self._tsFormat)
                except Exception:
                    when = str(times[index])
            label = entry.get("label") or ""
            return f"{label}\n{when}\n{val}".strip()
        try:
            x = float(xs[index])
            xVal = Logic.valuePrecision(x)
        except Exception:
            xVal = ""
        if mode == "fitted":
            return f"Observed {val}\nFitted {xVal}"
        return f"{entry.get('label') or 'Observed'} {val}\n{entry.get('xLabel') or 'Lagged'} {xVal}"

    def _legendRenderer(self):
        if self.canvas is None:
            return None
        try:
            return self.canvas.get_renderer()
        except Exception:
            return None

    def _isOverLegend(self, event):
        if self._legend is None or event is None or event.x is None or event.y is None:
            return False
        try:
            bbox = self._legend.get_window_extent(self._legendRenderer())
            pad = 3.0
            return bool(
                bbox.x0 - pad <= event.x <= bbox.x1 + pad
                and bbox.y0 - pad <= event.y <= bbox.y1 + pad
            )
        except Exception:
            return False

    def _legendHitIndex(self, event):
        if not self._isOverLegend(event):
            return None
        renderer = self._legendRenderer()
        try:
            for i, text in enumerate(self._legend.get_texts()):
                tb = text.get_window_extent(renderer)
                if tb.x0 - 8 <= event.x <= tb.x1 + 6 and tb.y0 - 3 <= event.y <= tb.y1 + 3:
                    return i
        except Exception:
            return None
        return None

    def _cancelToolbarInteraction(self):
        tb = self.toolbar
        if tb is None or self.canvas is None:
            return
        try:
            zinfo = getattr(tb, "_zoom_info", None)
            if zinfo is not None:
                cid = getattr(zinfo, "cid", None)
                if cid is not None:
                    self.canvas.mpl_disconnect(cid)
                try:
                    tb.remove_rubberband()
                except Exception:
                    pass
                tb._zoom_info = None
        except Exception:
            pass

    def _colorCycle(self, theme):
        if theme == "retro":
            return ["#00FF00", "#00FFFF", "#FF00FF", "#FFFF00", "#FF8800", "#FFFFFF"]
        if theme == "dark":
            return ["#4ea1ff", "#ff9f43", "#2ed573", "#ff6b6b", "#c56cf0", "#feca57"]
        return ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    def _applyTheme(self, fig, ax):
        retro = bool(Config.retroMode)
        dark = isSystemDarkMode()
        if retro and dark:
            fig.patch.set_facecolor("#1a1a1a")
            ax.set_facecolor("#101010")
            self._axBg = "#101010"
            ax.tick_params(colors="#00FF00")
            ax.xaxis.label.set_color("#00FF00")
            ax.yaxis.label.set_color("#00FF00")
            for spine in ax.spines.values():
                spine.set_color("#00FF00")
            ax.title.set_color("#00FF00")
            return "retro"
        if dark:
            fig.patch.set_facecolor("#2b2b2b")
            ax.set_facecolor("#1e1e1e")
            self._axBg = "#1e1e1e"
            ax.tick_params(colors="#e0e0e0")
            ax.xaxis.label.set_color("#e0e0e0")
            ax.yaxis.label.set_color("#e0e0e0")
            for spine in ax.spines.values():
                spine.set_color("#888888")
            ax.title.set_color("#e0e0e0")
            return "dark"
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")
        self._axBg = "#ffffff"
        ax.tick_params(colors="#222222")
        ax.xaxis.label.set_color("#222222")
        ax.yaxis.label.set_color("#222222")
        for spine in ax.spines.values():
            spine.set_color("#888888")
        ax.title.set_color("#222222")
        return "light"

    def _chartFont(self, size=9):
        try:
            from matplotlib import font_manager
            if Config.retroMode:
                path = Logic.resourcePath("ui/fonts/Silkscreen-Regular.ttf")
            else:
                path = Logic.resourcePath("ui/fonts/NotoSans-Regular.ttf")
            if not os.path.isfile(path):
                return font_manager.FontProperties(family="sans-serif", size=size)
            font_manager.fontManager.addfont(path)
            return font_manager.FontProperties(fname=path, size=size)
        except Exception:
            return None

    def _applyChartFonts(self, ax):
        tick = self._chartFont(9)
        axis = self._chartFont(10)
        if ax is None or tick is None:
            return
        try:
            ax.xaxis.label.set_fontproperties(axis or tick)
            ax.yaxis.label.set_fontproperties(axis or tick)
            for lab in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
                lab.set_fontproperties(tick)
        except Exception:
            pass

    def _styleEquation(self):
        theme = self._theme
        if Config.retroMode and isSystemDarkMode():
            theme = "retro"
        elif isSystemDarkMode():
            theme = "dark"
        else:
            theme = "light"
        if theme == "retro":
            self._equation.setStyleSheet(
                "color: #00FF00; background: #1a1a1a; padding: 6px;"
            )
        elif theme == "dark":
            self._equation.setStyleSheet(
                "color: #e0e0e0; background: #2b2b2b; padding: 6px;"
            )
        else:
            self._equation.setStyleSheet(
                "color: #222222; background: #f7f7f7; padding: 6px;"
            )
        try:
            Utils.applyRetroFont(self._equation)
        except Exception:
            pass

    def _tintIcon(self, icon, color, px):
        if icon is None or icon.isNull():
            return icon
        pix = icon.pixmap(px, px)
        if pix.isNull():
            return icon
        tinted = QPixmap(pix.size())
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, pix)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), color)
        painter.end()
        return QIcon(tinted)

    def _applyToolbarTheme(self):
        if self.toolbar is None:
            return
        buttons = self.toolbar.findChildren(QToolButton)
        orig = self._toolbarOrigIcons
        if orig is None:
            orig = {}
            for btn in buttons:
                orig[btn] = btn.icon()
            self._toolbarOrigIcons = orig
        if Config.retroMode and isSystemDarkMode():
            self.toolbar.setStyleSheet("QToolBar { background: #1a1a1a; border: none; }")
            green = QColor("#00FF00")
            for btn in buttons:
                src = orig.get(btn)
                if src is None or src.isNull():
                    continue
                sz = btn.iconSize()
                px = sz.width() if sz.width() > 0 else 24
                btn.setIcon(self._tintIcon(src, green, px))
        else:
            self.toolbar.setStyleSheet("")
            for btn in buttons:
                src = orig.get(btn)
                if src is not None:
                    btn.setIcon(src)
