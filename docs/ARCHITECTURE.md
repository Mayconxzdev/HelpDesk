# Arquitetura

## Estado atual

A aplicação é um monólito Flask. Modelos SQLAlchemy, rotas HTTP, eventos Socket.IO e parte das regras de negócio residem em `app.py`. Templates Jinja2 e JavaScript consomem as APIs no mesmo domínio. O cliente Electron carrega essa aplicação remota dentro de uma janela isolada.

## Componentes

- **Flask:** sessões, páginas e APIs JSON;
- **Flask-SQLAlchemy:** persistência relacional;
- **Flask-SocketIO:** presença, salas e eventos em tempo real;
- **Templates/static:** experiência web;
- **Electron:** shell desktop, tray e notificações;
- **security_utils.py:** cifra de campos sensíveis;
- **ia.py:** helper local opcional para recuperação de contexto.

## Fronteiras funcionais existentes

Apesar do monólito, o código contém domínios reconhecíveis:

- tickets;
- ativos e usuários de TI;
- contas, e-mails, certificados e programas;
- manutenção e auditoria;
- atalhos;
- chat, grupos e presença;
- integrações locais de IA.

## Arquitetura-alvo

A evolução recomendada é manter um único deploy, mas separar módulos internos:

```text
helpdesk/
├── app_factory.py
├── extensions.py
├── auth/
├── tickets/
├── assets/
├── access_registry/
├── chat/
├── audit/
└── integrations/
```

Cada domínio deve possuir blueprint, schemas, serviço e testes. O banco deve passar a usar Alembic/Flask-Migrate. Eventos do chat e operações sensíveis devem compartilhar políticas de autorização explícitas.

## Decisões

### SQLite local e PostgreSQL configurável

SQLite reduz a barreira para avaliação. PostgreSQL continua disponível por `DATABASE_URL`, sem credenciais codificadas.

### Sessão e WebSocket no mesmo produto

Flask-SocketIO reutiliza a identidade da sessão. Handlers agora rejeitam conexões sem usuário autenticado e validam acesso à sala.

### Segredos operacionais

Campos de senha e chave são cifrados antes da persistência. Payloads comuns retornam apenas `has_secret`. Uma implantação real deveria mover esse conteúdo para um cofre dedicado e usar autorização de revelação com auditoria específica.

### Electron

O renderer não possui Node.js. IPCs são pequenos e validados. Caminhos locais dependem de allowlist e atualizações são abertas em URL HTTPS permitida, sem execução automática de binários.
