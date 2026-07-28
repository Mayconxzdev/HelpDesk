## Contexto

<!-- Qual problema esta mudança resolve? -->

## Alterações

-

## Validação

- [ ] `python scripts/validate_public_release.py`
- [ ] `python scripts/check_markdown_links.py`
- [ ] `ruff check .`
- [ ] `pytest -q`
- [ ] `cd hd_electron && npm run check`
- [ ] Documentação e screenshots atualizados, quando aplicável

## Segurança e dados

- [ ] Não inclui `.env`, bases locais, credenciais, IPs privados ou dados pessoais
- [ ] Rotas sensíveis validam autenticação e autorização no backend
- [ ] Alterações no Electron preservam sandbox, isolamento e IPC restrito

## Evidências

<!-- Prints, logs sanitizados ou passos de reprodução. -->
