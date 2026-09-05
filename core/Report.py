# Report.py
# File a GitHub issue as the signed-in user (OAuth device flow + keyring).
# No client secret and no PAT in the shipped app.

from __future__ import annotations

import json
import os
import platform
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from core import Logic, Utils, Version

REPO = Version.GITHUB_REPO
CLIENT_ID = Version.GITHUB_OAUTH_CLIENT_ID
SCOPE = Version.GITHUB_OAUTH_SCOPE
UA = f"DataDoctor/{Version.displayVersion()} (+https://github.com/{REPO})"
MAX_LOG_CHARS = 3500
HTTP_TIMEOUT = 20
KEYRING_SERVICE = "DataDoctor"
TOKEN_KEY = "githubToken"
REFRESH_KEY = "githubRefreshToken"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
API_ROOT = "https://api.github.com"

REDACT_SECRET = re.compile(
    r"(?i)(password|passwd|pwd|api[_-]?key|secret|token|authorization)\s*[:=]\s*\S+"
)


def logPath() -> str:
    return Utils.getLogPath("app.log")


def redactSecrets(text: str) -> str:
    return REDACT_SECRET.sub(r"\1=***", text or "")


def logTail(maxChars: int = MAX_LOG_CHARS) -> str:
    path = logPath()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return ""
    text = redactSecrets(text.replace("\r\n", "\n").strip())
    if len(text) <= maxChars:
        return text
    return text[-maxChars:]


def issueBody(kind: str, summary: str = "", extra: str = "") -> str:
    """Markdown body for a GitHub issue."""
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
    msg = redactSecrets(msg)
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
        extra = "## Traceback\n\n```\n" + redactSecrets(tbText[:3000]) + "\n```"
    return issueBody("crash", summary=redactSecrets(f"{excType.__name__}: {excValue}"), extra=extra)


def readKeyring(key: str) -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, key) or ""
    except Exception as e:
        Logic.logMessage("WARN", f"Report keyring get {key}: {e}")
        return ""


def writeKeyring(key: str, value: str) -> None:
    try:
        import keyring
        if value:
            keyring.set_password(KEYRING_SERVICE, key, value)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, key)
            except Exception:
                pass
    except Exception as e:
        Logic.logMessage("WARN", f"Report keyring set {key}: {e}")


def storedGithubToken() -> str:
    return readKeyring(TOKEN_KEY)


def saveGithubTokens(accessToken: str, refreshToken: str = "") -> None:
    writeKeyring(TOKEN_KEY, accessToken or "")
    if refreshToken:
        writeKeyring(REFRESH_KEY, refreshToken)
    Logic.logMessage("INFO", "GitHub OAuth token stored in keyring")


def clearGithubTokens() -> None:
    writeKeyring(TOKEN_KEY, "")
    writeKeyring(REFRESH_KEY, "")
    Logic.logMessage("INFO", "GitHub OAuth token cleared")


def httpJson(url: str, method: str = "GET", fields=None, body=None, token: str | None = None, accept: str = "application/json"):
    headers = {
        "User-Agent": UA,
        "Accept": accept,
    }
    data = None
    if fields is not None:
        data = urllib.parse.urlencode(fields).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        errBody = ""
        try:
            errBody = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        parsed = {}
        try:
            parsed = json.loads(errBody) if errBody else {}
        except Exception:
            parsed = {"message": errBody or str(e)}
        parsed["_httpStatus"] = e.code
        raise GithubHttpError(e.code, parsed) from e


class GithubHttpError(Exception):
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = payload or {}
        msg = self.payload.get("error_description") or self.payload.get("message") or str(status)
        super().__init__(msg)


def requestDeviceCode() -> dict:
    data = httpJson(
        DEVICE_CODE_URL,
        method="POST",
        fields={"client_id": CLIENT_ID, "scope": SCOPE},
    )
    if not data.get("device_code") or not data.get("user_code"):
        err = data.get("error_description") or data.get("error") or "GitHub did not return a device code"
        raise RuntimeError(err)
    return data


def pollAccessToken(deviceCode: str) -> dict:
    return httpJson(
        ACCESS_TOKEN_URL,
        method="POST",
        fields={
            "client_id": CLIENT_ID,
            "device_code": deviceCode,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )


def refreshGithubToken() -> str:
    refresh = readKeyring(REFRESH_KEY)
    if not refresh:
        return ""
    try:
        data = httpJson(
            ACCESS_TOKEN_URL,
            method="POST",
            fields={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
        )
    except Exception as e:
        Logic.logMessage("WARN", f"GitHub token refresh failed: {e}")
        return ""
    token = data.get("access_token") or ""
    if token:
        saveGithubTokens(token, data.get("refresh_token") or refresh)
    return token


def createGithubIssue(title: str, body: str, token: str) -> dict:
    path = f"/repos/{REPO}/issues"
    payload = {"title": (title or "Data Doctor issue")[:256], "body": body or ""}
    return httpJson(
        API_ROOT + path,
        method="POST",
        body=payload,
        token=token,
        accept="application/vnd.github+json",
    )


def ensureGithubToken(parent=None) -> str:
    """Return a usable token, running device flow when none is stored."""
    token = storedGithubToken()
    if token:
        return token
    token = refreshGithubToken()
    if token:
        return token
    return runDeviceFlow(parent)


def runDeviceFlow(parent=None) -> str:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        return ""
    try:
        device = requestDeviceCode()
    except Exception as e:
        QMessageBox.warning(
            parent,
            "GitHub sign-in",
            "Could not start GitHub sign-in.\n\n"
            f"{e}\n\n"
            "On the OAuth App, Device Flow must be enabled.\n"
            "https://github.com/settings/developers",
        )
        Logic.logMessage("ERROR", f"GitHub device code request failed: {e}")
        return ""
    dlg = DeviceLoginDialog(device, parent)
    if dlg.exec():
        return dlg.token
    return ""


class DeviceLoginDialog:
    """Modal: show user_code, open GitHub, poll until authorized or cancelled."""

    def __init__(self, device: dict, parent=None):
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        )

        self.token = ""
        self.device = device
        self.intervalMs = max(5, int(device.get("interval") or 5)) * 1000
        self.deadline = device.get("expires_in") or 900
        self.elapsed = 0
        self.dlg = QDialog(parent)
        self.dlg.setWindowTitle("Sign in to GitHub")
        self.dlg.setModal(True)
        self.dlg.setMinimumWidth(420)
        layout = QVBoxLayout(self.dlg)
        intro = QLabel(
            "Data Doctor files GitHub issues as you.\n"
            "Enter this code on GitHub, then return here."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        code = QLabel(str(device.get("user_code") or ""))
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = code.font()
        font.setPointSize(max(14, font.pointSize() + 6))
        font.setBold(True)
        code.setFont(font)
        layout.addWidget(code)
        self.status = QLabel("Waiting for GitHub authorization…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        openBtn = QPushButton("Open GitHub")
        copyBtn = QPushButton("Copy code")
        cancelBtn = QPushButton("Cancel")
        openBtn.clicked.connect(self.openGithub)
        copyBtn.clicked.connect(self.copyCode)
        cancelBtn.clicked.connect(self.dlg.reject)
        row.addWidget(openBtn)
        row.addWidget(copyBtn)
        row.addStretch(1)
        row.addWidget(cancelBtn)
        layout.addLayout(row)
        self.pollTimer = QTimer(self.dlg)
        self.pollTimer.timeout.connect(self.pollOnce)
        self.dlg.rejected.connect(self.pollTimer.stop)
        self.dlg.accepted.connect(self.pollTimer.stop)
        copyToClipboard(str(device.get("user_code") or ""))
        self.pollTimer.start(self.intervalMs)

    def exec(self) -> bool:
        from PyQt6.QtWidgets import QDialog
        return self.dlg.exec() == QDialog.DialogCode.Accepted

    def openGithub(self) -> None:
        url = (
            self.device.get("verification_uri_complete")
            or self.device.get("verification_uri")
            or "https://github.com/login/device"
        )
        try:
            webbrowser.open(url)
        except Exception as e:
            Logic.logMessage("WARN", f"Report.openGithub: {e}")
        self.copyCode()

    def copyCode(self) -> None:
        copyToClipboard(str(self.device.get("user_code") or ""))
        self.status.setText("Code copied. Waiting for GitHub authorization…")

    def pollOnce(self) -> None:
        self.elapsed += self.intervalMs / 1000.0
        if self.elapsed >= float(self.deadline):
            self.pollTimer.stop()
            self.status.setText("The code expired. Close this window and try again.")
            return
        try:
            data = pollAccessToken(self.device["device_code"])
        except GithubHttpError as e:
            err = (e.payload.get("error") or "").strip()
            if err == "authorization_pending":
                return
            if err == "slow_down":
                self.intervalMs += 5000
                self.pollTimer.setInterval(self.intervalMs)
                return
            if err in ("expired_token", "access_denied", "unsupported_grant_type"):
                self.pollTimer.stop()
                self.status.setText(str(e) or err)
                return
            self.pollTimer.stop()
            self.status.setText(str(e))
            return
        except Exception as e:
            Logic.logMessage("WARN", f"GitHub device poll failed: {e}")
            return
        err = (data.get("error") or "").strip()
        if err == "authorization_pending":
            return
        if err == "slow_down":
            self.intervalMs += 5000
            self.pollTimer.setInterval(self.intervalMs)
            return
        if err:
            self.pollTimer.stop()
            self.status.setText(data.get("error_description") or err)
            return
        token = data.get("access_token") or ""
        if not token:
            return
        self.pollTimer.stop()
        saveGithubTokens(token, data.get("refresh_token") or "")
        self.token = token
        self.dlg.accept()


def submitIssue(parent, title: str, body: str) -> dict | None:
    """Authenticate if needed, POST the issue, return the GitHub issue dict."""
    from PyQt6.QtWidgets import QMessageBox

    token = ensureGithubToken(parent)
    if not token:
        return None
    lastError = None
    for attempt in range(2):
        try:
            data = createGithubIssue(title, body, token)
            number = data.get("number")
            url = data.get("html_url") or ""
            Logic.logMessage("INFO", f"GitHub issue created: #{number} {url}")
            return data
        except GithubHttpError as e:
            lastError = e
            if e.status in (401, 403) and attempt == 0:
                Logic.logMessage("WARN", f"GitHub issue auth failed ({e.status}); signing in again")
                clearGithubTokens()
                token = runDeviceFlow(parent)
                if not token:
                    return None
                continue
            break
        except Exception as e:
            lastError = e
            Logic.logException("GitHub issue create failed", e)
            break
    QMessageBox.warning(
        parent,
        "Could not file issue",
        "GitHub did not accept the issue.\n\n"
        f"{lastError or 'Unknown error'}",
    )
    return None


def showIssueCreated(parent, data: dict) -> None:
    from PyQt6.QtWidgets import QMessageBox

    number = data.get("number")
    url = data.get("html_url") or ""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Issue filed")
    box.setText(f"GitHub issue #{number} was created as your account.")
    if url:
        box.setInformativeText(url)
        openBtn = box.addButton("Open issue", QMessageBox.ButtonRole.AcceptRole)
    else:
        openBtn = None
        box.setInformativeText("Open GitHub to see it.")
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
    if openBtn is not None and box.clickedButton() is openBtn and url:
        try:
            webbrowser.open(url)
        except Exception as e:
            Logic.logMessage("WARN", f"Report.openIssueUrl: {e}")


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
        box.setInformativeText(
            "See app.log, or report it on GitHub (signs you in as your GitHub user)."
        )
        reportBtn = box.addButton("Report on GitHub", QMessageBox.ButtonRole.ActionRole)
        copyBtn = box.addButton("Copy log", QMessageBox.ButtonRole.ActionRole)
        folderBtn = box.addButton("Open log folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(box.button(QMessageBox.StandardButton.Ok))
        box.exec()
        clicked = box.clickedButton()
        if clicked is reportBtn:
            body = crashBody(excType, excValue, excTb)
            data = submitIssue(None, crashTitle(excType, excValue), body)
            if data:
                showIssueCreated(None, data)
        elif clicked is copyBtn:
            tail = logTail(8000)
            copyToClipboard(tail or "(app.log empty or missing)")
        elif clicked is folderBtn:
            openLogFolder()
    finally:
        app.dataDoctorShowingErrorDialog = False


def showManualReportDialog(parent=None) -> None:
    from PyQt6.QtWidgets import (
        QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
        QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
    )

    dlg = QDialog(parent)
    dlg.setWindowTitle("Report an issue")
    dlg.setModal(True)
    dlg.setMinimumWidth(520)
    dlg.resize(560, 420)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(
        "This files a GitHub issue as you. Data Doctor does not store GitHub passwords;\n"
        "the first time, a one-time code is shown for github.com/login/device."
    ))
    layout.addWidget(QLabel("Title"))
    titleEdit = QLineEdit(dlg)
    titleEdit.setPlaceholderText("Short summary")
    layout.addWidget(titleEdit)
    layout.addWidget(QLabel("What happened"))
    bodyEdit = QPlainTextEdit(dlg)
    bodyEdit.setPlaceholderText("What you did, what you expected, what you got.")
    layout.addWidget(bodyEdit)
    includeLog = QCheckBox("Include app.log tail")
    includeLog.setChecked(True)
    layout.addWidget(includeLog)
    extraRow = QHBoxLayout()
    copyBtn = QPushButton("Copy log")
    folderBtn = QPushButton("Open log folder")
    copyBtn.clicked.connect(lambda: copyToClipboard(logTail(8000) or "(app.log empty or missing)"))
    folderBtn.clicked.connect(openLogFolder)
    extraRow.addWidget(copyBtn)
    extraRow.addWidget(folderBtn)
    extraRow.addStretch(1)
    layout.addLayout(extraRow)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Submit")
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    def onSubmit():
        title = titleEdit.text().strip() or "Data Doctor issue"
        summary = bodyEdit.toPlainText().strip() or "_describe it here_"
        if includeLog.isChecked():
            body = issueBody("bug", summary=summary)
        else:
            body = "\n".join([
                f"**Kind:** bug",
                f"**Version:** {Version.displayVersion()}",
                f"**OS:** {platform.system()} {platform.release()} ({platform.machine()})",
                f"**Python:** {sys.version.split()[0]}",
                "",
                "## What happened",
                "",
                summary,
                "",
            ])
        data = submitIssue(dlg, title, body)
        if data:
            dlg.accept()
            showIssueCreated(parent, data)

    buttons.accepted.connect(onSubmit)
    dlg.exec()
