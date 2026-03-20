# Mentoria AI - Consultoria Multi-Agentes em Tempo Real

Mentoria AI é uma plataforma inovadora de consultoria empresarial que utiliza múltiplos agentes de Inteligência Artificial para fornecer mentoria especializada, interativa e em tempo real para empreendedores e empresas.

## 🚀 Como Funciona

O usuário apresenta o desafio do seu projeto e interage por voz com uma equipe multidisciplinar de 5 especialistas de IA. Os agentes conversam entre si, debatem ideias e fazem perguntas ao usuário para entender a fundo o problema.

Ao final da sessão, a transcrição completa é analisada e o sistema gera automaticamente um **Plano de Execução** detalhado em PDF, contendo um roteiro prático, análise de riscos e próximos passos.

## 👥 A Equipe de Especialistas (Agentes)

O sistema conta com 5 agentes, cada um com sua própria voz, personalidade e área de foco, orquestrados através do framework LiveKit:

1. 🎙 **Nathália (Apresentadora/Host)** - Orquestra a sessão, gerencia os turnos de fala e garante que todas as áreas do projeto sejam abordadas.
2. 🎙 **Carlos (CFO)** - Especialista em viabilidade financeira, fluxo de caixa, precificação e captação de recursos.
3. 🎙 **Daniel (Advogado)** - Focado em conformidade legal, análise de riscos, estruturas societárias e contratos.
4. 🎙 **Rodrigo (CMO)** - Especialista em aquisição de clientes, marketing estratégico, vendas e go-to-market.
5. 🎙 **Ana (CTO)** - Focada em viabilidade tecnológica, arquitetura de software, stack e escalabilidade.

## ✨ Principais Funcionalidades

### 1. Sala de Mentoria Interativa (WebRTC)
- **Voice Activity Detection (VAD)**: O usuário pode interromper os agentes a qualquer momento apenas começando a falar. Os agentes pausam instantaneamente.
- **Detecção de Fala em Tempo Real**: Indicadores visuais mostram qual agente está falando.
- **Painel de Transcrição**: Acompanhamento em texto de toda a conversa na lateral da tela.

### 2. Dashboard e Gestão
- **Gestão de Projetos**: Os usuários podem cadastrar múltiplos projetos para receber mentoria.
- **Histórico de Planos**: Acesso e download de todos os Planos de Execução já gerados em PDF.

### 3. Autenticação e Assinaturas
- Sistema de login seguro usando NextAuth.js.
- Gestão de créditos de mentoria.
- Painel de planos de assinatura (Free, Starter, Pro), pronto para integração com Stripe.

## 🛠 Arquitetura Tecnológica

### Frontend (Next.js 14+)
- **React 19 & Tailwind CSS**: Para uma interface de usuário responsiva e moderna.
- **NextAuth.js**: Gestão de autenticação.
- **LiveKit Components React**: Para gestão fluida da conexão WebRTC e renderização da sala de áudio.

### Backend (Node.js & Python)
- **Neon DB (PostgreSQL Serverless)**: Banco de dados relacional rápido e escalável.
- **Drizzle ORM**: Interação typesafe com o banco de dados.
- **Python Worker (LiveKit Agents)**: O "cérebro" da operação. Um serviço Python rodando o LiveKit Agents SDK para orquestrar os 5 LLMs em paralelo.

### Componentes de IA
- **LLM**:Gemini gemini-2.5-flash-native-audio-preview-12-2025 multi-modal.

- **Live **: agente).
- **VAD**: Modelo Silero VAD local no worker Python para latência ultra-baixa de interrupção.

## ⚙️ Como Rodar Localmente

### Pré-requisitos
- Node.js (v18+)
- Python (v3.10+)
- Contas no: Neon DB, LiveKit Cloud, Google AI Studio (Gemini)

### 1. Configuração do Frontend (Next.js)

```bash
# Instale as dependências
npm install

# Copie o env.local
cp .env.example .env

# Configure as variáveis no .env:
# DATABASE_URL (Neon)
# NEXTAUTH_SECRET e NEXTAUTH_URL
# LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL
```

Inicie o servidor de desenvolvimento:
```bash
npm run dev
```

### 2. Configuração do Worker Python (IA)

```bash
# Entre na pasta agents
cd agents

# Crie um ambiente virtual e instale dependências
python -m venv venv
source venv/bin/activate  # ou `venv\Scripts\activate` no Windows
pip install -r requirements.txt

# O Worker utilizará o mesmo arquivo .env da raiz do projeto.
# Certifique-se de ter configurado: GEMINI_API_KEY
```

Inicie o worker para orquestrar as salas:
```bash
python worker.py dev
```

---
*Mentoria AI - Transformando ideias em execução através de Inteligência Artificial Colaborativa.*
