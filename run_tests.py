import sys,json,unittest
from datetime import datetime,timezone
from pathlib import Path
from tests.test_portal import PortalTests
record=[]
class Recorder(unittest.TextTestResult):
    def addSuccess(self,test):
        super().addSuccess(test);record.append({'name':test.shortDescription() or test.id(),'ok':True,'executed_at':datetime.now(timezone.utc).isoformat(),'scope':'Testes locais de API, banco e arquivos temporários'})
    def addFailure(self,test,err):
        super().addFailure(test,err);record.append({'name':test.shortDescription() or test.id(),'ok':False})
    def addError(self,test,err):
        super().addError(test,err);record.append({'name':test.shortDescription() or test.id(),'ok':False})
suite=unittest.defaultTestLoader.loadTestsFromTestCase(PortalTests)
result=unittest.TextTestRunner(verbosity=2,resultclass=Recorder).run(suite)
Path('TEST_RESULTS.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
sys.exit(not result.wasSuccessful())
