import argparse,getpass,json,os,sys
from pathlib import Path
from app import create_app,initialize,connect,PH,uid,ROOT

def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['init-rh','serve','backup','restore']); p.add_argument('--data',default=os.environ.get('PORTAL_DATA',str(ROOT/'data'))); p.add_argument('--login'); p.add_argument('--name',default='Responsável RH'); p.add_argument('--file'); p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8000); a=p.parse_args()
    if a.command=='init-rh':
        initialize(a.data); c=connect(Path(a.data)/'portal.db')
        if c.execute("SELECT id FROM users WHERE role='rh'").fetchone(): sys.exit('Já existe RH. Não será criado outro por este comando.')
        login=a.login or input('Matrícula de administrador: ').strip().lower()
        import re
        if not re.fullmatch(r'[a-z0-9._-]{2,40}',login): sys.exit('Matrícula inválida.')
        pw=getpass.getpass('Defina senha (12+ caracteres): ')
        if len(pw)<12 or len(pw)>128 or pw!=getpass.getpass('Confirme: '): sys.exit('Senha inválida ou confirmação diferente.')
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT id FROM users WHERE role='rh'").fetchone(): sys.exit('RH já criado.')
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,1,0,0)',(uid(),login,a.name,'rh',PH.hash(pw))); c.commit(); c.close(); print('RH criado. Senha não armazenada em texto simples.')
    elif a.command=='serve':
        from waitress import serve
        serve(create_app(a.data),host=a.host,port=a.port,threads=4,max_request_body_size=18*1024*1024)
    elif a.command=='backup':
        if not a.file: sys.exit('Informe --file. Execute com a aplicação parada; online use a área do RH.')
        from backup_tools import backup_bytes
        Path(a.file).write_bytes(backup_bytes(a.data)); print('Backup salvo. Contém documentos e hashes de senha; guarde com acesso restrito.')
    else:
        if not a.file: sys.exit('Informe --file e --data apontando para uma pasta vazia.')
        from backup_tools import restore
        print(json.dumps(restore(Path(a.file).read_bytes(),a.data)))
if __name__=='__main__': main()
