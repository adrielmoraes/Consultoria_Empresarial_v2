# Mentoria AI - Consultoria Multi-Agentes em Tempo Real

Mentoria AI é uma plataforma de ponta para consultoria empresarial que utiliza múltiplos agentes de Inteligência Artificial para fornecer uma experiência imersiva, em tempo real, baseada em voz, para empreendedores e gestores de projetos.

## 🚀 Como Funciona

O usuário se cadastra com um fluxo de autenticação seguro, escolhe seu plano de acesso com Webhooks configurados no Stripe e acessa o seu Dashboard. Lá, cria "Projetos" e faz o **upload de anexos do negócio** (balanços, notas, ideias, sumários).

Na **Sala de Mentoria**, a LiveKit faz a orquestração WebRTC ultra-baixa latência:
O usuário interage "falando" nativamente com uma equipe de especialistas de IA (usando Gemini 2.5/3.1). Os agentes trocam turnos de fala, debatem os arquivos que você enviou e a transcrição da sua voz é gerada simultaneamente na tela.

Quando a consultoria acaba, o agente consolidador final (**Marco**) faz uma varredura silenciosa do mercado na web (Via DuckDuckGo) e gera **automáticamente um Plano de Execução (em formato PDF corporativo)** estruturado contendo análise financeira, marketing e próximos passos táticos a serem tomados pelo seu negócio.

## 👥 A Equipe Oculta e Especialistas (LiveKit Agents)

O sistema orquestra nativamente **6 Entidades IA** no Backend Python:

1. 🎙 **Nathália (Apresentadora/Host)** - Gere a sala, passa a palavra de modo dinâmico (transferência lateral de inteligência) e modera o foco.
2. 🎙 **Carlos (CFO)** - Especialista em viabilidade financeira e precificação de negócios.
3. 🎙 **Daniel (Advogado)** - Compliance Legal, LGPD, riscos regulatórios.
4. 🎙 **Rodrigo (CMO)** - Vendas, Gatilhos Mentais, Cost of Acquisition e Growth.
5. 🎙 **Ana (CTO)** - Focada em software, stack, hardware, automações tecnológicas.
6. 🧠 **Marco (Estrategista Chief)** - Agente Fantasma responsável por consolidar insights da sala, pesquisar o mercado e diagramar o PDF Final Report.

## ✨ Principais Funcionalidades

### 1. Neuromarketing Digital Landing Page
- Uma interface desenhada visando apelo profundo para leads (Framer Motion + Dark & Gold Systems).
- Copys orientadas por Pacing & Leading para conversão imediata, desenhadas na gigantesca rota raiz da página inicial (Páginas Otimizadas).
- Políticas de Privacidade e Termos de Uso geradas e indexáveis nativamente pelo App Router.

### 2. Autenticação & Gestão de Créditos
- Sistema de login seguro usando `NextAuth.js v5 Beta`.
- Base de dados utilizando `NeonDB Serverless` conectado via `Drizzle-ORM`.
- Fluxo dinâmico de permissão (Middleware Protections).

### 3. Integração Stripe + PIX
- Checkout Redirecionado ou Embeddado do `stripe` & `@stripe/stripe-js`.
- Configuração Multi-Mode (Assinatura / Compras Adicionais).
- Suporte homologado para PIX nativo na página de cobrança.

### 4. RAG Lite (Anexos Privados) e Web-Search 
- A plataforma usa `pdf-parse` e extração de Documentos locais carregados pelos usuários no frontend, alimentando o contexto dos modelos.
- Integração DuckDuckGo (`duckduckgo-search`) feita em Python assíncrono para os agentes captarem tendências diárias do mercado durante o draft executivo do Agente Marco.
- LLM Principal da Reunião: Geração contínua via **Gemini** (utilizando 2.5 Pro ou 3.1-flash-lite-preview na camada RAG).

## 🛠 Arquitetura Tecnológica Atualizada (Stack 2026/V4)

### Frontend (App Router)
- **Next.js 16.2.0**: A mais recente infraestrutura de renderização híbrida.
- **React 19**: Trazendo otimizações de hook e React Compiler.
- **Tailwind CSS v4**: PostCSS Engine Nativo.
- **Framer Motion v12**: Animações de Scroll fluidas e micro-interações UX-driven.

### Orquestração Media & Voice
- **LiveKit Server SDK / Client / Componentes React (>v2.15)**.
- Transcrição simultânea do usuário, Mute Tracking e Room Participants visualização.
- VAD (Voice Activity Detection): Silencia o agente perfeitamente quando o usuário começar a falar.

### Backend/Storage (Node.js & Python)
- **NeonDB** Serverless (Neon Postgres via `drizzle-adapter`).
- **Python Agents Worker**: Roda o SDK `livekit-agents` para manter a sala online, gerenciar a API do Google (gemini) e fazer a inferência baseada na placa gráfica ou endpoints externos cloud (VAD local com Silero).
- Tooling e Relatório: Utilização de `reportlab` no servidor e injeção do PDF via Base64 pelo Web Socket.

## ⚙️ Como Rodar Localmente

### Pré-requisitos
- Node.js (v18+)
- Python (v3.10+)
- Contas Externas ativas: Neon DB, LiveKit Cloud, Google AI Studio e Stripe.

### 1. Configuração do Servidor Frontend (Next.js)

```bash
# Instale as dependências (React 19 / Next 16)
npm install

# Aplique o schema de DB e Puxe sua config
npm run db:push

# Crie e preencha as variáveis de .env
# NEXTAUTH_SECRET, AUTH_DRIZZLE_URL, STRIPE_SECRET_KEY, LIVEKIT_URL, etc

# Suba a Vercel/Node Server local
npm run dev
```

### 2. Configuração do Hive Mind (Worker da Inteligência em Python)

```bash
# Navegue para o microserviço e prepare ambiente
cd agents
python -m venv venv
venv\Scripts\activate

# Instale os pacotes principais do RAG e Core
pip install -r requirements.txt
pip install duckduckgo-search

# Rodar o Worker Local interagindo com sua LiveKit API
python worker.py dev
```

---
*Mentoria AI - Consultoria guiada por IAs conversacionais em latência real.*
