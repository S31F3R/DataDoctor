# Oracle.py

import oracledb
import platform
import os
import keyring
import time
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Any, Optional
from core import Logic, Config

# After a bad password, refuse further connect attempts for this process so we
# do not spam Oracle and lock the account (multi-thread HDB / multi-DSN queries).
authFailureMessage = None

# Instant Client + env must be configured once. sqlRead creates many connections
# (per SDID × date chunk × thread). Old code prepended clientDir to PATH on every
# construct → after enough HDB tasks Windows hit: ValueError environment variable
# longer than 32767 characters.
clientInitLock = threading.Lock()
clientInitialized = False


class OracleAuthError(RuntimeError):
    """Wrong username/password or locked account — do not retry."""
    pass

def clearAuthFailure():
    """Call after the user updates Oracle credentials in Options."""
    global authFailureMessage
    authFailureMessage = None

def isAuthError(exc) -> bool:
    """True if this looks like bad credentials / locked account."""
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

def ensureOracleClientReady():
    """
    One-time Instant Client init + TNS_ADMIN. Safe to call from any thread;
    concurrent callers block until the first setup finishes.
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

        clientDirPath = "oracle/client"
        clientDir = Path(Logic.resourcePath(clientDirPath))
        if not clientDir.exists():
            raise FileNotFoundError(
                f"Oracle Instant Client directory not found: {clientDir}. "
                "Please download and unzip the Instant Client 23.9 for your platform into oracle/client."
            )

        expectedFiles = {
            "windows": ["oci.dll"],
            "linux": ["libociei.so"],
            "darwin": ["libociei.dylib"],
        }
        requiredFiles = expectedFiles.get(system)
        if not requiredFiles:
            raise RuntimeError(f"Unsupported platform: {system}")
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"oracleConnection.setup: Checking for platform-specific files in {clientDir}: {requiredFiles}",
            )
        filesExist = all((clientDir / f).exists() for f in requiredFiles)
        if not filesExist:
            raise FileNotFoundError(
                f"Oracle Instant Client files for {system.capitalize()} not found in {clientDir}. "
                "Please download and unzip the correct Instant Client 23.9 for your platform into oracle/client."
            )
        if Config.debug:
            Logic.logMessage("DEBUG", f"oracleConnection.setup: Validated Instant Client files for {system}")

        ensureClientOnPath(clientDir)

        try:
            oracledb.init_oracle_client(lib_dir=str(clientDir))
        except Exception as e:
            # Already initialized in this process is fine
            msg = str(e).lower()
            if "already been initialized" in msg or "has already been called" in msg:
                if Config.debug:
                    Logic.logMessage("DEBUG", "oracleConnection.setup: Instant Client already initialized")
            else:
                raise

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"oracleConnection.setup: Initialized oracledb with clientDir {clientDir}",
            )

        # TNS_ADMIN: prefer existing env (user tnsnames), else bundled admin
        envTns = os.environ.get('TNS_ADMIN')
        if envTns:
            if Config.debug:
                Logic.logMessage("DEBUG", f"oracleConnection.setup: Using env TNS_ADMIN: {envTns} (no copy)")
        else:
            resourceAdmin = Logic.resourcePath('oracle/network/admin')
            os.environ['TNS_ADMIN'] = resourceAdmin
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"oracleConnection.setup: Set TNS_ADMIN to program's path: {resourceAdmin} (no copy)",
                )

        clientInitialized = True

class oracleConnection:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection = None
        ensureOracleClientReady()

    def connect(self) -> oracledb.Connection:
        """Establish Oracle connection with PIV/MCS and user credentials."""
        global authFailureMessage

        # Do not hammer Oracle after a failed login (account lock protection)
        if authFailureMessage:
            raise OracleAuthError(authFailureMessage)

        try:
            user = keyring.get_password("DataDoctor", "oracleUser") or ''
            password = keyring.get_password("DataDoctor", "oraclePassword") or ''

            if not user or not password:
                if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.connect: Missing Oracle credentials")
                raise ValueError("Oracle username or password not set in keyring")
            
            self.connection = oracledb.connect(user=user, password=password, dsn=self.dsn)
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.connect: Connection established to {self.dsn}")
            # Successful login clears any prior auth block
            authFailureMessage = None
            user = None
            password = None
            return self.connection
        except OracleAuthError:
            raise
        except oracledb.Error as e:
            if isAuthError(e):
                authFailureMessage = (
                    "Oracle login failed: wrong username/password or account locked. "
                    "Fix credentials in Options — further connect attempts are blocked "
                    "this session to avoid locking the account."
                )
                Logic.logMessage("ERROR", f"oracleConnection.connect: Auth failure for {self.dsn}: {e}")
                raise OracleAuthError(authFailureMessage) from e
            Logic.logException(f"oracleConnection.connect: Error connecting to Oracle ({self.dsn})", e)
            user = None
            password = None
            raise
        except Exception as e:
            if isAuthError(e):
                authFailureMessage = (
                    "Oracle login failed: wrong username/password or account locked. "
                    "Fix credentials in Options — further connect attempts are blocked "
                    "this session to avoid locking the account."
                )
                Logic.logMessage("ERROR", f"oracleConnection.connect: Auth failure for {self.dsn}: {e}")
                raise OracleAuthError(authFailureMessage) from e
            Logic.logException(f"oracleConnection.connect: Unexpected error ({self.dsn})", e)
            user = None
            password = None
            raise

    def reconnect(self) -> oracledb.Connection:
        """Close any existing session and open a new one (same DSN/credentials)."""
        try:
            if self.connection is not None:
                self.connection.close()
        except Exception:
            pass
        self.connection = None
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

        if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Query '{query[:100]}' has bind vars: {hasBindVars}")

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
        if Config.debug:
            Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Validating query: {exactQuery}")

        if params:
            cursor.execute(exactQuery, params)
        else:
            cursor.execute(exactQuery)

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"OracleConnection.executeCustomQuery: Executed query: {exactQuery[:100]} with params {params}",
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
        """Close connection and clean up TNS_ADMIN directory."""
        try:
            if self.connection:
                self.connection.close()
                if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.close: Connection closed.")
        except oracledb.Error as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.close: Error closing connection: {e}")
        finally:
            pass # No temp dir to clean

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