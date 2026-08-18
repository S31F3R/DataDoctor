# Release notes

Each GitHub Release body is the markdown file named after the tag:

```
documentation/releases/v3.0.0-rc.2.1.md
documentation/releases/v3.0.0.md
```

`python scripts/publishRelease.py` creates a stub if the file is missing, then uses it as the Release notes. Edit the file and run publish again (`--skip-build --upload`) to update notes on an existing tag.

Older tags stay on GitHub until someone deletes that Release on the website. Publishing a newer RC does not remove the previous one.
