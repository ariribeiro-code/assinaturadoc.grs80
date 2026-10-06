# Registro de validação

Foram executados 13 testes automatizados no ambiente local com contas fictícias e pastas temporárias; todos passaram. Os resultados individuais estão em TEST_RESULTS.json e o comando reproduzível é `python run_tests.py` após instalar os requisitos.

Também passaram a compilação sintática dos arquivos Python e a validação sintática JavaScript (`node --check static/app.js`). As fontes Inter e Archivo estão locais e as referências de arquivos foram verificadas.

A restauração recuperou o mesmo PDF assinado em uma pasta separada, invalidou sessões e permitiu novo login. O teste de backup alterado recusou um conteúdo que não correspondia ao manifesto. Não é uma auditoria independente ou prova de proteção contra alterações intencionais do banco e manifesto juntos.

A conferência de telas com navegador automatizado não foi executada: o navegador necessário não estava disponível e seu download/instalação falhou neste ambiente. Não há resultado aprovado de navegação visual, posição dos campos em aparelhos reais ou assinatura com o dedo. Esses testes permanecem no checklist antes de produção.

Não foram testados Docker construído, hospedagem externa, domínio, certificado HTTPS, restauração em outra máquina, volume persistente do futuro servidor, integração Dropbox ou backups automáticos externos. Nenhum funcionário real foi convidado e nenhum documento real foi importado.
