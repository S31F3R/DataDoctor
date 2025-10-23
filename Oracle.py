import oracledb
import platform
import os
import tempfile
import shutil
import keyring
from pathlib import Path
from typing import List, Any, Optional
import Logic

class OracleConnection:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection = None
        self.tnsDir = None
        self._setup()

    def _setup(self):
        """Set up bundled Instant Client and TNS_ADMIN."""
        system = platform.system().lower()
        if platform.architecture()[0] != "64bit": raise RuntimeError("Only 64-bit platforms supported.")
        clientPaths = {
            "windows": "oracle/windows",
            "linux": "oracle/linux",
            "darwin": "oracle/macos"
        }

        clientPath = clientPaths.get(system)
        if not clientPath: raise RuntimeError(f"Unsupported platform: {system}")
        clientDir = Path(Logic.resourcePath(clientPath))
        if not clientDir.exists(): raise FileNotFoundError(f"Instant Client directory not found: {clientDir}")
        if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Using bundled Instant Client from {clientDir}")
        
        # Set platform-specific library path
        if system == "windows":
            os.environ['PATH'] = f"{clientDir};{os.environ.get('PATH', '')}"
        elif system == "linux":
            os.environ['LD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        elif system == "darwin":
            os.environ['DYLD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('DYLD_LIBRARY_PATH', '')}"

        oracledb.init_oracle_client(lib_dir=str(clientDir))
        if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Initialized oracledb with clientDir {clientDir}")

        # Setup TNS_ADMIN
        config = Logic.loadConfig()
        tnsAdmin = config.get('tnsNamesLocation')

        if not tnsAdmin: tnsAdmin = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin'))
        if tnsAdmin.startswith('%AppRoot%'): tnsAdmin = tnsAdmin.replace('%AppRoot%', Logic.appRoot)
        srcAdminDir = Path(tnsAdmin)

        if not srcAdminDir.exists():
            srcAdminDir = Path(Logic.resourcePath('oracle/network/admin'))            
            if Logic.debug: print(f"[DEBUG] OracleConnection._setup: tnsNamesLocation {tnsAdmin} not found, falling back to {srcAdminDir}")

        self.tnsDir = Path(tempfile.mkdtemp())
        tnsPath = self.tnsDir / "tnsnames.ora"
        sqlnetPath = self.tnsDir / "sqlnet.ora"

        if (srcAdminDir / "tnsnames.ora").exists():
            shutil.copy(srcAdminDir / "tnsnames.ora", tnsPath)
            if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Copied tnsnames.ora to {tnsPath}")
        else:
            tnsPath.write_text("")
            if Logic.debug: print("[DEBUG] OracleConnection._setup: Created empty tnsnames.ora")

        if (srcAdminDir / "sqlnet.ora").exists():
            sqlnetContent = (srcAdminDir / "sqlnet.ora").read_text()

            # Check for user-provided wallet (fallback for non-PIV mTLS)
            srcWalletDir = srcAdminDir / "wallet"

            if srcWalletDir.exists():
                walletDir = self.tnsDir / "wallet"
                shutil.copytree(srcWalletDir, walletDir)

                if "(METHOD_DATA = (DIRECTORY = " not in sqlnetContent:
                    sqlnetContent = sqlnetContent.replace("(METHOD = MCS)", f"(METHOD = MCS)(METHOD_DATA = (DIRECTORY = {walletDir}))")
                else:
                    sqlnetContent = sqlnetContent.replace(r"(METHOD_DATA = \(DIRECTORY = [^)]+\))", f"(METHOD_DATA = (DIRECTORY = {walletDir}))")

                if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Updated sqlnet.ora WALLET_LOCATION to {walletDir}")

            sqlnetPath.write_text(sqlnetContent)            
            if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Copied/updated sqlnet.ora to {sqlnetPath}")
        else:
            raise FileNotFoundError("sqlnet.ora not found for PIV/MCS configuration.")

        os.environ['TNS_ADMIN'] = str(self.tnsDir)
        if Logic.debug: print(f"[DEBUG] OracleConnection._setup: Set TNS_ADMIN to {self.tnsDir}")

    def connect(self) -> oracledb.Connection:
        """Establish Oracle connection with PIV/MCS and user credentials."""
        try:
            user = keyring.get_password("DataDoctor", "oracleUser") or ''
            password = keyring.get_password("DataDoctor", "oraclePassword") or ''

            if not user or not password:
                if Logic.debug: print("[DEBUG] OracleConnection.connect: Missing Oracle credentials")
                raise ValueError("Oracle username or password not set in keyring")
            self.connection = oracledb.connect(user=user, password=password, dsn=self.dsn)
            if Logic.debug: print(f"[DEBUG] OracleConnection.connect: Connection established to {self.dsn}")
            user = None
            password = None
            return self.connection
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] OracleConnection.connect: Error connecting to Oracle: {e}")
            user = None
            password = None
            raise
        except Exception as e:
            if Logic.debug: print(f"[DEBUG] OracleConnection.connect: Unexpected error: {e}")
            user = None
            password = None
            raise

    def executeSqlQuery(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> List[Any]:
        """Execute a SQL SELECT query and return results in timestamp,value format."""
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")
        cursor = self.connection.cursor()
        cursor.arraysize = 1000
        cursor.prefetchrows = 2000
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            if Logic.debug:
                print(f"[DEBUG] OracleConnection.executeSqlQuery: Executed query: {query[:100]}...")
            if fetchAll:
                results = cursor.fetchall()
                if Logic.debug: print(f"[DEBUG] OracleConnection.executeSqlQuery: Fetched {len(results)} rows")
            else:
                results = cursor.fetchone()
                if Logic.debug: print(f"[DEBUG] OracleConnection.executeSqlQuery: Fetched single row: {results}")

            formattedResults = []

            for row in (results if isinstance(results, list) else [results]):
                if len(row) >= 2:
                    timestamp = row[0].strftime('%m/%d/%y %H:%M:00') if isinstance(row[0], datetime) else str(row[0])
                    value = str(row[1]) if row[1] is not None else ''
                    formattedResults.append(f"{timestamp},{value}")

            if Logic.debug: print(f"[DEBUG] OracleConnection.executeSqlQuery: Formatted {len(formattedResults)} rows")
            return formattedResults
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] OracleConnection.executeSqlQuery: Error executing query: {e}")
            raise
        finally:
            cursor.close()
            if Logic.debug: print("[DEBUG] OracleConnection.executeSqlQuery: Cursor closed")

    def callStoredProcedure(self, procedureName: str, params: Optional[List[Any]] = None) -> List[Any]:
        """Call an Oracle stored procedure and return output values."""
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")
        cursor = self.connection.cursor()

        try:
            output = cursor.callproc(procedureName, params or [])
            if Logic.debug: print(f"[DEBUG] OracleConnection.callStoredProcedure: Called {procedureName} with params: {params}")
            return output
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] OracleConnection.callStoredProcedure: Error calling procedure: {e}")
            raise
        finally:
            cursor.close()
            if Logic.debug: print("[DEBUG] OracleConnection.callStoredProcedure: Cursor closed")

    def close(self):
        """Close connection and clean up TNS_ADMIN directory."""
        try:
            if self.connection:
                self.connection.close()
                if Logic.debug: print("[DEBUG] OracleConnection.close: Connection closed.")
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] OracleConnection.close: Error closing connection: {e}")
        finally:
            if self.tnsDir:
                shutil.rmtree(self.tnsDir, ignore_errors=True)
                if Logic.debug: print("[DEBUG] OracleConnection.close: Cleaned up TNS_ADMIN directory")