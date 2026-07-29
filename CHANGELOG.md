# Changelog

## 2.0.2 — CI verification hardening

- caminho SQLite local corrigido para evitar `instance/instance`;
- banco de testes isolado e descarregado corretamente;
- lockfile npm validado e novamente instalado no CI;
- caches Python e artefatos compilados rejeitados pela auditoria pública;
- sintaxe dos JavaScripts do navegador incluída no CI.


## 2.0.1 — CI hardening

- banco SQLite de testes isolado em caminho temporário absoluto;
- remoção de configuração externa conflitante no Pytest;
- job Electron executado sem instalação desnecessária de binários;
- lockfile reparado para remover faixas transitivas incompatíveis.

## 2.0.0 — Portfolio hardening

- distribuição pública sanitizada;
- autenticação demo configurável por ambiente;
- senhas com hash e campos operacionais cifrados;
- APIs sensíveis protegidas e payloads mascarados;
- Socket.IO e Electron endurecidos;
- helper RAG reescrito sem `pickle` e sem dados corporativos;
- testes, scripts de validação, CI e CodeQL;
- documentação de arquitetura, segurança, maturidade e case.
