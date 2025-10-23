import oracledb
import platform
import os
import tempfile
import shutil
import keyring
import Logic
import time
from pathlib import Path
from typing import List, Any, Optional
from datetime import datetime

class oracleConnection:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection = None
        self.tnsDir = None
        self._setup()

    def _setup(self):
        """Set up bundled Instant Client and TNS_ADMIN."""
        system = platform.system().lower()
        if platform.architecture()[0] != "64bit": raise RuntimeError("Only 64-bit platforms supported.")
        clientDirPath = "oracle/client"
        clientDir = Path(Logic.resourcePath(clientDirPath))
        if not clientDir.exists(): raise FileNotFoundError(f"Oracle Instant Client directory not found: {clientDir}. Please download and unzip the Instant Client 23.9 for your platform into oracle/client.")
        
        # Validate platform-specific files
        expectedFiles = {
            "windows": ["oci.dll"],
            "linux": ["libociei.so"],
            "darwin": ["libociei.dylib"]
        }

        requiredFiles = expectedFiles.get(system)
        if not requiredFiles: raise RuntimeError(f"Unsupported platform: {system}")
        if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Checking for platform-specific files in {clientDir}: {requiredFiles}")
        filesExist = all((clientDir / f).exists() for f in requiredFiles)
        if not filesExist: raise FileNotFoundError(f"Oracle Instant Client files for {system.capitalize()} not found in {clientDir}. Please download and unzip the correct Instant Client 23.9 for your platform into oracle/client.")
        if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Validated Instant Client files for {system}")

        # Set platform-specific library path
        if system == "windows":
            os.environ['PATH'] = f"{clientDir};{os.environ.get('PATH', '')}"
        elif system == "linux":
            os.environ['LD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        elif system == "darwin":
            os.environ['DYLD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('DYLD_LIBRARY_PATH', '')}"

        oracledb.init_oracle_client(lib_dir=str(clientDir))
        if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Initialized oracledb with clientDir {clientDir}")

        # Setup TNS_ADMIN 
        config = Logic.loadConfig()
        tnsAdmin = config.get('tnsNamesLocation')
        if not tnsAdmin: tnsAdmin = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin'))
        if tnsAdmin.startswith('%AppRoot%'): tnsAdmin = tnsAdmin.replace('%AppRoot%', Logic.appRoot)
        srcAdminDir = Path(tnsAdmin)

        if not srcAdminDir.exists():
            srcAdminDir = Path(Logic.resourcePath('oracle/network/admin'))
            if Logic.debug: print(f"[DEBUG] oracleConnection._setup: tnsNamesLocation {tnsAdmin} not found, falling back to {srcAdminDir}")

        self.tnsDir = Path(tempfile.mkdtemp())
        tnsPath = self.tnsDir / "tnsnames.ora"
        sqlnetPath = self.tnsDir / "sqlnet.ora"

        if (srcAdminDir / "tnsnames.ora").exists():
            shutil.copy(srcAdminDir / "tnsnames.ora", tnsPath)
            if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Copied tnsnames.ora to {tnsPath}")
        else:
            tnsPath.write_text("")
            if Logic.debug: print("[DEBUG] oracleConnection._setup: Created empty tnsnames.ora")
        if (srcAdminDir / "sqlnet.ora").exists():
            sqlnetContent = (srcAdminDir / "sqlnet.ora").read_text()
            srcWalletDir = srcAdminDir / "wallet"

            if srcWalletDir.exists():
                walletDir = self.tnsDir / "wallet"
                shutil.copytree(srcWalletDir, walletDir)

                if "(METHOD_DATA = (DIRECTORY = " not in sqlnetContent:
                    sqlnetContent = sqlnetContent.replace(
                        "(METHOD = MCS)",
                        f"(METHOD = MCS)(METHOD_DATA = (DIRECTORY = {walletDir}))"
                    )
                else:
                    sqlnetContent = sqlnetContent.replace(
                        r"(METHOD_DATA = \(DIRECTORY = [^)]+\))",
                        f"(METHOD_DATA = (DIRECTORY = {walletDir}))"
                    )

                if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Updated sqlnet.ora WALLET_LOCATION to {walletDir}")

            sqlnetPath.write_text(sqlnetContent)
            if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Copied/updated sqlnet.ora to {sqlnetPath}")
        else:
            raise FileNotFoundError("sqlnet.ora not found for PIV/MCS configuration.")
        
        os.environ['TNS_ADMIN'] = str(self.tnsDir)
        if Logic.debug: print(f"[DEBUG] oracleConnection._setup: Set TNS_ADMIN to {self.tnsDir}")

    def connect(self) -> oracledb.Connection:
        """Establish Oracle connection with PIV/MCS and user credentials."""
        try:
            user = keyring.get_password("DataDoctor", "oracleUser") or ''
            password = keyring.get_password("DataDoctor", "oraclePassword") or ''

            if not user or not password:
                if Logic.debug: print("[DEBUG] oracleConnection.connect: Missing Oracle credentials")
                raise ValueError("Oracle username or password not set in keyring")
            
            self.connection = oracledb.connect(user=user, password=password, dsn=self.dsn)
            if Logic.debug: print(f"[DEBUG] oracleConnection.connect: Connection established to {self.dsn}")
            user = None
            password = None
            return self.connection
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.connect: Error connecting to Oracle: {e}")
            user = None
            password = None
            raise
        except Exception as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.connect: Unexpected error: {e}")
            user = None
            password = None
            raise

    def executeQuery(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> List[Any]:
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
                print(f"[DEBUG] oracleConnection.executeQuery: Executed query: {query[:100]}...")
            if fetchAll:
                results = cursor.fetchall()
                if Logic.debug: print(f"[DEBUG] oracleConnection.executeQuery: Fetched {len(results)} rows")
            else:
                results = cursor.fetchone()
                if Logic.debug: print(f"[DEBUG] oracleConnection.executeQuery: Fetched single row: {results}")

            formattedResults = []

            for row in (results if isinstance(results, list) else [results]):
                if len(row) >= 2:
                    timestamp = row[0].strftime('%m/%d/%y %H:%M:00') if isinstance(row[0], datetime) else str(row[0])
                    value = str(row[1]) if row[1] is not None else ''
                    formattedResults.append(f"{timestamp},{value}")
                else: 
                    timestamp = row[0].strftime('%m/%d/%y %H:%M:00') if isinstance(row[0], datetime) else str(row[0])
                    value = ''

                formattedResults.append(f"{timestamp},{value}")

            if Logic.debug: print(f"[DEBUG] oracleConnection.executeQuery: Formatted {len(formattedResults)} rows")
            return formattedResults
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.executeQuery: Error executing query: {e}")
            raise
        finally:
            cursor.close()
            if Logic.debug: print("[DEBUG] oracleConnection.executeQuery: Cursor closed")

    def executeCustomQuery(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> Any:
        """Execute a SQL SELECT query and return results in timestamp,value format."""
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")

        if not params or not isinstance(params, (list, tuple)):
            if Logic.debug: print("[DEBUG] oracleConnection.executeCustomQuery: No or invalid params provided, risking SQL injection")
            raise ValueError("Params must be a non-empty list or tuple to prevent SQL injection")
        
        cursor = self.connection.cursor()
        cursor.arraysize = 1000
        cursor.prefetchrows = 2000     
        startTime = time.time()        

        try:
            cursor.execute(query, params)
            if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Executed query: {query[:100]} with params {params}")
            isSelect = cursor.description is not None
            executionTime = time.time() - startTime
            if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Query executed in {executionTime:.3f} seconds")
                
            if isSelect:
                if fetchAll:
                    results = cursor.fetchall()
                    if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Fetched {len(results)} rows")
                else: 
                    results = cursor.fetchone()
                    if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Fetched single row: {results}")

                if cursor.description: 
                    columns = [desc[0] for desc in cursor.description]
                    if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Found columns: {columns}")
                    formattedResults = [dict(zip(columns, row)) for row in (results if isinstance(results, list) else [results] if results else [])]
                    return formattedResults
                
                return results if isinstance(results, list) else [results] if results else []
            else:
                rowCount = cursor.rowcount  
                if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Affected {rowCount} rows")  
                return rowCount
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Oracle error: {e}")
            raise
        finally:
            cursor.close()
            if Logic.debug: print(f"[DEBUG] oracleConnection.executeCustomQuery: Cursor closed")

            

    def callStoredProcedure(self, procedureName: str, params: Optional[List[Any]] = None) -> List[Any]:
        """Call an Oracle stored procedure and return output values."""
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")
        cursor = self.connection.cursor()

        try:
            output = cursor.callproc(procedureName, params or [])
            if Logic.debug: print(f"[DEBUG] oracleConnection.callStoredProcedure: Called {procedureName} with params: {params}")
            return output
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.callStoredProcedure: Error calling procedure: {e}")
            raise
        finally:
            cursor.close()
            if Logic.debug: print("[DEBUG] oracleConnection.callStoredProcedure: Cursor closed")

    def close(self):
        """Close connection and clean up TNS_ADMIN directory."""
        try:
            if self.connection:
                self.connection.close()
                if Logic.debug: print("[DEBUG] oracleConnection.close: Connection closed.")
        except oracledb.Error as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.close: Error closing connection: {e}")
        finally:
            if self.tnsDir:
                shutil.rmtree(self.tnsDir, ignore_errors=True)
                if Logic.debug: print("[DEBUG] oracleConnection.close: Cleaned up TNS_ADMIN directory")

    def testConnection(self):
        if Logic.debug: print(f"[DEBUG] oracleConnection.testConnection: Testing connection to {self.dsn}")       

        try:
            self.connect()
            result = self.executeQuery("SELECT SYSDATE FROM DUAL", fetchAll=False)
            if Logic.debug: print(f"[DEBUG] oracleConnection.testConnection: Query result: {result}")
            if result: print(f"[INFO] Successfully connected to {self.dsn} and fetched SYSDATE: {result[0]}")
            else: print(f"[WARN] Connected to {self.dsn} but no result from query")
            return True
        except Exception as e:
            if Logic.debug: print(f"[DEBUG] oracleConnection.testConnection: Failed to connect to {self.dsn}: {e}")
            print(f"[ERROR] Connected test failed: {e}")
            return False
        finally: 
            self.close()