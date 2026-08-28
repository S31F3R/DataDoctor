# Release notes

Each GitHub Release body is the markdown file named after the tag:

```
documentation/releases/v3.0.0-rc.2.1.md
documentation/releases/v3.0.0.md
```

During development, write **change bullets only** in `documentation/Working Notes.txt`. That file has no version in its name because the next tag might be `v3.0.0-rc.2.4` or a full `v3.0.0`.

`python scripts/publishRelease.py` creates `documentation/releases/vVERSION.md` when the channel is chosen. It copies those bullets under `## Changes` (never a “Working Notes” heading), then resets the scratch file. If `vVERSION.md` already exists, that file is the GitHub Release body as-is (Working Notes are not re-applied).

A **published** `X.Y.Z` also folds `documentation/test.txt` **Confirmed** titles into `## Changes` when they were missed in Working Notes / that version’s rc and beta notes (and not already shipped in an older published release), then clears Confirmed. Confirmed is the bug/beta test log for the cycle that just shipped.

Edit the versioned file and run publish again (`--skip-build --upload`) to update notes on an existing tag. That re-uploads assets; to change notes only, edit the file and PATCH the GitHub Release body.

Older tags stay on GitHub until someone deletes that Release on the website. Publishing a newer RC does not remove the previous one.
