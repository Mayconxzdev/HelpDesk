<div align="center">

# HelpDesk & IT Operations

### Central interna para chamados, ativos, acessos, comunicação e assistência local de IA

[![HelpDesk CI](https://github.com/Mayconxzdev/HelpDesk/actions/workflows/ci.yml/badge.svg)](https://github.com/Mayconxzdev/HelpDesk/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Mayconxzdev/HelpDesk/actions/workflows/codeql.yml/badge.svg)](https://github.com/Mayconxzdev/HelpDesk/actions/workflows/codeql.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000?logo=flask&logoColor=white)
![Electron](https://img.shields.io/badge/Electron-Desktop-47848F?logo=electron&logoColor=white)

[Visão do produto](docs/PORTFOLIO_CASE_STUDY.md) · [Arquitetura](docs/ARCHITECTURE.md) · [Estado](docs/PROJECT_STATUS.md) · [Segurança](docs/SECURITY.md) · [English](README.en.md)

</div>

## Visão geral

Desenvolvi o HelpDesk para reunir atividades de TI que estavam espalhadas entre mensagens, e-mails e planilhas. A versão interna é utilizada por **11 pessoas** para abrir e acompanhar chamados, consultar ativos, organizar acessos e se comunicar com a equipe responsável.

| Área | Implementação atual |
|---|---|
| **Chamados e operação** | Prioridade, categoria, histórico, acompanhamento e comunicação em tempo real. |
| **Ativos e acessos** | Usuários, computadores, programas, certificados, manutenção, contas e compartilhamentos. |
| **Backend** | Flask, SQLAlchemy, sessões, APIs e Flask-SocketIO. |
| **Desktop** | Cliente Electron com tray, notificações e eventos Socket.IO. |
| **Segurança** | Hash de senhas, Fernet para campos sensíveis, mascaramento, origem restrita e Electron em sandbox. |
| **IA opcional** | Ollama e recuperação textual local; os módulos principais continuam funcionando sem IA. |
| **Qualidade** | Pytest, Ruff, Node Test Runner, CI, CodeQL e validação da versão pública. |

A versão interna continua ativa. Planejo incorporar suas capacidades gradualmente ao módulo de TI do **Portal**, preservando histórico, rastreabilidade e regras de acesso.

> Este repositório é uma edição pública sanitizada. Dados operacionais, credenciais, nomes, endereços internos e configurações de infraestrutura foram removidos ou substituídos por exemplos.

## O que desenvolvi

- abertura, prioridade, categoria, histórico e acompanhamento de chamados;
- inventário de usuários, computadores, programas, certificados e manutenção;
- gestão de contas, acessos, atalhos e compartilhamentos;
- chat em tempo real e notificações no cliente desktop;
- trilha de auditoria;
- assistência local de IA quando habilitada.

## Interface

| Portal de módulos | Autenticação |
|---|---|
| ![Portal principal](docs/portfolio/01-portal.webp) | ![Tela de login](docs/portfolio/02-login.webp) |

| Abertura de chamado | Chat interno |
|---|---|
| ![Abertura de chamado](docs/portfolio/03-ticket.webp) | ![Chat interno](docs/portfolio/05-chat.webp) |

## Arquitetura atual

O projeto é um **monólito Flask** com domínios, APIs, templates e eventos Socket.IO no mesmo processo. Essa escolha simplifica a operação interna. O arquivo principal ainda concentra responsabilidades e permanece registrado como dívida técnica.

```mermaid
flowchart LR
    U[Usuário] --> WEB[Templates + JavaScript]
    DESK[Electron] --> WEB
    WEB <-->|HTTP / JSON| API[Flask]
    WEB <-->|Socket.IO| RT[Flask-SocketIO]
    API --> AUTH[Sessões e autorização]
    API --> ORM[SQLAlchemy]
    RT --> ORM
    ORM --> DB[(SQLite / PostgreSQL)]
    API --> VAULT[Cifra de campos sensíveis]
    API -. opcional .-> OLLAMA[Ollama]
    RAG[Busca local opcional] --> OLLAMA
```

## Decisões técnicas

- SQLite por padrão para uso e avaliação local, com PostgreSQL disponível por configuração;
- senhas de login protegidas com hash Werkzeug;
- campos operacionais sensíveis cifrados e mascarados nas respostas comuns;
- Socket.IO com origem restrita;
- Electron com `contextIsolation`, `sandbox` e `nodeIntegration: false`;
- atualização manual validada, sem executar binários arbitrários;
- Ollama, Redis e recuperação local opcionais, sem bloquear os módulos principais.

## Stack

| Camada | Tecnologias |
|---|---|
| Backend | Python 3.12, Flask, Flask-SQLAlchemy, SQLAlchemy |
| Tempo real | Flask-SocketIO, Socket.IO |
| Frontend | Jinja2, HTML, CSS, JavaScript |
| Banco | SQLite, PostgreSQL opcional |
| Desktop | Electron, Node.js |
| Segurança | Werkzeug hashing, Fernet, cookies e origem restrita |
| IA opcional | Ollama, TF-IDF, scikit-learn, Redis |
| Qualidade | Pytest, Ruff, Node Test Runner, CodeQL, GitHub Actions |

## Executar localmente

```bash
git clone https://github.com/Mayconxzdev/HelpDesk.git
cd HelpDesk
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
pip install -r requirements-dev.txt
python app.py
```

Cliente Electron:

```bash
cd hd_electron
npm install
```

## Validar

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

## Estado e limites

- não há demonstração pública hospedada;
- `app.py` ainda deve ser dividido por blueprints e serviços;
- não existe um sistema completo de migrações de banco;
- o rate limit é local ao processo;
- arquivos do chat ainda ficam no banco, e não em object storage;
- a matriz de permissões é simplificada;
- Ollama, Redis e PostgreSQL dependem do ambiente;
- o sistema oferece rastreabilidade, mas não certifica conformidade ISO 9001.

## Autor

**Maycon da Silva Ferreira** — produto, arquitetura, backend, interface, cliente desktop, segurança, implantação, treinamento e sustentação.

## Licença

Distribuído sob a [licença MIT](LICENSE).
