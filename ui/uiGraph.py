# uiGraph.py
# Graph tab: plot mainTable series with zoom toolbar and multi Y-axis when
# scales / value bands differ. Supports dark/light system palette, hover
# tooltips, table timestamp formats, overlay pairs, legend show/hide.

from __future__ import annotations
import os
import re
from datetime import datetime
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QEvent
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
    Characteristic magnitude for multi-axis decisions.
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


def seriesValueRange(values):
    """(min, max) of finite values, or None if empty."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def seriesCenter(values):
    """Median of finite values (axis clustering key)."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    return float(np.median(finite))


def _rangesCompatible(rangeA, rangeB, scaleA, scaleB, scaleRatioThreshold=8.0, minOverlapFrac=0.12):
    """
    True when two series should share one Y-axis.

    Separate axes when:
      - characteristic scales differ a lot (e.g. elev vs tiny delta), or
      - value bands barely overlap (e.g. ~383 band vs ~214 band) so each
        group can use the full plot height for its trend.
    """
    sA = max(float(scaleA), 1e-12)
    sB = max(float(scaleB), 1e-12)
    ratio = max(sA, sB) / min(sA, sB)
    if ratio >= scaleRatioThreshold:
        return False
    if rangeA is None or rangeB is None:
        return True
    lo1, hi1 = rangeA
    lo2, hi2 = rangeB
    overlap = max(0.0, min(hi1, hi2) - max(lo1, lo2))
    span = max(hi1, hi2) - min(lo1, lo2)
    if span <= 1e-12:
        return True
    # Nearly non-overlapping bands → different axes
    if (overlap / span) < minOverlapFrac:
        return False
    return True


def assignAxes(seriesList, scaleRatioThreshold=8.0, maxAxes=4):
    """
    Partition series into one or more Y-axis groups.

    seriesList: list of (label, values[, texts])
    Returns list of groups; each group is a list of those tuples.
    Group 0 is plotted on the primary (left) axis; later groups on twins.
    """
    if not seriesList:
        return []
    if len(seriesList) == 1:
        return [list(seriesList)]

    # Greedy cluster: first compatible group wins; else open a new axis (cap maxAxes)
    groups = []  # each: items, range, scale, center
    for item in seriesList:
        vals = item[1]
        r = seriesValueRange(vals)
        s = seriesScale(vals)
        c = seriesCenter(vals)
        placed = False
        for g in groups:
            if _rangesCompatible(
                g['range'], r, g['scale'], s, scaleRatioThreshold=scaleRatioThreshold
            ):
                g['items'].append(item)
                if r is not None:
                    if g['range'] is None:
                        g['range'] = r
                    else:
                        g['range'] = (
                            min(g['range'][0], r[0]),
                            max(g['range'][1], r[1]),
                        )
                g['scale'] = max(g['scale'], s)
                # Running center for fallback nearest-group
                n = len(g['items'])
                g['center'] = (g['center'] * (n - 1) + c) / n
                placed = True
                break
        if placed:
            continue
        if len(groups) < maxAxes:
            groups.append({
                'items': [item],
                'range': r,
                'scale': s,
                'center': c,
            })
            continue
        # Cap reached: merge into nearest group by center distance
        best = min(groups, key=lambda g: abs(g['center'] - c))
        best['items'].append(item)
        if r is not None:
            if best['range'] is None:
                best['range'] = r
            else:
                best['range'] = (
                    min(best['range'][0], r[0]),
                    max(best['range'][1], r[1]),
                )
        best['scale'] = max(best['scale'], s)
        n = len(best['items'])
        best['center'] = (best['center'] * (n - 1) + c) / n

    # Never return an empty first group
    out = [g['items'] for g in groups if g['items']]
    return out if out else [list(seriesList)]


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
    """True when the active Qt palette is dark (follows Options Light/Dark)."""
    try:
        app = QApplication.instance()
        if app is None:
            return False
        # Palette only — styleHints.colorScheme can still report the OS while
        # applyColorTheme has already installed a forced light/dark palette.
        bg = app.palette().color(QPalette.ColorRole.Window)
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
    For overlay columns, return [(primaryLabel, vals, texts), (secondaryLabel, vals, texts)]
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
    primaryTexts = [''] * n
    secondaryTexts = [''] * n
    hasAny = False
    for i, r in enumerate(rows):
        item = table.item(r, col)
        if item is None:
            continue
        role = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(role, dict) or not role.get('overlay'):
            continue
        hasAny = True
        pRaw = role.get('primaryVal', '')
        sRaw = role.get('secondaryVal', '')
        primary[i] = parseNumeric(pRaw)
        secondary[i] = parseNumeric(sRaw)
        primaryTexts[i] = str(pRaw).strip() if pRaw not in (None, '') else ''
        secondaryTexts[i] = str(sRaw).strip() if sRaw not in (None, '') else ''

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
        out.append((pLabel, primary, primaryTexts))
    if np.any(np.isfinite(secondary)):
        out.append((sLabel, secondary, secondaryTexts))
    return out


def extractSeries(table, columns=None, rows=None, columnMetadata=None):
    """
    Read timestamps + numeric series from mainTable.

    Overlay columns expand to primary + secondary series (UserRole values).
    columns / rows default to current selection, or the full table when empty.

    Returns (timestamps list[datetime|None], tsTexts list[str],
             series list[(label, values, displayTexts)], warnings)
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
        texts = [''] * n
        for i, r in enumerate(rows):
            item = table.item(r, c)
            raw = item.text() if item is not None else ''
            vals[i] = parseNumeric(raw)
            texts[i] = (raw or '').strip()
        if not np.any(np.isfinite(vals)):
            warnings.append(f"Skipped '{label}' (no numeric values).")
            continue
        series.append((label, vals, texts))

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
        self._ax2 = None  # first twin (compat); full list is _yAxes
        self._yAxes = []  # all Y axes: [primary, twin1, twin2, ...]
        self._legend = None
        self._hoverCid = None
        self._keyCid = None
        self._pickCid = None
        self._pressCid = None
        self._releaseCid = None
        self._scrollCid = None
        # list of dicts: line, label, xs, ys, color, visible, axisIndex
        self._lineData = []
        self._tsDisplayFmt = '%m/%d/%y %H:%M:00'
        self._useDatetime = False
        self._theme = 'light'
        self._lastTipKey = None
        # Full data extents (with padding) — pan stays inside these
        self._xDataLim = None
        self._yDataLim = None
        self._y2DataLim = None
        self._yDataLims = []  # parallel to _yAxes
        self._clamping = False
        self._updatingMarkers = False
        self._autoscalingY = False
        self._autoscaleYPending = False
        self._lastXLim = None
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
        self._yDataLims = []
        self._lastXLim = None
        self._autoscaleYPending = False
        self._autoscalingY = False
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
            self._yAxes = []
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

    def _applyTheme(self, fig, ax, *extraAxes):
        """Style figure/axes for retro, system dark, or system light."""
        retro = bool(Config.retroMode)
        dark = (not retro) and isSystemDarkMode()
        # Flatten: allow ax2=None style or a list of twins
        twins = []
        for a in extraAxes:
            if a is None:
                continue
            if isinstance(a, (list, tuple)):
                twins.extend([x for x in a if x is not None])
            else:
                twins.append(a)

        # Twin tick colors cycle in retro so multi-axis stays readable
        retroTwinColors = ['#00FFFF', '#FF00FF', '#FFFF00', '#FF8800']

        if retro:
            fig.patch.set_facecolor('#1a1a1a')
            ax.set_facecolor('#101010')
            ax.tick_params(colors='#00FF00')
            ax.xaxis.label.set_color('#00FF00')
            ax.yaxis.label.set_color('#00FF00')
            for spine in ax.spines.values():
                spine.set_color('#00FF00')
            ax.title.set_color('#00FF00')
            for i, twin in enumerate(twins):
                c = retroTwinColors[i % len(retroTwinColors)]
                twin.set_facecolor('#101010')
                twin.tick_params(colors=c)
                twin.yaxis.label.set_color(c)
                for spine in twin.spines.values():
                    spine.set_color(c)
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
            for twin in twins:
                twin.set_facecolor(axBg)
                twin.tick_params(colors=textColor)
                twin.yaxis.label.set_color(textColor)
                for spine in twin.spines.values():
                    spine.set_color(spineColor)
            return 'dark'

        figBg = '#ffffff'
        axBg = '#ffffff'
        textColor = '#222222'
        spineColor = '#888888'
        fig.patch.set_facecolor(figBg)
        ax.set_facecolor(axBg)
        ax.tick_params(colors=textColor)
        ax.xaxis.label.set_color(textColor)
        ax.yaxis.label.set_color(textColor)
        for spine in ax.spines.values():
            spine.set_color(spineColor)
        ax.title.set_color(textColor)
        for twin in twins:
            twin.set_facecolor(axBg)
            twin.tick_params(colors=textColor)
            twin.yaxis.label.set_color(textColor)
            for spine in twin.spines.values():
                spine.set_color(spineColor)
        return 'light'

    def reapplyTheme(self):
        """Restyle an already-drawn graph after light/dark/retro change."""
        if self.figure is None or self._ax is None:
            self._applyToolbarTheme()
            return
        extra = list(self._yAxes[1:]) if self._yAxes else []
        theme = self._applyTheme(self.figure, self._ax, *extra)
        self._theme = theme
        colorCycle = self._colorCycle(theme)
        for i, entry in enumerate(self._lineData):
            color = colorCycle[i % len(colorCycle)]
            line = entry.get('line')
            if line is not None:
                try:
                    line.set_color(color)
                except Exception:
                    pass
            entry['color'] = color
        try:
            self._buildInteractiveLegend(theme)
        except Exception:
            pass
        self._applyToolbarTheme()
        if self.canvas is not None:
            try:
                self.canvas.draw_idle()
            except Exception:
                pass

    def _applyToolbarTheme(self):
        if self.toolbar is None:
            return
        if Config.retroMode:
            self.toolbar.setStyleSheet(
                "QToolBar { background: #1a1a1a; border: none; spacing: 2px; }"
                "QToolButton { background: #1a1a1a; color: #00FF00;"
                "  border: 1px solid #00aa00; border-radius: 2px; padding: 2px; }"
                "QToolButton:hover { background: #003300; }"
                "QToolButton:checked, QToolButton:pressed { background: #004400; }"
            )
        else:
            self.toolbar.setStyleSheet("")

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

        if theme == 'dark':
            try:
                legend.get_frame().set_facecolor('#2b2b2b')
                legend.get_frame().set_edgecolor('#888888')
                for text in legend.get_texts():
                    text.set_color('#e0e0e0')
            except Exception:
                pass
        elif theme == 'retro':
            try:
                legend.get_frame().set_facecolor('#1a1a1a')
                legend.get_frame().set_edgecolor('#00FF00')
                for text in legend.get_texts():
                    text.set_color('#00FF00')
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
        """Toggle visibility of series at _lineData index; refresh legend + axes.

        Keep the current X zoom (do not home the view). Refit Y only to remaining
        visible series still in the current X window. Hide Y-axis chrome when no
        series on that axis remain visible.
        """
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
        self._syncAxisVisibility()
        # Do not call _rescaleToVisible() — that resets X to full series range.
        self._autoscaleYToXView()
        if self.canvas is not None:
            self.canvas.draw_idle()
        return True

    def _syncAxisVisibility(self):
        """
        Show/hide each Y-axis (ticks, label, relevant spine) based on whether
        any series on that axis is currently visible.
        """
        axes = self._yAxes or ([self._ax] if self._ax is not None else [])
        if not axes:
            return
        for i, ax in enumerate(axes):
            if ax is None:
                continue
            hasVisible = False
            for entry in self._lineData:
                line = entry.get('line')
                if line is None or not line.get_visible():
                    continue
                if entry.get('axisIndex', 0) == i or line.axes is ax:
                    hasVisible = True
                    break
            try:
                ax.yaxis.set_visible(hasVisible)
            except Exception:
                pass
            # Primary (left) vs twins (right, possibly outward)
            try:
                if i == 0:
                    if 'left' in ax.spines:
                        ax.spines['left'].set_visible(hasVisible)
                else:
                    if 'right' in ax.spines:
                        ax.spines['right'].set_visible(hasVisible)
            except Exception:
                pass
            try:
                # Blank ylabel when hidden so it does not float alone
                if not hasVisible:
                    ax.set_ylabel('')
                elif not (ax.get_ylabel() or '').strip():
                    if i == 0:
                        ax.set_ylabel('Value')
                    elif i == 1:
                        ax.set_ylabel('Value (right)')
                    else:
                        ax.set_ylabel(f'Value ({i + 1})')
            except Exception:
                pass

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

    @staticmethod
    def _padLimits(valsList):
        """Min/max of concatenated arrays with 5% padding; None if empty."""
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

    def _axisIndexForEntry(self, entry):
        """Resolve which _yAxes slot a line entry belongs to."""
        if entry is None:
            return 0
        ai = entry.get('axisIndex')
        if isinstance(ai, int) and ai >= 0:
            return ai
        line = entry.get('line')
        if line is not None and self._yAxes:
            for i, ax in enumerate(self._yAxes):
                if line.axes is ax:
                    return i
        if line is not None and self._ax2 is not None and line.axes is self._ax2:
            return 1
        return 0

    def _rescaleToVisible(self):
        """
        Rescale Y (and shared X) from currently visible series.
        Keeps multi-axis groups independent on Y.
        """
        if self._ax is None:
            return
        axes = self._yAxes or [self._ax]
        ysByAxis = [[] for _ in axes]
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
            ai = self._axisIndexForEntry(entry)
            if 0 <= ai < len(ysByAxis):
                ysByAxis[ai].append(ys[finite])

        xLim = self._padLimits(allXs)
        if xLim is not None:
            self._ax.set_xlim(xLim)
        for i, ax in enumerate(axes):
            if ax is None:
                continue
            yLim = self._padLimits(ysByAxis[i])
            if yLim is not None:
                ax.set_ylim(yLim)

        try:
            self._lastXLim = tuple(self._ax.get_xlim())
        except Exception:
            self._lastXLim = None

        self._clampView()
        try:
            if self.toolbar is not None:
                self.toolbar.push_current()
        except Exception:
            pass

    def _autoscaleYToXView(self):
        """
        Fit Y axes to points whose X falls in the current xlim.

        Zoom / horizontal pan only change X; Y then matches on-screen data so a
        far-away outlier (e.g. -99999) no longer skews scale when it is off-screen.
        """
        if self._ax is None or not self._lineData or self._autoscalingY:
            return False
        try:
            x0, x1 = self._ax.get_xlim()
        except Exception:
            return False
        if x1 < x0:
            x0, x1 = x1, x0

        axes = self._yAxes or [self._ax]
        ysByAxis = [[] for _ in axes]
        for entry in self._lineData:
            line = entry.get('line')
            if line is None or not line.get_visible():
                continue
            xs = entry.get('xs')
            ys = entry.get('ys')
            if xs is None or ys is None or len(ys) == 0:
                continue
            xs = np.asarray(xs, dtype=float)
            ys = np.asarray(ys, dtype=float)
            if xs.size != ys.size:
                continue
            finite = np.isfinite(xs) & np.isfinite(ys)
            inView = finite & (xs >= x0) & (xs <= x1)
            if not np.any(inView):
                continue
            ai = self._axisIndexForEntry(entry)
            if 0 <= ai < len(ysByAxis):
                ysByAxis[ai].append(ys[inView])

        newLims = [self._padLimits(bucket) for bucket in ysByAxis]
        if all(lim is None for lim in newLims):
            return False

        self._autoscalingY = True
        changed = False
        try:
            for i, ax in enumerate(axes):
                if ax is None or newLims[i] is None:
                    continue
                yLim = newLims[i]
                try:
                    cur = tuple(ax.get_ylim())
                except Exception:
                    cur = None
                if (
                    cur is None
                    or abs(cur[0] - yLim[0]) > 1e-12
                    or abs(cur[1] - yLim[1]) > 1e-12
                ):
                    ax.set_ylim(yLim)
                    self._disableAxisOffset(ax)
                    changed = True
        finally:
            self._autoscalingY = False

        if changed and self.canvas is not None:
            try:
                self.canvas.draw_idle()
            except Exception:
                pass
        return changed

    def _scheduleAutoscaleY(self):
        """
        Run Y-fit after the current event finishes.

        Matplotlib zoom sets xlim then ylim from the rubberband; if we autoscale
        Y during xlim_changed, the subsequent set_ylim would undo it. Defer so
        we always win after both limits are applied.
        """
        if self._autoscaleYPending:
            return
        self._autoscaleYPending = True

        def _run():
            self._autoscaleYPending = False
            if self._ax is None or self._autoscalingY or self._clamping:
                return
            self._autoscaleYToXView()

        QTimer.singleShot(0, _run)

    def _storeDataLimits(self):
        """Capture padded data extents after initial plot (pan boundary)."""
        if self._ax is None:
            self._xDataLim = self._yDataLim = self._y2DataLim = None
            self._yDataLims = []
            return
        try:
            self._xDataLim = tuple(self._ax.get_xlim())
            axes = self._yAxes or [self._ax]
            self._yDataLims = []
            for ax in axes:
                if ax is None:
                    self._yDataLims.append(None)
                else:
                    self._yDataLims.append(tuple(ax.get_ylim()))
            self._yDataLim = self._yDataLims[0] if self._yDataLims else None
            self._y2DataLim = (
                self._yDataLims[1] if len(self._yDataLims) > 1 else None
            )
        except Exception:
            self._xDataLim = self._yDataLim = self._y2DataLim = None
            self._yDataLims = []

    @staticmethod
    def _disableAxisOffset(ax):
        """
        Force plain absolute tick labels on Y (and plain X when numeric).

        Matplotlib's default ScalarFormatter subtracts a common offset when the
        zoomed span is small relative to magnitude (e.g. elev 1040.2–1041.0
        becomes tick labels 0.2–1.0 with +1.04e3). Elevations / stage values
        must stay absolute so zoom never looks like a different quantity.
        """
        if ax is None:
            return
        try:
            ax.ticklabel_format(axis='y', useOffset=False, style='plain')
        except Exception:
            try:
                fmt = ax.yaxis.get_major_formatter()
                if hasattr(fmt, 'set_useOffset'):
                    fmt.set_useOffset(False)
                if hasattr(fmt, 'set_scientific'):
                    fmt.set_scientific(False)
            except Exception:
                pass

    def _clampAxis(self, ax, getLim, setLim, dataLim):
        """Keep a view window inside dataLim (allow zoom-in; block pan past ends).

        Only calls setLim when limits actually change so a no-op pan at full
        range does not redraw / re-layout the figure (visual "adjust").
        """
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
        # Relative tolerance: avoid float noise triggering a redraw
        tol = max(abs(dataSpan) * 1e-12, 1e-15)
        if viewSpan >= dataSpan - tol:
            # Already at (or past) full range — only snap if we truly drifted
            if abs(v0 - d0) > tol or abs(v1 - d1) > tol:
                setLim(d0, d1)
            return
        new0, new1 = v0, v1
        if new0 < d0 - tol:
            new0 = d0
            new1 = d0 + viewSpan
        if new1 > d1 + tol:
            new1 = d1
            new0 = d1 - viewSpan
        if abs(new0 - v0) > tol or abs(new1 - v1) > tol:
            setLim(new0, new1)

    def _clampView(self):
        """Constrain pan to the original timeseries / data range."""
        if self._clamping or self._ax is None:
            return
        self._clamping = True
        try:
            self._clampAxis(
                self._ax, self._ax.get_xlim, self._ax.set_xlim, self._xDataLim
            )
            axes = self._yAxes or [self._ax]
            lims = self._yDataLims or []
            for i, ax in enumerate(axes):
                if ax is None:
                    continue
                lim = lims[i] if i < len(lims) else None
                if lim is None and i == 0:
                    lim = self._yDataLim
                if lim is None and i == 1:
                    lim = self._y2DataLim
                if lim is not None:
                    self._clampAxis(ax, ax.get_ylim, ax.set_ylim, lim)
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

        axisGroups = assignAxes(series)
        nAxes = max(1, len(axisGroups))

        # Fixed margins — leave room for extra right-side Y axes
        fig = Figure(figsize=(8, 5), tight_layout=False)
        rightMargin = max(0.72, 0.92 - 0.06 * max(0, nAxes - 2))
        fig.subplots_adjust(left=0.08, right=rightMargin, top=0.96, bottom=0.14)
        self.figure = fig
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas.installEventFilter(self)
        ToolbarCls = _makeGraphToolbarClass() or NavigationToolbar2QT
        self.toolbar = ToolbarCls(self.canvas, self)
        self.toolbar.setObjectName('graphToolbar')
        self._applyToolbarTooltips()
        self._applyToolbarTheme()

        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.canvas, stretch=1)

        ax = fig.add_subplot(111)
        self._ax = ax
        self._ax2 = None
        self._yAxes = [ax]
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

        self._lineData = []
        colorIdx = 0

        def plotGroup(axTarget, group, axisIndex=0):
            nonlocal colorIdx
            for item in group:
                label = item[0]
                vals = item[1]
                texts = item[2] if len(item) > 2 else None
                color = colorCycle[colorIdx % len(colorCycle)]
                colorIdx += 1
                y = np.array(vals, dtype=float)
                mask = np.isfinite(x) & np.isfinite(y)
                if not np.any(mask):
                    continue
                # Keep NaNs in the plotted arrays so matplotlib breaks the
                # line at missing data instead of drawing a straight gap fill.
                nPts = int(mask.sum())
                markEvery = self._markerEveryForCount(nPts)
                markerSize = self._markerSizeForCount(nPts)
                finiteIdx = np.flatnonzero(mask)
                markerIdx = finiteIdx[::markEvery] if markEvery else finiteIdx
                (line,) = axTarget.plot(
                    x, y,
                    label=label,
                    color=color,
                    linewidth=1.4,
                    marker='o',
                    markersize=markerSize,
                    markevery=markerIdx.tolist() if markerIdx.size else None,
                    picker=5,
                )
                yTexts = None
                if texts is not None:
                    try:
                        yTexts = [texts[i] for i, keep in enumerate(mask) if keep]
                    except Exception:
                        yTexts = None
                self._lineData.append({
                    'line': line,
                    'label': label,
                    'xs': np.asarray(x[mask], dtype=float),
                    'ys': np.asarray(y[mask], dtype=float),
                    'yTexts': yTexts,
                    'color': color,
                    'visible': True,
                    'axisIndex': axisIndex,
                })
            ylabelColor = colorCycle[min(axisIndex, len(colorCycle) - 1)]
            if axisIndex == 0:
                yLabel = 'Value'
            elif axisIndex == 1:
                yLabel = 'Value (right)'
            else:
                yLabel = f'Value ({axisIndex + 1})'
            axTarget.set_ylabel(yLabel, color=ylabelColor)

        # Primary axis
        plotGroup(ax, axisGroups[0] if axisGroups else [], axisIndex=0)

        # Extra axes via twinx; offset spines for 3rd+ axes on the right
        for axisIndex in range(1, nAxes):
            twin = ax.twinx()
            if axisIndex > 1:
                try:
                    twin.spines['right'].set_position(
                        ('outward', 55 * (axisIndex - 1))
                    )
                except Exception:
                    pass
            self._yAxes.append(twin)
            if axisIndex == 1:
                self._ax2 = twin
            plotGroup(
                twin,
                axisGroups[axisIndex] if axisIndex < len(axisGroups) else [],
                axisIndex=axisIndex,
            )

        if len(self._yAxes) > 1:
            self._applyTheme(fig, ax, *self._yAxes[1:])

        if useDatetime:
            ax.xaxis_date()
            ax.xaxis.set_major_formatter(mdates.DateFormatter(self._tsDisplayFmt))
            for tickLabel in ax.get_xticklabels():
                tickLabel.set_rotation(30)
                tickLabel.set_horizontalalignment('right')
            ax.set_xlabel('Timestamp')
        else:
            ax.set_xlabel('Row')

        # Keep absolute Y values when zoomed (no 0.4–0.8 offset of 1040.x elev)
        for yax in self._yAxes:
            self._disableAxisOffset(yax)

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
        try:
            self._lastXLim = tuple(self._ax.get_xlim())
        except Exception:
            self._lastXLim = None
        # Initial full-range marker density; updates again on zoom/pan
        self._refreshMarkerDensity(draw=False)

        self._hoverCid = self.canvas.mpl_connect('motion_notify_event', self._onMotion)
        self._keyCid = self.canvas.mpl_connect('key_press_event', self._onKeyPress)
        # Legend toggles use button_press (not pick_event): zoom/pan holds widgetlock
        # which disables Figure.pick, so pick_event never fires while Zoom is default-on.
        self._pressCid = self.canvas.mpl_connect('button_press_event', self._onButtonPress)
        self._releaseCid = self.canvas.mpl_connect('button_release_event', self._onButtonRelease)
        # Clamp toolbar pan/zoom navigation as well
        try:
            self._ax.callbacks.connect('xlim_changed', self._onAxisLimitsChanged)
            for yax in self._yAxes:
                if yax is not None:
                    yax.callbacks.connect('ylim_changed', self._onAxisLimitsChanged)
        except Exception:
            pass
        self.canvas.setFocus()

        self.canvas.draw_idle()

        note = ''
        if warnings:
            note = ' '.join(warnings)
        if Config.debug:
            groupSizes = [len(g) for g in axisGroups]
            Logic.logMessage(
                "DEBUG",
                f"GraphPanel.plotFromTable: {nAxes} Y-axis group(s) sizes={groupSizes}, "
                f"series={len(self._lineData)}, rows={n}, datetime={useDatetime}, "
                f"theme={theme}, tsFmt={self._tsDisplayFmt!r}",
            )
        return True, note

    def eventFilter(self, obj, event):
        """Ctrl + mouse wheel zooms the time axis toward the pointer."""
        if (
            obj is self.canvas
            and event is not None
            and event.type() == QEvent.Type.Wheel
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            if self._zoomXFromWheel(event):
                return True
        return super().eventFilter(obj, event)

    def _wheelDataX(self, qevent):
        """X data coordinate under the wheel pointer, or None."""
        if self._ax is None or self.canvas is None or qevent is None:
            return None
        try:
            pos = qevent.position()
            if hasattr(self.canvas, 'mouseEventCoords'):
                xdisp, ydisp = self.canvas.mouseEventCoords(pos)
            else:
                xdisp = float(pos.x())
                height = float(self.canvas.height())
                ydisp = height - float(pos.y())
            inv = self._ax.transData.inverted()
            xdata, _ydata = inv.transform((xdisp, ydisp))
            return float(xdata)
        except Exception:
            return None

    def _zoomXFromWheel(self, qevent):
        """Zoom X around the cursor. Y refits via xlim_changed autoscale."""
        if self._ax is None or self.canvas is None:
            return False
        delta = 0
        try:
            delta = int(qevent.angleDelta().y())
        except Exception:
            pass
        if delta == 0:
            try:
                delta = int(qevent.pixelDelta().y())
            except Exception:
                pass
        if delta == 0:
            return False
        factor = 0.85 if delta > 0 else (1.0 / 0.85)
        try:
            x0, x1 = self._ax.get_xlim()
        except Exception:
            return False
        span = x1 - x0
        if not np.isfinite(span) or span == 0:
            return False
        xdata = self._wheelDataX(qevent)
        if xdata is None or not np.isfinite(xdata):
            xdata = (x0 + x1) / 2.0
        rel = (xdata - x0) / span
        if not np.isfinite(rel):
            rel = 0.5
        rel = min(max(float(rel), 0.0), 1.0)
        newSpan = span * factor
        dataLim = self._xDataLim
        if dataLim is not None:
            d0, d1 = dataLim
            if d1 < d0:
                d0, d1 = d1, d0
            dataSpan = d1 - d0
            if np.isfinite(dataSpan) and dataSpan > 0:
                if newSpan >= dataSpan:
                    nx0, nx1 = d0, d1
                else:
                    nx0 = xdata - rel * newSpan
                    nx1 = nx0 + newSpan
                    if nx0 < d0:
                        nx0, nx1 = d0, d0 + newSpan
                    if nx1 > d1:
                        nx1, nx0 = d1, d1 - newSpan
            else:
                nx0 = xdata - rel * newSpan
                nx1 = nx0 + newSpan
        else:
            nx0 = xdata - rel * newSpan
            nx1 = nx0 + newSpan
        if abs(nx1 - nx0) <= 0 or not (np.isfinite(nx0) and np.isfinite(nx1)):
            return False
        try:
            if self.toolbar is not None and hasattr(self.toolbar, 'push_current'):
                self.toolbar.push_current()
        except Exception:
            pass
        self._ax.set_xlim(nx0, nx1)
        return True

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

    def _markerEveryForCount(self, nPts):
        """How often to place a marker for nPts points in the current view."""
        nPts = int(nPts or 0)
        if nPts <= 5000:
            return 1
        if nPts <= 30000:
            return max(1, nPts // 4000)
        return max(1, nPts // 3000)

    def _markerSizeForCount(self, nPts):
        nPts = int(nPts or 0)
        if nPts <= 1000:
            return 3.5
        if nPts <= 5000:
            return 2.8
        if nPts <= 30000:
            return 2.2
        return 1.8

    def _refreshMarkerDensity(self, draw=True):
        """
        Recompute markevery from points visible in the current X range.

        Full-year 1-minute series thins when zoomed out; zooming into a day
        marks every minute instead of looking randomly sparse.
        """
        if self._updatingMarkers or self._ax is None or not self._lineData:
            return False
        try:
            x0, x1 = self._ax.get_xlim()
        except Exception:
            return False
        if x1 < x0:
            x0, x1 = x1, x0

        self._updatingMarkers = True
        changed = False
        try:
            for entry in self._lineData:
                line = entry.get('line')
                if line is None:
                    continue
                try:
                    xs = np.asarray(line.get_xdata(), dtype=float)
                    ys = np.asarray(line.get_ydata(), dtype=float)
                except Exception:
                    xs = np.asarray(entry.get('xs'), dtype=float) if entry.get('xs') is not None else None
                    ys = None
                if xs is None or xs.size == 0:
                    continue
                finite = np.isfinite(xs)
                if ys is not None and ys.size == xs.size:
                    finite = finite & np.isfinite(ys)
                inView = finite & (xs >= x0) & (xs <= x1)
                nVis = int(np.count_nonzero(inView))
                if nVis <= 0:
                    me = self._markerEveryForCount(int(np.count_nonzero(finite)) or xs.size)
                    idxs = np.flatnonzero(finite)[::me]
                else:
                    me = self._markerEveryForCount(nVis)
                    idxs = np.flatnonzero(inView)[::me]
                markEvery = idxs.tolist() if idxs.size else None
                try:
                    prev = line.get_markevery()
                except Exception:
                    prev = object()
                if markEvery != prev:
                    try:
                        line.set_markevery(markEvery)
                        line.set_markersize(self._markerSizeForCount(nVis or xs.size))
                        changed = True
                    except Exception as e:
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"_refreshMarkerDensity set: {e}")
        finally:
            self._updatingMarkers = False

        if changed and draw and self.canvas is not None:
            try:
                self.canvas.draw_idle()
            except Exception:
                pass
        return changed

    def _onAxisLimitsChanged(self, ax):
        """Keep toolbar pan/zoom from leaving the timeseries range; refresh markers."""
        if self._clamping or self._updatingMarkers or self._autoscalingY:
            return
        self._clampView()
        # When X moves (zoom / horizontal pan), refit Y to points still in view so
        # off-screen outliers (e.g. -99999) no longer dominate the scale.
        try:
            curX = tuple(self._ax.get_xlim()) if self._ax is not None else None
        except Exception:
            curX = None
        if curX is not None and curX != self._lastXLim:
            self._lastXLim = curX
            self._scheduleAutoscaleY()
        self._refreshMarkerDensity(draw=True)

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

    def _panLimitsClamped(self, cur0, cur1, dataLim, delta):
        """Return (new0, new1, changed) after applying delta and clamping to dataLim."""
        if dataLim is None:
            return cur0 + delta, cur1 + delta, abs(delta) > 0
        d0, d1 = dataLim
        if d1 < d0:
            d0, d1 = d1, d0
        dataSpan = d1 - d0
        viewSpan = cur1 - cur0
        if viewSpan < 0:
            cur0, cur1 = cur1, cur0
            viewSpan = -viewSpan
        tol = max(abs(dataSpan) * 1e-12, 1e-15) if np.isfinite(dataSpan) else 1e-15
        # Fully zoomed out: pan is a no-op (avoids snap-back redraw / "resize")
        if np.isfinite(dataSpan) and viewSpan >= dataSpan - tol:
            return cur0, cur1, False
        new0 = cur0 + delta
        new1 = cur1 + delta
        if new0 < d0:
            new0 = d0
            new1 = d0 + viewSpan
        if new1 > d1:
            new1 = d1
            new0 = d1 - viewSpan
        changed = abs(new0 - cur0) > tol or abs(new1 - cur1) > tol
        return new0, new1, changed

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
            nx0, nx1, xCh = self._panLimitsClamped(x0, x1, self._xDataLim, dx)
            ny0, ny1, yCh = self._panLimitsClamped(y0, y1, self._yDataLim, dy)
            changed = xCh or yCh
            if xCh:
                self._ax.set_xlim(nx0, nx1)
            if yCh:
                self._ax.set_ylim(ny0, ny1)
            # Proportional Y pan on every twin axis
            if yCh:
                axes = self._yAxes or [self._ax]
                lims = self._yDataLims or []
                span1 = (y1 - y0) if (y1 - y0) != 0 else 1.0
                for i, yax in enumerate(axes):
                    if i == 0 or yax is None:
                        continue
                    try:
                        y20, y21 = yax.get_ylim()
                    except Exception:
                        continue
                    spanI = y21 - y20
                    dyI = dy * (spanI / span1) if span1 else 0.0
                    limI = lims[i] if i < len(lims) else None
                    if limI is None and i == 1:
                        limI = self._y2DataLim
                    n20, n21, yICh = self._panLimitsClamped(y20, y21, limI, dyI)
                    if yICh:
                        yax.set_ylim(n20, n21)
                        changed = True
        except Exception:
            return
        self._midPan = (curPx, curPy)
        if changed:
            self.canvas.draw_idle()

    def _handleArrowPan(self, qtKey):
        """
        Pan current view by ~12% of visible range.
        Left/Right → X; Up/Down → Y (all axes when multi-axis).
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
        changed = False

        def _panAllY(direction):
            """direction: +1 up, -1 down."""
            nonlocal changed
            axes = self._yAxes or [self._ax]
            lims = self._yDataLims or []
            for i, yax in enumerate(axes):
                if yax is None:
                    continue
                try:
                    ya0, ya1 = yax.get_ylim()
                except Exception:
                    continue
                dYi = (ya1 - ya0) * frac * direction
                limI = lims[i] if i < len(lims) else None
                if limI is None and i == 0:
                    limI = self._yDataLim
                if limI is None and i == 1:
                    limI = self._y2DataLim
                n0, n1, ch = self._panLimitsClamped(ya0, ya1, limI, dYi)
                if ch:
                    yax.set_ylim(n0, n1)
                    changed = True

        if key == Qt.Key.Key_Left:
            nx0, nx1, ch = self._panLimitsClamped(x0, x1, self._xDataLim, -dx)
            if ch:
                self._ax.set_xlim(nx0, nx1)
                changed = True
        elif key == Qt.Key.Key_Right:
            nx0, nx1, ch = self._panLimitsClamped(x0, x1, self._xDataLim, dx)
            if ch:
                self._ax.set_xlim(nx0, nx1)
                changed = True
        elif key == Qt.Key.Key_Up:
            _panAllY(+1)
        elif key == Qt.Key.Key_Down:
            _panAllY(-1)
        else:
            return False

        if not changed:
            return True  # consumed key; nothing to redraw
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

        best = None  # (dist2_px, x, y, label, displayText)

        for entry in self._lineData:
            line = entry.get('line')
            if line is None or not line.get_visible():
                continue
            xs = entry.get('xs')
            ys = entry.get('ys')
            yTexts = entry.get('yTexts')
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
                    disp = ''
                    if yTexts is not None and 0 <= i < len(yTexts):
                        disp = yTexts[i] or ''
                    best = (dist2, float(xs[i]), float(ys[i]), label, disp)
            except Exception:
                continue

        if best is None:
            if self._lastTipKey is not None:
                QToolTip.hideText()
                self._lastTipKey = None
            return

        _dist, px, py, label, disp = best
        tsStr = self._formatXForTooltip(px)
        # Table/overlay display string so raw mode is not .4g-rounded.
        # Axis ticks stay matplotlib-plain (no 7-decimal labels).
        if disp:
            valStr = disp
        else:
            try:
                valStr = Logic.formatRawNumber(py) if Config.rawData else Logic.valuePrecision(py)
            except Exception:
                valStr = str(py)

        tip = f"{label}\n{tsStr}\n{valStr}"
        tipKey = (label, round(px, 6), round(py, 6))
        # Avoid re-showing the same tip every motion event (flicker)
        if tipKey != self._lastTipKey:
            self._lastTipKey = tipKey
            QToolTip.showText(QCursor.pos(), tip, self.canvas)
