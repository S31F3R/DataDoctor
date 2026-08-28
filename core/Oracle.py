# Oracle.py

import oracledb
import platform
import os
import keyring
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Any, Optional, Tuple, Dict
from core import Logic, Config

# After a bad password, refuse further connect attempts for *that DSN* so we
# do not spam Oracle and lock the account (multi-thread HDB / multi-DSN queries).
# Other databases stay available. The pause expires after AUTH_FAILURE_LOCK_SECONDS
# (or immediately when credentials are saved).
authFailureMessage = None  # legacy; no longer set. Use authFailureFor(dsn).
AUTH_FAILURE_LOCK_SECONDS = 300
_authFailuresLock = threading.Lock()
_authFailures: Dict[str, Tuple[str, float]] = {}

# Instant Client + env must be configured once. sqlRead creates many connections
# (per SDID × date chunk × thread). Old code prepended clientDir to PATH on every
# construct → after enough HDB tasks Windows hit: ValueError environment variable
# longer than 32767 characters.
clientInitLock = threading.Lock()
clientInitialized = False
# TNS_ADMIN inherited from the process environment (not one we set later).
_inheritedTnsAdmin = (os.environ.get("TNS_ADMIN") or "").strip()

# MCS (Microsoft Certificate Store) TLS: Windows prompts per *new* session.
# Serialize the first connect per DSN, then reuse live sessions so later
# threads/queries do not prompt again until the OS cache expires.
_walletMethodCache = None
_mcsConnectLock = threading.Lock()
_mcsPoolsLock = threading.Lock()
_mcsPools: Dict[str, "_McsPool"] = {}
_sqlnetLogState: Dict[str, int] = {}
_sqlnetProcessStart = time.time()
_SQLNET_TIME_RE = re.compile(
    r"Time:\s*(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{1,2}:\d{2}:\d{2})",
    re.IGNORECASE,
)

# Oracle docs: quoted passwords may not contain double-quote or return/newline.
# Also reject other control characters (unsafe / non-printable).
ORACLE_PASSWORD_FORBIDDEN_DISPLAY = (
    'double quote (")',
    'newline / carriage return',
    'other control characters (ASCII < 32)',
)


class OracleAuthError(RuntimeError):
    """Wrong username/password or locked account — do not retry."""
    pass


class OraclePasswordExpiredError(OracleAuthError):
    """Password expired (ORA-28001) — user can change it in Options → USBR."""
    pass

def _authDsnKey(dsn: str) -> str:
    """Normalize USBR-LCHDB / lchdb / USBR-LCHDB|LCHDBA to a dict key."""
    s = str(dsn or '').strip().lower()
    if '|' in s:
        s = s.split('|', 1)[0].strip()
    if '-' in s:
        s = s.split('-', 1)[-1].strip()
    return s


def _formatLockRemaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} second(s)"
    mins = (seconds + 59) // 60
    return f"{mins} minute(s)"


def clearAuthFailure(dsn: Optional[str] = None):
    """Clear auth fail-fast. No dsn → every database (credential save)."""
    global authFailureMessage
    authFailureMessage = None
    with _authFailuresLock:
        if dsn:
            _authFailures.pop(_authDsnKey(dsn), None)
        else:
            _authFailures.clear()


def setAuthFailure(dsn: str, message: str):
    key = _authDsnKey(dsn)
    if not key:
        return
    with _authFailuresLock:
        _authFailures[key] = (message, time.monotonic() + AUTH_FAILURE_LOCK_SECONDS)


def authFailureFor(dsn: str) -> Optional[str]:
    """User-facing block message for this DSN, or None if not blocked / expired."""
    key = _authDsnKey(dsn)
    if not key:
        return None
    now = time.monotonic()
    with _authFailuresLock:
        rec = _authFailures.get(key)
        if not rec:
            return None
        msg, expiry = rec
        if now >= expiry:
            _authFailures.pop(key, None)
            return None
        remaining = expiry - now
    wait = _formatLockRemaining(remaining)
    return (
        f"{msg}\n\nThis database is paused for {wait} to avoid locking the "
        "account. Other databases are still available."
    )

def _oracleErrorCode(exc) -> Optional[int]:
    """Extract numeric Oracle error code when present."""
    try:
        if hasattr(exc, 'args') and exc.args:
            err = exc.args[0]
            code = getattr(err, 'code', None)
            if code is not None:
                return int(code)
    except Exception:
        pass
    text = str(exc) if exc is not None else ''
    m = re.search(r'ORA-(\d+)', text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None

def isPasswordExpiredError(exc) -> bool:
    """True if Oracle reports password expired (ORA-28001)."""
    if _oracleErrorCode(exc) == 28001:
        return True
    text = (str(exc) if exc is not None else '').upper()
    return 'ORA-28001' in text or 'PASSWORD HAS EXPIRED' in text or 'PASSWORD EXPIRED' in text

def isUserDoesNotExistError(exc) -> bool:
    """True for ORA-01918 (user does not exist) — definitive missing account."""
    if _oracleErrorCode(exc) == 1918:
        return True
    text = (str(exc) if exc is not None else '').upper()
    return 'ORA-01918' in text or ('DOES NOT EXIST' in text and 'USER' in text)

def isLoginAuthError(exc) -> bool:
    """
    True for ORA-01017 invalid username/password on connect.

    Oracle does not distinguish wrong password from unknown user. For HDB
    password change we treat this as 'auth' so the UI can prompt for that
    database's current password (passwords often differ across HDBs).
    """
    if isUserDoesNotExistError(exc):
        return False
    code = _oracleErrorCode(exc)
    if code == 1017:
        return True
    text = (str(exc) if exc is not None else '').upper()
    if 'ORA-01017' in text or 'ORA-1017' in text:
        return True
    if 'INVALID USERNAME/PASSWORD' in text:
        return True
    if 'USERNAME/PASSWORD' in text and 'INVALID' in text:
        return True
    if 'INVALID USERNAME' in text or 'INVALID PASSWORD' in text:
        return True
    return False

def isUserMissingError(exc) -> bool:
    """
    Legacy helper: login auth failure or definitive missing user.
    Prefer isLoginAuthError / isUserDoesNotExistError for password-change flow.
    """
    return isLoginAuthError(exc) or isUserDoesNotExistError(exc)

def oracleUserIdent(username: str) -> str:
    """
    Normalize Oracle username for unquoted SQL identifiers.

    Unquoted Oracle identifiers are stored/matched as UPPERCASE. Quoting the
    username (e.g. ALTER USER "jsmith") looks for a case-sensitive name and
    often yields ORA-01918 even when the account exists as JSMITH.
    """
    u = (username or '').strip()
    if not u:
        raise ValueError('Oracle username is empty')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_#$]*', u):
        raise ValueError(
            'Oracle username has invalid characters for password change '
            '(use letters, digits, _, #, $ only)'
        )
    return u.upper()

def buildAlterUserPasswordSql(username: str, newPassword: str, oldPassword: str) -> str:
    """
    Build ALTER USER ... IDENTIFIED BY ... REPLACE ... matching HDB practice.

    Valid form (Oracle docs / Examples.txt):
      ALTER USER username IDENTIFIED BY "newPassword" REPLACE "oldPassword"

    - Username: unquoted, uppercased (standard Oracle identifier)
    - Passwords: double-quoted so special characters / case are preserved
    - Never log the returned string (contains secrets)
    """
    userIdent = oracleUserIdent(username)
    # Forbidden chars already validated on newPassword; still refuse " in either
    if '"' in (newPassword or '') or '"' in (oldPassword or ''):
        raise ValueError('Oracle passwords cannot contain double quotes')
    if '\n' in (newPassword or '') or '\r' in (newPassword or ''):
        raise ValueError('Oracle passwords cannot contain newlines')
    if '\n' in (oldPassword or '') or '\r' in (oldPassword or ''):
        raise ValueError('Oracle passwords cannot contain newlines')
    return (
        f'ALTER USER {userIdent} IDENTIFIED BY "{newPassword}" '
        f'REPLACE "{oldPassword}"'
    )

def isAuthError(exc) -> bool:
    """True if this looks like bad credentials / locked account / expired password."""
    if isPasswordExpiredError(exc):
        return True
    text = str(exc) if exc is not None else ''
    upper = text.upper()
    # Common Oracle auth codes
    codes = (
        'ORA-01017',  # invalid username/password
        'ORA-1017',
        'ORA-28000',  # account locked
        'ORA-28001',  # password expired
        'ORA-28003',
        'ORA-28043',
        'ORA-00988',
    )
    if any(c in upper for c in codes):
        return True
    if 'INVALID USERNAME' in upper or 'INVALID PASSWORD' in upper:
        return True
    if 'USERNAME/PASSWORD' in upper and 'INVALID' in upper:
        return True
    # python-oracledb often wraps with error object
    try:
        if hasattr(exc, 'args') and exc.args:
            err = exc.args[0]
            code = getattr(err, 'code', None)
            if code in (1017, 28000, 28001, 28003, 28043):
                return True
    except Exception:
        pass
    return False

def passwordExpiredMessage(dsn: str = '') -> str:
    """User-facing message for ORA-28001 (no secrets)."""
    label = (dsn or '').strip()
    where = f" ({label})" if label else ""
    return (
        f"Your Oracle/HDB password has expired{where}.\n\n"
        "You can change it in Options under the USBR tab "
        "(Oracle username and password)."
    )

def genericAuthFailureMessage(dsn: str = '') -> str:
    label = (dsn or '').strip() or "this database"
    return (
        f"Oracle login failed ({label}): wrong username/password or account locked. "
        "Update credentials in Options if they are wrong for this database."
    )

def validateOraclePassword(password: str) -> Tuple[bool, str]:
    """
    Validate an Oracle password for length and forbidden characters.
    Returns (ok, errorMessage). errorMessage is empty when ok.
    Never echoes the password itself.
    """
    minLen = int(getattr(Config, 'oraclePasswordMinLength', 12) or 12)
    maxLen = int(getattr(Config, 'oraclePasswordMaxLength', 30) or 30)
    if maxLen < minLen:
        maxLen = minLen
    forbiddenList = ', '.join(ORACLE_PASSWORD_FORBIDDEN_DISPLAY)

    if password is None:
        password = ''

    length = len(password)
    badChars = []
    for ch in password:
        if ch == '"':
            if '"' not in badChars:
                badChars.append('"')
        elif ch in ('\n', '\r'):
            label = 'newline/carriage return'
            if label not in badChars:
                badChars.append(label)
        elif ord(ch) < 32:
            label = f'control char (ASCII {ord(ch)})'
            if label not in badChars:
                badChars.append(label)

    tooShort = length < minLen
    tooLong = length > maxLen
    if tooShort or tooLong or badChars:
        lines = [
            "Invalid Oracle password.",
            "",
            f"Minimum length: {minLen} character(s).",
            f"Maximum length: {maxLen} character(s).",
        ]
        if tooShort or tooLong:
            lines.append(f"Your password is {length} character(s).")
        lines.append("")
        lines.append(f"Characters not allowed: {forbiddenList}.")
        if badChars:
            lines.append(f"Found: {', '.join(badChars)}.")
        return False, '\n'.join(lines)

    return True, ''

def databaseToDsn(dbName: str) -> str:
    """USBR-LCHDB or USBR-LCHDB|LCHDBA → lchdb (strip optional |SCHEMA)."""
    s = str(dbName or '').strip()
    if '|' in s:
        s = s.split('|', 1)[0].strip()
    if '-' in s:
        return s.split('-', 1)[1].lower()
    return s.lower()


def hdbDisplayName(dbName: str) -> str:
    """Strip |SCHEMA so UI/logs never show query-only schema suffixes."""
    s = str(dbName or '').strip()
    if '|' in s:
        return s.split('|', 1)[0].strip()
    return s


def isAccountLockedError(exc) -> bool:
    """True for ORA-28000 account locked."""
    if _oracleErrorCode(exc) == 28000:
        return True
    text = (str(exc) if exc is not None else '').upper()
    return 'ORA-28000' in text or 'ACCOUNT IS LOCKED' in text or 'ACCOUNT LOCKED' in text

def _executeAlterUserPassword(conn, username: str, oldPassword: str, newPassword: str) -> None:
    """
    Run ALTER USER ... IDENTIFIED BY "new" REPLACE "old" on an open connection.
    Never logs the SQL (contains secrets).
    """
    sql = buildAlterUserPasswordSql(username, newPassword, oldPassword)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        # DDL usually auto-commits; best-effort commit for non-DDL drivers
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        sql = None


def changePasswordOnDsn(
    dsn: str,
    username: str,
    oldPassword: str,
    newPassword: str,
    dbLabel: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Change password on one Oracle DSN using the old password to authenticate.

    Primary method (HDB / Examples.txt):
      ALTER USER username IDENTIFIED BY "newPassword" REPLACE "oldPassword"

    Username is unquoted UPPERCASE; passwords are double-quoted.
    Fallback: connection.changepassword(old, new).
    Expired password: connect(..., newpassword=new).

    Returns (status, detail) where status is:
      'success' — password changed
      'auth'    — ORA-01017: wrong password for this DB (UI may prompt for another)
      'locked'  — ORA-28000: account locked (shown to user)
      'missing' — ORA-01918: user does not exist (silent skip)
      'error'   — other failure (logged only; not shown as spam to users)

    Does NOT set the global authFailureMessage (per-DB skips must not block others).
    Never logs password values or the ALTER USER SQL.
    """
    label = hdbDisplayName(dbLabel or dsn)
    ensureOracleClientReady()

    try:
        userIdent = oracleUserIdent(username)
    except ValueError as e:
        return 'error', str(e)

    # Connect as the account (Oracle auth accepts any case; we use original then upper)
    connectUser = (username or '').strip()
    conn = None
    try:
        try:
            conn = oracledb.connect(user=connectUser, password=oldPassword, dsn=dsn)
        except Exception as e:
            if isPasswordExpiredError(e):
                # Expired: change as part of connect (newpassword=)
                try:
                    conn = oracledb.connect(
                        user=connectUser,
                        password=oldPassword,
                        newpassword=newPassword,
                        dsn=dsn,
                    )
                    Logic.logMessage(
                        "INFO",
                        f"Oracle password changed on {label} ({dsn}) for user {userIdent} "
                        f"(password was expired)",
                    )
                    return 'success', ''
                except Exception as e2:
                    if isLoginAuthError(e2):
                        Logic.logMessage(
                            "INFO",
                            f"Oracle password change needs per-DB password on {label} "
                            f"(expired path login failed: {_safeErrorText(e2)})",
                        )
                        return 'auth', _safeErrorText(e2)
                    if isAccountLockedError(e2):
                        Logic.logMessage(
                            "INFO",
                            f"Oracle password change: account locked on {label}",
                        )
                        return 'locked', 'Account locked'
                    if isUserDoesNotExistError(e2):
                        Logic.logMessage(
                            "INFO",
                            f"Oracle password change skipped on {label}: user does not exist",
                        )
                        return 'missing', _safeErrorText(e2)
                    Logic.logMessage(
                        "ERROR",
                        f"Oracle password change failed on {label} (expired path): "
                        f"{_safeErrorText(e2)}",
                    )
                    return 'error', _safeErrorText(e2)

            if isLoginAuthError(e):
                # Wrong password for this DB (or user not present — UI may prompt once)
                Logic.logMessage(
                    "INFO",
                    f"Oracle password change needs per-DB password on {label}: "
                    f"{_safeErrorText(e)}",
                )
                return 'auth', _safeErrorText(e)

            if isAccountLockedError(e):
                Logic.logMessage(
                    "INFO",
                    f"Oracle password change: account locked on {label}",
                )
                return 'locked', 'Account locked'

            if isUserDoesNotExistError(e):
                Logic.logMessage(
                    "INFO",
                    f"Oracle password change skipped on {label}: user does not exist",
                )
                return 'missing', _safeErrorText(e)

            # Other connect failures (TNS, network, etc.) — log only, no UI spam
            Logic.logMessage(
                "ERROR",
                f"Oracle password change connect failed on {label}: {_safeErrorText(e)}",
            )
            return 'error', _safeErrorText(e)

        # Connected — change password via ALTER USER (Examples.txt / Oracle standard)
        try:
            try:
                _executeAlterUserPassword(conn, userIdent, oldPassword, newPassword)
            except Exception as alterErr:
                # Fallback to driver API if ALTER USER is blocked/unavailable
                if hasattr(conn, 'changepassword'):
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            f"Oracle ALTER USER failed on {label}, trying changepassword: "
                            f"{_safeErrorText(alterErr)}",
                        )
                    conn.changepassword(oldPassword, newPassword)
                else:
                    raise

            Logic.logMessage(
                "INFO",
                f"Oracle password changed successfully on {label} ({dsn}) for user {userIdent}",
            )
            return 'success', ''
        except Exception as e:
            # Only ORA-01918 is definitive "user does not exist" after a successful login
            if isUserDoesNotExistError(e):
                Logic.logMessage(
                    "INFO",
                    f"Oracle password change skipped on {label}: user {userIdent} does not exist",
                )
                return 'missing', _safeErrorText(e)
            if isAccountLockedError(e):
                Logic.logMessage(
                    "INFO",
                    f"Oracle password change: account locked on {label} during ALTER",
                )
                return 'locked', 'Account locked'
            Logic.logMessage(
                "ERROR",
                f"Oracle password change failed on {label} for user {userIdent}: "
                f"{_safeErrorText(e)}",
            )
            return 'error', _safeErrorText(e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = None

def _safeErrorText(exc) -> str:
    """Stringify an exception without assuming secrets are present."""
    try:
        text = str(exc).strip() if exc is not None else 'Unknown error'
    except Exception:
        text = 'Unknown error'
    # Collapse whitespace; cap length for popups
    text = ' '.join(text.split())
    if len(text) > 300:
        text = text[:297] + '...'
    return text or 'Unknown error'

def changePasswordOnAllHdb(
    username: str,
    oldPassword: str,
    newPassword: str,
    databases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Change the Oracle password on HDB databases in parallel (one thread each).

    databases: display names to update (USBR-LCHDB). None → all in Config.

    Returns:
      {
        'success':    ['USBR-LCHDB', ...],
        'errors':     [('USBR-YAOHDB', 'reason'), ...],  # only locked (user-facing)
        'authFailed': ['USBR-ECOHDB', ...],  # ORA-01017 — UI may prompt per DB
      }
    Databases where the account did not exist (ORA-01918) or other non-auth
    failures (TNS/network) are omitted from the UI summary (logged only).
    """
    rawDatabases = list(getattr(Config, 'hdbOracleDatabases', ()) or ())
    # Normalize to display labels only (strip |SCHEMA)
    allNames = [hdbDisplayName(db) for db in rawDatabases if hdbDisplayName(db)]
    if databases:
        wanted = {hdbDisplayName(n) for n in databases if n}
        databases = [n for n in allNames if n in wanted]
    else:
        databases = allNames
    success: List[str] = []
    errors: List[Tuple[str, str]] = []
    authFailed: List[str] = []
    lock = threading.Lock()

    if not databases:
        Logic.logMessage("WARN", "changePasswordOnAllHdb: no HDB databases configured")
        return {'success': success, 'errors': errors, 'authFailed': authFailed}

    Logic.logMessage(
        "INFO",
        f"Oracle password change starting for user {username} on {len(databases)} HDB database(s)",
    )

    def worker(dbName: str):
        dsn = databaseToDsn(dbName)
        status, detail = changePasswordOnDsn(
            dsn=dsn,
            username=username,
            oldPassword=oldPassword,
            newPassword=newPassword,
            dbLabel=dbName,
        )
        with lock:
            if status == 'success':
                success.append(dbName)
            elif status == 'auth':
                authFailed.append(dbName)
            elif status == 'locked':
                # User-facing: locked accounts only (not TNS/network spam)
                errors.append((dbName, detail or 'Account locked'))
            # 'missing' / 'error' → intentional silence in UI summary (still in app.log)

    maxWorkers = max(1, len(databases))
    with ThreadPoolExecutor(max_workers=maxWorkers) as executor:
        futures = [executor.submit(worker, db) for db in databases]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                Logic.logMessage(
                    "ERROR",
                    f"changePasswordOnAllHdb: unexpected worker failure: {_safeErrorText(e)}",
                )

    # Stable order for UI (config order)
    order = {name: i for i, name in enumerate(databases)}
    success.sort(key=lambda n: order.get(n, 999))
    errors.sort(key=lambda pair: order.get(pair[0], 999))
    authFailed.sort(key=lambda n: order.get(n, 999))

    Logic.logMessage(
        "INFO",
        f"Oracle password change pass finished for user {username}: "
        f"{len(success)} succeeded, {len(errors)} locked/user-facing error(s), "
        f"{len(authFailed)} need per-DB password, "
        f"{len(databases) - len(success) - len(errors) - len(authFailed)} skipped "
        f"(user not found or non-auth connect error)",
    )
    return {'success': success, 'errors': errors, 'authFailed': authFailed}

def pathHasDir(envValue, directory, sep):
    """True if directory already appears as a PATH-style entry."""
    if not envValue:
        return False
    dirNorm = os.path.normcase(os.path.normpath(str(directory)))
    for part in envValue.split(sep):
        if not part:
            continue
        if os.path.normcase(os.path.normpath(part)) == dirNorm:
            return True
    return False

def ensureClientOnPath(clientDir):
    """Prepend Instant Client to the process library path at most once."""
    system = platform.system().lower()
    clientStr = str(clientDir)

    if system == "windows":
        sep = ';'
        key = 'PATH'
    elif system == "linux":
        sep = ':'
        key = 'LD_LIBRARY_PATH'
    elif system == "darwin":
        sep = ':'
        key = 'DYLD_LIBRARY_PATH'
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    current = os.environ.get(key, '')
    if pathHasDir(current, clientStr, sep):
        if Config.debug:
            Logic.logMessage("DEBUG", f"oracleConnection: {key} already includes Instant Client")
        return

    # Guard Windows 32k env limit even if PATH is already huge for other reasons
    candidate = f"{clientStr}{sep}{current}" if current else clientStr
    if system == "windows" and len(candidate) > 32767:
        # Prefer putting client first by dropping duplicate-looking noise only if needed
        # Last resort: set PATH to client + truncated original (keep as much as fits)
        maxOrig = 32767 - len(clientStr) - 1
        trimmed = current[:maxOrig] if maxOrig > 0 else ''
        candidate = f"{clientStr}{sep}{trimmed}" if trimmed else clientStr
        Logic.logMessage(
            "WARN",
            f"oracleConnection: {key} would exceed 32767 chars; trimmed to fit Instant Client"
        )
    os.environ[key] = candidate
    if Config.debug:
        Logic.logMessage("DEBUG", f"oracleConnection: Prepended Instant Client to {key} (len={len(candidate)})")

def inheritedTnsAdmin():
    """TNS_ADMIN from the process environment at import; empty if we set it later."""
    return _inheritedTnsAdmin


def packagedTnsAdmin():
    """Packaged oracle/network/admin (tnsnames.ora / sqlnet.ora live here)."""
    return os.path.normpath(Logic.resourcePath("oracle/network/admin"))


def resolveTnsAdmin():
    """
    Folder Instant Client uses for tnsnames.ora and sqlnet.ora.

    1. TNS_ADMIN environment variable, if set
    2. Options → Oracle → TNS Names Location, if saved
    3. Packaged oracle/network/admin (we do not ship tnsnames.ora)
    """
    inherited = (_inheritedTnsAdmin or "").strip()
    if inherited:
        return os.path.normpath(inherited)
    try:
        from core import Utils
        loc = (Utils.loadConfig().get("tnsNamesLocation") or "").strip()
        if loc:
            if "%AppRoot%" in loc:
                loc = loc.replace("%AppRoot%", getattr(Config, "appRoot", "") or "")
            loc = os.path.normpath(loc)
            if loc:
                return loc
    except Exception:
        pass
    return packagedTnsAdmin()


def applyTnsAdmin(path=None):
    """
    Set process TNS_ADMIN before Instant Client init.

    Instant Client defaults to <clientDir>/network/admin when this is unset,
    which is NOT where we put sqlnet.ora / tnsnames.ora.
    """
    admin = path or resolveTnsAdmin()
    os.environ["TNS_ADMIN"] = admin
    return admin


def ensureOracleClientReady():
    """
    One-time Instant Client init + TNS_ADMIN. Safe to call from any thread;
    concurrent callers block until the first setup finishes.

    Instant Client priority:
      1. Packaged oracle/client next to the app (always, when present)
      2. System Instant Client already on PATH / LD_LIBRARY_PATH
      3. Thin mode (no Instant Client) — last resort

    tnsnames.ora / sqlnet.ora (same folder):
      1. TNS_ADMIN environment variable
      2. Options TNS Names Location
      3. Packaged oracle/network/admin
    TNS_ADMIN is applied before init_oracle_client so Instant Client does not
    look at oracle/client/network/admin.
    """
    global clientInitialized
    if clientInitialized:
        return

    with clientInitLock:
        if clientInitialized:
            return

        system = platform.system().lower()
        if platform.architecture()[0] != "64bit":
            raise RuntimeError("Only 64-bit platforms supported.")

        tnsAdmin = applyTnsAdmin()
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"oracleConnection.setup: TNS_ADMIN={tnsAdmin} "
                f"(sqlnet.ora present={os.path.isfile(os.path.join(tnsAdmin, 'sqlnet.ora'))}, "
                f"tnsnames.ora present={os.path.isfile(os.path.join(tnsAdmin, 'tnsnames.ora'))})",
            )
        else:
            Logic.logMessage(
                "INFO",
                f"oracleConnection.setup: Using TNS_ADMIN {tnsAdmin}",
            )

        # Packaged client is Instant Client Basic Lite (raw files, no installer).
        # Full Basic library names still count as ready.
        expectedAny = {
            "windows": ["oci.dll"],
            "linux": ["libociicus.so", "libociei.so"],
            "darwin": ["libociicus.dylib", "libociei.dylib"],
        }
        requiredAny = expectedAny.get(system)
        if not requiredAny:
            raise RuntimeError(f"Unsupported platform: {system}")

        clientDirPath = "oracle/client"
        clientDir = Path(Logic.resourcePath(clientDirPath))
        packagedReady = clientDir.exists() and any(
            (clientDir / f).exists() for f in requiredAny
        )

        if packagedReady:
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.setup: Using packaged Instant Client at {clientDir}",
                )
            ensureClientOnPath(clientDir)
            try:
                oracledb.init_oracle_client(lib_dir=str(clientDir))
            except Exception as e:
                msg = str(e).lower()
                if "already been initialized" in msg or "has already been called" in msg:
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            "oracleConnection.setup: Instant Client already initialized",
                        )
                else:
                    raise
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.setup: Initialized oracledb with packaged clientDir {clientDir}",
                )
        else:
            # Packaged client missing — try system Instant Client, then thin mode
            if clientDir.exists():
                Logic.logMessage(
                    "WARN",
                    f"oracleConnection.setup: Packaged Instant Client incomplete at {clientDir}; "
                    f"trying system Oracle client",
                )
            else:
                Logic.logMessage(
                    "WARN",
                    f"oracleConnection.setup: Packaged Instant Client not found at {clientDir}; "
                    f"trying system Oracle client",
                )
            try:
                oracledb.init_oracle_client()  # system search path / ORACLE_HOME
                Logic.logMessage(
                    "INFO",
                    "oracleConnection.setup: Using system Instant Client (packaged not available)",
                )
            except Exception as e:
                msg = str(e).lower()
                if "already been initialized" in msg or "has already been called" in msg:
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            "oracleConnection.setup: Instant Client already initialized (system)",
                        )
                else:
                    # Thin mode — works for many DSNs; TCPS/wallet may still need thick client
                    Logic.logMessage(
                        "WARN",
                        f"oracleConnection.setup: No Instant Client available "
                        f"({_safeErrorText(e)}); continuing in thin mode",
                    )

        clientInitialized = True
        ingestSqlnetLog()


def sqlnetWalletMethod() -> Optional[str]:
    """
    METHOD from sqlnet.ora WALLET_LOCATION (MCS or FILE), or None.

    Bundled sqlnet.ora uses METHOD = MCS (Windows certificate store).
    """
    global _walletMethodCache
    if _walletMethodCache is not None:
        return _walletMethodCache or None

    # sqlnet.ora comes from the same folder as tnsnames.ora
    candidates = []
    try:
        candidates.append(os.path.join(resolveTnsAdmin(), "sqlnet.ora"))
    except Exception:
        pass
    method = None
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Strip comment lines so a commented WALLET_LOCATION is ignored
        live = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
        )
        m = re.search(r"METHOD\s*=\s*([A-Za-z0-9_]+)", live, re.IGNORECASE)
        if m:
            method = m.group(1).strip().upper()
            break
    _walletMethodCache = method or ""
    return method


def isMcsAuth() -> bool:
    """True when sqlnet.ora asks Instant Client to use the Windows cert store."""
    return sqlnetWalletMethod() == "MCS"


def _sqlnetLogPaths() -> List[str]:
    dirs = []
    try:
        dirs.append(os.getcwd())
    except Exception:
        pass
    appRoot = getattr(Config, "appRoot", "") or ""
    if appRoot:
        dirs.append(appRoot)
        parent = os.path.dirname(appRoot)
        if parent:
            dirs.append(parent)
    tns = os.environ.get("TNS_ADMIN") or ""
    if tns:
        dirs.append(tns)
        dirs.append(os.path.normpath(os.path.join(tns, "..", "log")))
    try:
        dirs.append(Logic.resourcePath("oracle/network/admin"))
        dirs.append(Logic.resourcePath("oracle/network/log"))
        dirs.append(Logic.resourcePath("oracle/client"))
        dirs.append(Logic.resourcePath("."))
    except Exception:
        pass
    seen = set()
    out: List[str] = []
    for d in dirs:
        if not d:
            continue
        p = os.path.normpath(os.path.join(d, "sqlnet.log"))
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _sqlnetBlockTime(block: str):
    """Parse Instant Client 'Time: 25-AUG-2026 17:10:23' if present."""
    m = _SQLNET_TIME_RE.search(block or "")
    if not m:
        return None
    raw = m.group(1).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%B-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _fatalSqlnetBlocks(text: str) -> List[str]:
    if not text or not text.strip():
        return []
    chunks = re.split(r"\n{2,}", text.replace("\r\n", "\n"))
    found = []
    for chunk in chunks:
        chunk = chunk.strip()
        if chunk and re.search(r"\bfatal\b", chunk, re.IGNORECASE):
            found.append(chunk)
    if found:
        return found
    return [
        ln.strip()
        for ln in text.splitlines()
        if re.search(r"\bfatal\b", ln, re.IGNORECASE)
    ]


def ingestSqlnetLog() -> None:
    """
    Copy Fatal entries that Instant Client appended *after this process started*
    into app.log as ERROR, in the live log timeline.

    First sight of a sqlnet.log is EOF only — never dump hours of old Fatals
    into the current query. Blocks whose Oracle Time: is before process start
    are skipped even if they sit in newly-read bytes (file truncated/rewritten).
    """
    cutoff = datetime.fromtimestamp(_sqlnetProcessStart) - timedelta(seconds=120)
    for path in _sqlnetLogPaths():
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if path not in _sqlnetLogState:
            # First sight: remember EOF; do not ingest history
            _sqlnetLogState[path] = size
            continue
        prev = _sqlnetLogState[path]
        if size < prev:
            prev = 0
        if size == prev:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(prev)
                newText = f.read()
        except Exception:
            continue
        _sqlnetLogState[path] = size
        for block in _fatalSqlnetBlocks(newText):
            when = _sqlnetBlockTime(block)
            if when is not None and when < cutoff:
                continue
            clipped = block if len(block) <= 4000 else block[:3997] + "..."
            whenLabel = when.strftime("%H:%M:%S") if when is not None else ""
            prefix = f"sqlnet.log {whenLabel}: " if whenLabel else "sqlnet.log: "
            Logic.logMessage("ERROR", prefix + clipped)


def _connectionAlive(conn) -> bool:
    """
    MCS sessions must not be ping-tested. A stale Windows cert/smart-card
    cache can abort the process with 0x80100070 (SCARD_W_CACHE_ITEM_NOT_FOUND)
    instead of a Python exception.
    """
    return conn is not None


def _tryCloseOracle(conn) -> None:
    try:
        if conn is not None:
            conn.close()
    except BaseException:
        pass


class _McsPool:
    """Idle MCS sessions for one DSN. Connections are not thread-safe."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.lock = threading.Lock()
        self.firstStarted = False
        self.firstDone = threading.Event()
        self.idle: List[Any] = []
        self.liveCount = 0
        self.maxSize = 15


def _mcsPoolFor(dsn: str) -> _McsPool:
    key = (dsn or "").strip().lower()
    with _mcsPoolsLock:
        pool = _mcsPools.get(key)
        if pool is None:
            pool = _McsPool(key)
            _mcsPools[key] = pool
        return pool


def acquireMcsConnection(dsn: str, connectFn):
    """
    Check out a live MCS session, or open one. First connect per DSN is
    serialized so Windows only prompts once; later connects wait for that
    handshake so the cert cache is warm.
    """
    pool = _mcsPoolFor(dsn)
    with pool.lock:
        if pool.idle:
            # Reuse without ping (MCS native ping can fatal 0x80100070).
            return pool.idle.pop()
        waitForFirst = pool.firstStarted
        if not pool.firstStarted:
            pool.firstStarted = True
            waitForFirst = False

    if waitForFirst:
        pool.firstDone.wait(timeout=180)

    try:
        with _mcsConnectLock:
            conn = connectFn()
    except Exception:
        with pool.lock:
            if not pool.firstDone.is_set():
                pool.firstStarted = False
            pool.firstDone.set()
        raise

    with pool.lock:
        pool.liveCount += 1
        pool.firstDone.set()
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"MCS pool: new session for {dsn} (live={pool.liveCount})",
        )
    return conn


def releaseMcsConnection(dsn: str, conn) -> None:
    if conn is None:
        return
    pool = _mcsPoolFor(dsn)
    with pool.lock:
        pool.idle.append(conn)


def discardMcsConnection(dsn: str, conn) -> None:
    _tryCloseOracle(conn)
    pool = _mcsPoolFor(dsn)
    with pool.lock:
        pool.liveCount = max(0, pool.liveCount - 1)
        pool.idle = [c for c in pool.idle if c is not conn]


class oracleConnection:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection = None
        self._fromMcsPool = False
        ensureOracleClientReady()

    def _newSession(self) -> oracledb.Connection:
        """Open a brand-new oracledb session (keyring user/password)."""
        user = keyring.get_password("DataDoctor", "oracleUser") or ""
        password = keyring.get_password("DataDoctor", "oraclePassword") or ""
        if not user or not password:
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    "oracleConnection.connect: Missing Oracle credentials",
                )
            raise ValueError("Oracle username or password not set in keyring")
        return oracledb.connect(user=user, password=password, dsn=self.dsn)

    def connect(self) -> oracledb.Connection:
        """Establish Oracle connection with PIV/MCS and user credentials."""
        blocked = authFailureFor(self.dsn)
        if blocked:
            raise OracleAuthError(blocked)

        try:
            if isMcsAuth():
                self.connection = acquireMcsConnection(self.dsn, self._newSession)
                self._fromMcsPool = True
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"oracleConnection.connect: MCS pooled session for {self.dsn}",
                    )
            else:
                self._fromMcsPool = False
                self.connection = self._newSession()
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"oracleConnection.connect: Connection established to {self.dsn}",
                    )
            clearAuthFailure(self.dsn)
            ingestSqlnetLog()
            return self.connection
        except OracleAuthError:
            ingestSqlnetLog()
            raise
        except oracledb.Error as e:
            ingestSqlnetLog()
            if isPasswordExpiredError(e):
                setAuthFailure(self.dsn, passwordExpiredMessage(self.dsn))
                Logic.logMessage(
                    "ERROR",
                    f"oracleConnection.connect: Password expired for {self.dsn}: {e}",
                )
                raise OraclePasswordExpiredError(
                    authFailureFor(self.dsn) or passwordExpiredMessage(self.dsn)
                ) from e
            if isAuthError(e):
                setAuthFailure(self.dsn, genericAuthFailureMessage(self.dsn))
                Logic.logMessage("ERROR", f"oracleConnection.connect: Auth failure for {self.dsn}: {e}")
                raise OracleAuthError(
                    authFailureFor(self.dsn) or genericAuthFailureMessage(self.dsn)
                ) from e
            Logic.logException(f"oracleConnection.connect: Error connecting to Oracle ({self.dsn})", e)
            raise
        except Exception as e:
            ingestSqlnetLog()
            if isPasswordExpiredError(e):
                setAuthFailure(self.dsn, passwordExpiredMessage(self.dsn))
                Logic.logMessage(
                    "ERROR",
                    f"oracleConnection.connect: Password expired for {self.dsn}: {e}",
                )
                raise OraclePasswordExpiredError(
                    authFailureFor(self.dsn) or passwordExpiredMessage(self.dsn)
                ) from e
            if isAuthError(e):
                setAuthFailure(self.dsn, genericAuthFailureMessage(self.dsn))
                Logic.logMessage("ERROR", f"oracleConnection.connect: Auth failure for {self.dsn}: {e}")
                raise OracleAuthError(
                    authFailureFor(self.dsn) or genericAuthFailureMessage(self.dsn)
                ) from e
            Logic.logException(f"oracleConnection.connect: Unexpected error ({self.dsn})", e)
            raise

    def reconnect(self) -> oracledb.Connection:
        """Close any existing session and open a new one (same DSN/credentials)."""
        conn = self.connection
        self.connection = None
        if getattr(self, "_fromMcsPool", False) and conn is not None:
            discardMcsConnection(self.dsn, conn)
            self._fromMcsPool = False
        else:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
        return self.connect()

    def isConnectionError(self, exc) -> bool:
        """True if the session looks dead (safe to reconnect and retry once)."""
        if isAuthError(exc):
            return False
        text = str(exc).upper() if exc is not None else ''
        markers = (
            'DPI-1010',  # not connected
            'DPI-1080',  # connection closed
            'DPY-4011',  # connection was closed
            'DPY-1001',
            'ORA-03113',  # end-of-file on communication channel
            'ORA-03114',
            'ORA-03135',  # connection lost contact
            'ORA-12571',
            'ORA-25408',
            'NOT CONNECTED',
            'CONNECTION WAS CLOSED',
            'BROKEN PIPE',
            '80100070',  # SCARD_W_CACHE_ITEM_NOT_FOUND (MCS / PIV)
            'SCARD',
            'CACHE_ITEM_NOT_FOUND',
        )
        return any(m in text for m in markers)

    def executeCustomQuery(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> Any:
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")

        # Remove any white space
        query = query.strip()

        # Check if ; was at the end of the query, if so, remove it
        if query.endswith(';'):
            query = query[:-1]

            if Config.debug:
                Logic.logMessage("DEBUG", "Removed trailing semicolon from query")

        # Detect bind variables (e.g., :1, :name) more precisely
        hasBindVars = bool(re.search(r'(?<!\w):(\d+|[a-zA-Z]\w*)', query))

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"OracleConnection.executeCustomQuery: {len(query)} chars, binds={hasBindVars}",
            )

        if not params and hasBindVars:
            if Config.debug: Logic.logMessage("DEBUG", "OracleConnection.executeCustomQuery: Bind variables detected but no params provided")
            raise ValueError("Bind variables found in query but params not provided. Use parameterized input to prevent SQL injection.")

        if params and not isinstance(params, (list, tuple)):
            if Config.debug: Logic.logMessage("DEBUG", "OracleConnection.executeCustomQuery: Invalid params type, risking SQL injection")
            raise ValueError("Params must be a list or tuple to prevent SQL injection")

        if params and not hasBindVars:
            if Config.debug: Logic.logMessage("DEBUG", "OracleConnection.executeCustomQuery: Params provided but no bind variables in query")
            raise ValueError("Query has no bind variables but params were provided")

        cursor = self.connection.cursor()
        cursor.arraysize = 1000
        cursor.prefetchrows = 2000
        startTime = time.time()

        try:
            return self.runQueryOnCursor(cursor, query, params, fetchAll, startTime)
        except oracledb.Error as e:
            ingestSqlnetLog()
            if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Oracle error: {e}")
            raise
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            if Config.debug: Logic.logMessage("DEBUG", "OracleConnection.executeCustomQuery: Cursor closed")

    def runQueryOnCursor(self, cursor, query, params, fetchAll, startTime):
        exactQuery = query
        if params:
            cursor.execute(exactQuery, params)
        else:
            cursor.execute(exactQuery)

        if Config.debug:
            nParams = len(params) if params is not None else 0
            Logic.logMessage(
                "DEBUG",
                f"OracleConnection.executeCustomQuery: executed {len(exactQuery)} chars, {nParams} bind params",
            )
        isSelect = cursor.description is not None
        executionTime = time.time() - startTime
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"OracleConnection.executeCustomQuery: Query executed in {executionTime:.3f} seconds",
            )

        if isSelect:
            if fetchAll:
                results = cursor.fetchall()
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"OracleConnection.executeCustomQuery: Fetched {len(results)} rows",
                    )
            else:
                results = cursor.fetchone()
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"OracleConnection.executeCustomQuery: Fetched single row: {results}",
                    )
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"OracleConnection.executeCustomQuery: Found columns: {columns}",
                    )
                formattedResults = [
                    dict(zip(columns, row))
                    for row in (results if isinstance(results, list) else [results] if results else [])
                ]
                return formattedResults

            return results if isinstance(results, list) else [results] if results else []
        else:
            rowCount = cursor.rowcount
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"OracleConnection.executeCustomQuery: Affected {rowCount} rows",
                )
            return rowCount

    def executeCustomQueryWithRetry(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> Any:
        """
        Run a query; on lost-connection errors, reconnect once and retry.
        Used by long-lived worker sessions that reuse one connection across tasks.
        """
        try:
            return self.executeCustomQuery(query, params=params, fetchAll=fetchAll)
        except Exception as e:
            if isAuthError(e) or not self.isConnectionError(e):
                raise
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection: connection error on {self.dsn}, reconnecting once: {e}",
                )
            self.reconnect()
            return self.executeCustomQuery(query, params=params, fetchAll=fetchAll)

    def callStoredProcedure(
        self,
        procedureName: str,
        params: Optional[List[Any]] = None,
        commit: bool = True,
        paramNames: Optional[List[str]] = None,
    ) -> List[Any]:
        """
        Call an Oracle stored procedure with positional parameters.

        params: values in procedure-definition order (None → NULL).
        commit: if True, commit after a successful call (needed for DML procedures).
        paramNames: optional labels for DEBUG logging only.
        """
        if not self.connection:
            raise RuntimeError("No active connection. Call connect() first.")

        paramList = list(params) if params is not None else []
        cursor = self.connection.cursor()
        startTime = time.time()

        try:
            if Config.debug:
                if paramNames and len(paramNames) == len(paramList):
                    paired = ', '.join(
                        f"{n}={self._formatParamForLog(v)}" for n, v in zip(paramNames, paramList)
                    )
                else:
                    paired = ', '.join(self._formatParamForLog(v) for v in paramList)
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.callStoredProcedure: {procedureName} on {self.dsn} "
                    f"params=[{paired}]",
                )

            output = cursor.callproc(procedureName, paramList)

            if commit:
                self.connection.commit()
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"oracleConnection.callStoredProcedure: committed {procedureName} "
                        f"on {self.dsn}",
                    )

            elapsed = time.time() - startTime
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.callStoredProcedure: {procedureName} OK in {elapsed:.3f}s",
                )
            return list(output) if output is not None else []
        except oracledb.Error as e:
            # Best-effort rollback so a failed write does not leave a dirty txn
            try:
                if commit and self.connection is not None:
                    self.connection.rollback()
            except Exception:
                pass
            Logic.logException(
                f"oracleConnection.callStoredProcedure: {procedureName} failed on {self.dsn}",
                e,
            )
            raise
        except Exception as e:
            try:
                if commit and self.connection is not None:
                    self.connection.rollback()
            except Exception:
                pass
            Logic.logException(
                f"oracleConnection.callStoredProcedure: unexpected error calling "
                f"{procedureName} on {self.dsn}",
                e,
            )
            raise
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    @staticmethod
    def _formatParamForLog(value):
        """Safe short string for DEBUG (no secrets expected in proc params)."""
        if value is None:
            return 'NULL'
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        text = repr(value)
        if len(text) > 80:
            return text[:77] + '...'
        return text

    def callStoredProcedureWithRetry(
        self,
        procedureName: str,
        params: Optional[List[Any]] = None,
        commit: bool = True,
        paramNames: Optional[List[str]] = None,
    ) -> List[Any]:
        """
        Call a stored procedure; on lost-connection errors, reconnect once and retry.
        Used by long-lived worker sessions that reuse one connection across writes.
        """
        try:
            return self.callStoredProcedure(
                procedureName, params=params, commit=commit, paramNames=paramNames
            )
        except Exception as e:
            if isAuthError(e) or not self.isConnectionError(e):
                raise
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.callStoredProcedureWithRetry: connection error on "
                    f"{self.dsn}, reconnecting once: {e}",
                )
            self.reconnect()
            return self.callStoredProcedure(
                procedureName, params=params, commit=commit, paramNames=paramNames
            )

    def close(self):
        """Return MCS sessions to the pool; otherwise close the Oracle handle."""
        conn = self.connection
        self.connection = None
        if getattr(self, "_fromMcsPool", False) and conn is not None:
            releaseMcsConnection(self.dsn, conn)
            self._fromMcsPool = False
            if Config.debug:
                Logic.logMessage("DEBUG", "oracleConnection.close: MCS session returned to pool")
            return
        try:
            if conn is not None:
                conn.close()
                if Config.debug:
                    Logic.logMessage("DEBUG", "oracleConnection.close: Connection closed.")
        except oracledb.Error as e:
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.close: Error closing connection: {e}",
                )

    def testConnection(self):
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.testConnection: Testing connection to {self.dsn}")       

        try:
            self.connect()
            result = self.executeCustomQuery("SELECT SYSDATE FROM DUAL", fetchAll=False)
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.testConnection: Query result: {result}")
            if result: Logic.logMessage("INFO", f"Successfully connected to {self.dsn} and fetched SYSDATE: {result[0]}")
            else: Logic.logMessage("WARN", f"Connected to {self.dsn} but no result from query")
            return True
        except Exception as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.testConnection: Failed to connect to {self.dsn}: {e}")
            Logic.logMessage("ERROR", f"Connected test failed: {e}")
            return False
        finally: 
            self.close()