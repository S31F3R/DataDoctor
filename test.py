import Oracle
import Logic

Logic.debug = True
conn = Oracle.oracleConnection("LCHDB")
conn.connect()
#result = conn.executeCustomQuery("SELECT SYSDATE FROM DUAL", params=None, fetchAll=False)
result = conn.executeCustomQuery("SELECT * FROM BLYTHE_DMDEI WHERE id = :1", params=[1], fetchAll=True)
print(result)
conn.close()