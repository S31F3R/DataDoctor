# uiGraph.py
# Graph tab: plot mainTable series with zoom toolbar and dual Y-axis when scales differ.
# Supports dark/light system palette, hover tooltips, table timestamp formats, overlay pairs.

from __future__ import annotations
import re
from datetime import datetime
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget, QSizePolicy, QLabel
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


def headerLabel(table, col):
    """Single-line legend label from multi-line table header."""
    item = table.horizontalHeaderItem(col) if table is not None else None
    if item is None:
        return f"Col {col + 1}"
    text = (item.text() or '').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text or f"Col {col + 1}"


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


def _overlaySeriesFromColumn(table, col, baseLabel):
    """
    For overlay columns, return [(primaryLabel, vals), (secondaryLabel, vals)]
    from per-cell UserRole primaryVal / secondaryVal. Empty list if not overlay data.
    """
    if table is None or table.rowCount() <= 0:
        return []
    nRows = table.rowCount()
    primary = np.full(nRows, np.nan)
    secondary = np.full(nRows, np.nan)
    hasAny = False
    for r in range(nRows):
        item = table.item(r, col)
        if item is None:
            continue
        role = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(role, dict) or not role.get('overlay'):
            continue
        hasAny = True
        primary[r] = parseNumeric(role.get('primaryVal', ''))
        secondary[r] = parseNumeric(role.get('secondaryVal', ''))

    if not hasAny:
        return []

    # Prefer short labels from role dataIds when present
    pId = sId = None
    for r in range(nRows):
        item = table.item(r, col)
        if item is None:
            continue
        role = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(role, dict) and role.get('overlay'):
            pId = role.get('dataId1') or pId
            sId = role.get('dataId2') or sId
            if pId and sId:
                break

    pLabel = f"{baseLabel} (primary)" if not pId else f"{pId} (primary)"
    sLabel = f"{baseLabel} (secondary)" if not sId else f"{sId} (secondary)"
    out = []
    if np.any(np.isfinite(primary)):
        out.append((pLabel, primary))
    if np.any(np.isfinite(secondary)):
        out.append((sLabel, secondary))
    return out


def extractSeries(table, columns=None, columnMetadata=None):
    """
    Read timestamps + numeric series from mainTable.

    Overlay columns expand to primary + secondary series (UserRole values).

    Returns (timestamps list[datetime|None], tsTexts list[str], series list[(label, values)], warnings)
    """
    warnings = []
    if table is None or table.rowCount() <= 0 or table.columnCount() <= 0:
        return [], [], [], ["No data in the Data Query table to graph."]

    if columns is None:
        columns = selectedDataColumns(table)
    if not columns:
        return [], [], [], ["No columns available to graph."]

    nRows = table.rowCount()
    timestamps = []
    tsTexts = []
    for r in range(nRows):
        vh = table.verticalHeaderItem(r)
        tsText = vh.text() if vh is not None else ''
        tsTexts.append(tsText)
        dt, _fmt = parseTimestamp(tsText)
        timestamps.append(dt)

    # If almost no timestamps parsed, use row index as X
    parsedCount = sum(1 for t in timestamps if t is not None)
    useDatetime = parsedCount >= max(2, int(nRows * 0.5))
    if not useDatetime:
        warnings.append("Could not parse most timestamps; using row index on the X axis.")

    metaList = columnMetadata if columnMetadata is not None else []
    series = []
    for c in columns:
        label = headerLabel(table, c)
        meta = metaList[c] if c < len(metaList) else {}
        colType = (meta.get('type') if isinstance(meta, dict) else None) or ''

        # Overlay column: graph primary + secondary (not the merged cell alone)
        if colType == 'overlay':
            overlaySeries = _overlaySeriesFromColumn(table, c, label)
            if overlaySeries:
                series.extend(overlaySeries)
                continue
            # Fall through if role data missing

        # Also try overlay detection from cell roles even without metadata
        if not colType or colType == 'normal':
            sample = table.item(0, c) if nRows > 0 else None
            role0 = sample.data(Qt.ItemDataRole.UserRole) if sample is not None else None
            if isinstance(role0, dict) and role0.get('overlay'):
                overlaySeries = _overlaySeriesFromColumn(table, c, label)
                if overlaySeries:
                    series.extend(overlaySeries)
                    continue

        vals = np.empty(nRows, dtype=float)
        for r in range(nRows):
            item = table.item(r, c)
            vals[r] = parseNumeric(item.text() if item is not None else '')
        if not np.any(np.isfinite(vals)):
            warnings.append(f"Skipped '{label}' (no numeric values).")
            continue
        series.append((label, vals))

    if not series:
        return timestamps, tsTexts, [], ["No numeric series found to graph."]
    return timestamps, tsTexts, series, warnings


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
        self._hoverCid = None
        self._annot = None
        self._lineData = []  # list of (line, label, x_arr, y_arr, useDatetime, tsFmt)
        self._tsDisplayFmt = '%m/%d/%y %H:%M:00'
        self._useDatetime = False

    def clearPlot(self):
        if self.canvas is not None:
            if self._hoverCid is not None and self.canvas is not None:
                try:
                    self.canvas.mpl_disconnect(self._hoverCid)
                except Exception:
                    pass
                self._hoverCid = None
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
            self._annot = None
            self._lineData = []
        if self._placeholder is not None:
            self._placeholder.show()

    def _applyToolbarTooltips(self):
        """Ensure matplotlib nav toolbar buttons have clear tooltips."""
        if self.toolbar is None:
            return
        # Map common action texts / tooltips to short labels
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
                # matplotlib often uses text like "home" or icons with tooltip already
                for k, v in tipMap.items():
                    if k.lower() in key.lower() or k.lower() in tip.lower():
                        action.setToolTip(v)
                        break
                if not action.toolTip():
                    if text:
                        action.setToolTip(text)
            # Also set on child QToolButtons if present
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
            gridAlpha = 0.25
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

        # Light (default matplotlib-ish, slightly cleaned)
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

    def plotFromTable(self, table, columns=None, columnMetadata=None):
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

        # Pull columnMetadata from main window if not passed
        if columnMetadata is None and table is not None:
            parent = table.window() if hasattr(table, 'window') else None
            if parent is not None:
                columnMetadata = getattr(parent, 'columnMetadata', None)

        timestamps, tsTexts, series, warnings = extractSeries(
            table, columns, columnMetadata=columnMetadata
        )
        if not series:
            msg = warnings[0] if warnings else "Nothing to graph."
            return False, msg

        # Tear down previous figure
        self.clearPlot()
        if self._placeholder is not None:
            self._placeholder.hide()

        fig = Figure(figsize=(8, 5), tight_layout=True)
        self.figure = fig
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setObjectName('graphToolbar')
        self._applyToolbarTooltips()

        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.canvas, stretch=1)

        ax = fig.add_subplot(111)
        self._ax = ax
        self._ax2 = None

        theme = self._applyTheme(fig, ax)
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
        lines = []
        self._lineData = []
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
                    picker=5,
                )
                lines.append(line)
                self._lineData.append((
                    line, label,
                    np.asarray(x[mask], dtype=float),
                    np.asarray(y[mask], dtype=float),
                ))
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
            # Match Data Query vertical header format exactly
            ax.xaxis.set_major_formatter(mdates.DateFormatter(self._tsDisplayFmt))
            fig.autofmt_xdate()
            ax.set_xlabel('Timestamp')
        else:
            ax.set_xlabel('Row')

        # Title intentionally blank (user request)
        ax.set_title('')

        # Combined legend
        labels = [ln.get_label() for ln in lines]
        if lines:
            legend = ax.legend(lines, labels, loc='best', fontsize=8)
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

        gridColor = '#666666' if theme in ('dark', 'retro') else None
        if gridColor:
            ax.grid(True, alpha=0.3, color=gridColor)
        else:
            ax.grid(True, alpha=0.3)

        # Hover tooltip for data points
        self._annot = ax.annotate(
            '',
            xy=(0, 0),
            xytext=(12, 12),
            textcoords='offset points',
            bbox=dict(
                boxstyle='round',
                fc=('#333333' if theme in ('dark', 'retro') else '#ffffe0'),
                ec=('#aaaaaa' if theme in ('dark', 'retro') else '#888888'),
                alpha=0.92,
            ),
            color=('#e0e0e0' if theme in ('dark', 'retro') else '#000000'),
            fontsize=9,
            visible=False,
            zorder=20,
        )
        self._hoverCid = self.canvas.mpl_connect('motion_notify_event', self._onHover)

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

    def _formatXForTooltip(self, xVal):
        """Format x coordinate using the same table timestamp format when possible."""
        if self._useDatetime and mdates is not None:
            try:
                dt = mdates.num2date(xVal)
                # num2date may be timezone-aware; strip for strftime parity with table
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
        """Show tooltip near the nearest data point under the cursor."""
        if self._annot is None or self.canvas is None or not self._lineData:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            if self._annot.get_visible():
                self._annot.set_visible(False)
                self.canvas.draw_idle()
            return

        # Find nearest point across all lines (in display coords for fair distance)
        best = None  # (dist2, x, y, label, axes)

        for line, label, xs, ys in self._lineData:
            if xs.size == 0:
                continue
            # Only consider lines on the hovered axes (or always if dual)
            if line.axes is not event.inaxes and self._ax2 is not None:
                # Allow hover on either axis
                pass
            # Distance in data space scaled roughly by axis span
            try:
                xspan = max(float(np.nanmax(xs) - np.nanmin(xs)), 1e-12)
                yspan = max(float(np.nanmax(ys) - np.nanmin(ys)), 1e-12)
            except Exception:
                xspan, yspan = 1.0, 1.0
            dx = (xs - event.xdata) / xspan
            # Map y to hovered axes if possible
            if line.axes is event.inaxes:
                dy = (ys - event.ydata) / yspan
            else:
                # Cross-axis: use display coords for y comparison
                try:
                    pts = line.axes.transData.transform(np.column_stack([xs, ys]))
                    mouse = np.array([event.x, event.y], dtype=float)
                    d2 = (pts[:, 0] - mouse[0]) ** 2 + (pts[:, 1] - mouse[1]) ** 2
                    i = int(np.argmin(d2))
                    dist2 = float(d2[i])
                    # Threshold ~12 px
                    if dist2 < 144 and (best is None or dist2 < best[0]):
                        best = (dist2, float(xs[i]), float(ys[i]), label, line.axes)
                    continue
                except Exception:
                    dy = (ys - event.ydata) / yspan
            d2 = dx * dx + dy * dy
            i = int(np.argmin(d2))
            dist2 = float(d2[i])
            # ~2% of data span
            if dist2 < 0.0004 and (best is None or dist2 < best[0]):
                best = (dist2, float(xs[i]), float(ys[i]), label, line.axes)

        if best is None:
            if self._annot.get_visible():
                self._annot.set_visible(False)
                self.canvas.draw_idle()
            return

        _dist, px, py, label, axTarget = best
        # Annotate on the axes that owns the point
        if self._annot.axes is not axTarget:
            # Move annotation to the correct axes
            try:
                self._annot.remove()
            except Exception:
                pass
            self._annot = axTarget.annotate(
                '',
                xy=(0, 0),
                xytext=(12, 12),
                textcoords='offset points',
                bbox=dict(boxstyle='round', fc='#ffffe0', ec='#888888', alpha=0.92),
                fontsize=9,
                visible=False,
                zorder=20,
            )
        tsStr = self._formatXForTooltip(px)
        # Format value cleanly
        try:
            if abs(py) >= 1000 or (abs(py) > 0 and abs(py) < 0.01):
                valStr = f"{py:g}"
            else:
                valStr = f"{py:.4g}"
        except Exception:
            valStr = str(py)

        self._annot.xy = (px, py)
        self._annot.set_text(f"{label}\n{tsStr}\n{valStr}")
        self._annot.set_visible(True)
        self.canvas.draw_idle()
