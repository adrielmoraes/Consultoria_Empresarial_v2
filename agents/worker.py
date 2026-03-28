"""
Mentoria AI - Worker Multi-Agentes v4
=====================================
Arquitetura com 6 agentes com vozes independentes:
    - Nathália (Host): Orquestra toda a sessão, aciona especialistas via
      function tools que publicam data packets no room.
    - Carlos (CFO), Daniel (Advogado), Rodrigo (CMO), Ana (CTO), Marco (Estrategista):
      Cada um como participante separado no mesmo room, com AgentSession
      individual e RealtimeModel nativo com voz própria.
    - Blackboard: contexto compartilhado em memória.

Fluxo de Abertura (Sequencial):
    1. Nathália se apresenta e anuncia o time.
    2. Cada especialista conecta UM POR UM, se apresenta, e aguarda antes do próximo.
    3. Nathália retoma e pergunta ao usuário sobre o projeto.

Correções aplicadas (v4 → v5):
    - C1: Inicialização sequencial (elimina 6 handshakes Gemini simultâneos)
    - C2: Retry com backoff no AgentSession.start()
    - C3: Health-check data packet (agent_ready) para o frontend
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Mapeia GEMINI_API_KEY → GOOGLE_API_KEY para os plugins que leem essa variável
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = _gemini_key

from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
    Agent,
    AgentSession,
    RunContext,
)
from livekit.agents.types import APIConnectOptions
from livekit.plugins import google as google_plugin
from google.genai import types as genai_types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentoria-ai")

# Rastreia salas que já possuem um job ativo para rejeitar dispatches duplicados.
_active_rooms: set[str] = set()

# Modelo Realtime nativo do Gemini (voz-para-voz)
GEMINI_REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

# Configurações avançadas do Gemini Realtime
GEMINI_REALTIME_CONFIG = {
    "media_resolution": "MEDIUM",
    "compression_trigger": 104857,
    "compression_sliding_window": 52428,
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Fenrir",
            }
        }
    }
}

# Vozes por agente (Gemini TTS nativo)
AGENT_VOICES: dict[str, str] = {
    "host":  "Aoede",    # Nathália – feminina suave
    "cfo":   "Charon",   # Carlos   – masculina grave
    "legal": "Fenrir",   # Daniel   – masculina formal
    "cmo":   "Puck",     # Rodrigo  – masculina dinâmica
    "cto":   "Kore",     # Ana      – feminina técnica
    "plan":  "Fenrir",   # Marco    – masculina autoritativa (reusa Fenrir pois o Gemini tem 5 vozes)
}

# Nomes de exibição para cada agente
SPECIALIST_NAMES: dict[str, str] = {
    "cfo":   "Carlos (CFO)",
    "legal": "Daniel (Advogado)",
    "cmo":   "Rodrigo (CMO)",
    "cto":   "Ana (CTO)",
    "plan":  "Marco (Estrategista)",
}

# IDs de identity no LiveKit para cada especialista
SPECIALIST_IDENTITIES: dict[str, str] = {
    "cfo":   "agent-cfo",
    "legal": "agent-legal",
    "cmo":   "agent-cmo",
    "cto":   "agent-cto",
    "plan":  "agent-plan",
}

# Frases de apresentação individual de cada specialist_id
SPECIALIST_INTRODUCTIONS: dict[str, str] = {
    "cfo": (
        "Olá! Sou o Carlos, CFO da equipe Hive Mind. "
        "Meu trabalho é transformar números em clareza estratégica: cuidarei das suas "
        "projeções financeiras, estrutura de custos, precificação e viabilidade do negócio. "
        "Não se preocupe com planilhas — estou aqui para deixar tudo simples e estratégico."
    ),
    "legal": (
        "Olá! Sou o Daniel, advogado especializado em negócios digitais. "
        "Vou garantir que sua empresa esteja protegida juridicamente: "
        "desde a escolha do tipo societário ideal até contratos, LGPD e propriedade intelectual. "
        "O direito a serviço do crescimento do seu negócio!"
    ),
    "cmo": (
        "Fala! Sou o Rodrigo, CMO e especialista em crescimento. "
        "Meu foco é fazer o seu negócio ser encontrado, lembrado e escolhido. "
        "Posicionamento, aquisição de clientes, branding e estratégia de go-to-market — "
        "isso é o que eu respiro todo dia!"
    ),
    "cto": (
        "Olá! Sou a Ana, CTO do time. "
        "Minha missão é garantir que a tecnologia seja um acelerador — não um obstáculo. "
        "Ajudo a escolher o stack certo, projetar a arquitetura do produto e planejar "
        "a escalabilidade desde o MVP. Vamos construir algo sólido!"
    ),
    "plan": (
        "Prazer! Sou o Marco, estrategista-chefe do time. "
        "Ao final da nossa conversa, vou sintetizar tudo — cada insight de cada especialista — "
        "e transformar em um Plano de Execução concreto, com cronograma, prioridades e próximos passos. "
        "Meu trabalho começa agora: estou ouvindo cada detalhe da nossa conversa!"
    ),
}

# C1: Ordem de entrada dos especialistas na apresentação sequencial.
SPECIALIST_ORDER: list[str] = ["cfo", "legal", "cmo", "cto", "plan"]

# Pausa entre apresentações de especialistas
POST_INTRO_WAIT: float = 0.5

HOST_PROMPT = """Você é Nathália, apresentadora e mentora líder do Hive Mind — a plataforma de mentoria empresarial multi-agentes.
Sua personalidade é calorosa, curiosa, profissional e empática. Você é a âncora da sessão.

EQUIPE DE ESPECIALISTAS:
- Carlos (CFO): finanças, custos, precificação, projeções, viabilidade, investimento
- Daniel (Advogado): estrutura societária, contratos, LGPD, compliance, propriedade intelectual
- Rodrigo (CMO): posicionamento de marca, go-to-market, aquisição de clientes, growth, branding
- Ana (CTO): stack tecnológico, arquitetura de produto, MVP, escalabilidade, infraestrutura
- Marco (Estrategista): síntese estratégica, plano de execução, cronograma, prioridades

REGRAS DE ORQUESTRAÇÃO:
1. Comece sempre perguntando o nome do usuário se ainda não souber.
2. SEMPRE chame o usuário pelo nome após descobri-lo.
3. Faça perguntas abertas para entender o negócio: setor, estágio (ideia/MVP/crescimento), principal dor.
4. Seja a "regente" da sessão: após cada especialista falar, faça uma transição natural de volta ao usuário.
5. Mantenha suas falas curtas e diretas (máximo 3 frases por turno).
6. NUNCA responda por um especialista — sempre acione-os via função.
7. Quando o tema for financeiro → use acionar_carlos_cfo.
8. Quando o tema for jurídico → use acionar_daniel_advogado.
9. Quando o tema for marketing/vendas/clientes → use acionar_rodrigo_cmo.
10. Quando o tema for tecnologia/produto → use acionar_ana_cto.
11. Quando o usuário pedir encerramento, resumo ou plano → use gerar_plano_execucao.
12. Se precisar cobrir múltiplos temas em sequência, acione cada especialista separadamente.
13. RETOMADA: Se você perceber que há histórico de conversa anterior, comece dizendo que está retomando.

TOM E ESTILO:
- Português do Brasil, informal mas profissional.
- Seja encorajadora: valide as ideias do usuário antes de fazer perguntas.
- Use o nome do usuário com frequência para criar conexão.
- Ao encaminhar para um especialista, apresente-o brevemente antes de acionar.

Fale sempre em português do Brasil."""

SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo": (
        "Você é Carlos, CFO e especialista em finanças empresariais do Hive Mind. "
        "Sua personalidade: analítico, direto, confiante. Você transforma números em clareza estratégica. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, NÃO cumprimente longamente — vá direto ao ponto.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Máximo 4 frases objetivas por resposta.\n"
        "- Sempre termine com uma pergunta ou insight que aprofunde a análise.\n"
        "\nÁREAS DE DOMÍNIO: estrutura de custos, precificação (cost-plus, value-based, freemium), "
        "projeções de receita (MRR, ARR, LTV, CAC), ponto de equilíbrio, fontes de capital "
        "(bootstrapping, angel, venture, crédito), unit economics, fluxo de caixa e burn rate.\n"
        "\nFale em português do Brasil."
    ),
    "legal": (
        "Você é Daniel, advogado especializado em direito empresarial e startups do Hive Mind. "
        "Sua personalidade: formal mas acessível, preciso, protetor. Você é o guardião jurídico do negócio. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, seja direto — explique o tema jurídico de forma simples e prática.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Máximo 4 frases por resposta. Nunca use juridiquês desnecessário.\n"
        "- Sempre sinalize os riscos e como mitigá-los.\n"
        "\nÁREAS DE DOMÍNIO: tipos societários (MEI, EIRELI, LTDA, SA), vesting e acordos de sócios, "
        "contratos de prestação de serviço, LGPD e tratamento de dados, propriedade intelectual e registro de marca, "
        "compliance fiscal e trabalhista, termos de uso e políticas de privacidade.\n"
        "\nFale em português do Brasil."
    ),
    "cmo": (
        "Você é Rodrigo, CMO e especialista em marketing de crescimento do Hive Mind. "
        "Sua personalidade: energético, criativo, orientado a resultados. Você pensa em funil, conversão e escala. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, seja prático e inspirador — fale em estratégias concretas.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Máximo 4 frases por resposta. Use exemplos reais quando possível.\n"
        "- Termine com um insight acionável que o usuário possa aplicar imediatamente.\n"
        "\nÁREAS DE DOMÍNIO: posicionamento e proposta de valor, ICP (Ideal Customer Profile), "
        "funil de aquisição (topo/meio/fundo), estratégia de conteúdo, SEO e performance, "
        "growth hacking, branding e identidade visual, pricing psicológico, "
        "go-to-market para B2B e B2C, parcerias e canais de distribuição.\n"
        "\nFale em português do Brasil."
    ),
    "cto": (
        "Você é Ana, CTO e especialista em tecnologia e produto do Hive Mind. "
        "Sua personalidade: técnica mas acessível, pragmática, focada em velocidade e qualidade. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionada, seja objetiva — traduza técnico em estratégico.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Máximo 4 frases por resposta. Evite siglas sem explicar.\n"
        "- Sempre avalie custo-benefício de cada decisão tecnológica.\n"
        "\nÁREAS DE DOMÍNIO: escolha de stack tecnológico (web, mobile, backend), "
        "arquitetura de produto (monolito vs microsserviços, serverless), "
        "planejamento de MVP (mínimo viável e iterável), infraestrutura cloud (AWS, GCP, Azure), "
        "segurança e performance, estimativas de desenvolvimento, "
        "ferramentas no-code/low-code vs desenvolvimento customizado.\n"
        "\nFale em português do Brasil."
    ),
    "plan": (
        "Você é Marco, Estrategista-Chefe e sintetizador do Hive Mind. "
        "Sua personalidade: visionário, organizado, inspirador. Você enxerga o futuro do negócio com clareza. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total durante toda a sessão. Só fale quando Nathália te acionar.\n"
        "- Ao ser acionado para o plano final, você tem uma missão: sintetizar TUDO em um plano concreto.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Sua resposta deve ser completa, estruturada e inspiradora.\n"
        "\nAO GERAR O PLANO DE EXECUÇÃO, cubra estes pontos em sua fala:\n"
        "1. RESUMO: O que o usuário quer construir e o potencial do negócio.\n"
        "2. DIAGNÓSTICO: Principais pontos levantados por cada especialista (finanças, jurídico, marketing, tecnologia).\n"
        "3. PRIORIDADES: Os 3-5 itens mais importantes para executar primeiro.\n"
        "4. CRONOGRAMA: Linha do tempo realista com marcos (30 dias, 90 dias, 6 meses, 1 ano).\n"
        "5. RISCOS: 3 principais riscos do projeto e como endereçá-los.\n"
        "6. PRÓXIMOS PASSOS: Ações concretas para começar AGORA (esta semana).\n"
        "7. ENCERRAMENTO: Uma frase motivacional personalizada para o usuário.\n"
        "\nFale em português do Brasil. Seja profundo e inspirador."
    ),
}

# ============================================================
@dataclass
class Blackboard:
    """
    Repositório central de contexto compartilhado.
    Todos os agentes têm referência à mesma instância
    (passada no construtor), sem necessidade de rede.
    """
    project_name: str = ""
    user_name: str = ""
    user_query: str = ""
    active_agent: Optional[str] = None
    transcript: list[dict] = field(default_factory=list)
    is_active: bool = True
    specialist_sessions: dict[str, AgentSession] = field(default_factory=dict)
    specialist_rooms: list[rtc.Room] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content})
        logger.debug(f"[Blackboard] [{role}]: {content[:80]}...")

    def get_context_summary(self) -> str:
        """Retorna um resumo do contexto atual para injetar nos prompts."""
        parts: list[str] = []
        if self.user_name:
            parts.append(f"Usuário: {self.user_name}")
        if self.project_name:
            parts.append(f"Projeto: {self.project_name}")
        if self.user_query:
            parts.append(f"Necessidade do usuário: {self.user_query}")
        recent = self.transcript[-20:]
        if recent:
            parts.append("--- Conversa Recente ---")
            for msg in recent:
                parts.append(f"[{msg['role']}]: {msg['content']}")
        return "\n".join(parts)

    def get_full_transcript(self) -> str:
        return "\n\n".join(f"[{m['role']}]: {m['content']}" for m in self.transcript)

# ============================================================
class SpecialistAgent(Agent):
    """
    Cada especialista é um Agent independente com RealtimeModel nativo.
    Ele entra no mesmo room com identidade separada e aguarda ser ativado.
    """

    def __init__(self, spec_id: str, blackboard: Blackboard) -> None:
        name = SPECIALIST_NAMES[spec_id]

        super().__init__(
            instructions=SPECIALIST_SYSTEM_PROMPTS[spec_id],
            llm=google_plugin.realtime.RealtimeModel(
                model=GEMINI_REALTIME_MODEL,
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                voice=AGENT_VOICES[spec_id],
                realtime_input_config=genai_types.RealtimeInputConfig(
                    automatic_activity_detection=genai_types.AutomaticActivityDetection(
                        disabled=False,
                    ),
                ),
                context_window_compression=genai_types.ContextWindowCompressionConfig(
                    trigger_tokens=GEMINI_REALTIME_CONFIG["compression_trigger"],
                    sliding_window=genai_types.SlidingWindow(
                        target_tokens=GEMINI_REALTIME_CONFIG["compression_sliding_window"]
                    ),
                ),
                conn_options=APIConnectOptions(timeout=30.0),
            ),
            allow_interruptions=True,
        )
        self._spec_id = spec_id
        self._name = name
        self._blackboard = blackboard

class HostAgent(Agent):
    """
    Nathália usa o modelo multimodal para orquestrar a sessão.
    """
    def __init__(
        self,
        blackboard: Blackboard,
        room: rtc.Room,
    ) -> None:
        llm = google_plugin.realtime.RealtimeModel(
            model=GEMINI_REALTIME_MODEL,
            api_key=os.environ.get("GOOGLE_API_KEY", ""),
            voice=AGENT_VOICES["host"],
            realtime_input_config=genai_types.RealtimeInputConfig(
                automatic_activity_detection=genai_types.AutomaticActivityDetection(
                    disabled=False,
                ),
            ),
            context_window_compression=genai_types.ContextWindowCompressionConfig(
                trigger_tokens=GEMINI_REALTIME_CONFIG["compression_trigger"],
                sliding_window=genai_types.SlidingWindow(
                    target_tokens=GEMINI_REALTIME_CONFIG["compression_sliding_window"]
                ),
            ),
            conn_options=APIConnectOptions(timeout=15.0),
        )

        super().__init__(
            instructions=HOST_PROMPT,
            llm=llm,
            allow_interruptions=True,
        )
        self._blackboard = blackboard
        self._room = room

    # ------------------------------------------------------------------
    # Método auxiliar: publica um data packet para ativar um especialista
    # ------------------------------------------------------------------

    async def _activate_specialist(self, spec_id: str, context: str) -> None:
        self._blackboard.active_agent = spec_id
        self._blackboard.add_message("Sistema", f"Acionando {SPECIALIST_NAMES[spec_id]}: {context}")
        payload = json.dumps({
            "type": "activate_agent",
            "agent_id": spec_id,
            "context": context,
            "transcript_summary": self._blackboard.get_context_summary(),
        }).encode()
        await self._room.local_participant.publish_data(payload, reliable=True)
        logger.info(f"[Host] Acionando especialista: {spec_id} | contexto: {context}")

    # ------------------------------------------------------------------
    # Function tools – chamados pelo LLM da Nathália quando necessário
    # ------------------------------------------------------------------

    @function_tool
    async def acionar_carlos_cfo(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Carlos (CFO) para análise financeira.
        Use quando o usuário precisar de: precificação, projeção de receita,
        viabilidade financeira, estrutura de custos ou fontes de financiamento.
        """
        await self._activate_specialist("cfo", questao)
        return f"Carlos (CFO) foi acionado para analisar: {questao}"

    @function_tool
    async def acionar_daniel_advogado(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Daniel (Advogado) para orientação jurídica.
        Use quando o usuário precisar de: tipo societário, contratos,
        LGPD, compliance ou proteção de propriedade intelectual.
        """
        await self._activate_specialist("legal", questao)
        return f"Daniel (Advogado) foi acionado para analisar: {questao}"

    @function_tool
    async def acionar_rodrigo_cmo(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Rodrigo (CMO) para estratégia de marketing e vendas.
        Use quando o usuário precisar de: posicionamento, go-to-market,
        aquisição de clientes, branding ou estratégia de crescimento.
        """
        await self._activate_specialist("cmo", questao)
        return f"Rodrigo (CMO) foi acionado para analisar: {questao}"

    @function_tool
    async def acionar_ana_cto(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Ana (CTO) para orientação técnica.
        Use quando o usuário precisar de: stack tecnológico, arquitetura,
        infraestrutura, escalabilidade ou estimativa de desenvolvimento.
        """
        await self._activate_specialist("cto", questao)
        return f"Ana (CTO) foi acionada para analisar: {questao}"

    @function_tool
    async def gerar_plano_execucao(
        self,
        context: RunContext,
    ) -> str:
        """
        Aciona Marco (Estrategista) para gerar o Plano de Execução final consolidado.
        Use quando o usuário quiser encerrar a sessão ou solicitar um plano estruturado.
        """
        full_transcript = self._blackboard.get_full_transcript()
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        # Prompt rico para o Marco gerar o plano falado
        plan_prompt = (
            f"Você foi acionado para gerar o Plano de Execução Final para {user_name}."
            f" O projeto/contexto é: {project_name}."
            f"\n\nTranscrição completa da sessão:\n{full_transcript}"
            f"\n\nGere agora o Plano de Execução completo seguindo a estrutura do seu prompt: "
            f"Resumo, Diagnóstico por Área, Prioridades, Cronograma, Riscos, "
            f"Próximos Passos Imediatos e Mensagem Final para {user_name}. "
            f"Seja completo, específico e inspirador."
        )

        await self._activate_specialist("plan", plan_prompt)

        # Gera o documento Markdown estruturado para o frontend
        markdown_plan = self._generate_markdown_plan(user_name, project_name)

        try:
            plan_payload = json.dumps({
                "type": "execution_plan",
                "plan": markdown_plan,
                "text": markdown_plan,
            }).encode()
            await self._room.local_participant.publish_data(plan_payload, reliable=True)
            logger.info("[Host] Plano de execução Markdown publicado como data packet.")
        except Exception as e:
            logger.warning(f"[Host] Erro ao publicar plano de execução: {e}")

        return "Marco (Estrategista) está apresentando o Plano de Execução completo."

    def _generate_markdown_plan(self, user_name: str, project_name: str) -> str:
        """Gera documento Markdown estruturado com base no contexto acumulado no Blackboard."""
        from datetime import datetime
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")

        transcript_lines = self._blackboard.transcript
        cfo_insights = [m["content"] for m in transcript_lines if "Carlos" in m.get("role", "")]
        legal_insights = [m["content"] for m in transcript_lines if "Daniel" in m.get("role", "")]
        cmo_insights = [m["content"] for m in transcript_lines if "Rodrigo" in m.get("role", "")]
        cto_insights = [m["content"] for m in transcript_lines if "Ana" in m.get("role", "")]
        user_messages = [m["content"] for m in transcript_lines if m.get("role") == "Usuário"]

        def fmt_insights(items: list) -> str:
            if not items:
                return "_Nenhuma análise registrada para esta área._"
            return "\n".join(f"- {item[:300]}" for item in items[:5])

        user_context = (
            "\n".join(f"- {u[:200]}" for u in user_messages[:10])
            if user_messages else "_Sem mensagens registradas._"
        )

        return f"""# 📋 Plano de Execução — Hive Mind

**Usuário:** {user_name}
**Sessão:** {project_name}
**Gerado em:** {now}

---

## 1. 🎯 Resumo Executivo

Esta sessão de mentoria reuniu um time completo de especialistas para analisar o projeto de **{user_name}** sob diferentes perspectivas: financeira, jurídica, marketing e tecnologia.

**Principais pontos levantados pelo usuário:**
{user_context}

---

## 2. 📊 Diagnóstico por Área

### 💰 Finanças — Carlos (CFO)
{fmt_insights(cfo_insights)}

### ⚖️ Jurídico — Daniel (Advogado)
{fmt_insights(legal_insights)}

### 📣 Marketing & Crescimento — Rodrigo (CMO)
{fmt_insights(cmo_insights)}

### 💻 Tecnologia & Produto — Ana (CTO)
{fmt_insights(cto_insights)}

---

## 3. 🚨 Prioridades Críticas

> As prioridades abaixo foram definidas com base nos temas discutidos durante a sessão.

1. **Validação do modelo de negócio** — Confirmar demanda real antes de qualquer investimento.
2. **Estrutura jurídica adequada** — Formalizar a empresa e proteger propriedade intelectual.
3. **Go-to-market enxuto** — Iniciar com um canal de aquisição principal, medir e escalar.
4. **MVP tecnológico** — Construir o mínimo viável para testar hipóteses com usuários reais.
5. **Fluxo de caixa positivo** — Garantir faturamento antes de escalar custos.

---

## 4. 📅 Cronograma Sugerido

- **30 dias:** Formalizar empresa, definir ICP e proposta de valor (Jurídico + Estratégia)
- **60 dias:** Lançar MVP ou versão beta, iniciar primeiras vendas (Produto + Vendas)
- **90 dias:** Validar unit economics - CAC, LTV - e ajustar pricing (Financeiro + Marketing)
- **6 meses:** Escalar canal principal de marketing (Growth + Operações)
- **12 meses:** Expandir produto/equipe, avaliar captação externa (Estratégia + Financeiro)

---

## 5. ⚠️ Riscos e Mitigações

- **Falta de tração com clientes:**
  - *Mitigação:* Validar antes de construir, fazer vendas manuais primeiro.
- **Burn rate elevado:**
  - *Mitigação:* Manter operação enxuta, priorizar receita sobre crescimento.
- **Problemas jurídicos futuros:**
  - *Mitigação:* Regularizar desde o início com suporte jurídico especializado.

---

## 6. ✅ Próximos Passos Imediatos (Esta Semana)

- [ ] Escrever a proposta de valor em 1 frase clara
- [ ] Identificar os 10 primeiros potenciais clientes para contato direto
- [ ] Escolher o modelo societário adequado (MEI, LTDA, etc.)
- [ ] Mapear os custos fixos e variáveis do negócio
- [ ] Definir o escopo mínimo do MVP e tecnologia necessária

---

## 7. 💬 Mensagem Final

*"{user_name}, você já deu o passo mais importante: buscou perspectivas diferentes e fez as perguntas certas. Agora é hora de executar com foco e disciplina. Lembre-se: os melhores negócios não nasceram perfeitos — foram construídos iteração por iteração. O time Hive Mind está aqui quando precisar!"*

— **Marco, Estrategista-Chefe · Hive Mind**

---

*Documento gerado automaticamente pela plataforma **Hive Mind** com base na sessão de mentoria realizada em {now}.*
"""

async def _start_specialist_in_room(
    spec_id: str,
    blackboard: Blackboard,
    ws_url: str,
    lk_api_key: str,
    lk_api_secret: str,
    room_name: str,
    host_room: rtc.Room,
    auto_introduce: bool = False,
) -> Optional[AgentSession]:
    """
    Conecta um SpecialistAgent ao room como participante separado.
    Retorna a AgentSession criada.

    C1/C2/C3: Inicialização sequencial com retry no AgentSession.start()
    e publicação de health-check data packet (agent_ready) ao conectar.
    """
    name = SPECIALIST_NAMES[spec_id]
    identity = SPECIALIST_IDENTITIES[spec_id]
    logger.info(f"[{name}] Iniciando conexão...")

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 3.0  # segundos

    try:
        # Gera token JWT com permissões de áudio + data explícitas
        token = (
            api.AccessToken(lk_api_key, lk_api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )

        # C5: Conecta ao room SEM subscrever ao áudio do usuário.
        # Especialistas só ouvem o usuário quando são explicitamente ativados.
        # Isso evita que todos respondam simultaneamente ao usuário.
        room_options = rtc.RoomOptions(auto_subscribe=False)
        room = rtc.Room()

        # C5: Controle de subscrição de áudio — ativado/desativado por data packet
        _audio_subscribed = False

        def _subscribe_user_audio():
            """Subscreve ao áudio do usuário (chamado quando o especialista é ativado)."""
            nonlocal _audio_subscribed
            if _audio_subscribed:
                return
            _audio_subscribed = True
            for p in room.remote_participants.values():
                if p.identity.startswith("user-"):
                    for pub in p.track_publications.values():
                        if pub.kind == rtc.TrackKind.KIND_AUDIO:
                            pub.set_subscribed(True)
            logger.info(f"[{name}] Áudio do usuário SUBSCRITO (ativado).")

        def _unsubscribe_user_audio():
            """Dessubscreve do áudio do usuário (chamado quando outro especialista é ativado)."""
            nonlocal _audio_subscribed
            if not _audio_subscribed:
                return
            _audio_subscribed = False
            for p in room.remote_participants.values():
                if p.identity.startswith("user-"):
                    for pub in p.track_publications.values():
                        if pub.kind == rtc.TrackKind.KIND_AUDIO:
                            pub.set_subscribed(False)
            logger.info(f"[{name}] Áudio do usuário DESSUBSCRITO (silenciado).")

        # Quando o usuário publicar áudio depois, subscreve SOMENTE se ativado
        def _on_track_published(publication, participant):
            if _audio_subscribed and participant.identity.startswith("user-") and publication.kind == rtc.TrackKind.KIND_AUDIO:
                publication.set_subscribed(True)

        room.on("track_published", _on_track_published)

        connected = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    room.connect(ws_url, token, options=room_options),
                    timeout=15.0,
                )
                connected = True
                # NÃO subscreve ao áudio aqui — será feito apenas quando ativado
                break
            except (asyncio.TimeoutError, Exception) as conn_err:
                retry_delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"[{name}] Room tentativa {attempt}/{MAX_RETRIES} falhou: {conn_err}. "
                    f"Retentando em {retry_delay}s..."
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(retry_delay)

        if not connected:
            logger.error(f"[{name}] Falha ao conectar ao room após {MAX_RETRIES} tentativas.")
            try:
                await host_room.local_participant.publish_data(
                    json.dumps({
                        "type": "agent_error",
                        "agent_id": spec_id,

"name": name,
                    }).encode(),
                    reliable=True,
                )
            except Exception:
                pass
            return None

        logger.info(f"[{name}] Room conectado.")
        blackboard.specialist_rooms.append(room)

        # C2: Instancia agent + sessão com retry no start()
        agent = SpecialistAgent(spec_id, blackboard)
        session = AgentSession()

        session_started = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    session.start(agent, room=room),
                    timeout=15.0,
                )
                session_started = True
                break
            except (asyncio.TimeoutError, Exception) as start_err:
                retry_delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"[{name}] AgentSession.start() tentativa {attempt}/{MAX_RETRIES} "
                    f"falhou: {start_err}. Retentando em {retry_delay}s..."
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(retry_delay)
                    # Recria agent e session para nova tentativa
                    agent = SpecialistAgent(spec_id, blackboard)
                    session = AgentSession()

        if not session_started:
            logger.error(f"[{name}] AgentSession falhou após {MAX_RETRIES} tentativas.")
            try:
                await room.disconnect()
            except Exception:
                pass
            try:
                await host_room.local_participant.publish_data(
                    json.dumps({
                        "type": "agent_error",
                        "agent_id": spec_id,
                        "name": name,
                    }).encode(),
                    reliable=True,
                )
            except Exception:
                pass
            return None

        logger.info(f"[{name}] AgentSession iniciada com RealtimeModel nativo.")

        # Aguarda o RealtimeModel inicializar
        await asyncio.sleep(2.0)
        logger.info(f"[{name}] RealtimeModel inicializado.")

        # Registra a sessão no Blackboard
        blackboard.specialist_sessions[spec_id] = session

        # C3: Publica health-check data packet para o frontend
        try:
            await host_room.local_participant.publish_data(
                json.dumps({
                    "type": "agent_ready",
                    "agent_id": spec_id,
                    "name": name,
                }).encode(),
                reliable=True,
            )
            logger.info(f"[{name}] Health-check agent_ready publicado.")
        except Exception as e:
            logger.warning(f"[{name}] Erro ao publicar agent_ready: {e}")

        # Auto-apresentação: instrui o agente a dizer o texto de apresentação
        if auto_introduce:
            intro_text = SPECIALIST_INTRODUCTIONS[spec_id]
            logger.info(f"[{name}] Iniciando auto-apresentação...")
            try:
                await asyncio.wait_for(
                    session.generate_reply(
                        instructions=(
                            f"Por favor, apresente-se dizendo: {intro_text}"
                        ),
                    ),
                    timeout=15.0,
                )
                logger.info(f"[{name}] Auto-apresentação concluída.")
            except asyncio.TimeoutError:
                logger.warning(f"[{name}] Timeout na auto-apresentação (30s).")
            except Exception as e:
                logger.warning(f"[{name}] Erro na auto-apresentação: {type(e).__name__}: {e}", exc_info=True)

        # Captura transcrição do especialista via evento
        @session.on("conversation_item_added")
        def _on_agent_speech(event) -> None:
            if not blackboard.is_active:
                return

            text = ""
            if hasattr(event, "item") and hasattr(event.item, "content"):
                content = event.item.content
                if isinstance(content, list):
                    text = " ".join(
                        getattr(part, "text", str(part))
                        for part in content
                        if part
                    )
                elif isinstance(content, str):
                    text = content
                else:

                    text = str(content) if content else ""
            elif hasattr(event, "item") and hasattr(event.item, "text_content"):
                text = event.item.text_content or ""
            elif hasattr(event, "text"):
                text = event.text or ""

            text = text.strip()
            if not text:
                return
            blackboard.add_message(name, text)
            asyncio.create_task(
                host_room.local_participant.publish_data(
                    json.dumps({
                        "type": "transcript",
                        "speaker": name,
                        "text": text,
                    }).encode(),
                    reliable=True,
                )
            )

        # C5: Escuta data packets para ativação/desativação coordenada.
        # Quando ativado: subscreve ao áudio do usuário + gera resposta.
        # Quando outro é ativado: dessubscreve do áudio (silencia).
        @room.on("data_received")
        def _on_data(dp: rtc.DataPacket) -> None:
            try:
                msg = json.loads(dp.data.decode())
                if msg.get("type") == "activate_agent":
                    if msg.get("agent_id") == spec_id:
                        # === ATIVAÇÃO: este especialista foi chamado ===
                        ctx_summary = msg.get("transcript_summary", "")
                        context_text = msg.get("context", "")

                        # Atualiza instruções com contexto da sessão
                        if ctx_summary:
                            new_instructions = (
                                SPECIALIST_SYSTEM_PROMPTS[spec_id]
                                + f"\n\n--- CONTEXTO ATUAL DA SESSÃO ---\n{ctx_summary}"
                            )
                            asyncio.create_task(
                                agent.update_instructions(new_instructions)
                            )

                        # C5: Subscreve ao áudio do usuário
                        _subscribe_user_audio()

                        # Gera resposta forçada com o contexto da questão
                        prompt = (
                            f"Nathália acabou de te acionar. O contexto é: {context_text}. "
                            f"Responda de forma objetiva e profissional."
                        )
                        asyncio.create_task(
                            session.generate_reply(instructions=prompt)
                        )

                        logger.info(f"[{name}] ATIVADO via data packet — áudio ON + reply gerado.")
                    else:
                        # === DESATIVAÇÃO: outro especialista foi chamado ===
                        _unsubscribe_user_audio()
                        logger.debug(f"[{name}] DESATIVADO (ativo agora: {msg.get('agent_id')}).")
            except Exception as e:
                logger.warning(f"[{name}] Erro ao processar data packet: {e}")

        return session

    except Exception as e:
        logger.error(f"[{name}] Erro ao iniciar: {e}", exc_info=True)
        return None

async def entrypoint(ctx: JobContext) -> None:
    # Log em arquivo para diagnóstico (compatível com Windows e Linux)
    log_path = os.path.join(tempfile.gettempdir(), "mentoria_agent.log")
    _fh = logging.FileHandler(log_path, mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)

    logger.info(f"=== ENTRYPOINT MENTORIA AI v5 – sala: {ctx.room.name} ===")

    # Conecta o worker ao room com auto-subscribe de áudio.
    # IMPORTANTE: O RealtimeModel do Gemini exige que o AgentSession
    # gerencie a subscrição de áudio automaticamente. Usar SUBSCRIBE_NONE
    # impede que o pipeline interno receba o áudio do microfone do usuário.
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
    logger.info(f"Worker conectado ao room: {ctx.room.name}")

    # Blackboard compartilhado
    blackboard = Blackboard(project_name=ctx.room.name)

    # Variáveis de ambiente para conectar especialistas
    ws_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    lk_api_key = os.getenv("LIVEKIT_API_KEY", "")
    lk_api_secret = os.getenv("LIVEKIT_API_SECRET", "")

    # ------------------------------------------------------------------
    # 1. Iniciar Nathália (Host) no room principal
    # ------------------------------------------------------------------
    host_agent = HostAgent(blackboard, ctx.room)

    host_session = AgentSession()

    try:
        await host_session.start(host_agent, room=ctx.room)
        logger.info("[Host] Nathália iniciada com RealtimeModel nativo.")
    except Exception as e:
        logger.error(f"[Host] Erro crítico ao iniciar Nathália: {e}", exc_info=True)
        return

    shutdown_event = asyncio.Event()

    @ctx.room.on("disconnected")
    def _on_room_disconnected(*args, **kwargs) -> None:
        logger.info("[Room] Room principal desconectado. Disparando shutdown.")
        shutdown_event.set()

    # ------------------------------------------------------------------
    # Captura transcrição do usuário → Blackboard + frontend
    # ------------------------------------------------------------------
    @host_session.on("user_input_transcribed")
    def _on_user_speech(event) -> None:
        if not blackboard.is_active:
            return

        text = ""
        if hasattr(event, "transcript"):
            text = event.transcript
        elif hasattr(event, "text"):
            text = event.text
        else:
            text = str(event)

        if not text:
            return
        blackboard.add_message("Usuário", text)
        if not blackboard.user_query:
            blackboard.user_query = text
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Você", "text": text}).encode(),
                reliable=True,
            )
        )

    # ------------------------------------------------------------------
    # Captura transcrição da Nathália → Blackboard + frontend
    # ------------------------------------------------------------------
    @host_session.on("conversation_item_added")
    def _on_host_speech(event) -> None:
        if not blackboard.is_active:
            return

        text = ""
        if hasattr(event, "item") and hasattr(event.item, "content"):
            content = event.item.content
            if isinstance(content, list):
                text = " ".join(
                    getattr(part, "text", str(part))
                    for part in content
                    if part
                )
            elif isinstance(content, str):
                text = content
            else:
                text = str(content) if content else ""
        elif hasattr(event, "item") and hasattr(event.item, "text_content"):
            text = event.item.text_content or ""
        elif hasattr(event, "text"):
            text = event.text or ""

        text = text.strip()
        if not text:
            return
        blackboard.add_message("Nathália", text)
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Nathália", "text": text}).encode(),
                reliable=True,
            )
        )

    # ------------------------------------------------------------------
    # 2. Fluxo de Apresentação ou Retomada de Sessão
    # ------------------------------------------------------------------
    async def welcome_and_introductions() -> None:
        """
        Se o Blackboard já tem histórico (retomada de sessão interrompida),
        Nathália retoma sem repetir apresentações.
        Caso contrário, executa o fluxo completo de boas-vindas.
        """
        is_resuming = len(blackboard.transcript) > 0

        # Conecta todos os especialistas CONCORRENTEMENTE
        logger.info("[Apresentação] Conectando todos os especialistas simultaneamente...")
        connect_tasks = []
        for spec_id in SPECIALIST_ORDER:
            task = asyncio.create_task(
                _start_specialist_in_room(
                    spec_id=spec_id,
                    blackboard=blackboard,
                    ws_url=ws_url,
                    lk_api_key=lk_api_key,
                    lk_api_secret=lk_api_secret,
                    room_name=ctx.room.name,
                    host_room=ctx.room,
                    auto_introduce=False,
                )
            )
            connect_tasks.append(task)

        # Aguarda Nathália estabilizar e o RealtimeModel conectar ao Gemini
        await asyncio.sleep(2.0)

        if is_resuming:
            # ── MODO RETOMADA ──────────────────────────────────────────
            user_name_part = f", {blackboard.user_name}" if blackboard.user_name else ""
            resumption_context = blackboard.get_context_summary()
            logger.info("[Host] Nathália retomando sessão existente...")
            resumption_msg = (
                f"Estou retomando nossa sessão! "
                f"Olá{user_name_part}, que bom ter você de volta. "
                f"Nossa conversa foi interrompida, mas tenho todo o contexto do que discutimos. "
                f"Podemos continuar exatamente de onde paramos. "
                f"Estávamos falando sobre: {blackboard.user_query or 'seu projeto'}. "
                f"Como você gostaria de continuar?"
            )
            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=(
                            f"Retome a sessão de forma calorosa dizendo: {resumption_msg} "
                            f"Contexto da sessão anterior para você: {resumption_context}"
                        ),
                    ),
                    timeout=30.0,
                )
            except Exception as e:
                logger.warning(f"[Host] Erro ao retomar sessão: {e}")

            # Aguarda especialistas reconectarem (sem apresentações)
            await asyncio.gather(*connect_tasks)
            logger.info("[Host] Retomada concluída. Todos os especialistas reconectados.")

        else:
            # ── MODO INICIAL ───────────────────────────────────────────
            host_greeting = (
                "Olá! Seja muito bem-vindo ao Hive Mind! "
                "Sou a Nathália, sua apresentadora e mentora líder desta sessão. "
                "Montei uma equipe completa de especialistas para te ajudar hoje: "
                "Carlos no financeiro, Daniel no jurídico, Rodrigo em marketing, "
                "Ana em tecnologia e Marco como estrategista-chefe. "
                "Eles vão se apresentar um a um agora. Fique à vontade!"
            )
            logger.info("[Host] Nathália enviando apresentação inicial...")
            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=f"Por favor, diga a seguinte apresentação de forma calorosa e natural: {host_greeting}",
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning("[Host] Timeout (30s) ao gerar reply inicial.")
            except Exception as e:
                logger.warning(f"[Host] Erro ao gerar reply inicial: {type(e).__name__}: {e}", exc_info=True)

            # Aguarda todos os especialistas conectarem
            sessions = await asyncio.gather(*connect_tasks)
            spec_sessions = dict(zip(SPECIALIST_ORDER, sessions))

            # Especialistas se apresentam SEQUENCIALMENTE
            for spec_id in SPECIALIST_ORDER:
                if not blackboard.is_active:
                    logger.info("[Apresentação] Job encerrando, abortando sequência.")
                    return

                session = spec_sessions.get(spec_id)
                if not session:
                    continue

                spec_name = SPECIALIST_NAMES[spec_id]
                logger.info(f"[Apresentação] Iniciando apresentação de {spec_name}...")
                intro_text = SPECIALIST_INTRODUCTIONS[spec_id]

                try:
                    await asyncio.wait_for(
                        session.generate_reply(
                            instructions=(
                                f"Apresente-se de forma calorosa e natural dizendo: {intro_text} "
                                f"Máximo 3 frases. Não cumprimente difusamente — seja direto e memorável."
                            ),
                        ),
                        timeout=25.0,
                    )
                    logger.info(f"[Apresentação] {spec_name} concluiu.")
                    await asyncio.sleep(POST_INTRO_WAIT)
                except Exception as e:
                    logger.warning(f"[Apresentação] Erro na apresentação de {spec_name}: {e}")

            logger.info("[Apresentação] Todos os especialistas foram apresentados.")

            if not blackboard.is_active:
                return

            # Nathália fecha as apresentações e convida o usuário a falar
            if blackboard.user_name:
                closing = (
                    f"Pronto, {blackboard.user_name}! Toda a nossa equipe já se apresentou. "
                    f"Agora sou toda ouvidos — qual é o seu maior desafio ou a principal questão "
                    f"que você quer resolver hoje?"
                )
            else:
                closing = (
                    "Pronto! Toda a nossa equipe já se apresentou. "
                    "Antes de tudo, adoraria saber o seu nome — e depois me conte: "
                    "qual é o seu projeto ou negócio e o que você quer resolver hoje?"
                )

            logger.info("[Host] Nathália fazendo pergunta inicial...")
            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=f"Faça a seguinte pergunta de forma calorosa e natural: {closing}",
                    ),
                    timeout=30.0,
                )
            except Exception as e:
                logger.warning(f"[Host] Erro na pergunta inicial: {e}")

            logger.info("[Host] Fluxo de abertura concluído.")

    asyncio.create_task(welcome_and_introductions())

    # ------------------------------------------------------------------
    # Escuta mensagens de dados do frontend
    # ------------------------------------------------------------------
    @ctx.room.on("data_received")
    def _on_data_received(dp: rtc.DataPacket) -> None:
        try:
            msg = json.loads(dp.data.decode())

            if msg.get("type") == "end_session":
                logger.info("[Room] Pedido de encerramento recebido do frontend.")
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        json.dumps({
                            "type": "session_end",
                            "full_transcript": blackboard.get_full_transcript(),
                            "context_summary": blackboard.get_context_summary(),
                        }).encode(),
                        reliable=True,
                    )
                )
                shutdown_event.set()

            elif msg.get("type") == "set_project_name":
                blackboard.project_name = msg.get("name", "")
                logger.info(f"[Room] Nome do projeto definido: {blackboard.project_name}")

            elif msg.get("type") == "set_user_name":
                blackboard.user_name = msg.get("name", "")
                logger.info(f"[Room] Nome do usuário definido: {blackboard.user_name}")

        except Exception as e:
            logger.warning(f"[Room] Erro ao processar data packet do frontend: {e}")

    # ------------------------------------------------------------------
    # Loop principal — mantém o worker vivo enquanto o room estiver ativo
    # ------------------------------------------------------------------
    logger.info("=== Job em execução. Aguardando interação... ===")
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        logger.info("[Job] Cancelado externamente. Encerrando.")
    except Exception as e:
        logger.error(f"[Job] Erro no loop principal: {e}", exc_info=True)
    finally:
        blackboard.is_active = False
        logger.info("[Job] Iniciando limpeza de recursos...")

        for spec_room in blackboard.specialist_rooms:
            try:
                await spec_room.disconnect()
            except Exception as e:
                logger.warning(f"[Job] Erro ao desconectar room de especialista: {e}")

        # C4: Libera a sala do guard global para permitir novos jobs futuros
        _active_rooms.discard(ctx.room.name)
        logger.info(f"[Job] Sala '{ctx.room.name}' liberada do guard. Encerrado.")

# ============================================================
async def on_job_request(req) -> None:
    """
    Chamado pelo LiveKit antes de despachar cada job.
    Se a sala já tem um job ativo, rejeita o novo pedido.
    Isso evita que múltiplas instâncias dos agentes rodem
    simultaneamente no mesmo room, causando embaralhamento de vozes.
    """
    room_name = req.room.name
    if room_name in _active_rooms:
        logger.warning(
            f"[Guard] Job REJEITADO para sala '{room_name}' — "
            f"já existe um job ativo. Salas ativas: {_active_rooms}"
        )
        await req.reject()
        return

    _active_rooms.add(room_name)
    logger.info(
        f"[Guard] Job ACEITO para sala '{room_name}'. "
        f"Salas ativas: {_active_rooms}"
    )
    await req.accept(
        name="Nathália (Host)",
        identity="agent-host",
    )

# ============================================================
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=on_job_request,
            agent_name="mentoria-agent",
        )
    )