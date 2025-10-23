import Oracle
import Logic

Logic.debug = True
conn = Oracle.oracleConnection("LCHDB")
conn.testConnection()