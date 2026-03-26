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

# C4: Guard global contra jobs duplicados na mesma sala.
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
    "plan":  "Charon",   # Marco    – masculina autoritativa (compartilha voz)
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

# C1: Ordem de entrada dos especialistas na apresentação sequencial.
SPECIALIST_ORDER: list[str] = ["cfo", "legal", "cmo", "cto", "plan"]

# Tempo de espera (em segundos) após cada especialista se apresentar
# antes de conectar o próximo. Dá tempo para o áudio ser ouvido.
POST_INTRO_WAIT: float = 0.5


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
- Identifique o NOME do usuário e os tópicos do projeto/problema.
- SEMPRE chame o usuário pelo nome.
- Quando precisar de análise financeira, use a função acionar_carlos_cfo.
- Quando precisar de orientação jurídica, use acionar_daniel_advogado.
- Quando precisar de estratégia de marketing, use acionar_rodrigo_cmo.
- Quando precisar de orientação técnica, use acionar_ana_cto.
- Quando o usuário quiser encerrar ou pedir o plano, use gerar_plano_execucao.
- SEMPRE faça pelo menos uma pergunta ao usuário por interação.
- Mantenha respostas curtas (máximo 3 frases por turno).
- Fale em português do Brasil."""

SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo": (
        "Você é Carlos, o CFO (Chief Financial Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio absoluto. Você SÓ PODE FALAR quando Nathália (a apresentadora) o acionar. "
        "Se souber o nome do usuário pelas transcrições anteriores, use-o para chamá-lo pelo nome. "
        "Quando acionado, analise custos, receitas, precificação e viabilidade financeira. "
        "Seja preciso, profissional e objetivo. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "legal": (
        "Você é Daniel, o Advogado do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio absoluto. Você SÓ PODE FALAR quando Nathália (a apresentadora) o acionar. "
        "Se souber o nome do usuário pelas transcrições anteriores, use-o para chamá-lo pelo nome. "
        "Quando acionado, foque em contratos, estrutura societária, LGPD e compliance. "
        "Seja formal, preciso e claro. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "cmo": (
        "Você é Rodrigo, o CMO (Chief Marketing Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio absoluto. Você SÓ PODE FALAR quando Nathália (a apresentadora) o acionar. "
        "Se souber o nome do usuário pelas transcrições anteriores, use-o para chamá-lo pelo nome. "
        "Quando acionado, foque em posicionamento, aquisição de clientes, branding e growth. "
        "Seja dinâmico, entusiasmado e prático. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "cto": (
        "Você é Ana, a CTO (Chief Technology Officer) do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio absoluto. Você SÓ PODE FALAR quando Nathália (a apresentadora) o acionar. "
        "Se souber o nome do usuário pelas transcrições anteriores, use-o para chamá-lo pelo nome. "
        "Quando acionada, foque em stack tecnológico, arquitetura, infraestrutura e escalabilidade. "
        "Seja técnica, prática e objetiva. Máximo 4 frases por resposta. "
        "Fale em português do Brasil."
    ),
    "plan": (
        "Você é Marco, o Estrategista-Chefe do Mentoria AI. "
        "Você participa de uma sessão de mentoria empresarial multi-agentes. "
        "AGUARDE em silêncio absoluto. Você SÓ PODE FALAR quando Nathália (a apresentadora) o acionar. "
        "Se souber o nome do usuário pelas transcrições anteriores, use-o para chamá-lo pelo nome. "
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
# SPECIALIST AGENT
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
        Aciona Marco (Estrategista) para gerar o Plano de Execução consolidado.
        Use quando o usuário quiser encerrar a sessão ou pedir um resumo
        estruturado com próximos passos.
        """
        ctx_summary = self._blackboard.get_context_summary()
        await self._activate_specialist("plan", ctx_summary)

        try:
            plan_payload = json.dumps({
                "type": "execution_plan",
                "plan": ctx_summary,
                "text": ctx_summary,
            }).encode()
            await self._room.local_participant.publish_data(plan_payload, reliable=True)
            logger.info("[Host] Plano de execução publicado como data packet.")
        except Exception as e:
            logger.warning(f"[Host] Erro ao publicar plano de execução: {e}")

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

    logger.info(f"=== ENTRYPOINT MENTORIA AI v5 – sala: {ctx.room.name} ===")

    # Conecta o worker ao room sem auto-subscribe (Host não precisa ouvir especialistas)
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_NONE)
    logger.info(f"Worker conectado ao room: {ctx.room.name}")
    
    def _subscribe_host_to_user_audio(publication, participant):
        if participant.identity.startswith("user-") and publication.kind == rtc.TrackKind.KIND_AUDIO:
            publication.set_subscribed(True)

    ctx.room.on("track_published", _subscribe_host_to_user_audio)
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            _subscribe_host_to_user_audio(publication, participant)

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
    # 2. Fluxo de Apresentação Sequencial:
    # ------------------------------------------------------------------
    async def welcome_and_introductions() -> None:
        # 2a. Conecta todos os especialistas CONCORRENTEMENTE em background
        # para economizar tempo enquanto a Nathália se inicializa.
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

        # Aguarda Nathália estabilizar no room e o RealtimeModel conectar ao Gemini
        await asyncio.sleep(2.0)

        # 2b. Nathália se apresenta e anuncia o time
        host_greeting = (
            "Olá! Seja muito bem-vindo ao Mentoria AI! "
            "Sou a Nathália, sua apresentadora e mentora líder desta sessão. "
            "Nossa equipe de especialistas já está conectada e vai se apresentar agora."
        )
        logger.info("[Host] Nathália enviando apresentação inicial...")
        try:
            await asyncio.wait_for(
                host_session.generate_reply(
                    instructions=f"Por favor, diga a seguinte apresentação: {host_greeting}",
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("[Host] Timeout (30s) ao gerar reply inicial - RealtimeModel pode não ter conectado ao Gemini.")
        except Exception as e:
            logger.warning(f"[Host] Erro ao gerar reply inicial: {type(e).__name__}: {e}", exc_info=True)

        # Aguarda todos os especialistas terminarem de conectar (caso ainda não tenham)
        sessions = await asyncio.gather(*connect_tasks)
        spec_sessions = dict(zip(SPECIALIST_ORDER, sessions))

        # 2c. Especialistas se apresentam SEQUENCIALMENTE (instantaneamente após Nathália)
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
                        instructions=f"Por favor, apresente-se rapidamente dizendo: {intro_text}. Se souber o nome do usuário, salde-o pelo nome.",
                    ),
                    timeout=25.0,
                )
                logger.info(f"[Apresentação] {spec_name} concluiu.")
                await asyncio.sleep(POST_INTRO_WAIT)
            except Exception as e:
                logger.warning(f"[Apresentação] Erro na apresentação de {spec_name}: {e}")

        logger.info("[Apresentação] Todos os especialistas foram apresentados.")

        # Guard — não continua se o job já estiver encerrando
        if not blackboard.is_active:
            return

        # 2c. Nathália retoma e faz a pergunta inicial ao usuário
        closing_base = "Agora que você já conhece toda a nossa equipe, me conte: "
        if blackboard.user_name:
            closing = f"{closing_base}{blackboard.user_name}, qual é o seu principal desafio de negócio ou projeto atual? Estou aqui para ouvir você!"
        else:
            closing = f"{closing_base}qual é o seu nome e qual é o seu principal desafio de negócio ou projeto atual? Estou aqui para ouvir você!"

        logger.info("[Host] Nathália fazendo pergunta inicial...")
        try:
            await asyncio.wait_for(
                host_session.generate_reply(
                    instructions=f"Faça a seguinte pergunta: {closing}",
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
# C4: Guard contra jobs duplicados — rejeita segundo job na mesma sala
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
# ENTRY POINT DO WORKER
# ============================================================

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=on_job_request,
            agent_name="mentoria-agent",
        )
    )