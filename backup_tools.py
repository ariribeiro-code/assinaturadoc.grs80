import hashlib,io,json,sqlite3,zipfile,tempfile,os,shutil
from pathlib import Path
from datetime import datetime,timezone

def sha(x): return hashlib.sha256(x).hexdigest()
def backup_bytes(directory):
    directory=Path(directory)
    with tempfile.TemporaryDirectory() as td:
        copy=Path(td)/'portal.db'; src=sqlite3.connect(directory/'portal.db'); dest=sqlite3.connect(copy)
        src.backup(dest); src.close(); dest.execute('DELETE FROM sessions'); dest.execute('DELETE FROM attempts'); dest.commit()
        names=set()
        for table,cols in [('batches',['source']),('documents',['file','signed_file'])]:
            for col in cols:
                for row in dest.execute(f'SELECT {col} FROM {table} WHERE {col} IS NOT NULL'): names.add(row[0])
        dest.close(); files={'portal.db':copy.read_bytes()}
        for name in names: files['files/'+name]=(directory/'files'/name).read_bytes()
        manifest={'version':1,'created':datetime.now(timezone.utc).isoformat(),'files':{k:sha(v) for k,v in files.items()}}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for k,v in files.items(): z.writestr(k,v)
            z.writestr('manifest.json',json.dumps(manifest,indent=2))
        return buf.getvalue()

def restore(raw,destination):
    """Offline only, into an absent/empty target. No password or session export in reports."""
    dest=Path(destination).resolve()
    if dest.exists() and any(dest.iterdir()): raise ValueError('Restaure em uma pasta vazia, nunca sobre o portal em uso.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or len(names)>100000 or sum(i.file_size for i in z.infolist())>2_000_000_000: raise ValueError('Backup inválido ou muito grande.')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('version')!=1 or set(names)!=(set(manifest['files'])|{'manifest.json'}): raise ValueError('Manifesto inválido.')
        with tempfile.TemporaryDirectory(dir=dest.parent) as td:
            stage=Path(td)
            for name,h in manifest['files'].items():
                if name!='portal.db' and not (name.startswith('files/') and len(Path(name).parts)==2 and Path(name).suffix=='.pdf'): raise ValueError('Caminho inválido.')
                if '..' in Path(name).parts or Path(name).is_absolute(): raise ValueError('Caminho inseguro.')
                data=z.read(name)
                if sha(data)!=h: raise ValueError('Checksum divergente: '+name)
                p=stage/name; p.parent.mkdir(exist_ok=True); p.write_bytes(data)
            c=sqlite3.connect(stage/'portal.db')
            try:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Banco inconsistente.')
                if c.execute('SELECT version FROM schema_version').fetchone()[0]!=1: raise ValueError('Versão de banco não suportada.')
                for f,h in c.execute('SELECT source,source_hash FROM batches UNION ALL SELECT file,hash FROM documents UNION ALL SELECT signed_file,signed_hash FROM documents WHERE signed_file IS NOT NULL'):
                    if sha((stage/'files'/f).read_bytes())!=h: raise ValueError('Arquivo do banco divergente.')
                c.execute('DELETE FROM sessions'); c.execute('DELETE FROM attempts'); c.commit()
            finally: c.close()
            dest.mkdir(exist_ok=True,mode=0o700); (dest/'files').mkdir(exist_ok=True,mode=0o700)
            shutil.copy2(stage/'portal.db',dest/'portal.db')
            for file in (stage/'files').glob('*'): shutil.copy2(file,dest/'files'/file.name)
    return {'ok':True,'files':len(manifest['files'])-1,'sessions':'invalidated'}
