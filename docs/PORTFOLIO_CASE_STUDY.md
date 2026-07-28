# Case de portfólio — HelpDesk & IT Operations

## Contexto

O projeto nasceu para concentrar rotinas internas de suporte e controle de TI que estavam distribuídas entre conversas, planilhas e conhecimento informal. A solução reúne chamados, ativos, acessos, atalhos e chat em uma aplicação web acompanhada por um cliente Electron.

## Problema

A fragmentação dificultava três pontos:

1. rastrear o que havia sido solicitado e resolvido;
2. entender a relação entre colaborador, equipamento, acesso e manutenção;
3. manter comunicação rápida sem perder completamente o histórico.

## Solução implementada

A aplicação organiza as informações em domínios funcionais:

- chamados com prioridade, categoria, histórico e métricas;
- usuários, computadores, contas, e-mails, certificados e programas;
- manutenção e trilha de alteração;
- atalhos pessoais e globais;
- conversas individuais e em grupo por Socket.IO;
- cliente desktop com tray e notificações;
- contexto técnico opcional para Ollama.

## Trabalho de modernização para publicação

A preparação do portfólio não se limitou ao README. A distribuição pública passou por mudanças de engenharia:

- remoção de credenciais, IPs e dados corporativos codificados;
- substituição de senhas em texto puro e Base64 por hashes;
- cifra de campos operacionais sensíveis;
- restrição de origem no Socket.IO;
- proteção de rotas que estavam expostas;
- remoção de chaves públicas de serviços externos;
- endurecimento do Electron;
- troca de `pickle` por estado seguro e reproduzível no helper de IA;
- criação de testes, auditorias automatizadas e workflows de CI.

## Trade-offs

O sistema continua sendo um monólito. Refatorar todos os domínios antes de publicar aumentaria o risco de regressão e apagaria o valor de mostrar uma modernização incremental. A estratégia escolhida foi:

1. corrigir riscos críticos;
2. tornar a execução local reproduzível;
3. adicionar testes de contrato;
4. documentar a dívida técnica;
5. preparar a separação futura em blueprints e serviços.

## Resultado de portfólio

O repositório demonstra capacidade de trabalhar em código existente, identificar problemas reais, reduzir risco, documentar decisões e criar um caminho de evolução — competências importantes em projetos profissionais, nos quais raramente se começa do zero.
