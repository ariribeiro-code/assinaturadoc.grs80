"""PDFs individuais são reconstruídos de pixels, sem anexos ou conteúdo oculto."""
import io, math, threading
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium

PDF_LOCK=threading.RLock()  # PDFium não é thread-safe.
MAX_PAGES=60

def inspect_pdf(raw):
    with PDF_LOCK:
        doc=pdfium.PdfDocument(raw)
        try:
            if not 1<=len(doc)<=MAX_PAGES: raise ValueError('Use um PDF de 1 a 60 páginas.')
            for i in range(len(doc)):
                p=doc[i]; w,h=p.get_size(); p.close()
                if w<100 or h<100 or w*h>1_600_000: raise ValueError('Dimensões de página não suportadas.')
            return len(doc)
        finally: doc.close()

def page_png(raw,index,scale=1.35):
    with PDF_LOCK:
        doc=pdfium.PdfDocument(raw)
        try:
            page=doc[index]; bitmap=page.render(scale=scale); im=bitmap.to_pil(); out=io.BytesIO(); im.save(out,format='PNG'); bitmap.close(); page.close(); return out.getvalue()
        finally: doc.close()

def split_safe(raw,pages):
    out=io.BytesIO(); c=canvas.Canvas(out)
    with PDF_LOCK:
        doc=pdfium.PdfDocument(raw)
        try:
            for index in pages:
                p=doc[index]; w,h=p.get_size(); bitmap=p.render(scale=1.7); im=bitmap.to_pil()
                c.setPageSize((w,h)); c.drawImage(ImageReader(im),0,0,width=w,height=h); c.showPage(); bitmap.close(); p.close()
        finally: doc.close()
    c.save(); return out.getvalue()

def validate_fields(fields,page_count,required):
    if not isinstance(fields,list) or len(fields)>240: raise ValueError('Campos inválidos.')
    clean=[]
    for f in fields:
        page=f.get('page'); kind=f.get('kind'); x=f.get('x'); y=f.get('y')
        if type(page)!=int or not 0<=page<page_count or kind not in ('signature','date'): raise ValueError('Página/campo inválido.')
        w,h=(.32,.065) if kind=='signature' else (.22,.03)
        if type(x) not in (float,int) or type(y) not in (float,int) or not math.isfinite(x+y) or not 0<=x<=1-w or not 0<=y<=1-h: raise ValueError('Campo fora da página.')
        clean.append(dict(page=page,kind=kind,x=x,y=y,w=w,h=h))
    if required and not all(any(f['page']==p and f['kind']==k for f in clean) for p in range(page_count) for k in ('signature','date')):
        raise ValueError('Posicione assinatura e data em cada página. Nas duas vias, marque os dois pares de campos.')
    return clean

def validate_strokes(strokes):
    if not isinstance(strokes,list) or not 1<=len(strokes)<=100: raise ValueError('Desenhe a assinatura.')
    n=0; xs=[]; ys=[]
    for line in strokes:
        if not isinstance(line,list): raise ValueError('Assinatura inválida.')
        for p in line:
            if not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in p): raise ValueError('Assinatura inválida.')
            n+=1; xs.append(p[0]); ys.append(p[1])
    if not 6<=n<=12000 or max(xs)-min(xs)<.04 or max(ys)-min(ys)<.02: raise ValueError('Desenhe uma assinatura legível.')
    return strokes

def sign_pdf(raw,fields,strokes,at,evidence_id):
    reader=PdfReader(io.BytesIO(raw)); writer=PdfWriter()
    stamp=datetime.fromisoformat(at).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')
    for i,page in enumerate(reader.pages):
        w,h=float(page.mediabox.width),float(page.mediabox.height); out=io.BytesIO(); c=canvas.Canvas(out,pagesize=(w,h))
        for f in fields:
            if f['page']!=i: continue
            x,y,fw,fh=f['x']*w,(1-f['y']-f['h'])*h,f['w']*w,f['h']*h
            if f['kind']=='signature':
                c.setStrokeColorRGB(0,.06,.3); c.setLineWidth(.9)
                for line in strokes:
                    if len(line)<2: continue
                    p=c.beginPath(); p.moveTo(x+line[0][0]*fw,y+(1-line[0][1])*fh)
                    for pt in line[1:]: p.lineTo(x+pt[0]*fw,y+(1-pt[1])*fh)
                    c.drawPath(p)
            else:
                c.setFont('Helvetica',min(8,fh*.45)); c.drawString(x,y+fh*.35,stamp)
        c.showPage(); c.save(); page.merge_page(PdfReader(out).pages[0]); writer.add_page(page)
    # Evidence page separate: never obscure original payroll content.
    out=io.BytesIO(); c=canvas.Canvas(out,pagesize=(595,842)); c.setFont('Helvetica-Bold',18); c.drawString(45,780,'Registro de assinatura eletrônica')
    c.setFont('Helvetica',10)
    for j,line in enumerate([f'Protocolo: {evidence_id}',f'Confirmado em: {stamp} (America/Sao_Paulo)',f'Páginas confirmadas: {len(reader.pages)}','A confirmação abrange todas as vias exibidas deste documento.','Registro do piloto. Não constitui certificado ICP-Brasil.']): c.drawString(45,735-j*23,line)
    c.save(); writer.add_page(PdfReader(out).pages[0]); result=io.BytesIO(); writer.write(result); return result.getvalue()

def merge_pdfs(files):
    writer=PdfWriter()
    for data in files:
        for p in PdfReader(io.BytesIO(data)).pages: writer.add_page(p)
    out=io.BytesIO(); writer.write(out); return out.getvalue()

def sample_pdf(names,title,dual=False):
    out=io.BytesIO(); c=canvas.Canvas(out,pagesize=(595,842))
    for name in names:
        for y in ([800,410] if dual else [800]):
            c.setFillColorRGB(0,.06,.36); c.setFont('Helvetica-Bold',18); c.drawString(42,y,'GRS80 | Documento de teste')
            c.setFillColorRGB(.25,.25,.25); c.setFont('Helvetica-Bold',12); c.drawString(42,y-34,title)
            c.setFont('Helvetica',11); c.drawString(42,y-66,name); c.drawString(42,y-90,'DADOS FICTÍCIOS - SEM VALOR PARA USO REAL')
            c.drawString(42,y-130,'Este recibo é exclusivo para testar o portal e a assinatura.')
            c.line(45,y-243,250,y-243); c.line(330,y-243,545,y-243)
            c.drawString(45,y-259,'Assinatura'); c.drawString(330,y-259,'Data e hora')
        c.showPage()
    c.save(); return out.getvalue()

def sample_fields(dual=False):
    result=[]
    for y in ([.265,.728] if dual else [.265]):
        result.extend([dict(page=0,kind='signature',x=.075,y=y),dict(page=0,kind='date',x=.555,y=y+.03)])
    return validate_fields(result,1,True)
