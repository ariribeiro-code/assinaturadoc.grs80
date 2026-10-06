"""GRS80 Portal — piloto independente, uma instância e volume persistente."""
import contextlib, hashlib, io, json, os, re, secrets, sqlite3, threading, time, uuid, zipfile
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, g, send_file
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from werkzeug.exceptions import HTTPException
import pdf_tools as pdf

ROOT=Path(__file__).resolve().parent
PH=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
DUMMY=PH.hash(secrets.token_urlsafe(20))
LOCK=threading.RLock()
CATEGORIES=['Holerite','Férias','Vale-transporte','Benefícios','EPI e equipamentos','Declarações','Outros']
CONSENT='Conferi todas as páginas e vias deste documento e confirmo minha assinatura eletrônica nesta versão.'

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def fail(message,status=400):
    from werkzeug.exceptions import HTTPException
    e=HTTPException(description=message); e.code=status; raise e

def connect(path):
    c=sqlite3.connect(path,timeout=30,isolation_level=None); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=FULL'); return c

def initialize(data_dir):
    p=Path(data_dir); p.mkdir(parents=True,exist_ok=True,mode=0o700); (p/'files').mkdir(exist_ok=True,mode=0o700)
    c=connect(p/'portal.db'); c.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
    for name in CATEGORIES: c.execute('INSERT OR IGNORE INTO categories VALUES(?,?)',(digest(name.encode())[:16],name))
    c.close()

def create_app(data_dir=None,testing=False):
    app=Flask(__name__,static_folder='static'); app.config.update(TESTING=testing,MAX_CONTENT_LENGTH=18*1024*1024)
    app.config['DATA']=Path(data_dir or os.environ.get('PORTAL_DATA',ROOT/'data')).resolve()
    app.config['MODE']=os.environ.get('PORTAL_MODE','pilot'); app.config['ORIGIN']=os.environ.get('PUBLIC_ORIGIN','http://127.0.0.1:8000').rstrip('/')
    if app.config['MODE'] not in ('pilot','production'): raise RuntimeError('PORTAL_MODE inválido')
    if app.config['MODE']=='production' and not app.config['ORIGIN'].startswith('https://'): raise RuntimeError('Produção requer PUBLIC_ORIGIN HTTPS')
    initialize(app.config['DATA'])
    def db():
        if 'db' not in g: g.db=connect(app.config['DATA']/'portal.db')
        return g.db
    @contextlib.contextmanager
    def tx():
        with LOCK:
            db().execute('BEGIN IMMEDIATE')
            try: yield db(); db().execute('COMMIT')
            except BaseException: db().execute('ROLLBACK'); raise
    def row(sql,args=()): return db().execute(sql,args).fetchone()
    def rows(sql,args=()): return [dict(x) for x in db().execute(sql,args)]
    def audit(action,target=None): db().execute('INSERT INTO audit VALUES(?,?,?,?,?)',(uid(),g.user['id'] if getattr(g,'user',None) else None,action,target,now()))
    def write_file(raw):
        if app.config.get('FAIL_STORAGE'): raise OSError('simulated storage unavailable')
        name=uid()+'.pdf'; dest=app.config['DATA']/'files'/name
        with open(dest,'xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        # Persist directory entry before committing metadata.
        if os.name!='nt':
            fd=os.open(dest.parent,os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        return name
    def read_file(name,expected=None):
        if not re.fullmatch(r'[a-f0-9-]+\.pdf',name): fail('Arquivo inválido.',500)
        raw=(app.config['DATA']/'files'/name).read_bytes()
        if expected and digest(raw)!=expected: fail('Falha na verificação do arquivo. Contate o RH.',503)
        return raw
    def protected(role=None):
        def deco(f):
            @wraps(f)
            def wrapper(*a,**k):
                if not getattr(g,'user',None): fail('Entre com sua matrícula e senha.',401)
                if g.user['must_change'] and request.path not in ('/api/me','/api/password','/api/logout'): fail('Troque a senha temporária antes de continuar.',428)
                if role and g.user['role']!=role: fail('Acesso não permitido.',403)
                if request.method not in ('GET','HEAD','OPTIONS'):
                    token=request.headers.get('X-CSRF-Token','')
                    if not token or not secrets.compare_digest(token,g.session['csrf']): fail('Sessão inválida. Atualize a página.',403)
                return f(*a,**k)
            return wrapper
        return deco
    @app.before_request
    def auth():
        g.user=None
        if request.path.startswith('/api/'):
            if request.method not in ('GET','HEAD','OPTIONS'):
                origin=request.headers.get('Origin')
                if origin and origin!=app.config['ORIGIN']: fail('Origem não permitida.',403)
                if request.headers.get('Sec-Fetch-Site')=='cross-site': fail('Origem não permitida.',403)
            token=request.cookies.get('portal_session','')
            if token:
                session=row('SELECT * FROM sessions WHERE token=?',(digest(token.encode()),))
                if session and session['expires']>time.time() and session['last_seen']>time.time()-1800:
                    user=row('SELECT id,login,name,role,active,must_change,fictitious FROM users WHERE id=? AND active=1',(session['user_id'],))
                    if user:
                        g.user=dict(user); g.session=dict(session)
                        db().execute('UPDATE sessions SET last_seen=? WHERE token=?',(time.time(),session['token']))
    @app.after_request
    def headers(r):
        r.headers['Cache-Control']='no-store'; r.headers['X-Content-Type-Options']='nosniff'; r.headers['X-Frame-Options']='SAMEORIGIN'; r.headers['Referrer-Policy']='no-referrer'
        r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
        r.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        if app.config['MODE']=='production': r.headers['Strict-Transport-Security']='max-age=31536000'
        return r
    @app.teardown_appcontext
    def close(_):
        if 'db' in g: g.db.close()
    @app.errorhandler(HTTPException)
    def http_error(e): return jsonify(error=e.description),e.code or 500
    @app.errorhandler(ValueError)
    def bad_value(e): return jsonify(error=str(e)),400
    @app.errorhandler(Exception)
    def error(e):
        app.logger.error('Operation failed: %s',type(e).__name__)
        return jsonify(error='Não foi possível concluir. Nenhum sucesso foi confirmado. Tente novamente ou contate o RH.'),503
    @app.get('/')
    def index(): return app.send_static_file('index.html')
    @app.get('/health')
    def health(): db().execute('SELECT 1'); return {'ok':True}
    @app.post('/api/login')
    def login():
        if not request.is_json: fail('Envie os dados no formato esperado.')
        data=request.get_json(); name=str(data.get('login','')).strip().lower()[:100]; password=str(data.get('password',''))[:256]
        keys=[digest(('login:'+name).encode()),digest(('ip:'+str(request.remote_addr)).encode())]
        with tx():
            for key in keys:
                old=row('SELECT * FROM attempts WHERE key=?',(key,))
                if old and old['until']>time.time() and old['count']>=10: fail('Muitas tentativas. Aguarde 15 minutos.',429)
        user=row('SELECT * FROM users WHERE login=?',(name,)); ok=False
        try: ok=PH.verify(user['password'] if user else DUMMY,password)
        except VerificationError: pass
        if not ok or not user or not user['active']:
            with tx():
                for key in keys:
                    db().execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN attempts.until<? THEN 1 ELSE attempts.count+1 END, until=CASE WHEN attempts.until<? THEN excluded.until ELSE attempts.until END',(key,time.time()+900,time.time(),time.time()))
            fail('Matrícula ou senha incorreta.',401)
        token=secrets.token_urlsafe(40); csrf=secrets.token_urlsafe(32)
        with tx():
            db().execute('DELETE FROM attempts WHERE key=?',(keys[0],))
            db().execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db().execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(digest(token.encode()),user['id'],csrf,time.time()+28800,time.time()))
            g.user=dict(user); audit('login')
        response=jsonify(ok=True); response.set_cookie('portal_session',token,httponly=True,secure=app.config['MODE']=='production',samesite='Strict',max_age=28800,path='/'); return response
    @app.get('/api/me')
    @protected()
    def me(): return {'user':g.user,'csrf':g.session['csrf'],'mode':app.config['MODE'],'consent':CONSENT}
    @app.post('/api/logout')
    @protected()
    def logout():
        db().execute('DELETE FROM sessions WHERE token=?',(g.session['token'],)); r=jsonify(ok=True); r.delete_cookie('portal_session'); return r
    @app.post('/api/password')
    @protected()
    def password():
        data=request.get_json(); old=row('SELECT password FROM users WHERE id=?',(g.user['id'],))
        try: PH.verify(old['password'],str(data.get('current','')))
        except VerificationError: fail('Senha atual incorreta.',403)
        pw=str(data.get('password',''))
        if not 12<=len(pw)<=128: fail('Use uma senha de 12 a 128 caracteres.')
        if pw==data.get('current'): fail('Escolha uma senha diferente da temporária.')
        with tx():
            db().execute('UPDATE users SET password=?,must_change=0 WHERE id=?',(PH.hash(pw),g.user['id']))
            db().execute('DELETE FROM sessions WHERE user_id=? AND token!=?',(g.user['id'],g.session['token'])); audit('password_changed')
        return {'ok':True}
    @app.get('/api/users')
    @protected('rh')
    def users(): return rows("SELECT id,login,name,role,active,fictitious FROM users WHERE role='employee' ORDER BY name")
    def new_user(login,name,role='employee',fictitious=0,password=None,must_change=1):
        if not re.fullmatch(r'[a-z0-9._-]{2,40}',login): fail('Matrícula: use 2 a 40 letras, números, ponto, traço ou sublinhado.')
        if not 2<=len(name)<=100: fail('Informe o nome.')
        if row('SELECT id FROM users WHERE login=?',(login,)): fail('Matrícula já cadastrada.',409)
        password=password or secrets.token_urlsafe(18); id=uid()
        db().execute('INSERT INTO users VALUES(?,?,?,?,?,1,?,?)',(id,login,name,role,PH.hash(password),must_change,fictitious))
        return {'id':id,'login':login,'name':name,'password':password}
    @app.post('/api/users')
    @protected('rh')
    def add_user():
        data=request.get_json()
        with tx():
            user=new_user(str(data.get('login','')).lower().strip(),str(data.get('name','')).strip(),fictitious=int(app.config['MODE']=='pilot')); audit('employee_created',user['id'])
        return user
    @app.post('/api/users/<id>/reset')
    @protected('rh')
    def reset_user(id):
        user=row("SELECT * FROM users WHERE id=? AND role='employee'",(id,))
        if not user: fail('Funcionário não encontrado.',404)
        password=secrets.token_urlsafe(18)
        with tx():
            db().execute('UPDATE users SET password=?,must_change=1 WHERE id=?',(PH.hash(password),id)); db().execute('DELETE FROM sessions WHERE user_id=?',(id,)); audit('password_reset',id)
        return {'login':user['login'],'password':password}
    @app.post('/api/users/<id>/active')
    @protected('rh')
    def active_user(id):
        active=request.get_json().get('active')
        if type(active)!=bool: fail('Valor inválido.')
        with tx():
            db().execute("UPDATE users SET active=? WHERE id=? AND role='employee'",(int(active),id)); db().execute('DELETE FROM sessions WHERE user_id=?',(id,)); audit('employee_access_changed',id)
        return {'ok':True}
    @app.get('/api/categories')
    @protected()
    def categories(): return rows('SELECT * FROM categories ORDER BY name')
    @app.post('/api/categories')
    @protected('rh')
    def add_category():
        name=str(request.get_json().get('name','')).strip()
        if not 2<=len(name)<=60: fail('Nome inválido.')
        with tx():
            if row('SELECT id FROM categories WHERE name=?',(name,)): fail('Categoria já existe.',409)
            db().execute('INSERT INTO categories VALUES(?,?)',(uid(),name))
        return {'ok':True}
    def batch(id):
        b=row('SELECT b.*, c.name category_name FROM batches b JOIN categories c ON c.id=b.category WHERE b.id=?',(id,))
        if not b: fail('Lote não encontrado.',404)
        return dict(b)
    def stats(id):
        b=batch(id); expected=row('SELECT count(*) n FROM items WHERE batch_id=?',(id,))['n']
        docs=rows("SELECT d.* FROM documents d JOIN items i ON i.id=d.item_id WHERE i.batch_id=? AND d.status!='superseded'",(id,))
        signed=0
        for x in docs:
            if x['status']=='signed' and x['signed_file'] and x['signed_hash']:
                try:
                    read_file(x['signed_file'],x['signed_hash']); signed+=1
                except (OSError,HTTPException):
                    pass  # Lote não completo se o artefato final sumiu ou foi corrompido.

        return {'expected':expected,'signed':signed,'pending':max(0,expected-signed) if b['required'] else 0,'complete':bool(b['state']=='released' and b['required'] and expected>0 and signed==expected and len(docs)==expected),'percent':round(100*signed/expected) if expected and b['required'] else None}
    @app.get('/api/batches')
    @protected('rh')
    def batches():
        result=rows('SELECT b.*,c.name category_name FROM batches b JOIN categories c ON c.id=b.category ORDER BY b.created DESC')
        for b in result: b['stats']=stats(b['id']); b.pop('source'); b.pop('source_hash')
        return result
    def add_batch(raw,title,category,period,due,required,fictitious=0):
        if not 2<=len(title)<=120 or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',period): fail('Informe título e competência válidos.')
        if due:
            try: datetime.strptime(due,'%Y-%m-%d')
            except ValueError: fail('Prazo inválido.')
        if not row('SELECT id FROM categories WHERE id=?',(category,)): fail('Categoria inválida.')
        count=pdf.inspect_pdf(raw); id=uid(); path=write_file(raw)
        db().execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(id,title,category,period,due,int(required),'draft',path,digest(raw),count,now(),fictitious))
        return id
    @app.post('/api/batches')
    @protected('rh')
    def upload_batch():
        f=request.files.get('file')
        if not f: fail('Selecione um PDF.')
        raw=f.read()
        if len(raw)>15*1024*1024 or not raw.startswith(b'%PDF'): fail('Envie um PDF de até 15 MB.')
        with tx():
            id=add_batch(raw,request.form.get('title','').strip(),request.form.get('category',''),request.form.get('period',''),request.form.get('due',''),request.form.get('required')=='true',int(app.config['MODE']=='pilot')); audit('batch_created',id)
        return {'id':id}
    @app.get('/api/batches/<id>')
    @protected('rh')
    def get_batch(id):
        b=batch(id); b['items']=rows('SELECT i.*,u.name,u.login FROM items i JOIN users u ON u.id=i.user_id WHERE i.batch_id=? ORDER BY position',(id,)); b['stats']=stats(id); b.pop('source'); b.pop('source_hash'); return b
    @app.get('/api/batches/<id>/pages/<int:page>')
    @protected('rh')
    def batch_page(id,page):
        b=batch(id)
        if not 0<=page<b['page_count']: fail('Página inválida.',404)
        return send_file(io.BytesIO(pdf.page_png(read_file(b['source'],b['source_hash']),page)),mimetype='image/png')
    def release_batch(id,assignments):
        b=batch(id)
        if b['state']!='draft': fail('Lote já liberado.',409)
        if not isinstance(assignments,list) or len(assignments)!=b['page_count']: fail('Revise todas as páginas.')
        grouped={}
        for index,a in enumerate(assignments):
            if a.get('reviewed') is not True or a.get('single_person') is not True: fail('Confirme que cada página contém somente um funcionário. Páginas compartilhadas precisam ser separadas antes do envio.')
            user=row("SELECT id FROM users WHERE id=? AND role='employee' AND active=1",(a.get('user_id',''),))
            if not user: fail('Funcionário inválido.')
            fields=pdf.validate_fields(a.get('fields',[]),1,bool(b['required']))
            part=grouped.setdefault(user['id'],{'pages':[],'fields':[]})
            for f in fields: f['page']=len(part['pages']); part['fields'].append(f)
            part['pages'].append(index)
        raw=read_file(b['source'],b['source_hash'])
        for pos,(user,part) in enumerate(grouped.items()):
            item=uid(); doc=uid(); data=pdf.split_safe(raw,part['pages']); path=write_file(data)
            db().execute('INSERT INTO items VALUES(?,?,?,?,?,?)',(item,id,user,pos,json.dumps(part['pages']),json.dumps(part['fields'])))
            db().execute('INSERT INTO documents VALUES(?,?,1,NULL,?,?,?,?,?,NULL,NULL,NULL,?)',(doc,item,'pending' if b['required'] else 'available',path,digest(data),json.dumps(part['fields']),len(part['pages']),now()))
        db().execute("UPDATE batches SET state='released' WHERE id=?",(id,)); audit('batch_released',id)
    @app.post('/api/batches/<id>/release')
    @protected('rh')
    def release(id):
        with tx(): release_batch(id,request.get_json().get('assignments'))
        return {'ok':True}
    BASE="SELECT d.*,i.user_id,i.batch_id,i.position,u.name,u.login,b.title,b.period,b.due,b.required,c.name category,b.fictitious FROM documents d JOIN items i ON i.id=d.item_id JOIN users u ON u.id=i.user_id JOIN batches b ON b.id=i.batch_id JOIN categories c ON c.id=b.category"
    def doc(id):
        d=row(BASE+' WHERE d.id=?',(id,))
        if not d or (g.user['role']!='rh' and d['user_id']!=g.user['id']): fail('Documento não encontrado.',404)
        return dict(d)
    def public_doc(d):
        for key in ('file','signed_file'): d.pop(key,None)
        d['fields']=json.loads(d['fields']); return d
    @app.get('/api/documents')
    @protected()
    def documents():
        args=() if g.user['role']=='rh' else (g.user['id'],)
        sql=BASE+('' if g.user['role']=='rh' else ' WHERE i.user_id=?')+' ORDER BY d.created DESC'
        return [public_doc(d) for d in rows(sql,args)]
    @app.get('/api/documents/<id>')
    @protected()
    def get_doc(id): return public_doc(doc(id))
    @app.post('/api/documents/<id>/view')
    @protected()
    def viewed(id):
        d=doc(id)
        if d['user_id']==g.user['id']:
            with tx(): db().execute("UPDATE documents SET status='viewed' WHERE id=? AND status='pending'",(id,))
        return {'ok':True}
    @app.get('/api/documents/<id>/file')
    @protected()
    def download_doc(id):
        d=doc(id); signed=bool(d['signed_file']); raw=read_file(d['signed_file'] if signed else d['file'],d['signed_hash'] if signed else d['hash'])
        return send_file(io.BytesIO(raw),mimetype='application/pdf',as_attachment=True,download_name=f"{d['login']}_{d['period']}_v{d['version']}_{'assinado' if signed else 'documento'}.pdf")
    @app.get('/api/documents/<id>/pages/<int:page>')
    @protected()
    def doc_page(id,page):
        d=doc(id)
        if not 0<=page<d['page_count']: fail('Página inválida.',404)
        return send_file(io.BytesIO(pdf.page_png(read_file(d['signed_file'] or d['file'],d['signed_hash'] or d['hash']),page)),mimetype='image/png')
    @app.post('/api/documents/<id>/sign')
    @protected('employee')
    def sign(id):
        data=request.get_json()
        if data.get('consent') is not True: fail('Confirme a leitura antes de assinar.')
        key=str(data.get('key',''))
        if not re.fullmatch('[a-f0-9-]{36}',key): fail('Identificador de confirmação inválido.')
        with tx():
            d=doc(id)
            if d['signed_file']: return {'ok':True,'already_signed':True,'time':d['signed_at']}
            if not d['required'] or d['status'] not in ('pending','viewed'): fail('Documento indisponível para assinatura.',409)
            if data.get('hash')!=d['hash']: fail('A versão mudou. Reabra o documento.',409)
            if row('SELECT id FROM evidence WHERE request_key=?',(key,)): fail('Confirmação já utilizada.',409)
            strokes=pdf.validate_strokes(data.get('strokes')); evidence_id=uid(); at=now()
            raw=read_file(d['file'],d['hash']); final=pdf.sign_pdf(raw,json.loads(d['fields']),strokes,at,evidence_id); path=write_file(final); final_hash=digest(final)
            read_file(path,final_hash)
            db().execute("UPDATE documents SET status='signed',signed_file=?,signed_hash=?,signed_at=? WHERE id=?",(path,final_hash,at,id))
            db().execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)',(evidence_id,id,g.user['id'],key,at,d['hash'],final_hash,CONSENT,json.dumps(strokes),request.headers.get('User-Agent','')[:300]))
            audit('document_signed',id)
        return {'ok':True,'time':at}
    @app.post('/api/documents/<id>/issue')
    @protected('employee')
    def issue(id):
        message=str(request.get_json().get('message','')).strip()
        if not 5<=len(message)<=2000: fail('Descreva a divergência em 5 a 2000 caracteres.')
        with tx():
            d=doc(id)
            if d['status'] not in ('pending','viewed','available'): fail('Documento indisponível para esta ação.',409)
            db().execute('INSERT INTO issues VALUES(?,?,?,?,NULL,?,NULL,?)',(uid(),id,g.user['id'],message,now(),d['status']))
            db().execute("UPDATE documents SET status='review' WHERE id=?",(id,)); audit('divergence_reported',id)
        return {'ok':True}
    @app.get('/api/issues')
    @protected()
    def issues():
        return rows('SELECT x.*,u.name,b.title FROM issues x JOIN users u ON u.id=x.user_id JOIN documents d ON d.id=x.document_id JOIN items i ON i.id=d.item_id JOIN batches b ON b.id=i.batch_id'+('' if g.user['role']=='rh' else ' WHERE x.user_id=?')+' ORDER BY x.created DESC',() if g.user['role']=='rh' else (g.user['id'],))
    @app.post('/api/issues/<id>/resolve')
    @protected('rh')
    def resolve(id):
        response=str(request.get_json().get('response','')).strip()
        if not 3<=len(response)<=2000: fail('Informe uma resposta.')
        with tx():
            issue=row('SELECT * FROM issues WHERE id=? AND resolved IS NULL',(id,))
            if not issue: fail('Divergência não encontrada.',404)
            db().execute('UPDATE issues SET response=?,resolved=? WHERE id=?',(response,now(),id)); db().execute("UPDATE documents SET status=? WHERE id=? AND status='review'",(issue['prior'],issue['document_id'])); audit('divergence_resolved',id)
        return {'ok':True}
    @app.post('/api/documents/<id>/version')
    @protected('rh')
    def version(id):
        f=request.files.get('file')
        if not f or request.form.get('reviewed')!='true': fail('Revise o PDF e seus campos antes de confirmar.')
        raw=f.read(); count=pdf.inspect_pdf(raw); fields=pdf.validate_fields(json.loads(request.form.get('fields','[]')),count,bool(doc(id)['required']))
        with tx():
            old=doc(id)
            if old['status']=='superseded': fail('Versão já substituída.',409)
            clean=pdf.split_safe(raw,list(range(count))); path=write_file(clean); nid=uid()
            db().execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?)',(nid,old['item_id'],old['version']+1,id,'pending' if old['required'] else 'available',path,digest(clean),json.dumps(fields),count,now()))
            db().execute("UPDATE documents SET status='superseded' WHERE id=?",(id,)); db().execute("UPDATE issues SET response='Documento corrigido em nova versão.',resolved=? WHERE document_id=? AND resolved IS NULL",(now(),id)); audit('new_version',nid)
        return {'id':nid}
    @app.get('/api/batches/<id>/export/<fmt>')
    @protected('rh')
    def export(id,fmt):
        with LOCK:
            b=batch(id); st=stats(id)
            if b['state']!='released' or (b['required'] and not st['complete']): fail('O lote ainda não está completo. Confira as pendências.',409)
            docs=rows(BASE+" WHERE i.batch_id=? AND d.status!='superseded' ORDER BY i.position",(id,))
            if len(docs)!=st['expected'] or not docs: fail('Lote incompleto.',409)
            files={f"{i+1:03}_{d['login']}_{b['period']}_v{d['version']}.pdf":read_file(d['signed_file'] or d['file'],d['signed_hash'] or d['hash']) for i,d in enumerate(docs)}
            if fmt=='pdf': output=pdf.merge_pdfs(files.values()); mime='application/pdf'
            elif fmt=='zip':
                buf=io.BytesIO()
                with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                    for name,raw in files.items(): z.writestr(name,raw)
                    z.writestr('verificacao.json',json.dumps({k:digest(v) for k,v in files.items()},indent=2))
                output=buf.getvalue(); mime='application/zip'
            else: fail('Formato inválido.',404)
            audit('batch_export',id)
        return send_file(io.BytesIO(output),mimetype=mime,as_attachment=True,download_name=f"GRS80_{b['period']}_{id[:8]}.{fmt}")
    @app.post('/api/seed')
    @protected('rh')
    def seed():
        if app.config['MODE']!='pilot': fail('Exemplos disponíveis somente no piloto.',403)
        if row('SELECT id FROM users WHERE fictitious=1 LIMIT 1'): fail('Os dados fictícios já existem. Use os lotes disponíveis.',409)
        with tx():
            users=[new_user('teste.ana','Ana Exemplo',fictitious=1),new_user('teste.bruno','Bruno Exemplo',fictitious=1)]
            for j,name in enumerate(CATEGORIES[:-1]):
                cat=row('SELECT id FROM categories WHERE name=?',(name,))['id']; dual=j==0; required=name!='Declarações'
                raw=pdf.sample_pdf([u['name'] for u in users],f'{name} - exemplo',dual)
                id=add_batch(raw,f'{name} • lote de teste',cat,'2026-10','',required,1)
                assignments=[dict(user_id=u['id'],reviewed=True,single_person=True,fields=pdf.sample_fields(dual) if required else []) for u in users]; release_batch(id,assignments)
            audit('pilot_seed')
        return {'credentials':users}
    @app.get('/api/backup')
    @protected('rh')
    def backup():
        from backup_tools import backup_bytes
        with LOCK:
            audit('backup_export'); raw=backup_bytes(app.config['DATA'])
        return send_file(io.BytesIO(raw),mimetype='application/zip',as_attachment=True,download_name=f'GRS80_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
    @app.get('/api/audit')
    @protected('rh')
    def audit_list(): return rows('SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY time DESC LIMIT 200')
    @app.post('/api/preview')
    @protected('rh')
    def preview():
        import base64
        f=request.files.get('file')
        if not f: fail('Selecione um PDF.')
        raw=f.read(); count=pdf.inspect_pdf(raw)
        if count>12: fail('Para correções, use até 12 páginas por documento.')
        return {'pages':[base64.b64encode(pdf.page_png(raw,i)).decode() for i in range(count)]}
    @app.get('/api/validation')
    @protected('rh')
    def validation():
        path=ROOT/'TEST_RESULTS.json'
        return {'tests':json.loads(path.read_text(encoding='utf-8')) if path.exists() else [],'pending':['Hospedagem HTTPS e volume persistente configurados e testados','Backup externo automático, retenção e alertas','Piloto no celular real com RH e dois funcionários','Revisão independente de segurança e processo de assinatura','Operação: monitoramento, recuperação de acesso e responsável técnico'],'mode':app.config['MODE']}
    return app
