# GRS80 — Portal do Colaborador | Piloto independente

Projeto funcional para homologação, com acesso próprio por matrícula e senha. Não depende de Lovable nem de login no ChatGPT. Este pacote não está hospedado: contém o código, as telas, os testes e a preparação para uma instalação sob controle da empresa. Não inclui salários, documentos reais, contas prontas ou senhas.

## O que foi implementado

- Login individual, papéis de RH e funcionário validados no servidor, senha com Argon2, sessões de 8 horas / 30 minutos de inatividade, proteção CSRF, limitação de tentativas e troca de senha temporária no primeiro acesso.
- RH cria funcionários, redefine senhas e desativa acessos. Somente um operador com acesso ao servidor cria o primeiro RH; não há cadastro público de administrador.
- Documentos por categoria e competência; envio individual ou lote por PDF; revisão manual de cada página e titular, com posicionamento de assinatura/data. Páginas de diferentes pessoas exigem separação prévia — o sistema bloqueia liberação sem confirmação.
- Documentos individuais são reconstruídos a partir de imagens das páginas escolhidas, removendo texto invisível, scripts, anexos e conteúdo de outras páginas. O original do lote permanece restrito ao RH. Isso reduz a busca/acessibilidade do PDF final; esta escolha deve ser revista no projeto final para preservar acessibilidade sem expor conteúdo oculto.
- Funcionário visualiza apenas seus documentos, assina com dedo/mouse, confirma todas as páginas e vias e baixa o PDF final. Data/hora provêm do servidor, apresentadas em America/Sao_Paulo; a competência não muda a data de assinatura.
- Evidência da assinatura com versão, hashes, protocolo, confirmação, traços e horário. Não é assinatura com certificado ICP-Brasil; não há promessa de validade jurídica automática.
- Assinatura só é concluída após persistir e verificar o PDF. Confirmações repetidas não criam novos registros. Falhas preservam o estado pendente.
- Histórico imutável de arquivos assinados, divergências e correção em nova versão que exige nova assinatura.
- Contagem pelo total de destinatários previstos. Download conjunto em PDF/ZIP somente quando todos os documentos exigidos estiverem assinados. Documento de consulta não conta como assinatura.
- Backup manual de banco, documentos e evidências com manifesto SHA-256. Restauração offline em pasta vazia e invalidação de sessões restauradas.
- Logo e cores GRS80; fontes locais Archivo e Inter; interface responsiva.

## Iniciar o piloto local

Necessário Python 3.12 ou Docker. Abra a pasta do projeto em um terminal:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python manage.py init-rh --login rh --name "Responsável RH"
python manage.py serve
```

O primeiro comando de administração pede a senha sem exibi-la. A senha deve ter 12 a 128 caracteres. Acesse `http://127.0.0.1:8000` no mesmo computador; entre com a matrícula e senha que você definiu. Em **Validação e backup**, crie os exemplos de teste. As duas senhas fictícias são exibidas uma única vez ao RH. Entregue cada senha individualmente e troque-a no primeiro acesso.

O endereço local só funciona enquanto o serviço estiver rodando naquele computador. Não é um endereço de internet e não deve ser usado como publicação final.

### Docker

```sh
docker compose build
docker compose run --rm portal python manage.py init-rh --login rh --name "Responsável RH"
docker compose up -d
```

O volume `portal-data` preserva banco e arquivos. Nunca execute `docker compose down -v` no ambiente em uso: isso remove o volume. A porta permanece no localhost; um proxy HTTPS deve publicar o domínio quando a hospedagem for escolhida.

## Testes e resultado

```sh
python run_tests.py
```

`TEST_RESULTS.json` registra os testes realmente executados neste pacote e os limites da validação. Os testes usam contas e pastas temporárias. O teste de restauração recupera um PDF assinado em banco/armazenamento separados, verifica seu conteúdo e permite novo login. Testes locais não aprovam uma hospedagem ainda não configurada.

## Armazenamento

Todo dado em `PORTAL_DATA` deve estar em **disco/volume persistente**, com acesso só ao usuário do serviço e ao operador autorizado. SQLite é adequado a este piloto de **uma instância**; não use múltiplas réplicas ou um sistema de arquivos de rede compartilhado. A pasta de arquivos não é servida publicamente. A autenticação é conferida em todo download e visualização.

No servidor, monitore disco, saúde do serviço e erros. Use backups externos protegidos, retenção definida e teste periódico de restauração. Essas rotinas externas ainda não foram configuradas. Não armazenar documentos reais neste piloto até validar hospedagem e processo.

## Status e limites antes de produção

- Falta escolher e configurar a hospedagem, domínio/subdomínio, HTTPS, volume persistente e responsáveis pelas contas.
- Falta sincronizar este código com um repositório privado da empresa. O pacote ZIP é uma cópia do código, não um backup automático.
- Falta configurar backup externo automático, criptografia, retenção, alertas e operação da recuperação de acesso.
- Falta uma rodada de uso em celulares reais com RH e funcionários, revisão independente de segurança e validação do processo de assinatura adotado pela empresa.
- O portal depende de manutenção. Não há garantia de zero falhas, publicação perpétua ou proteção contra administrador mal-intencionado com acesso ao servidor.
- Versão do esquema: 1. Atualizações futuras exigem migrações versionadas e backup anterior; o inicializador não migra alterações de tabelas existentes.
- PDFs até 15 MB / 60 páginas por lote; correção com prévia até 12 páginas. Não há OCR ou reconhecimento automático de matrícula neste piloto. A vinculação é manual e revisável.
- O servidor rasteriza PDFs para isolamento. A comprovação de que a página pertence só ao destinatário depende da revisão do RH; não há detector automático infalível de conteúdo pessoal.
- Assinaturas têm registro e hashes, mas não carimbo de tempo externo ou assinatura criptográfica. A compilação em PDF é para organização; preserve os documentos individuais e as evidências.
- Os backups incluem hashes de senha e traços de assinatura. São privados. Os checksums detectam corrupção, mas não comprovam a origem de um backup alterado junto com seu manifesto.
- O protótipo não implementa autenticação em dois fatores, recuperação por e-mail ou integração automática com Dropbox/Drive. Redefinição de funcionário é feita pelo RH; recuperação do RH exige operador autorizado do servidor.

## Referências técnicas

- Flask / publicação: https://flask.palletsprojects.com/en/stable/deploying/
- pypdf: https://pypdf.readthedocs.io/
- PDFium Python: https://pypdfium2.readthedocs.io/
- Argon2: https://argon2-cffi.readthedocs.io/

Consulte `OPERACAO.md` para backup, restauração, publicação e rollback.
