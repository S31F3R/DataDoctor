# Release notes

Each GitHub Release body is the markdown file named after the tag:

```
documentation/releases/v3.0.0-rc.2.1.md
documentation/releases/v3.0.0.md
```

During development, write bullets in `documentation/Working Notes.txt` (bug fixes, GitHub issue numbers, features/TASKS). Copy them here into the versioned file before publishing.

`python scripts/publishRelease.py` uses the versioned file as the GitHub Release body. If that file is missing, it seeds from Working Notes, then clears Working Notes. Edit the versioned file and run publish again (`--skip-build --upload`) to update notes on an existing tag.

Older tags stay on GitHub until someone deletes that Release on the website. Publishing a newer RC does not remove the previous one.
