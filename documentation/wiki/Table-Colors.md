# Table colors

Data Query uses these colors for QAQC, overlay, delta, and pending upload. **Options → Appearance** shows the same swatches (the real colors, not names). Double-click a color to change it; **Restore Defaults** puts them back.

These are the defaults (GitHub wiki cannot follow your custom palette):

| Meaning | Color | When |
|---------|-------|------|
| Missing data | <span style="background:#64C3F7;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Empty cell whose timestamp is now or earlier (QAQC). Also HDB `r_base` fallback. |
| Below expected min | <span style="background:#F9F06B;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Value &lt; `expectedMin` |
| Above expected max | <span style="background:#F9C211;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Value &gt; `expectedMax` |
| Below cutoff min | <span style="background:#FFA348;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Value &lt; `cuttoffMin` |
| Above cutoff max | <span style="background:#C01C28;color:#FFF;padding:2px 14px;border:1px solid #888">Aa</span> | Value &gt; `cutoffMax` |
| Rate of change | <span style="background:#F66151;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Adjacent-step change &gt; `rateOfChange` |
| Consecutive equal | <span style="background:#57E389;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Two adjacent values are equal |
| Delta positive | <span style="background:#222;color:#FFA500;padding:2px 14px;border:1px solid #888">Aa</span> | Delta column &gt; 0 |
| Delta negative | <span style="background:#222;color:#44A5FF;padding:2px 14px;border:1px solid #888">Aa</span> | Delta column &lt; 0 |
| Overlay differs | <span style="background:#222;color:#FF0000;padding:2px 14px;border:1px solid #888">Aa</span> | Overlay pair both present but not equal |
| Overlay secondary only | <span style="background:#DDA0DD;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Secondary has a value, primary does not (auto-marked for upload) |
| Overlay primary only | <span style="background:#FFB6C1;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> | Primary has a value, secondary does not |
| Pending edit / upload | <span style="background:#C2185B;color:#FFF;padding:2px 14px;border:1px solid #888">Aa</span> | User edit or overlay fill waiting to upload |
| Uploaded this session | <span style="background:#00695C;color:#FFF;padding:2px 14px;border:1px solid #888">Aa</span> | Write succeeded this session |

Delta columns skip QAQC (they use the +/− text colors only). Matching overlay values keep QAQC colors.

If you change **Color Theme**, the table in Options still shows the colors the query table uses. Defaults are the same in light and dark unless you customize them.
