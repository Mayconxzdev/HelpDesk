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

- instala o lockfile com `npm ci --ignore-scripts`;
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
ruff check .
python -m compileall -q app.py ia.py security_utils.py tests scripts
pytest -q

cd hd_electron
npm ci --ignore-scripts
npm run check
```

O badge deve estar verde no commit usado em candidaturas. Um workflow configurado não é evidência de execução bem-sucedida até o GitHub Actions concluir os jobs.
