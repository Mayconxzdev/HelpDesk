# Estado e maturidade

| Área | Estado | Observação |
|---|---|---|
| Autenticação local | Funcional | Identidades demo por ambiente; falta provedor corporativo. |
| Tickets | Funcional | Fluxo principal implementado; falta SLA configurável e testes mais amplos. |
| Inventário | Funcional parcial | Cadastro amplo; validações e migrações precisam evoluir. |
| Auditoria | Funcional parcial | Registra mudanças relevantes, mas não é log imutável externo. |
| Chat | Funcional | Texto, grupos, mídia e presença; anexos precisam migrar para object storage. |
| Electron | Funcional | Shell endurecido; build Windows deve ser validado em runner Windows. |
| IA via Ollama | Experimental | Depende de serviço local e não participa do CI. |
| Helper RAG | Experimental | Base demonstrativa e fallback local; não é motor de conhecimento corporativo pronto. |
| PostgreSQL | Configurável | Caminho disponível, sem teste de integração no CI básico. |
| CI | Configurado | Python, contratos públicos, Electron checks e CodeQL; o resultado deve ser confirmado no commit publicado. |

## Próximas prioridades

1. separar `app.py` por blueprints e serviços;
2. introduzir Alembic/Flask-Migrate;
3. criar autorização por permissão, não apenas perfis;
4. mover anexos para storage dedicado;
5. usar rate limiting compartilhado;
6. adicionar integração PostgreSQL em CI;
7. publicar demonstração com dados sintéticos;
8. criar teste E2E do fluxo login → ticket → encerramento.
