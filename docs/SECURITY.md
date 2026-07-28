# Segurança técnica

## Melhorias aplicadas

- credenciais e IPs privados foram removidos do código;
- senhas de autenticação são hashes Werkzeug;
- campos operacionais sensíveis usam Fernet em repouso;
- APIs comuns mascaram segredos;
- cookie de sessão usa `HttpOnly`, `SameSite` e `Secure` configurável;
- operações de escrita validam a origem quando o navegador envia `Origin`;
- Socket.IO possui allowlist de origem e exige sessão;
- redirecionamento após login aceita apenas caminhos locais;
- inventário, cofre operacional e IA local exigem perfil administrativo;
- a integração com Ollama fica desabilitada até ativação explícita por ambiente;
- uploads possuem limite global de tamanho;
- Electron não habilita Node.js no renderer;
- IPC de abertura de diretório exige allowlist;
- atualização não baixa nem executa um binário arbitrário;
- CI procura artefatos sensíveis e padrões conhecidos.

## Limites

- a proteção de origem não substitui um sistema completo de CSRF;
- o rate limit fica em memória e não é compartilhado entre processos;
- a cifra deriva uma chave local quando o ambiente não é produção; produção exige chave dedicada;
- não existe rotação automatizada de segredos;
- os campos cifrados ainda pertencem ao banco da aplicação;
- o projeto precisa de revisão externa antes de lidar com dados reais.

## Produção

No mínimo:

1. `APP_ENV=production`;
2. `FLASK_SECRET_KEY` aleatória com 32 ou mais caracteres;
3. `CREDENTIAL_ENCRYPTION_KEY` gerada por Fernet;
4. HTTPS e `SESSION_COOKIE_SECURE=true`;
5. `ENABLE_DEMO_AUTH=false`;
6. PostgreSQL com usuário de privilégio mínimo;
7. origem Socket.IO restrita ao domínio real;
8. proxy reverso, observabilidade e backup;
9. identidade corporativa e política de autorização granular.
