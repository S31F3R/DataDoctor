# uiGraph.py
# Graph tab: plot mainTable series with zoom toolbar and dual Y-axis when scales differ.
# Supports dark/light system palette, hover tooltips, table timestamp formats, overlay pairs.

from __future__ import annotations
import os
import re
from datetime import datetime
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QCursor
from PyQt6.QtWidgets import (
    QApplication, QVBoxLayout, QWidget, QSizePolicy, QLabel, QToolTip,
    QFileDialog, QMessageBox,
)
from core import Config, Logic, Utils

# Lazy matplotlib imports so startup still works if the package is missing
_mplReady = False
Figure = None
FigureCanvasQTAgg = None
NavigationToolbar2QT = None
mdates = None
_mplModule = None


def _ensureMatplotlib():
    global _mplReady, Figure, FigureCanvasQTAgg, NavigationToolbar2QT, mdates, _mplModule
    if _mplReady:
        return True
    try:
        from matplotlib.figure import Figure as _Figure
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg as _Canvas,
            NavigationToolbar2QT as _Toolbar,
        )
        import matplotlib as _mpl
        import matplotlib.dates as _mdates

        Figure = _Figure
        FigureCanvasQTAgg = _Canvas
        NavigationToolbar2QT = _Toolbar
        mdates = _mdates
        _mplModule = _mpl
        _mplReady = True
        return True
    except Exception as e:
        Logic.logException("uiGraph: matplotlib import failed", e)
        return False


_GraphToolbarCls = None


def _makeGraphToolbarClass():
    """Subclass NavigationToolbar2QT once matplotlib is available."""
    global _GraphToolbarCls
    if _GraphToolbarCls is not None:
        return _GraphToolbarCls
    if not _ensureMatplotlib():
        return None

    class GraphToolbar(NavigationToolbar2QT):
        """Zoom-default toolbar; graph saves remember last folder like CSV export."""

        def __init__(self, canvas, parent=None):
            super().__init__(canvas, parent)
            self._activateDefaultZoom()

        def _activateDefaultZoom(self):
            """Enter zoom-to-rect mode so the user can drag-zoom immediately."""
            try:
                # zoom() toggles — only enter if not already zoom
                mode = getattr(self, 'mode', None)
                modeName = str(mode).lower() if mode is not None else ''
                if 'zoom' not in modeName:
                    self.zoom()
            except Exception as e:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"GraphToolbar default zoom: {e}")

        def save_figure(self, *args):
            """Save figure; start in last graph-save folder (persisted in user.config)."""
            try:
                import json
                filetypes = self.canvas.get_supported_filetypes_grouped()
                sorted_filetypes = sorted(filetypes.items())
                default_filetype = self.canvas.get_default_filetype()

                config = Utils.loadConfig()
                startpath = (config.get('lastGraphSavePath') or '').strip()
                if not startpath or not os.path.isdir(startpath):
                    # Fall back to last CSV export folder, then Documents
                    startpath = (config.get('lastExportPath') or '').strip()
                if not startpath or not os.path.isdir(startpath):
                    startpath = os.path.expanduser("~/Documents")
                startpath = os.path.normpath(os.path.abspath(startpath))

                start = os.path.join(startpath, self.canvas.get_default_filename())
                filters = []
                selectedFilter = None
                for name, exts in sorted_filetypes:
                    exts_list = " ".join(f'*.{ext}' for ext in exts)
                    filt = f'{name} ({exts_list})'
                    if default_filetype in exts:
                        selectedFilter = filt
                    filters.append(filt)
                filters = ';;'.join(filters)

                fname, _filt = QFileDialog.getSaveFileName(
                    self.canvas.parent() or self,
                    "Save graph",
                    start,
                    filters,
                    selectedFilter,
                )
                if not fname:
                    return fname
                try:
                    self.canvas.figure.savefig(fname)
                except Exception as e:
                    QMessageBox.critical(
                        self, "Error saving file", str(e),
                        QMessageBox.StandardButton.Ok,
                    )
                    return fname

                # Remember folder for next graph save
                saveDir = os.path.dirname(os.path.abspath(fname))
                try:
                    config = Utils.loadConfig()
                    config['lastGraphSavePath'] = saveDir
                    with open(Utils.getConfigPath(), 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2)
                except Exception as e:
                    Logic.logException("GraphToolbar: failed to save lastGraphSavePath", e)
                # Keep matplotlib's own memory in sync for this session
                try:
                    if _mplModule is not None:
                        _mplModule.rcParams['savefig.directory'] = saveDir
                except Exception:
                    pass
                return fname
            except Exception as e:
                Logic.logException("GraphToolbar.save_figure failed", e)
                # Fall back to stock behavior if something unexpected breaks
                try:
                    return super().save_figure(*args)
                except Exception:
                    return None

    _GraphToolbarCls = GraphToolbar
    return _GraphToolbarCls


# Timestamp formats used by Data Query vertical headers (most specific first)
_TS_FORMATS = (
    '%m/%d/%y %H:%M:00',
    '%m/%d/%y %H:%M:%S',
    '%m/%d/%y %H:%M',
    '%m/%d/%y',
    '%m/%y',
    '%Y',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
    '%m/%d/%Y %H:%M:%S',
    '%m/%d/%Y %H:%M',
    '%m/%d/%Y',
)


def parseTimestamp(text):
    """Parse a table timestamp string to datetime, or None. Returns (dt, fmt) if possible."""
    if not text:
        return None, None
    s = str(text).strip()
    if not s:
        return None, None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt), fmt
        except ValueError:
            continue
    # Last resort: dateutil-free ISO-ish cleanup
    try:
        cleaned = s.replace('T', ' ').split('.')[0]
        return datetime.fromisoformat(cleaned), None
    except Exception:
        return None, None


def detectTimestampDisplayFormat(tsTexts):
    """
    Pick the strftime pattern that matches the majority of table timestamp strings.
    Used so graph X labels match the Data Query vertical header exactly.
    """
    samples = [str(t).strip() for t in tsTexts if t and str(t).strip()]
    if not samples:
        return '%m/%d/%y %H:%M:00'
    bestFmt = None
    bestCount = 0
    for fmt in _TS_FORMATS:
        count = 0
        for s in samples[:min(40, len(samples))]:
            try:
                datetime.strptime(s, fmt)
                count += 1
            except ValueError:
                continue
        if count > bestCount:
            bestCount = count
            bestFmt = fmt
    return bestFmt or '%m/%d/%y %H:%M:00'


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


def headerFirstLine(table, col):
    """
    First non-empty line of the table header only (ignore dataID / interval
    lines below the first \\n). Used for graph legends.
    """
    item = table.horizontalHeaderItem(col) if table is not None else None
    if item is None:
        return f"Col {col + 1}"
    text = item.text() or ''
    for line in text.split('\n'):
        line = line.strip()
        if line:
            return line
    return f"Col {col + 1}"


def headerLabel(table, col):
    """Single-line legend label from multi-line table header (first line only)."""
    # Prefer first header line so legends match dict "commonName-datatype"
    # without the dataID / interval second line.
    return headerFirstLine(table, col)


def isSystemDarkMode():
    """True when the active Qt palette is dark (Window background is dark)."""
    try:
        app = QApplication.instance()
        if app is None:
            return False
        # Prefer styleHints when available (Qt 6.5+)
        try:
            hints = app.styleHints()
            scheme = hints.colorScheme()
            from PyQt6.QtCore import Qt as _Qt
            if scheme == _Qt.ColorScheme.Dark:
                return True
            if scheme == _Qt.ColorScheme.Light:
                return False
        except Exception:
            pass
        bg = app.palette().color(QPalette.ColorRole.Window)
        # Relative luminance
        r, g, b = bg.redF(), bg.greenF(), bg.blueF()
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return lum < 0.45
    except Exception:
        return False


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


def selectedDataRows(table):
    """
    Row indices to graph from selection.
    - Selected cells / ranges → those rows only (partial timeseries)
    - No selection → all rows
    """
    if table is None or table.rowCount() <= 0:
        return []

    rows = set()
    for idx in table.selectedIndexes():
        rows.add(idx.row())
    for r in table.selectedRanges():
        for row in range(r.topRow(), r.bottomRow() + 1):
            rows.add(row)

    if rows:
        return sorted(rows)
    return list(range(table.rowCount()))


def _overlaySeriesFromColumn(table, col, baseLabel, headerFirstLines=None, rows=None):
    """
    For overlay columns, return [(primaryLabel, vals), (secondaryLabel, vals)]
    from per-cell UserRole primaryVal / secondaryVal. Empty list if not overlay data.

    Legend labels use the first line of each series' original header (dict-style
    commonName-datatype), not raw dataIDs. headerFirstLines is [primary, secondary]
    when available from columnMetadata.

    rows: optional list of table row indices to include (selection subset).
    """
    if table is None or table.rowCount() <= 0:
        return []
    if rows is None:
        rows = list(range(table.rowCount()))
    if not rows:
        return []
    n = len(rows)
    primary = np.full(n, np.nan)
    secondary = np.full(n, np.nan)
    hasAny = False
    for i, r in enumerate(rows):
        item = table.item(r, col)
        if item is None:
            continue
        role = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(role, dict) or not role.get('overlay'):
            continue
        hasAny = True
        primary[i] = parseNumeric(role.get('primaryVal', ''))
        secondary[i] = parseNumeric(role.get('secondaryVal', ''))

    if not hasAny:
        return []

    # Prefer stored first-lines from the pre-overlay headers (distinct per series)
    pName = sName = None
    if isinstance(headerFirstLines, (list, tuple)) and len(headerFirstLines) >= 2:
        pName = (headerFirstLines[0] or '').strip() or None
        sName = (headerFirstLines[1] or '').strip() or None
    fallback = (baseLabel or headerFirstLine(table, col) or f"Col {col + 1}").strip()
    pName = pName or fallback
    sName = sName or fallback
    # If both collapsed to the same label, disambiguate with primary/secondary
    if pName == sName:
        pLabel = f"{pName} (primary)"
        sLabel = f"{sName} (secondary)"
    else:
        pLabel = pName
        sLabel = sName
    out = []
    if np.any(np.isfinite(primary)):
        out.append((pLabel, primary))
    if np.any(np.isfinite(secondary)):
        out.append((sLabel, secondary))
    return out


def extractSeries(table, columns=None, rows=None, columnMetadata=None):
    """
    Read timestamps + numeric series from mainTable.

    Overlay columns expand to primary + secondary series (UserRole values).
    columns / rows default to current selection, or the full table when empty.

    Returns (timestamps list[datetime|None], tsTexts list[str], series list[(label, values)], warnings)
    """
    warnings = []
    if table is None or table.rowCount() <= 0 or table.columnCount() <= 0:
        return [], [], [], ["No data in the Data Query table to graph."]

    if columns is None:
        columns = selectedDataColumns(table)
    if not columns:
        return [], [], [], ["No columns available to graph."]

    if rows is None:
        rows = selectedDataRows(table)
    if not rows:
        return [], [], [], ["No rows available to graph."]

    n = len(rows)
    timestamps = []
    tsTexts = []
    for r in rows:
        vh = table.verticalHeaderItem(r)
        tsText = vh.text() if vh is not None else ''
        tsTexts.append(tsText)
        dt, _fmt = parseTimestamp(tsText)
        timestamps.append(dt)

    # If almost no timestamps parsed, use row index as X
    parsedCount = sum(1 for t in timestamps if t is not None)
    useDatetime = parsedCount >= max(2, int(n * 0.5))
    if not useDatetime:
        warnings.append("Could not parse most timestamps; using row index on the X axis.")

    metaList = columnMetadata if columnMetadata is not None else []
    series = []
    for c in columns:
        label = headerLabel(table, c)
        meta = metaList[c] if c < len(metaList) else {}
        colType = (meta.get('type') if isinstance(meta, dict) else None) or ''
        headerLines = meta.get('headerFirstLines') if isinstance(meta, dict) else None

        # Overlay column: graph primary + secondary (not the merged cell alone)
        if colType == 'overlay':
            overlaySeries = _overlaySeriesFromColumn(
                table, c, label, headerFirstLines=headerLines, rows=rows
            )
            if overlaySeries:
                series.extend(overlaySeries)
                continue
            # Fall through if role data missing

        # Also try overlay detection from cell roles even without metadata
        if not colType or colType == 'normal':
            sampleRow = rows[0]
            sample = table.item(sampleRow, c)
            role0 = sample.data(Qt.ItemDataRole.UserRole) if sample is not None else None
            if isinstance(role0, dict) and role0.get('overlay'):
                overlaySeries = _overlaySeriesFromColumn(
                    table, c, label, headerFirstLines=headerLines, rows=rows
                )
                if overlaySeries:
                    series.extend(overlaySeries)
                    continue

        vals = np.empty(n, dtype=float)
        for i, r in enumerate(rows):
            item = table.item(r, c)
            vals[i] = parseNumeric(item.text() if item is not None else '')
        if not np.any(np.isfinite(vals)):
            warnings.append(f"Skipped '{label}' (no numeric values).")
            continue
        series.append((label, vals))

    if not series:
        return timestamps, tsTexts, [], ["No numeric series found to graph."]
    return timestamps, tsTexts, series, warnings


# Legend toggle markers (checkbox look without a side panel)
_LEGEND_ON = '☑'
_LEGEND_OFF = '☐'


class GraphPanel(QWidget):
    """
    Graph content: matplotlib canvas + NavigationToolbar (zoom / pan / home).
    In-plot legend with click-to-toggle (checkbox marks), arrow-key pan, Qt tooltips.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('tabGraph')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        self._legend = None
        self._hoverCid = None
        self._keyCid = None
        self._pickCid = None
        self._pressCid = None
        self._releaseCid = None
        self._scrollCid = None
        self._lineData = []  # list of dicts: line, label, xs, ys, color, visible
        self._tsDisplayFmt = '%m/%d/%y %H:%M:00'
        self._useDatetime = False
        self._theme = 'light'
        self._lastTipKey = None
        # Full data extents (with padding) — pan stays inside these
        self._xDataLim = None
        self._yDataLim = None
        self._y2DataLim = None
        self._clamping = False
        # Middle-mouse pan state: (last xdata, last ydata) in axes coords
        self._midPan = None

    def clearPlot(self):
        try:
            QToolTip.hideText()
        except Exception:
            pass
        self._lastTipKey = None
        self._xDataLim = None
        self._yDataLim = None
        self._y2DataLim = None
        self._midPan = None
        if self.canvas is not None:
            for cid in (
                self._hoverCid, self._keyCid, self._pickCid,
                self._pressCid, self._releaseCid, self._scrollCid,
            ):
                if cid is not None:
                    try:
                        self.canvas.mpl_disconnect(cid)
                    except Exception:
                        pass
            self._hoverCid = None
            self._keyCid = None
            self._pickCid = None
            self._pressCid = None
            self._releaseCid = None
            self._scrollCid = None
            if self.toolbar is not None:
                self._layout.removeWidget(self.toolbar)
                self.toolbar.setParent(None)
                self.toolbar.deleteLater()
            self._layout.removeWidget(self.canvas)
            self.canvas.setParent(None)
            self.canvas.deleteLater()
            self.toolbar = None
            self.canvas = None
            self.figure = None
            self._ax = None
            self._ax2 = None
            self._legend = None
            self._lineData = []
        if self._placeholder is not None:
            self._placeholder.show()

    def _applyToolbarTooltips(self):
        """Ensure matplotlib nav toolbar buttons have clear tooltips."""
        if self.toolbar is None:
            return
        tipMap = {
            'Home': 'Reset original view',
            'Back': 'Back to previous view',
            'Forward': 'Forward to next view',
            'Pan': 'Pan axes with left mouse, zoom with right',
            'Zoom': 'Zoom to rectangle',
            'Subplots': 'Configure subplots',
            'Configure subplots': 'Configure subplots',
            'Save': 'Save the figure',
            'Save the figure': 'Save the figure',
        }
        try:
            for action in self.toolbar.actions():
                text = (action.text() or '').strip()
                tip = (action.toolTip() or '').strip()
                key = text or tip
                for k, v in tipMap.items():
                    if k.lower() in key.lower() or k.lower() in tip.lower():
                        action.setToolTip(v)
                        break
                if not action.toolTip() and text:
                    action.setToolTip(text)
            from PyQt6.QtWidgets import QToolButton
            for btn in self.toolbar.findChildren(QToolButton):
                tip = (btn.toolTip() or '').strip()
                text = (btn.text() or '').strip()
                key = tip or text
                for k, v in tipMap.items():
                    if k.lower() in key.lower():
                        btn.setToolTip(v)
                        break
                if not btn.toolTip() and text:
                    btn.setToolTip(text)
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"GraphPanel toolbar tooltips: {e}")

    def _applyTheme(self, fig, ax, ax2=None):
        """Style figure/axes for retro, system dark, or system light."""
        retro = bool(Config.retroMode)
        dark = (not retro) and isSystemDarkMode()

        if retro:
            fig.patch.set_facecolor('#1a1a1a')
            ax.set_facecolor('#101010')
            ax.tick_params(colors='#00FF00')
            ax.xaxis.label.set_color('#00FF00')
            ax.yaxis.label.set_color('#00FF00')
            for spine in ax.spines.values():
                spine.set_color('#00FF00')
            ax.title.set_color('#00FF00')
            if ax2 is not None:
                ax2.set_facecolor('#101010')
                ax2.tick_params(colors='#00FFFF')
                ax2.yaxis.label.set_color('#00FFFF')
                for spine in ax2.spines.values():
                    spine.set_color('#00FFFF')
            return 'retro'

        if dark:
            figBg = '#2b2b2b'
            axBg = '#1e1e1e'
            textColor = '#e0e0e0'
            spineColor = '#888888'
            fig.patch.set_facecolor(figBg)
            ax.set_facecolor(axBg)
            ax.tick_params(colors=textColor)
            ax.xaxis.label.set_color(textColor)
            ax.yaxis.label.set_color(textColor)
            for spine in ax.spines.values():
                spine.set_color(spineColor)
            ax.title.set_color(textColor)
            if ax2 is not None:
                ax2.set_facecolor(axBg)
                ax2.tick_params(colors=textColor)
                ax2.yaxis.label.set_color(textColor)
                for spine in ax2.spines.values():
                    spine.set_color(spineColor)
            return 'dark'

        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#ffffff')
        return 'light'

    def _colorCycle(self, theme):
        if theme == 'retro':
            return [
                '#00FF00', '#00FFFF', '#FF00FF', '#FFFF00', '#FF8800',
                '#88FF00', '#00FF88', '#FF0088', '#8888FF', '#FFFFFF',
            ]
        if theme == 'dark':
            return [
                '#4ea1ff', '#ff9f43', '#2ed573', '#ff6b6b', '#c56cf0',
                '#feca57', '#ff9ff3', '#54a0ff', '#5f27cd', '#01a3a4',
            ]
        return [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        ]

    def _legendLabel(self, baseLabel, visible=True):
        mark = _LEGEND_ON if visible else _LEGEND_OFF
        return f"{mark} {baseLabel}"

    def _buildInteractiveLegend(self, theme):
        """
        In-plot legend (same spot as before). Click an entry to toggle that
        series; labels use ☑/☐ so it still feels like checkboxes without a side panel.

        Toggles are handled in button_press (not pick_event): zoom/pan mode holds
        canvas.widgetlock, which blocks Figure.pick and would silence legend clicks.
        """
        if self._ax is None or not self._lineData:
            self._legend = None
            return

        lines = [e['line'] for e in self._lineData if e.get('line') is not None]
        labels = [
            self._legendLabel(e.get('label') or '', e.get('line').get_visible())
            for e in self._lineData if e.get('line') is not None
        ]
        if not lines:
            self._legend = None
            return

        legend = self._ax.legend(lines, labels, loc='best', fontsize=8)
        legend.set_title("Click to show/hide")
        try:
            legend.get_title().set_fontsize(7)
        except Exception:
            pass

        if theme == 'dark':
            try:
                legend.get_frame().set_facecolor('#2b2b2b')
                legend.get_frame().set_edgecolor('#888888')
                for text in legend.get_texts():
                    text.set_color('#e0e0e0')
                legend.get_title().set_color('#aaaaaa')
            except Exception:
                pass
        elif theme == 'retro':
            try:
                legend.get_frame().set_facecolor('#1a1a1a')
                legend.get_frame().set_edgecolor('#00FF00')
                for text in legend.get_texts():
                    text.set_color('#00FF00')
                legend.get_title().set_color('#00FF00')
            except Exception:
                pass

        # Keep legend proxy lines always drawn (dimmed when series is off)
        try:
            for legLine in legend.get_lines():
                legLine.set_visible(True)
        except Exception:
            pass

        self._legend = legend

    def _legendRenderer(self):
        """Best-effort renderer for window-extent hit tests."""
        if self.canvas is None:
            return None
        try:
            return self.canvas.get_renderer()
        except Exception:
            return None

    def _isOverLegend(self, event):
        """True if the mouse event is inside the legend frame (display coords)."""
        if self._legend is None or event is None:
            return False
        if event.x is None or event.y is None:
            return False
        try:
            bbox = self._legend.get_window_extent(self._legendRenderer())
            pad = 3.0
            # Cast to plain bool — bbox coords are often numpy scalars
            return bool(
                bbox.x0 - pad <= event.x <= bbox.x1 + pad
                and bbox.y0 - pad <= event.y <= bbox.y1 + pad
            )
        except Exception:
            return False

    def _legendHitIndex(self, event):
        """
        Series index if (event.x, event.y) hits a legend row (line sample or label).
        None if not over a row (still may be over legend frame — see _isOverLegend).
        """
        if self._legend is None or event is None:
            return None
        if event.x is None or event.y is None:
            return None
        if not self._isOverLegend(event):
            return None
        renderer = self._legendRenderer()
        try:
            texts = self._legend.get_texts()
            lines = self._legend.get_lines()
            for i, text in enumerate(texts):
                if i >= len(self._lineData):
                    break
                try:
                    tb = text.get_window_extent(renderer)
                except Exception:
                    continue
                # Extend left to cover the colored line sample next to the label
                x0 = tb.x0 - 30.0
                if i < len(lines):
                    try:
                        lb = lines[i].get_window_extent(renderer)
                        x0 = min(x0, lb.x0 - 4.0)
                    except Exception:
                        pass
                y0, y1 = tb.y0 - 3.0, tb.y1 + 3.0
                x1 = tb.x1 + 6.0
                if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                    return i
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"_legendHitIndex: {e}")
        return None

    def _toggleSeriesAt(self, idx):
        """Toggle visibility of series at _lineData index; refresh legend + axes."""
        if idx is None or idx < 0 or idx >= len(self._lineData):
            return False
        entry = self._lineData[idx]
        line = entry.get('line')
        if line is None:
            return False
        visible = not line.get_visible()
        line.set_visible(visible)
        entry['visible'] = visible
        self._refreshLegendAppearance()
        self._rescaleToVisible()
        if self.canvas is not None:
            self.canvas.draw_idle()
        return True

    def _cancelToolbarInteraction(self):
        """
        Abort zoom rubberband / pan that the toolbar already started on this click.
        Needed because the toolbar's button_press runs before ours (registered first).
        """
        tb = self.toolbar
        if tb is None or self.canvas is None:
            return
        try:
            zinfo = getattr(tb, '_zoom_info', None)
            if zinfo is not None:
                try:
                    cid = getattr(zinfo, 'cid', None)
                    if cid is not None:
                        self.canvas.mpl_disconnect(cid)
                except Exception:
                    pass
                try:
                    tb.remove_rubberband()
                except Exception:
                    pass
                tb._zoom_info = None

            pinfo = getattr(tb, '_pan_info', None)
            if pinfo is not None:
                try:
                    cid = getattr(pinfo, 'cid', None)
                    if cid is not None:
                        self.canvas.mpl_disconnect(cid)
                except Exception:
                    pass
                try:
                    for ax in getattr(pinfo, 'axes', ()) or ():
                        try:
                            ax.end_pan()
                        except Exception:
                            pass
                except Exception:
                    pass
                # Restore toolbar's normal motion handler (release_pan does this)
                try:
                    tb._id_drag = self.canvas.mpl_connect(
                        'motion_notify_event', tb.mouse_move
                    )
                except Exception:
                    pass
                tb._pan_info = None
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"_cancelToolbarInteraction: {e}")

    def _refreshLegendAppearance(self):
        """Update ☑/☐ marks and dim legend proxies for hidden series."""
        if self._legend is None:
            return
        try:
            legLines = self._legend.get_lines()
            legTexts = self._legend.get_texts()
            for i, entry in enumerate(self._lineData):
                if i >= len(legTexts):
                    break
                line = entry.get('line')
                visible = bool(line.get_visible()) if line is not None else True
                base = entry.get('label') or ''
                legTexts[i].set_text(self._legendLabel(base, visible))
                alpha = 1.0 if visible else 0.35
                legTexts[i].set_alpha(alpha)
                if i < len(legLines):
                    legLines[i].set_alpha(alpha)
        except Exception:
            pass

    def _rescaleToVisible(self):
        """
        Rescale Y (and shared X) from currently visible series.
        Keeps dual-axis groups independent on Y.
        """
        if self._ax is None:
            return
        leftYs = []
        rightYs = []
        allXs = []
        for entry in self._lineData:
            line = entry.get('line')
            if line is None or not line.get_visible():
                continue
            xs = entry.get('xs')
            ys = entry.get('ys')
            if xs is None or ys is None or len(ys) == 0:
                continue
            finite = np.isfinite(xs) & np.isfinite(ys)
            if not np.any(finite):
                continue
            allXs.append(xs[finite])
            if line.axes is self._ax2 and self._ax2 is not None:
                rightYs.append(ys[finite])
            else:
                leftYs.append(ys[finite])

        def _padLimits(valsList):
            if not valsList:
                return None
            cat = np.concatenate(valsList)
            if cat.size == 0:
                return None
            lo = float(np.nanmin(cat))
            hi = float(np.nanmax(cat))
            if not np.isfinite(lo) or not np.isfinite(hi):
                return None
            if lo == hi:
                pad = abs(lo) * 0.05 if lo != 0 else 1.0
                return lo - pad, hi + pad
            span = hi - lo
            return lo - span * 0.05, hi + span * 0.05

        xLim = _padLimits(allXs)
        if xLim is not None:
            self._ax.set_xlim(xLim)
        yLim = _padLimits(leftYs)
        if yLim is not None:
            self._ax.set_ylim(yLim)
        if self._ax2 is not None:
            y2 = _padLimits(rightYs)
            if y2 is not None:
                self._ax2.set_ylim(y2)

        self._clampView()
        try:
            if self.toolbar is not None:
                self.toolbar.push_current()
        except Exception:
            pass

    def _storeDataLimits(self):
        """Capture padded data extents after initial plot (pan boundary)."""
        if self._ax is None:
            self._xDataLim = self._yDataLim = self._y2DataLim = None
            return
        try:
            self._xDataLim = tuple(self._ax.get_xlim())
            self._yDataLim = tuple(self._ax.get_ylim())
            self._y2DataLim = (
                tuple(self._ax2.get_ylim()) if self._ax2 is not None else None
            )
        except Exception:
            self._xDataLim = self._yDataLim = self._y2DataLim = None

    def _clampAxis(self, ax, getLim, setLim, dataLim):
        """Keep a view window inside dataLim (allow zoom-in; block pan past ends)."""
        if ax is None or dataLim is None:
            return
        d0, d1 = dataLim
        if d1 < d0:
            d0, d1 = d1, d0
        dataSpan = d1 - d0
        if dataSpan <= 0 or not np.isfinite(dataSpan):
            return
        try:
            v0, v1 = getLim()
        except Exception:
            return
        if v1 < v0:
            v0, v1 = v1, v0
        viewSpan = v1 - v0
        if not np.isfinite(viewSpan) or viewSpan <= 0:
            return
        if viewSpan >= dataSpan:
            setLim(d0, d1)
            return
        if v0 < d0:
            v0 = d0
            v1 = d0 + viewSpan
        if v1 > d1:
            v1 = d1
            v0 = d1 - viewSpan
        setLim(v0, v1)

    def _clampView(self):
        """Constrain pan to the original timeseries / data range."""
        if self._clamping or self._ax is None:
            return
        self._clamping = True
        try:
            self._clampAxis(
                self._ax, self._ax.get_xlim, self._ax.set_xlim, self._xDataLim
            )
            self._clampAxis(
                self._ax, self._ax.get_ylim, self._ax.set_ylim, self._yDataLim
            )
            if self._ax2 is not None and self._y2DataLim is not None:
                self._clampAxis(
                    self._ax2, self._ax2.get_ylim, self._ax2.set_ylim, self._y2DataLim
                )
        finally:
            self._clamping = False

    def plotFromTable(self, table, columns=None, rows=None, columnMetadata=None):
        """
        Build/rebuild the graph from mainTable.
        columns / rows: optional subsets (default = current selection, else full table).
        Returns (ok: bool, message: str).
        """
        if not _ensureMatplotlib():
            return False, (
                "matplotlib is not installed.\n\n"
                "Install it with:\n  pip install matplotlib\n"
                "Then restart Data Doctor."
            )

        if columnMetadata is None and table is not None:
            parent = table.window() if hasattr(table, 'window') else None
            if parent is not None:
                columnMetadata = getattr(parent, 'columnMetadata', None)

        timestamps, tsTexts, series, warnings = extractSeries(
            table, columns=columns, rows=rows, columnMetadata=columnMetadata
        )
        if not series:
            msg = warnings[0] if warnings else "Nothing to graph."
            return False, msg

        self.clearPlot()
        if self._placeholder is not None:
            self._placeholder.hide()

        # Fixed margins — avoid tight_layout so hover/rescales never jump the frame
        fig = Figure(figsize=(8, 5), tight_layout=False)
        fig.subplots_adjust(left=0.08, right=0.92, top=0.96, bottom=0.14)
        self.figure = fig
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        ToolbarCls = _makeGraphToolbarClass() or NavigationToolbar2QT
        self.toolbar = ToolbarCls(self.canvas, self)
        self.toolbar.setObjectName('graphToolbar')
        self._applyToolbarTooltips()

        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.canvas, stretch=1)

        ax = fig.add_subplot(111)
        self._ax = ax
        self._ax2 = None
        theme = self._applyTheme(fig, ax)
        self._theme = theme
        colorCycle = self._colorCycle(theme)

        n = len(series[0][1])
        useDatetime = (
            timestamps
            and sum(1 for t in timestamps if t is not None) >= max(2, int(n * 0.5))
        )
        self._useDatetime = useDatetime
        self._tsDisplayFmt = detectTimestampDisplayFormat(tsTexts)

        if useDatetime:
            x = mdates.date2num([
                t if t is not None else np.nan for t in timestamps
            ])
        else:
            x = np.arange(n, dtype=float)

        leftSeries, rightSeries = assignAxes(series)
        self._lineData = []
        colorIdx = 0

        def plotGroup(axTarget, group, isRight=False):
            nonlocal colorIdx
            for label, vals in group:
                color = colorCycle[colorIdx % len(colorCycle)]
                colorIdx += 1
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
                    picker=5,
                )
                self._lineData.append({
                    'line': line,
                    'label': label,
                    'xs': np.asarray(x[mask], dtype=float),
                    'ys': np.asarray(y[mask], dtype=float),
                    'color': color,
                    'visible': True,
                })
            ylabelColor = colorCycle[0] if not isRight else colorCycle[min(1, len(colorCycle) - 1)]
            axTarget.set_ylabel(
                'Value' + (' (right)' if isRight else ''),
                color=ylabelColor,
            )

        plotGroup(ax, leftSeries, isRight=False)

        if rightSeries:
            ax2 = ax.twinx()
            self._ax2 = ax2
            self._applyTheme(fig, ax, ax2)
            plotGroup(ax2, rightSeries, isRight=True)

        if useDatetime:
            ax.xaxis_date()
            ax.xaxis.set_major_formatter(mdates.DateFormatter(self._tsDisplayFmt))
            for tickLabel in ax.get_xticklabels():
                tickLabel.set_rotation(30)
                tickLabel.set_horizontalalignment('right')
            ax.set_xlabel('Timestamp')
        else:
            ax.set_xlabel('Row')

        ax.set_title('')

        gridColor = '#666666' if theme in ('dark', 'retro') else None
        if gridColor:
            ax.grid(True, alpha=0.3, color=gridColor)
        else:
            ax.grid(True, alpha=0.3)

        # In-plot legend with ☑/☐ click-to-toggle (no left panel)
        self._buildInteractiveLegend(theme)

        # Capture home extents before any pan (used as clamp bounds)
        self.canvas.draw()
        self._storeDataLimits()

        self._hoverCid = self.canvas.mpl_connect('motion_notify_event', self._onMotion)
        self._keyCid = self.canvas.mpl_connect('key_press_event', self._onKeyPress)
        # Legend toggles use button_press (not pick_event): zoom/pan holds widgetlock
        # which disables Figure.pick, so pick_event never fires while Zoom is default-on.
        self._pressCid = self.canvas.mpl_connect('button_press_event', self._onButtonPress)
        self._releaseCid = self.canvas.mpl_connect('button_release_event', self._onButtonRelease)
        # Clamp toolbar pan/zoom navigation as well
        try:
            self._ax.callbacks.connect('xlim_changed', self._onAxisLimitsChanged)
            self._ax.callbacks.connect('ylim_changed', self._onAxisLimitsChanged)
            if self._ax2 is not None:
                self._ax2.callbacks.connect('ylim_changed', self._onAxisLimitsChanged)
        except Exception:
            pass
        self.canvas.setFocus()

        self.canvas.draw_idle()

        note = ''
        if warnings:
            note = ' '.join(warnings)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"GraphPanel.plotFromTable: {len(leftSeries)} left, "
                f"{len(rightSeries)} right, rows={n}, datetime={useDatetime}, "
                f"theme={theme}, tsFmt={self._tsDisplayFmt!r}",
            )
        return True, note

    def keyPressEvent(self, event):
        """Arrow keys pan the graph when the panel has focus."""
        if self._handleArrowPan(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _onKeyPress(self, event):
        """matplotlib key_press_event (canvas focused)."""
        if event is None or not event.key:
            return
        keyMap = {
            'left': Qt.Key.Key_Left,
            'right': Qt.Key.Key_Right,
            'up': Qt.Key.Key_Up,
            'down': Qt.Key.Key_Down,
        }
        qtKey = keyMap.get(str(event.key).lower())
        if qtKey is not None:
            self._handleArrowPan(qtKey)

    def _onAxisLimitsChanged(self, ax):
        """Keep toolbar pan/zoom from leaving the timeseries range."""
        if self._clamping:
            return
        self._clampView()

    def _onButtonPress(self, event):
        """
        Left-click: toggle series via legend rows (works while Zoom/Pan is active).
        Middle-click: free pan without needing toolbar pan mode.
        """
        if event is None:
            return

        # Legend show/hide — must not rely on pick_event (blocked by widgetlock in zoom)
        if event.button == 1:
            idx = self._legendHitIndex(event)
            if idx is not None:
                self._toggleSeriesAt(idx)
                self._cancelToolbarInteraction()
                try:
                    QToolTip.hideText()
                except Exception:
                    pass
                return
            # Click on legend frame/title: don't start a zoom rubberband there
            if self._isOverLegend(event):
                self._cancelToolbarInteraction()
                return

        if event.button != 2 or event.inaxes is None:
            return
        # Store display pixels so pan stays stable after limit changes
        self._midPan = (float(event.x), float(event.y))
        try:
            QToolTip.hideText()
        except Exception:
            pass

    def _onButtonRelease(self, event):
        if event is not None and event.button == 2 and self._midPan is not None:
            self._midPan = None
            try:
                if self.toolbar is not None:
                    self.toolbar.push_current()
            except Exception:
                pass

    def _onMotion(self, event):
        """Middle-mouse drag pans; otherwise show hover tooltip."""
        if self._midPan is not None:
            self._handleMiddlePan(event)
            return
        self._onHover(event)

    def _handleMiddlePan(self, event):
        """Pan axes by middle-mouse drag, clamped to data range."""
        if self._ax is None or self.canvas is None or self._midPan is None:
            return
        if event is None or event.x is None or event.y is None:
            return
        lastPx, lastPy = self._midPan
        curPx, curPy = float(event.x), float(event.y)
        try:
            inv = self._ax.transData.inverted()
            p0 = inv.transform((lastPx, lastPy))
            p1 = inv.transform((curPx, curPy))
            dx = float(p0[0] - p1[0])
            dy = float(p0[1] - p1[1])
            x0, x1 = self._ax.get_xlim()
            y0, y1 = self._ax.get_ylim()
            self._ax.set_xlim(x0 + dx, x1 + dx)
            self._ax.set_ylim(y0 + dy, y1 + dy)
            if self._ax2 is not None:
                y20, y21 = self._ax2.get_ylim()
                span1 = (y1 - y0) if (y1 - y0) != 0 else 1.0
                span2 = y21 - y20
                dy2 = dy * (span2 / span1) if span1 else 0.0
                self._ax2.set_ylim(y20 + dy2, y21 + dy2)
        except Exception:
            return
        self._clampView()
        self._midPan = (curPx, curPy)
        self.canvas.draw_idle()

    def _handleArrowPan(self, qtKey):
        """
        Pan current view by ~12% of visible range.
        Left/Right → X; Up/Down → Y (both axes when dual).
        """
        if self._ax is None or self.canvas is None:
            return False
        key = qtKey
        frac = 0.12
        try:
            x0, x1 = self._ax.get_xlim()
            y0, y1 = self._ax.get_ylim()
        except Exception:
            return False
        dx = (x1 - x0) * frac
        dy = (y1 - y0) * frac

        if key == Qt.Key.Key_Left:
            self._ax.set_xlim(x0 - dx, x1 - dx)
        elif key == Qt.Key.Key_Right:
            self._ax.set_xlim(x0 + dx, x1 + dx)
        elif key == Qt.Key.Key_Up:
            self._ax.set_ylim(y0 + dy, y1 + dy)
            if self._ax2 is not None:
                y20, y21 = self._ax2.get_ylim()
                dy2 = (y21 - y20) * frac
                self._ax2.set_ylim(y20 + dy2, y21 + dy2)
        elif key == Qt.Key.Key_Down:
            self._ax.set_ylim(y0 - dy, y1 - dy)
            if self._ax2 is not None:
                y20, y21 = self._ax2.get_ylim()
                dy2 = (y21 - y20) * frac
                self._ax2.set_ylim(y20 - dy2, y21 - dy2)
        else:
            return False

        self._clampView()
        try:
            if self.toolbar is not None:
                self.toolbar.push_current()
        except Exception:
            pass
        self.canvas.draw_idle()
        return True

    def _formatXForTooltip(self, xVal):
        """Format x coordinate using the same table timestamp format when possible."""
        if self._useDatetime and mdates is not None:
            try:
                dt = mdates.num2date(xVal)
                if getattr(dt, 'tzinfo', None) is not None:
                    dt = dt.replace(tzinfo=None)
                return dt.strftime(self._tsDisplayFmt)
            except Exception:
                return str(xVal)
        try:
            if float(xVal) == int(xVal):
                return str(int(xVal))
        except Exception:
            pass
        return f"{xVal:.4g}"

    def _onHover(self, event):
        """
        Show a Qt tooltip near the cursor for the nearest visible data point.

        Uses QToolTip (not matplotlib annotation) so the plot frame never jumps
        when a point near the top edge is hovered.
        """
        if self.canvas is None or not self._lineData:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            if self._lastTipKey is not None:
                QToolTip.hideText()
                self._lastTipKey = None
            return

        best = None  # (dist2_px, x, y, label)

        for entry in self._lineData:
            line = entry.get('line')
            if line is None or not line.get_visible():
                continue
            xs = entry.get('xs')
            ys = entry.get('ys')
            label = entry.get('label') or ''
            if xs is None or ys is None or xs.size == 0:
                continue
            try:
                # Distance in display pixels — fair for dual axes
                pts = line.axes.transData.transform(np.column_stack([xs, ys]))
                mouse = np.array([event.x, event.y], dtype=float)
                d2 = (pts[:, 0] - mouse[0]) ** 2 + (pts[:, 1] - mouse[1]) ** 2
                i = int(np.argmin(d2))
                dist2 = float(d2[i])
                # ~14 px hit radius
                if dist2 < 196 and (best is None or dist2 < best[0]):
                    best = (dist2, float(xs[i]), float(ys[i]), label)
            except Exception:
                continue

        if best is None:
            if self._lastTipKey is not None:
                QToolTip.hideText()
                self._lastTipKey = None
            return

        _dist, px, py, label = best
        tsStr = self._formatXForTooltip(px)
        try:
            if abs(py) >= 1000 or (abs(py) > 0 and abs(py) < 0.01):
                valStr = f"{py:g}"
            else:
                valStr = f"{py:.4g}"
        except Exception:
            valStr = str(py)

        tip = f"{label}\n{tsStr}\n{valStr}"
        tipKey = (label, round(px, 6), round(py, 6))
        # Avoid re-showing the same tip every motion event (flicker)
        if tipKey != self._lastTipKey:
            self._lastTipKey = tipKey
            QToolTip.showText(QCursor.pos(), tip, self.canvas)
