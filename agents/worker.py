"""
Mentoria AI - Worker Multi-Agentes v4
======================================
Arquitetura com 6 agentes com vozes independentes:
    - Nathália (Host): Orquestra toda a sessão, aciona especialistas via
      function tools que publicam data packets no room.
    - Carlos (CFO), Daniel (Advogado), Rodrigo (CMO), Ana (CTO), Marco (Estrategista):
      Cada um como participante separado no mesmo room, com AgentSession
      individual e RealtimeModel nativo com voz própria.
    - Blackboard: contexto compartilhado em memória.

Fluxo de Abertura:
    1. Nathália se apresenta e apresenta o time.
    2. Cada especialista se apresenta individualmente, um a um, com sua voz.
    3. Nathália retoma e pergunta ao usuário sobre o projeto.

Correções aplicadas (v4):
    - Eventos: agent_speech_committed / user_speech_committed (API correta)
    - say(): chamado na AgentSession, não no Agent
    - Removido ctx.wait_for_shutdown() inexistente → asyncio.Event().wait()
    - Removido VAD Silero (conflita com RealtimeModel nativo)
    - Log path compatível com Windows via tempfile
    - Removida dependência de livekit-plugins-silero e livekit-plugins-openai
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


# Modelo Realtime nativo do Gemini (voz-para-voz)
GEMINI_REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

# Configurações avançadas do Gemini Realtime (baseadas no código base fornecido)
GEMINI_REALTIME_CONFIG = {
    "media_resolution": "MEDIUM",  # Atualmente não suportado diretamente pelo plugin LiveKit
    "compression_trigger": 104857,
    "compression_sliding_window": 52428,
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Zephyr",
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
    "plan":  "Zephyr",   # Marco    – masculina autoritativa
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

# Frases de apresentação individual de cada especialista
SPECIALIST_INTRODUCTIONS: dict[str, str] = {
    "cfo": (
        "Olá! Sou o Carlos, responsável pela área financeira. "
        "Posso ajudar com análise de custos, precificação, projeções de receita "
        "e viabilidade financeira do seu projeto. Prazer em conhecê-lo!"
    ),
    "legal": (
        "Prazer! Sou o Daniel, advogado da equipe. "
        "Cuido de questões jurídicas como tipo societário, contratos, "
        "LGPD e compliance. Conte comigo para proteger seu negócio."
    ),
    "cmo": (
        "E aí! Rodrigo aqui, sou o CMO da equipe. "
        "Minha área é marketing e crescimento: posicionamento de marca, "
        "aquisição de clientes e estratégia de go-to-market. Vamos juntos!"
    ),
    "cto": (
        "Olá! Sou a Ana, CTO do time. "
        "Trabalho com arquitetura de sistemas, stack tecnológico, "
        "infraestrutura e escalabilidade. Estou aqui para o que precisar!"
    ),
    "plan": (
        "Prazer! Marco aqui, estrategista-chefe. "
        "Meu papel é sintetizar tudo que discutirmos e entregar "
        "um Plano de Execução completo ao final da sessão. Conte comigo!"
    ),
}


# ============================================================
# PROMPTS
# ============================================================

HOST_PROMPT = """Você é Nathália, a Apresentadora (Host) do Mentoria AI.
Seu papel é orquestrar a sessão de mentoria empresarial multi-agentes.

ESPECIALISTAS DISPONÍVEIS:
- Carlos (CFO): finanças, custos, projeções, viabilidade
- Daniel (Advogado): aspectos jurídicos, contratos, LGPD
- Rodrigo (CMO): marketing, posicionamento, aquisição de clientes
- Ana (CTO): tecnologia, infraestrutura, escalabilidade
- Marco (Estrategista): síntese final e plano de execução

REGRAS:
- Receba o usuário de forma calorosa e profissional.
- Identifique os tópicos do projeto/problema do usuário.
- Quando precisar de análise financeira, use a função acionar_carlos_cfo.
- Quando precisar de orientação jurídica, use acionar_daniel_advogado.
- Quando precisar de estratégia de marketing, use acionar_rodrigo_cmo.
- Quando precisar de orientação técnica, use acionar_ana_cto.
- Quando o usuário quiser encerrar ou pedir o plano, use gerar_plano_execucao.
- SEMPRE faça pelo menos uma pergunta ao usuário por interação.
- Mantenha respostas curtas (máximo 3 frases por turno).
- Fale em português do Brasil."""

# Prompts de sistema para cada especialista.
SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo": (
        "Você é Carlos, o CFO (Chief Financial Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio até que Nathália (a apresentadora) ou o usuário chame seu nome "
        "ou peça uma análise financeira. "
        "Quando acionado, analise custos, receitas, precificação e viabilidade financeira. "
        "Seja preciso, profissional e objetivo. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "legal": (
        "Você é Daniel, o Advogado do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio até que Nathália ou o usuário chame seu nome "
        "ou peça orientação jurídica. "
        "Quando acionado, foque em contratos, estrutura societária, LGPD e compliance. "
        "Seja formal, preciso e claro. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "cmo": (
        "Você é Rodrigo, o CMO (Chief Marketing Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio até que Nathália ou o usuário chame seu nome "
        "ou peça estratégia de marketing. "
        "Quando acionado, foque em posicionamento, aquisição de clientes, branding e growth. "
        "Seja dinâmico, entusiasmado e prático. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "cto": (
        "Você é Ana, a CTO (Chief Technology Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio até que Nathália ou o usuário chame seu nome "
        "ou peça orientação técnica. "
        "Quando acionada, foque em stack tecnológico, arquitetura, infraestrutura e escalabilidade. "
        "Seja técnica, prática e objetiva. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "plan": (
        "Você é Marco, o Estrategista-Chefe do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio até que Nathália ou o usuário peça o Plano de Execução. "
        "Quando acionado, sintetize TUDO que foi discutido na sessão e entregue um "
        "Plano de Execução estruturado com: "
        "1) Resumo do projeto, 2) Principais recomendações por área, "
        "3) Cronograma sugerido, 4) Riscos e mitigações, 5) Próximos passos concretos. "
        "Seja claro, organizado e inspirador. Fale em português do Brasil."
    ),
}


# ============================================================
# BLACKBOARD – contexto compartilhado entre todos os agentes
# ============================================================

@dataclass
class Blackboard:
    """
    Repositório central de contexto compartilhado.
    Todos os agentes têm referência à mesma instância
    (passada no construtor), sem necessidade de rede.
    """
    project_name: str = ""
    user_query: str = ""
    active_agent: Optional[str] = None
    transcript: list[dict] = field(default_factory=list)
    is_active: bool = True
    # Dicionário que armazena a AgentSession de cada especialista para say()
    specialist_sessions: dict[str, AgentSession] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content})
        logger.debug(f"[Blackboard] [{role}]: {content[:80]}...")

    def get_context_summary(self) -> str:
        """Retorna um resumo do contexto atual para injetar nos prompts."""
        parts: list[str] = []
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
# SPECIALIST AGENT
# ============================================================

class SpecialistAgent(Agent):
    """
    Cada especialista é um Agent independente com RealtimeModel nativo.
    Ele entra no mesmo room com identidade separada e aguarda ser ativado.

    A ativação acontece via data packet do tipo 'activate_agent'
    publicado pela Nathália no room.
    """

    def __init__(self, spec_id: str, blackboard: Blackboard) -> None:
        name = SPECIALIST_NAMES[spec_id]

        super().__init__(
            instructions=SPECIALIST_SYSTEM_PROMPTS[spec_id],
            llm=google_plugin.realtime.RealtimeModel(
                model=GEMINI_REALTIME_MODEL,
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                voice=AGENT_VOICES[spec_id],
                realtime_input_config=genai_types.RealtimeInputConfig(),
                context_window_compression=genai_types.ContextWindowCompressionConfig(
                    trigger_tokens=GEMINI_REALTIME_CONFIG["compression_trigger"],
                    sliding_window=genai_types.SlidingWindow(
                        target_tokens=GEMINI_REALTIME_CONFIG["compression_sliding_window"]
                    ),
                ),
                conn_options=APIConnectOptions(timeout=20.0),
            ),
            allow_interruptions=True,
        )
        self._spec_id = spec_id
        self._name = name
        self._blackboard = blackboard


# ============================================================
# HOST AGENT – Nathália
# ============================================================

class HostAgent(Agent):
    """
    Nathália usa o modelo multimodal para orquestrar a sessão.
    """
    def __init__(
        self,
        blackboard: Blackboard,
        room: rtc.Room,
    ) -> None:
        # Configuração do modelo baseada no código base Node.js
        llm = google_plugin.realtime.RealtimeModel(
            model=GEMINI_REALTIME_MODEL,
            api_key=os.environ.get("GOOGLE_API_KEY", ""),
            voice=AGENT_VOICES["host"],
            # Atribuindo as configurações do exemplo via realtime_input_config
            realtime_input_config=genai_types.RealtimeInputConfig(),
            context_window_compression=genai_types.ContextWindowCompressionConfig(
                trigger_tokens=GEMINI_REALTIME_CONFIG["compression_trigger"],
                sliding_window=genai_types.SlidingWindow(
                    target_tokens=GEMINI_REALTIME_CONFIG["compression_sliding_window"]
                ),
            ),
            conn_options=APIConnectOptions(timeout=20.0),
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
        """
        Publica um data packet no room indicando qual especialista deve falar.
        """
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
        Aciona Marco (Estrategista) para gerar o Plano de Execução consolidado.
        Use quando o usuário quiser encerrar a sessão ou pedir um resumo
        estruturado com próximos passos.
        """
        await self._activate_specialist("plan", self._blackboard.get_context_summary())
        return "Marco (Estrategista) está preparando o Plano de Execução consolidado."


# ============================================================
# FUNÇÃO AUXILIAR: conectar especialista ao room
# ============================================================

async def _start_specialist_in_room(
    spec_id: str,
    blackboard: Blackboard,
    ws_url: str,
    lk_api_key: str,
    lk_api_secret: str,
    room_name: str,
    delay: float = 0.0,
) -> Optional[AgentSession]:
    """
    Conecta um SpecialistAgent ao room como participante separado.
    Retorna a AgentSession para que possa ser usada para say() na apresentação.
    """
    if delay > 0:
        await asyncio.sleep(delay)

    name = SPECIALIST_NAMES[spec_id]
    identity = SPECIALIST_IDENTITIES[spec_id]
    logger.info(f"[{name}] Iniciando conexão (delay={delay}s)...")

    try:
        # Gera token JWT para o especialista
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
                )
            )
            .to_jwt()
        )

        # Conecta ao room
        room = rtc.Room()
        try:
            await asyncio.wait_for(
                room.connect(ws_url, token),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[{name}] Timeout ao conectar ao room.")
            return None

        logger.info(f"[{name}] Room conectado.")

        # Silencia text stream topics que chegam de outros AgentSessions
        # (lk.agent.events e lk.transcription) — evita INFO logs de "no callback attached"
        async def _noop_stream_handler(reader, participant_info):
            pass

        room.register_text_stream_handler("lk.agent.events", _noop_stream_handler)
        room.register_text_stream_handler("lk.transcription", _noop_stream_handler)

        # Instancia o agent e a sessão
        agent = SpecialistAgent(spec_id, blackboard)

        # AgentSession SEM vad — o RealtimeModel nativo já tem VAD interno
        session = AgentSession()

        # Inicia o agent no room
        await session.start(agent, room=room)
        logger.info(f"[{name}] AgentSession iniciada com RealtimeModel nativo.")

        # Registra a sessão no Blackboard para uso na apresentação
        blackboard.specialist_sessions[spec_id] = session

        # Captura transcrição do especialista via evento correto
        @session.on("agent_speech_committed")
        def _on_agent_speech(event) -> None:
            # Extrai o texto da mensagem do agente
            text = ""
            if hasattr(event, "message") and hasattr(event.message, "content"):
                text = event.message.content
            elif hasattr(event, "text"):
                text = event.text
            else:
                text = str(event)

            if not text:
                return
            blackboard.add_message(name, text)
            # Publica transcrição para o frontend via data channel
            asyncio.create_task(
                room.local_participant.publish_data(
                    json.dumps({
                        "type": "transcript",
                        "speaker": name,
                        "text": text,
                    }).encode(),
                    reliable=True,
                )
            )

        # Escuta data packets para ativação coordenada
        @room.on("data_received")
        def _on_data(dp: rtc.DataPacket) -> None:
            try:
                msg = json.loads(dp.data.decode())
                if msg.get("type") == "activate_agent":
                    if msg.get("agent_id") == spec_id:
                        ctx_summary = msg.get("transcript_summary", "")
                        if ctx_summary:
                            agent.instructions = (
                                SPECIALIST_SYSTEM_PROMPTS[spec_id]
                                + f"\n\n--- CONTEXTO ATUAL DA SESSÃO ---\n{ctx_summary}"
                            )
                        logger.info(f"[{name}] Ativado via data packet.")
                    else:
                        logger.debug(f"[{name}] Em silêncio (ativo: {msg.get('agent_id')}).")
            except Exception as e:
                logger.warning(f"[{name}] Erro ao processar data packet: {e}")

        return session

    except Exception as e:
        logger.error(f"[{name}] Erro ao iniciar: {e}", exc_info=True)
        return None


# ============================================================
# ENTRYPOINT
# ============================================================

async def entrypoint(ctx: JobContext) -> None:
    # Log em arquivo para diagnóstico (compatível com Windows e Linux)
    log_path = os.path.join(tempfile.gettempdir(), "mentoria_agent.log")
    _fh = logging.FileHandler(log_path, mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)

    logger.info(f"=== ENTRYPOINT MENTORIA AI v4 – sala: {ctx.room.name} ===")

    # Conecta o worker ao room (somente áudio)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
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

    # AgentSession SEM vad — RealtimeModel nativo já tem VAD interno
    host_session = AgentSession()

    try:
        await host_session.start(host_agent, room=ctx.room)
        logger.info("[Host] Nathália iniciada com RealtimeModel nativo.")
    except Exception as e:
        logger.error(f"[Host] Erro crítico ao iniciar Nathália: {e}", exc_info=True)
        return

    # ------------------------------------------------------------------
    # Captura transcrição do usuário → Blackboard + frontend
    # Evento correto: user_speech_committed
    # ------------------------------------------------------------------
    @host_session.on("user_speech_committed")
    def _on_user_speech(event) -> None:
        text = ""
        if hasattr(event, "message") and hasattr(event.message, "content"):
            text = event.message.content
        elif hasattr(event, "text"):
            text = event.text
        elif hasattr(event, "transcript"):
            text = event.transcript
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
    # Evento correto: agent_speech_committed
    # ------------------------------------------------------------------
    @host_session.on("agent_speech_committed")
    def _on_host_speech(event) -> None:
        text = ""
        if hasattr(event, "message") and hasattr(event.message, "content"):
            text = event.message.content
        elif hasattr(event, "text"):
            text = event.text
        else:
            text = str(event)

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
    # 2. Iniciar especialistas de forma escalonada
    # ------------------------------------------------------------------
    spec_ids = ["cfo", "legal", "cmo", "cto", "plan"]
    spec_sessions: dict[str, AgentSession] = {}

    for i, sid in enumerate(spec_ids):
        delay = (i + 1) * 7.0  # 7s, 14s, 21s, 28s, 35s
        asyncio.create_task(
            _start_specialist_in_room(
                spec_id=sid,
                blackboard=blackboard,
                ws_url=ws_url,
                lk_api_key=lk_api_key,
                lk_api_secret=lk_api_secret,
                room_name=ctx.room.name,
                delay=delay,
            )
        )

    logger.info("[Especialistas] Tarefas de conexão escalonada disparadas.")

    # ------------------------------------------------------------------
    # 3. Fluxo de Apresentação: Nathália apresenta o time
    # ------------------------------------------------------------------
    async def welcome_and_introductions() -> None:
        # Aguarda Nathália conectar
        await asyncio.sleep(8.0)

        # 3a. Nathália se apresenta e apresenta o time (via generate_reply com RealtimeModel)
        host_greeting = (
            "Olá! Seja muito bem-vindo ao Mentoria AI! "
            "Sou a Nathália, sua apresentadora e mentora líder. "
            "Estou aqui com nosso time completo! "
            "Temos Carlos, nosso CFO para finanças. "
            "Daniel, nosso advogado para questões jurídicas. "
            "Rodrigo, CMO para marketing e crescimento. "
            "Ana, CTO para tecnologia e sistemas. "
            "E Marco, nosso estrategista-chefe. "
            "Todos prontos para ajudar no seu projeto!"
        )
        logger.info("[Host] Enviando saudação inicial...")
        try:
            # Usar generate_reply em vez de say() com RealtimeModel
            await host_session.generate_reply(
                instructions=(
                    "Fale esta mensagem exatamente como está escrita, sem adicionar nada: "
                    f"{host_greeting}"
                )
            )
        except Exception as e:
            logger.warning(f"[Host] Erro ao gerar reply: {e}")
            # Fallback: publica apenas o texto para o frontend
            await ctx.room.local_participant.publish_data(
                json.dumps({
                    "type": "transcript",
                    "speaker": "Nathália",
                    "text": host_greeting,
                }).encode(),
                reliable=True,
            )

        # 3b. Pausa e Nathália faz a pergunta inicial
        await asyncio.sleep(3.0)
        closing = (
            "Agora me conte: qual é o seu projeto ou principal desafio de negócio hoje? "
            "Estou aqui para ouvir você!"
        )
        try:
            await host_session.generate_reply(
                instructions=f"Fale esta mensagem: {closing}"
            )
        except Exception as e:
            logger.warning(f"[Host] Erro na pergunta inicial: {e}")
            await ctx.room.local_participant.publish_data(
                json.dumps({
                    "type": "transcript",
                    "speaker": "Nathália",
                    "text": closing,
                }).encode(),
                reliable=True,
            )

        logger.info("[Host] Apresentação concluída.")

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

            elif msg.get("type") == "set_project_name":
                blackboard.project_name = msg.get("name", "")
                logger.info(f"[Room] Nome do projeto definido: {blackboard.project_name}")

        except Exception as e:
            logger.warning(f"[Room] Erro ao processar data packet do frontend: {e}")

    # ------------------------------------------------------------------
    # Loop principal — mantém o worker vivo enquanto o room estiver ativo
    # ------------------------------------------------------------------
    logger.info("=== Job em execução. Aguardando interação... ===")
    shutdown_event = asyncio.Event()
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        logger.info("[Job] Cancelado externamente. Encerrando.")
    except Exception as e:
        logger.error(f"[Job] Erro no loop principal: {e}", exc_info=True)
    finally:
        blackboard.is_active = False
        logger.info("[Job] Encerrado.")


# ============================================================
# ENTRY POINT DO WORKER
# ============================================================

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="mentoria-agent",
        )
    )