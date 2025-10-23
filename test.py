import Oracle
import Logic

Logic.debug = True
conn = Oracle.oracleConnection("LCHDB")
conn.connect()
result = conn.executeCustomQuery("SELECT SYSDATE FROM DUAL", params=[None], fetchAll=False)
print(result)
conn.close()