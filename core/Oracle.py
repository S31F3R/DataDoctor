# Oracle.py

import oracledb
import platform
import os
import tempfile
import shutil
import keyring
import time
import re
from pathlib import Path
from typing import List, Any, Optional
from core import Logic, Config, Utils

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
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Checking for platform-specific files in {clientDir}: {requiredFiles}")
        filesExist = all((clientDir / f).exists() for f in requiredFiles)
        if not filesExist: raise FileNotFoundError(f"Oracle Instant Client files for {system.capitalize()} not found in {clientDir}. Please download and unzip the correct Instant Client 23.9 for your platform into oracle/client.")
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Validated Instant Client files for {system}")

        # Set platform-specific library path
        if system == "windows":
            os.environ['PATH'] = f"{clientDir};{os.environ.get('PATH', '')}"
        elif system == "linux":
            os.environ['LD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        elif system == "darwin":
            os.environ['DYLD_LIBRARY_PATH'] = f"{clientDir}:{os.environ.get('DYLD_LIBRARY_PATH', '')}"

        oracledb.init_oracle_client(lib_dir=str(clientDir))
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Initialized oracledb with clientDir {clientDir}")

        # Setup TNS_ADMIN with program's sqlnet.ora always, and tnsnames.ora from env if exists (copy to temp)
        self.tnsDir = tempfile.mkdtemp()
        programAdmin = Logic.resourcePath('oracle/network/admin')
        shutil.copy(os.path.join(programAdmin, 'sqlnet.ora'), self.tnsDir)
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Copied program's sqlnet.ora to temp {self.tnsDir}")

        envTns = os.environ.get('TNS_ADMIN')
        tnsFile = 'tnsnames.ora'
        if envTns:
            userTnsPath = os.path.join(envTns, tnsFile)
            if os.path.exists(userTnsPath):
                shutil.copy(userTnsPath, self.tnsDir)
                if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Copied user's tnsnames.ora from {envTns} to temp {self.tnsDir}")
            else:
                shutil.copy(os.path.join(programAdmin, tnsFile), self.tnsDir)
                if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: User tnsnames.ora not found, copied program's to temp {self.tnsDir}")
        else:
            shutil.copy(os.path.join(programAdmin, tnsFile), self.tnsDir)
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: No env TNS_ADMIN, copied program's tnsnames.ora to temp {self.tnsDir}")

        os.environ['TNS_ADMIN'] = self.tnsDir
        if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection._setup: Set TNS_ADMIN to temp {self.tnsDir}")

    def connect(self) -> oracledb.Connection:
        """Establish Oracle connection with PIV/MCS and user credentials."""
        try:
            user = keyring.get_password("DataDoctor", "oracleUser") or ''
            password = keyring.get_password("DataDoctor", "oraclePassword") or ''

            if not user or not password:
                if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.connect: Missing Oracle credentials")
                raise ValueError("Oracle username or password not set in keyring")
            
            self.connection = oracledb.connect(user=user, password=password, dsn=self.dsn)
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.connect: Connection established to {self.dsn}")
            user = None
            password = None
            return self.connection
        except oracledb.Error as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.connect: Error connecting to Oracle: {e}")
            user = None
            password = None
            raise
        except Exception as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.connect: Unexpected error: {e}")
            user = None
            password = None
            raise

    def executeCustomQuery(self, query: str, params: Optional[List[Any]] = None, fetchAll: bool = True) -> Any:
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")

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
            exactQuery = query 
            if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Validating query: {exactQuery}")

            if params:
                cursor.execute(exactQuery, params)
            else:
                cursor.execute(exactQuery)

            if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Executed query: {exactQuery[:100]} with params {params}")
            isSelect = cursor.description is not None
            executionTime = time.time() - startTime
            if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Query executed in {executionTime:.3f} seconds")

            if isSelect:
                if fetchAll:
                    results = cursor.fetchall()
                    if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Fetched {len(results)} rows")
                else:
                    results = cursor.fetchone()
                    if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Fetched single row: {results}")
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Found columns: {columns}")
                    formattedResults = [dict(zip(columns, row)) for row in (results if isinstance(results, list) else [results] if results else [])]
                    return formattedResults

                return results if isinstance(results, list) else [results] if results else []
            else:
                rowCount = cursor.rowcount
                if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Affected {rowCount} rows")
                return rowCount
        except oracledb.Error as e:
            if Config.debug: Logic.logMessage("DEBUG", f"OracleConnection.executeCustomQuery: Oracle error: {e}")
            raise
        finally:
            cursor.close()
            if Config.debug: Logic.logMessage("DEBUG", "OracleConnection.executeCustomQuery: Cursor closed")         

    def callStoredProcedure(self, procedureName: str, params: Optional[List[Any]] = None) -> List[Any]:
        """Call an Oracle stored procedure and return output values."""
        if not self.connection: raise RuntimeError("No active connection. Call connect() first.")
        cursor = self.connection.cursor()

        try:
            output = cursor.callproc(procedureName, params or [])
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.callStoredProcedure: Called {procedureName} with params: {params}")
            return output
        except oracledb.Error as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.callStoredProcedure: Error calling procedure: {e}")
            raise
        finally:
            cursor.close()
            if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.callStoredProcedure: Cursor closed")

    def close(self):
        """Close connection and clean up TNS_ADMIN directory."""
        try:
            if self.connection:
                self.connection.close()
                if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.close: Connection closed.")
        except oracledb.Error as e:
            if Config.debug: Logic.logMessage("DEBUG", f"oracleConnection.close: Error closing connection: {e}")
        finally:
            if self.tnsDir:
                shutil.rmtree(self.tnsDir, ignore_errors=True)
                if Config.debug: Logic.logMessage("DEBUG", "oracleConnection.close: Cleaned up TNS_ADMIN directory")

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