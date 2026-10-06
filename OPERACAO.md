# Operação e validação do piloto

## 1. Contas e publicação

A empresa deve controlar domínio, conta de hospedagem, repositório e destino dos backups. O funcionário acessará um endereço próprio e entrará com matrícula e senha. Não publicamos este pacote em Sites, Lovable ou outro serviço. A escolha da hospedagem continua pendente; nenhum custo foi contratado.

Instalação prevista: uma instância do serviço Waitress, volume persistente para `/data` e proxy reverso com certificado HTTPS. No modo de produção, definir `PORTAL_MODE=production` e `PUBLIC_ORIGIN=https://colaborador.DOMINIO-DA-EMPRESA`. A aplicação recusa inicializar produção com origem HTTP. Configure o proxy sem permitir que o público acesse a porta interna diretamente. O serviço não confia em cabeçalhos de proxy enviados pelo cliente.

Só aplique configurações de proxy confiável quando o provedor e a cadeia de encaminhamento estiverem definidos. A limitação de tentativas também usa o endereço da conexão; atrás de um proxy pode limitar várias pessoas pelo mesmo endereço. Validar esse comportamento na implantação e adicionar limitação no proxy.

Não confundir o endereço `127.0.0.1` com publicação. Não publicar servidor de desenvolvimento nem abrir a pasta de arquivos pela web. Não colocar banco/arquivos em disco efêmero, pois podem desaparecer em um reinício ou nova versão.

## 2. Pré-liberação

- Abrir a aplicação por HTTPS, entrar como RH, trocar senhas e validar término de sessão.
- Confirmar que cookies usam Secure, HttpOnly e SameSite.
- Testar A e B via suas contas, inclusive tentando IDs/links diretos e download um do outro.
- Testar upload, revisão e liberação de um lote fictício com duas vias.
- Conferir assinatura com o dedo em aparelho real, legibilidade, campos e horário.
- Interromper armazenamento em ambiente de teste e confirmar que o status não fica assinado.
- Confirmar que documentos só para consulta não contam como assinaturas.
- Assinar todo o lote, baixar PDF/ZIP e conferir páginas e destinatários.
- Baixar backup, restaurar em ambiente separado e conferir hashes, logins e documento assinado.
- Definir horários de backup externo, retenção, responsáveis e rotina de restauração.
- Revisar o texto de confirmação e o processo de assinatura da empresa antes de uso real.

## 3. Backup

Pela área RH: **Validação e backup → Baixar backup completo**. O backup online usa a mesma trava das operações que alteram os documentos para obter banco e arquivos consistentes. Guarde-o fora do servidor em local restrito e protegido.

Alternativa administrativa, com o serviço parado:

```sh
python manage.py backup --data /caminho/dados --file /caminho/protegido/backup.zip
```

O arquivo tem `portal.db`, `files/` e `manifest.json`. As sessões não são restauradas. Há hashes das senhas, documentos, traços e evidências — não compartilhe o ZIP publicamente. Defina retenção e criptografia no destino escolhido. O backup automático não foi configurado.

## 4. Restauração

No ambiente isolado, com a aplicação parada:

```sh
python manage.py restore --data /caminho/novo-vazio --file /caminho/protegido/backup.zip
```

O comando recusa pasta com dados, valida caminhos, manifesto, integridade/relacionamentos do banco e hashes dos arquivos referenciados. A sessão anterior deixa de funcionar; novo login usa a senha que estava vigente no backup. Compare o PDF final, protocolo e hashes com o ambiente original. A restauração não instala o código: preserve o pacote/repositório correspondente à versão do banco.

Não extrair ZIP diretamente sobre uma instalação ativa. Não tratar manifesto SHA-256 como certificado de autenticidade. Mantenha origem e transporte do backup confiáveis.

## 5. Atualizações e retorno de versão

1. Registrar a versão do código, executar testes e guardar o pacote.
2. Gerar backup de banco e arquivos; confirmar que foi armazenado externamente.
3. Aplicar mudanças primeiro no ambiente de homologação.
4. Executar as verificações de login, documento, assinatura e exportação.
5. Para mudanças de esquema, planejar migração específica, manter histórico e testar restauração.
6. Publicar código no mesmo ambiente com o volume preservado; conferir saúde e fluxos essenciais.
7. Se falhar, suspender operações de assinatura e restaurar código anterior. Se o esquema mudou, restaurar o backup compatível em ambiente separado antes de trocar a instalação. Não sobrescrever dados novos sem conciliação.

## 6. Recuperação e resposta a falhas

Funcionário: RH gera senha temporária e as sessões existentes são encerradas. Desativar funcionário também invalida sessões.

RH: como não há recuperação pública por e-mail, o operador autorizado do servidor deve redefinir a senha pelo procedimento interno da empresa. Confirmar a identidade antes da alteração, registrar a intervenção e encerrar as sessões dessa conta. Uma interface administrativa de recuperação adicional deve ser projetada antes da produção; nunca criar um botão anônimo de “primeiro RH”.

Acompanhar espaço disponível, `/health`, falhas de backup e alertas de acesso. A aplicação não confirma sucesso de assinatura quando falha a persistência. Se o servidor cair entre gravar arquivo e confirmar o banco, pode sobrar um arquivo sem referência; não apagar arquivos automaticamente sem comparar com o banco e backups. Arquivos sem referência não entram no backup normal.

## 7. Dados e limites

O primeiro piloto usa somente exemplos fictícios. Exportações completas ficam restritas ao RH. PDFs individuais são preservados; correção gera uma nova versão. Original do lote nunca é entregue ao funcionário.

Esta é uma base de homologação local, sem autorização para usar o volume temporário desta conversa como armazenamento da empresa. A hospedagem final e o subdomínio ainda precisam ser configurados.
