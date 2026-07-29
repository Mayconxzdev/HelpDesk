# Integração contínua

## HelpDesk CI

O workflow `.github/workflows/ci.yml` possui dois jobs independentes.

### Python

- instala as dependências bloqueadas por faixa em `requirements-dev.txt`;
- verifica a higiene da distribuição pública;
- valida links locais da documentação;
- executa o conjunto crítico do Ruff;
- compila as fontes Python;
- executa os testes Pytest sobre SQLite temporário.

### Electron

Os testes do job Electron usam apenas o Node.js e arquivos locais. O CI não baixa binários do Electron nem gera instaladores; empacotamento desktop deve ser validado em um workflow de release separado.


- instala a árvore bloqueada com scripts de pós-instalação desativados;
- valida o manifesto e a consistência do lockfile;
- executa verificações de sintaxe e contratos de segurança após validar a instalação bloqueada;
- valida a sintaxe dos processos main, preload e utilitários;
- executa contratos de segurança para URL, atualização e abertura de pastas.

O CI não gera instalador Windows nem assina binários. Essas etapas exigem um runner e credenciais específicos de release.

## CodeQL

`.github/workflows/codeql.yml` analisa Python e JavaScript em pushes, pull requests e agenda semanal.

## Reprodução local

```bash
pip install -r requirements-dev.txt
python scripts/validate_public_release.py
python scripts/check_markdown_links.py
python scripts/check_npm_lock.py
python -m pip check
ruff check .
python -m compileall -q app.py ia.py security_utils.py tests scripts
python -m pytest -q

cd hd_electron
npm ci --ignore-scripts
npm run check
```

O badge deve estar verde no commit usado em candidaturas. Um workflow configurado não é evidência de execução bem-sucedida até o GitHub Actions concluir os jobs.
