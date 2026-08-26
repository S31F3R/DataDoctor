# Report.py
# Open a GitHub issue from the app without shipping a token.
# User logs in in the browser (they need a GitHub account).

from __future__ import annotations

import os
import platform
import sys
import traceback
import urllib.parse
import webbrowser
from pathlib import Path

from core import Logic, Utils, Version

REPO = Version.GITHUB_REPO
# Keep the URL under typical browser limits; full log stays on disk / clipboard.
_MAX_LOG_CHARS = 3500
# GitHub + login?return_to doubles the URL. Long body= query strings 500 with
# "Whoops, something went wrong!". Keep the opened URL short.
_MAX_URL_CHARS = 1800
_lastOpenIssue = (0.0, "")


def logPath() -> str:
    return Utils.getLogPath("app.log")


def logTail(maxChars: int = _MAX_LOG_CHARS) -> str:
    path = logPath()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return ""
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= maxChars:
        return text
    return text[-maxChars:]


def issueBody(kind: str, summary: str = "", extra: str = "") -> str:
    """Markdown body for issues/new?body= (issue forms ignore this)."""
    lines = [
        f"**Kind:** {kind}",
        f"**Version:** {Version.displayVersion()}",
        f"**OS:** {platform.system()} {platform.release()} ({platform.machine()})",
        f"**Python:** {sys.version.split()[0]}",
        "",
        "## What happened",
        "",
        summary or "_describe it here_",
        "",
    ]
    if extra:
        lines.extend([extra.rstrip(), ""])
    tail = logTail()
    if tail:
        lines.extend([
            "## app.log (tail)",
            "",
            "```",
            tail,
            "```",
            "",
        ])
    else:
        lines.extend(["## app.log", "", "_no log tail available_", ""])
    return "\n".join(lines)


def issueUrl(title: str, body: str, template: str | None = None) -> str:
    """
    Build issues/new URL.

    GitHub issue *forms* (template=*.yml) ignore body= and combining them
    can 500. Huge body= query strings also 500 ("Whoops, something went
    wrong!") after login redirects. Prefer a short title-only (or form)
    URL and put the full markdown on the clipboard.
    """
    shortTitle = (title or "Data Doctor issue")[:120]
    if template:
        q = {"title": shortTitle, "template": template}
        return f"https://github.com/{REPO}/issues/new?{urllib.parse.urlencode(q)}"

    base = f"https://github.com/{REPO}/issues/new"
    titleOnly = base + "?" + urllib.parse.urlencode({"title": shortTitle})
    if not body:
        return titleOnly
    withBody = base + "?" + urllib.parse.urlencode({"title": shortTitle, "body": body})
    if len(withBody) <= _MAX_URL_CHARS:
        return withBody
    return titleOnly


def openIssue(title: str, body: str, template: str | None = None) -> str:
    """Open GitHub issues/new. Debounced so one crash cannot open two tabs."""
    import time

    global _lastOpenIssue
    url = issueUrl(title, body, template=template)
    now = time.time()
    lastT, lastUrl = _lastOpenIssue
    if lastUrl == url and (now - lastT) < 4.0:
        Logic.logMessage("DEBUG", "Report.openIssue: skipped duplicate open")
        return url
    _lastOpenIssue = (now, url)
    try:
        webbrowser.open(url)
    except Exception as e:
        Logic.logMessage("WARN", f"Report.openIssue: {e}")
    return url


def openLogFolder() -> str | None:
    folder = Utils.getLogDir()
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass
    try:
        webbrowser.open(Path(folder).resolve().as_uri())
        return folder
    except Exception as e:
        Logic.logMessage("WARN", f"Report.openLogFolder: {e}")
        return folder


def copyToClipboard(text: str) -> bool:
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        app.clipboard().setText(text)
        return True
    except Exception:
        return False


def crashTitle(excType, excValue) -> str:
    name = getattr(excType, "__name__", "Error")
    msg = str(excValue or "").strip().splitlines()[0] if excValue else ""
    if msg:
        return f"Crash: {name}: {msg}"[:120]
    return f"Crash: {name}"


def crashBody(excType, excValue, excTb) -> str:
    tbText = ""
    try:
        tbText = "".join(traceback.format_exception(excType, excValue, excTb)).rstrip()
    except Exception:
        tbText = f"{excType}: {excValue}"
    extra = ""
    if tbText:
        extra = "## Traceback\n\n```\n" + tbText[:3000] + "\n```"
    return issueBody("crash", summary=f"{excType.__name__}: {excValue}", extra=extra)


def showCrashDialog(excType, excValue, excTb) -> None:
    """QMessageBox with Report / Copy log / Open log. No extra Options UI."""
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app is None:
        return
    if getattr(app, "dataDoctorShowingErrorDialog", False):
        return
    app.dataDoctorShowingErrorDialog = True
    try:
        box = QMessageBox(None)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Unexpected Error")
        box.setText(
            "An unexpected error occurred and was logged.\n\n"
            f"{excType.__name__}: {excValue}\n\n"
            "The application will continue if possible."
        )
        box.setInformativeText("See app.log, or report it on GitHub (needs a GitHub account).")
        reportBtn = box.addButton("Report on GitHub", QMessageBox.ButtonRole.ActionRole)
        copyBtn = box.addButton("Copy log", QMessageBox.ButtonRole.ActionRole)
        folderBtn = box.addButton("Open log folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(box.button(QMessageBox.StandardButton.Ok))
        box.exec()
        clicked = box.clickedButton()
        if clicked is reportBtn:
            # Full details on the clipboard. URL is a short crash form — a
            # body= URL with the log tail was hitting GitHub "Whoops".
            body = crashBody(excType, excValue, excTb)
            copied = copyToClipboard(body)
            openIssue(crashTitle(excType, excValue), "", template="crash.yml")
            extra = QMessageBox(None)
            extra.setIcon(QMessageBox.Icon.Information)
            extra.setWindowTitle("Report on GitHub")
            extra.setText(
                "GitHub opened in your browser. You need a GitHub account.\n\n"
                + (
                    "The full crash report was copied to the clipboard — "
                    "paste it into the issue form."
                    if copied
                    else "Paste the traceback from app.log into the issue form."
                )
            )
            extra.addButton(QMessageBox.StandardButton.Ok)
            extra.exec()
        elif clicked is copyBtn:
            tail = logTail(8000)
            copyToClipboard(tail or "(app.log empty or missing)")
        elif clicked is folderBtn:
            openLogFolder()
    finally:
        app.dataDoctorShowingErrorDialog = False


def showManualReportDialog(parent=None) -> None:
    from PyQt6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Report an issue")
    box.setText(
        "This opens GitHub in your browser. You need a GitHub account.\n"
        "Log in there if asked — Data Doctor does not store GitHub passwords."
    )
    reportBtn = box.addButton("Open GitHub", QMessageBox.ButtonRole.AcceptRole)
    copyBtn = box.addButton("Copy log", QMessageBox.ButtonRole.ActionRole)
    folderBtn = box.addButton("Open log folder", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is reportBtn:
        # Issue form (bug.yml) — do not also send body=; forms ignore it.
        url = f"https://github.com/{REPO}/issues/new?template=bug.yml"
        try:
            webbrowser.open(url)
        except Exception as e:
            Logic.logMessage("WARN", f"Report.openIssue: {e}")
    elif clicked is copyBtn:
        copyToClipboard(logTail(8000) or "(app.log empty or missing)")
    elif clicked is folderBtn:
        openLogFolder()
