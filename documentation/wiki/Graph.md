# Graph

The **Graph** button plots the Data Query table into a Graph tab (or a detached window). You can also **Graph** from a header or cell context menu — header Graph uses **all selected columns**, not only the one you right-clicked.

## Tools

- Graph opens with the **Zoom** tool active.
- **Middle-mouse** pans. Arrow keys also pan. The view stays clamped to the data range.
- Legend click toggles a series (`☑` / `☐`) and rescales. That does **not** reset X zoom.
- Multiple Y axes when series live on different value bands. Hide an axis from the legend the same way.
- Y scale fits data in the **current X view** (an off-screen outlier should not squash the visible range). Zoomed Y stays in **absolute** values (no offset “delta scale”).
- Markers (dots) are always on and stay dense when you zoom into 1-minute data.

## Hover and colors

- Hover tooltip shows the **same text as the table cell** (raw digits when Raw data is on; rounded otherwise).
- Axis tick labels stay short — they do not dump 7 decimal places.
- Tooltip is stable at the top edge of the plot (no frame jump).
- Series colors follow system dark/light. Title is left blank on purpose.

## Overlay series

Overlay columns plot both members. Legend labels are the first header line (`commonName-datatype`), not the raw DataID.

## Save / detach

- **Save** starts in the last folder you used (`user.config`).
- Right-click the Graph **tab** → Detach. The detached window minimizes to the taskbar / dock. Attach puts it back.
- Toolbar buttons have tooltips.

## Related

[Overlay and Delta](Overlay-and-Delta) · [Querying](Querying)
