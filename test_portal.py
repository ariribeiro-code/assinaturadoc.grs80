import base64,concurrent.futures,io,json,secrets,sqlite3,tempfile,unittest,uuid,zipfile
from pathlib import Path
from app import create_app,connect,PH,uid,CONSENT
from pdf_tools import sample_pdf,sample_fields
from backup_tools import restore
from pypdf import PdfReader

class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'data'; self.app=create_app(self.path,testing=True)
        self.pw=secrets.token_urlsafe(18); self.ids={}
        c=connect(self.path/'portal.db')
        for login,role in [('rh','rh'),('ana','employee'),('bruno','employee')]:
            id=uid();self.ids[login]=id;c.execute('INSERT INTO users VALUES(?,?,?,?,?,1,0,0)',(id,login,login.title(),role,PH.hash(self.pw)))
        c.close();self.rh=self.client('rh');self.a=self.client('ana');self.b=self.client('bruno')
    def tearDown(self):self.temp.cleanup()
    def client(self,name):
        c=self.app.test_client();r=c.post('/api/login',json={'login':name,'password':self.pw});self.assertEqual(r.status_code,200,r.json);c.csrf=c.get('/api/me').json['csrf'];return c
    def post(self,c,path,data=None,**kw):return c.post(path,json=data if not kw else None,headers={'X-CSRF-Token':c.csrf},**kw)
    def upload(self,required=True):
        cat=self.rh.get('/api/categories').json[0]['id'];f=sample_pdf(['Ana','Bruno'],'Fictício',True)
        r=self.rh.post('/api/batches',data={'file':(io.BytesIO(f),'test.pdf'),'title':'Lote teste','category':cat,'period':'2026-10','required':str(required).lower()},headers={'X-CSRF-Token':self.rh.csrf});self.assertEqual(r.status_code,200,r.json);return r.json['id']
    def release(self,b,required=True):
        ass=[{'user_id':self.ids[k],'reviewed':True,'single_person':True,'fields':sample_fields(True) if required else []} for k in ['ana','bruno']]
        r=self.post(self.rh,f'/api/batches/{b}/release',{'assignments':ass});self.assertEqual(r.status_code,200,r.json)
        return self.a.get('/api/documents').json[0],self.b.get('/api/documents').json[0]
    def sign(self,c,d,key=None):return self.post(c,f"/api/documents/{d['id']}/sign",{'key':key or str(uuid.uuid4()),'hash':d['hash'],'consent':True,'strokes':[[[.1,.7],[.2,.2],[.3,.6],[.4,.3],[.5,.65],[.7,.3],[.85,.55]]]})
    def test_01_login_csrf_and_roles(self):
        "Login, proteção CSRF e funções restritas ao RH"
        c=self.app.test_client();self.assertEqual(c.get('/api/documents').status_code,401)
        self.assertEqual(c.post('/api/login',json={'login':'rh','password':self.pw},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.a.get('/api/users').status_code,403)
        self.assertEqual(self.a.post('/api/logout',json={}).status_code,403)
        self.assertEqual(self.post(self.a,'/api/users',{'login':'hacker','name':'X','role':'rh'}).status_code,403)
        self.assertEqual(c.post('/api/login',json={'login':'rh','password':'wrong'}).status_code,401)
    def test_02_isolation_download_and_storage(self):
        "Funcionário A não lê documentos, imagens ou downloads de B"
        b=self.upload();a,d=self.release(b)
        self.assertEqual(len(self.a.get('/api/documents').json),1)
        for suffix in ['', '/file','/pages/0']:
            self.assertEqual(self.a.get(f"/api/documents/{d['id']}"+suffix).status_code,404)
        self.assertEqual(self.a.get('/api/batches/'+b).status_code,403)
        self.assertEqual(self.a.get('/api/backup').status_code,403)
        self.assertEqual(self.sign(self.a,d).status_code,404)
        self.assertEqual(self.a.get('/files/test.pdf').status_code,404)
        raw=self.a.get(f"/api/documents/{a['id']}/file").data
        self.assertEqual(len(PdfReader(io.BytesIO(raw)).pages),1)
        self.assertNotIn(b'Bruno',raw)
    def test_03_review_mandatory_and_dual_fields(self):
        "Liberação exige revisão, titular único, assinatura e data"
        b=self.upload();ass=[{'user_id':self.ids[k],'reviewed':True,'single_person':True,'fields':sample_fields(True)} for k in ['ana','bruno']]
        ass[0]['single_person']=False;self.assertEqual(self.post(self.rh,f'/api/batches/{b}/release',{'assignments':ass}).status_code,400)
        ass[0]['single_person']=True;ass[0]['fields']=[];self.assertEqual(self.post(self.rh,f'/api/batches/{b}/release',{'assignments':ass}).status_code,400)
        self.assertEqual(self.rh.get('/api/documents').json,[])
    def test_04_signed_persistence_idempotency_and_exports(self):
        "Assinatura persistida, repetição segura e PDF/ZIP completos"
        b=self.upload();a,d=self.release(b);key=str(uuid.uuid4())
        self.assertEqual(self.rh.get(f'/api/batches/{b}/export/pdf').status_code,409)
        self.assertEqual(self.sign(self.a,a,key).status_code,200);self.assertEqual(self.sign(self.a,a,key).status_code,200)
        fresh=self.client('ana');self.assertEqual(fresh.get(f"/api/documents/{a['id']}").json['status'],'signed')
        final=self.a.get(f"/api/documents/{a['id']}/file").data;self.assertEqual(len(PdfReader(io.BytesIO(final)).pages),2)
        st=self.rh.get('/api/batches/'+b).json['stats'];self.assertEqual(st['signed'],1);self.assertFalse(st['complete'])
        self.assertEqual(self.sign(self.b,d).status_code,200)
        self.assertTrue(self.rh.get('/api/batches/'+b).json['stats']['complete'])
        r=self.rh.get(f'/api/batches/{b}/export/pdf');self.assertEqual(r.status_code,200);self.assertEqual(len(PdfReader(io.BytesIO(r.data)).pages),4)
        z=self.rh.get(f'/api/batches/{b}/export/zip');self.assertEqual(z.status_code,200);self.assertEqual(len(zipfile.ZipFile(io.BytesIO(z.data)).namelist()),3)
        c=connect(self.path/'portal.db');self.assertEqual(c.execute('SELECT count(*) FROM evidence').fetchone()[0],2)
        with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE documents SET hash='fake' WHERE id=?",(a['id'],))
        c.close()
    def test_05_storage_failure_and_retry(self):
        "Falha no armazenamento não marca assinado; nova tentativa funciona"
        b=self.upload();a,_=self.release(b);self.app.config['FAIL_STORAGE']=True;key=str(uuid.uuid4())
        self.assertEqual(self.sign(self.a,a,key).status_code,503)
        self.assertEqual(self.a.get(f"/api/documents/{a['id']}").json['status'],'pending')
        self.app.config['FAIL_STORAGE']=False;self.assertEqual(self.sign(self.a,a,key).status_code,200)
    def test_06_consultation_not_signature(self):
        "Lote de consulta não exibe falso 100% de assinaturas"
        b=self.upload(False);a,_=self.release(b,False);st=self.rh.get('/api/batches/'+b).json['stats'];self.assertIsNone(st['percent']);self.assertFalse(st['complete']);self.assertEqual(st['pending'],0)
        self.assertEqual(self.sign(self.a,a).status_code,409);self.assertEqual(self.rh.get(f'/api/batches/{b}/export/zip').status_code,200)
    def test_07_divergence_and_new_version(self):
        "Divergência bloqueia assinatura; correção preserva versão anterior"
        b=self.upload();a,_=self.release(b)
        r=self.post(self.a,f"/api/documents/{a['id']}/issue",{'message':'Preciso corrigir o período.'});self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.sign(self.a,a).status_code,409)
        issue=self.rh.get('/api/issues').json[0];self.assertEqual(self.post(self.rh,f"/api/issues/{issue['id']}/resolve",{'response':'Conferimos e está correto.'}).status_code,200)
        self.assertEqual(self.sign(self.a,a).status_code,200)
        oldfile=self.a.get(f"/api/documents/{a['id']}/file").data
        f=sample_pdf(['Ana'],'Correção')
        r=self.rh.post(f"/api/documents/{a['id']}/version",data={'file':(io.BytesIO(f),'v2.pdf'),'reviewed':'true','fields':json.dumps(sample_fields())},headers={'X-CSRF-Token':self.rh.csrf});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.a.get(f"/api/documents/{r.json['id']}").json['status'],'pending')
        self.assertEqual(self.a.get(f"/api/documents/{a['id']}").json['status'],'superseded')
        self.assertEqual(self.a.get(f"/api/documents/{a['id']}/file").data,oldfile)
    def test_08_backup_restore_and_tampering(self):
        "Backup restaurado em ambiente separado com hashes e sessões invalidadas"
        b=self.upload();a,_=self.release(b);self.assertEqual(self.sign(self.a,a).status_code,200)
        expected=self.a.get(f"/api/documents/{a['id']}/file").data
        r=self.rh.get('/api/backup');self.assertEqual(r.status_code,200,r.json);target=Path(self.temp.name)/'restored';report=restore(r.data,target);self.assertTrue(report['ok'])
        restored=create_app(target,True).test_client();self.assertEqual(restored.get('/api/me').status_code,401)
        self.assertEqual(restored.post('/api/login',json={'login':'ana','password':self.pw}).status_code,200)
        self.assertEqual(restored.get(f"/api/documents/{a['id']}/file").data,expected)
        with self.assertRaises(ValueError):restore(r.data,target)
        zin=zipfile.ZipFile(io.BytesIO(r.data));buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for name in zin.namelist():z.writestr(name,b'corrupt' if name=='portal.db' else zin.read(name))
        with self.assertRaises(ValueError):restore(buf.getvalue(),Path(self.temp.name)/'bad')
    def test_09_reset_disable_and_first_password(self):
        "Senha temporária exige troca; desativação e reset encerram sessões"
        r=self.post(self.rh,'/api/users',{'login':'novo','name':'Novo Exemplo'});self.assertEqual(r.status_code,200)
        c=self.app.test_client();self.assertEqual(c.post('/api/login',json={'login':'novo','password':r.json['password']}).status_code,200);c.csrf=c.get('/api/me').json['csrf'];self.assertEqual(c.get('/api/documents').status_code,428)
        self.assertEqual(self.post(c,'/api/password',{'current':r.json['password'],'password':secrets.token_urlsafe(20)}).status_code,200)
        self.assertEqual(c.get('/api/documents').status_code,200)
        self.post(self.rh,f"/api/users/{self.ids['ana']}/reset",{});self.assertEqual(self.a.get('/api/me').status_code,401)
        self.post(self.rh,f"/api/users/{self.ids['bruno']}/active",{'active':False});self.assertEqual(self.b.get('/api/me').status_code,401)
    def test_10_concurrent_confirmation(self):
        "Duas confirmações simultâneas geram apenas uma evidência"
        b=self.upload();a,_=self.release(b);c1=self.client('ana');c2=self.client('ana');key=str(uuid.uuid4())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:res=list(pool.map(lambda c:self.sign(c,a,key).status_code,[c1,c2]))
        self.assertEqual(res,[200,200]);c=connect(self.path/'portal.db');self.assertEqual(c.execute('SELECT count(*) FROM evidence').fetchone()[0],1);c.close()
    def test_11_login_rate_limit(self):
        "Tentativas de senha limitadas no servidor"
        c=self.app.test_client()
        for _ in range(10):self.assertEqual(c.post('/api/login',json={'login':'unknown','password':'wrong'}).status_code,401)
        self.assertEqual(c.post('/api/login',json={'login':'unknown','password':'wrong'}).status_code,429)
    def test_12_seed_real_data_and_preview(self):
        "Exemplos fictícios completos e visualização protegida de PDF"
        r=self.post(self.rh,'/api/seed',{});self.assertEqual(r.status_code,200,r.json);self.assertEqual(len(r.json['credentials']),2)
        self.assertEqual(len(self.rh.get('/api/batches').json),6)
        self.assertEqual(self.post(self.rh,'/api/seed',{}).status_code,409)
        raw=sample_pdf(['Ana'],'Teste');r=self.rh.post('/api/preview',data={'file':(io.BytesIO(raw),'p.pdf')},headers={'X-CSRF-Token':self.rh.csrf});self.assertEqual(r.status_code,200);self.assertTrue(base64.b64decode(r.json['pages'][0]).startswith(b'\x89PNG'))

    def test_13_missing_artifact_prevents_completion(self):
        "Arquivo final ausente impede conclusão e exportação do lote"
        b=self.upload();a,d=self.release(b);self.assertEqual(self.sign(self.a,a).status_code,200);self.assertEqual(self.sign(self.b,d).status_code,200)
        c=connect(self.path/'portal.db');name=c.execute('SELECT signed_file FROM documents WHERE id=?',(a['id'],)).fetchone()[0];c.close();(self.path/'files'/name).unlink()
        st=self.rh.get('/api/batches/'+b).json['stats'];self.assertFalse(st['complete']);self.assertEqual(st['signed'],1)
        self.assertEqual(self.rh.get(f'/api/batches/{b}/export/pdf').status_code,409)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(PortalTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    import sys
    sys.exit(not result.wasSuccessful())
