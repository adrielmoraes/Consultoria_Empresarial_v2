"""
Mentoria AI - Worker Multi-Agentes v2
======================================
6 agentes: Nathália (Host/Apresentadora), Carlos (CFO), Daniel (Advogado),
           Rodrigo (CMO), Ana (CTO), Marco (Estrategista/Planner)

Nathália usa Google Realtime (Gemini Live) com VAD e function tools.
Os especialistas usam Gemini TTS diretamente via google.genai SDK,
cada um conectado ao room com identidade própria (participante separado).
Marco gera o Plano de Execução ao final da sessão.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Mapeamos GEMINI_API_KEY → GOOGLE_API_KEY para os plugins que leem essa variável
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = _gemini_key

import google.genai as genai
import google.genai.types as genai_types

from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
    function_tool,
    Agent,
    AgentSession,
    RunContext,
)
from livekit.plugins import google as google_plugin
from livekit.plugins import silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentoria-ai")


# ============================================================
# CONFIG
# ============================================================

GEMINI_REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_CHAT_MODEL = "gemini-2.5-flash"
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

AGENT_VOICES: dict[str, str] = {
    "host":  "Aoede",    # Nathália – feminina suave
    "cfo":   "Charon",   # Carlos   – masculina grave
    "legal": "Fenrir",   # Daniel   – masculina formal
    "cmo":   "Puck",     # Rodrigo  – masculina dinâmica
    "cto":   "Kore",     # Ana      – feminina técnica
    "plan":  "Zephyr",   # Marco    – masculina autoritativa
}

SPECIALIST_NAMES: dict[str, str] = {
    "host":  "Nathália (Apresentadora)",
    "cfo":   "Carlos (CFO)",
    "legal": "Daniel (Advogado)",
    "cmo":   "Rodrigo (CMO)",
    "cto":   "Ana (CTO)",
    "plan":  "Marco (Estrategista)",
}

# Frases de auto-apresentação de cada especialista
SPECIALIST_INTROS: dict[str, str] = {
    "cfo": (
        "Olá! Muito prazer, eu sou o Carlos, CFO e especialista em finanças. "
        "Meu trabalho aqui é analisar a viabilidade econômica do seu projeto: "
        "precificação, projeções de receita, estrutura de custos e fontes de financiamento. "
        "Fico feliz em te ajudar a construir um negócio financeiramente sólido!"
    ),
    "legal": (
        "Oi! Eu sou o Daniel, advogado especialista em direito empresarial. "
        "Cuido dos aspectos jurídicos do seu negócio: tipo societário, contratos, "
        "conformidade com a LGPD e proteção legal. "
        "Pode ficar tranquilo que estarei aqui para te orientar em cada passo!"
    ),
    "cmo": (
        "Ei, que bom ter você aqui! Sou o Rodrigo, CMO e especialista em marketing e vendas. "
        "Vou ajudar a definir seu posicionamento de mercado, estratégias de aquisição de clientes "
        "e como fazer o seu produto conquistar o mercado brasileiro. Bora crescer juntos!"
    ),
    "cto": (
        "Olá! Eu sou a Ana, CTO e especialista em tecnologia. "
        "Cuido da parte técnica: stack tecnológico, arquitetura de sistema, infraestrutura e escalabilidade. "
        "Vou garantir que a tecnologia do seu projeto seja robusta, moderna e dentro do orçamento!"
    ),
    "plan": (
        "Olá a todos! Muito prazer, eu sou o Marco, estrategista-chefe. "
        "Meu papel é diferente dos demais: ao final da nossa sessão, vou sintetizar tudo que discutirmos "
        "e entregar um Plano de Execução completo, com cronograma, riscos e próximos passos concretos. "
        "Acompanharei toda a conversa e no final, entrego tudo organizado para você!"
    ),
}


# ============================================================
# PROMPTS
# ============================================================

HOST_PROMPT = """Você é Nathália, a Apresentadora (Host) do Mentoria AI.
Seu papel é orquestrar a sessão de mentoria empresarial multi-agentes.

REGRAS:
- Receba o usuário de forma calorosa e profissional.
- Identifique os tópicos do projeto/problema do usuário.
- Acione os especialistas chamando-os pelo nome na conversa (ex: "Carlos, o que você acha das finanças?").
- SEMPRE faça pelo menos uma pergunta ao usuário por interação.
- Após o especialista falar, resuma brevemente e pergunte ao usuário se tem dúvidas.
- Mantenha respostas curtas (máximo 3 frases por turno).
- Quando o usuário quiser encerrar ou pedir o plano, chame o Marco.
- Fale em português do Brasil."""

SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo": (
        "Você é Carlos, o CFO (Chief Financial Officer). Sua voz é Charon. "
        "Você faz parte de uma mentoria empresarial multi-agentes. "
        "Fique em silêncio e ouça atentamente até que Nathália (a apresentadora) ou o usuário chame seu nome ou peça uma análise financeira. "
        "Ao ser acionado, analise custos, receitas e viabilidade. "
        "Seja proativo mas breve (máximo 4 frases). Mantenha o tone profissional."
    ),
    "legal": (
        "Você é Daniel, o Advogado. Sua voz é Fenrir. "
        "Você faz parte de uma mentoria empresarial multi-agentes. "
        "Fique em silêncio até ser chamado por Nathália ou o usuário. "
        "Foque em contratos, estrutura societária e LGPD. "
        "Seja formal e preciso (máximo 4 frases)."
    ),
    "cmo": (
        "Você é Rodrigo, o CMO. Sua voz é Puck. "
        "Você faz parte de uma mentoria empresarial multi-agentes. "
        "Fique em silêncio até ser chamado. "
        "Foque em marketing, aquisição de clientes e branding. "
        "Seja dinâmico e entusiasmado (máximo 4 frases)."
    ),
    "cto": (
        "Você é Ana, a CTO. Sua voz é Kore. "
        "Você faz parte de uma mentoria empresarial multi-agentes. "
        "Fique em silêncio até ser chamada. "
        "Foque em tecnologia, escalabilidade e desenvolvimento. "
        "Seja técnica e prática (máximo 4 frases)."
    ),
    "plan": (
        "Você é Marco, o Estrategista. Sua voz é Zephyr. "
        "Você faz parte de uma mentoria empresarial multi-agentes. "
        "Fique em silêncio até ser chamado. "
        "Sua função é consolidar as ideias e propor um plano de execução. "
        "Apresente um resumo estruturado com próximos passos."
    ),
}


# ============================================================
# BLACKBOARD – contexto compartilhado
# ============================================================

@dataclass
class Blackboard:
    project_name: str = ""
    user_query: str = ""
    transcript: list[dict] = field(default_factory=list)
    is_active: bool = True

    def add_message(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content})

    def get_context_summary(self) -> str:
        parts: list[str] = []
        if self.project_name:
            parts.append(f"Projeto: {self.project_name}")
        if self.user_query:
            parts.append(f"Necessidade do usuário: {self.user_query}")
        recent = self.transcript[-16:]
        if recent:
            parts.append("--- Conversa Recente ---")
            for msg in recent:
                parts.append(f"[{msg['role']}]: {msg['content']}")
        return "\n".join(parts)

    def get_full_transcript(self) -> str:
        return "\n\n".join(f"[{m['role']}]: {m['content']}" for m in self.transcript)


# ============================================================
# SPECIALIST AGENT – Realtime Native Audio
# ============================================================

class SpecialistAgent(Agent):
    """
    Especialista como um agente Realtime completo (voz-para-voz).
    Ele escuta a sala e só fala quando provocado.
    """

    def __init__(self, spec_id: str, blackboard: Blackboard) -> None:
        name = SPECIALIST_NAMES[spec_id]
        super().__init__(
            instructions=SPECIALIST_SYSTEM_PROMPTS[spec_id],
            llm=google_plugin.realtime.RealtimeModel(
                model=GEMINI_REALTIME_MODEL,
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                voice=AGENT_VOICES[spec_id],
            ),
            allow_interruptions=True,
        )
        self._spec_id = spec_id
        self._name = name
        self._blackboard = blackboard

    async def run(self, room: rtc.Room) -> None:
        """Inicia a sessão do especialista no room."""
        # Nota: start() retorna a sessão
        session = self.start(room)
        
        @session.on("conversation_item_added")
        def _on_item_added(event) -> None:
            # Captura a fala do especialista no Blackboard
            item = getattr(event, "item", None)
            if item and item.role == "assistant" and item.text_content:
                content = item.text_content
                self._blackboard.add_message(self._name, content)
                # Publica transcrição para o frontend
                asyncio.create_task(
                    room.local_participant.publish_data(
                        json.dumps({"type": "transcript", "speaker": self._name, "text": content}).encode(),
                        reliable=True,
                    )
                )

        logger.info(f"[{self._name}] Sessão Native Audio iniciada.")


# ============================================================
# HOST AGENT – Nathália orquestra os especialistas
# ============================================================

class HostAgent(Agent):
    """
    Nathália – usa Google RealtimeModel (Gemini Live) para STT+LLM+TTS.
    Aciona especialistas via voz na sala.
    """

    def __init__(
        self,
        blackboard: Blackboard,
        room: rtc.Room,
    ) -> None:
        super().__init__(
            instructions=HOST_PROMPT,
            llm=google_plugin.realtime.RealtimeModel(
                model=GEMINI_REALTIME_MODEL,
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                voice=AGENT_VOICES["host"],
            ),
            allow_interruptions=True,
        )
        self._blackboard = blackboard
        self._room = room

    # ------ function tools ------

    @function_tool
    async def acionar_carlos_cfo(self, context: RunContext, questao: str) -> str:
        """Aciona Carlos (CFO) para análise financeira."""
        return f"Chamando Carlos para analisar: {questao}"

    @function_tool
    async def acionar_daniel_advogado(self, context: RunContext, questao: str) -> str:
        """Aciona Daniel (Advogado) para orientação jurídica."""
        return f"Chamando Daniel para analisar: {questao}"

    @function_tool
    async def acionar_rodrigo_cmo(self, context: RunContext, questao: str) -> str:
        """Aciona Rodrigo (CMO) para estratégia de marketing."""
        return f"Chamando Rodrigo para analisar: {questao}"

    @function_tool
    async def acionar_ana_cto(self, context: RunContext, questao: str) -> str:
        """Aciona Ana (CTO) para orientação técnica."""
        return f"Chamando Ana para analisar: {questao}"

    @function_tool
    async def debate_completo(self, context: RunContext, tema: str) -> str:
        """Inicia debate com TODOS os especialistas."""
        return f"Iniciando debate com todos sobre: {tema}"

    @function_tool
    async def gerar_plano_execucao(self, context: RunContext) -> str:
        """Aciona Marco para gerar o Plano de Execução."""
        return "Marco está preparando o plano consolidado agora."


# ============================================================
# ENTRYPOINT
# ============================================================

async def _connect_agent(
    agent: Agent,
    ws_url: str,
    lk_api_key: str,
    lk_api_secret: str,
    room_name: str,
    identity: str,
    name: str,
    delay: float = 0
) -> bool:
    """Conecta um agente individual ao room e inicia sua sessão com um atraso opcional."""
    if delay > 0:
        await asyncio.sleep(delay)
        
    logger.info(f"[{name}] Iniciando conexão após {delay}s de espera...")
    try:
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
        room = rtc.Room()
        # Aumentamos o timeout para 60s devido a instabilidade regional do Gemini
        await asyncio.wait_for(room.connect(ws_url, token), timeout=60.0)
        
        # Em 1.4+, usamos AgentSession para iniciar o Agent
        session = AgentSession()
        await session.start(agent, room=room)
        
        logger.info(f"[{name}] Conectado com sucesso.")
        return True
    except Exception as e:
        logger.error(f"[{name}] Erro ao conectar: {e}")
        return False


async def entrypoint(ctx: JobContext) -> None:
    # Logging em arquivo para diagnóstico de processo filho
    _fh = logging.FileHandler("/tmp/mentoria_agent.log", mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_fh)

    logger.info(f"=== ENTRYPOINT NATIVE AUDIO – sala: {ctx.room.name} ===")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Conectado ao room {ctx.room.name}")

    blackboard = Blackboard(project_name=ctx.room.name)

    ws_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    lk_api_key = os.getenv("LIVEKIT_API_KEY", "")
    lk_api_secret = os.getenv("LIVEKIT_API_SECRET", "")

    # 1. Nathália (Host)
    host_agent = HostAgent(blackboard, ctx.room)
    host_session = AgentSession(
        vad=silero.VAD.load()
    )
    try:
        await host_session.start(host_agent, room=ctx.room)
        logger.info("[Host] Nathália iniciada.")
    except Exception as e:
        logger.error(f"[Host] Erro ao iniciar a sessão da Nathália: {e}", exc_info=True)
        return

    # 2. Conectar especialistas de forma escalonada (Staggered)
    spec_ids = ["cfo", "legal", "cmo", "cto", "plan"]
    specialists = [SpecialistAgent(sid, blackboard) for sid in spec_ids]
    
    async def _connect_all_specs():
        logger.info("[Especialistas] Iniciando conexão escalonada...")
        for i, sid in enumerate(spec_ids):
            # Atraso incremental para evitar sobrecarga
            delay = i * 2.5
            asyncio.create_task(_connect_agent(
                specialists[i], ws_url, lk_api_key, lk_api_secret, 
                ctx.room.name, f"agent-{sid}", SPECIALIST_NAMES[sid],
                delay=delay
            ))
        logger.info("[Especialistas] Tarefas de conexão disparadas.")

    asyncio.create_task(_connect_all_specs())

    # Transcrição do usuário → blackboard + frontend
    @host_session.on("user_input_transcribed")
    def _on_user_speech(event) -> None:
        text: str = getattr(event, "transcript", "")
        if not text: return
        blackboard.add_message("Usuário", text)
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Você", "text": text}).encode(),
                reliable=True,
            )
        )

    # Fala da host → blackboard + frontend
    @host_session.on("agent_speech_transcribed") # Ajustado para o evento correto de transcrição do agente
    def _on_host_speech(event) -> None:
        text: str = getattr(event, "transcript", "")
        if not text: return
        blackboard.add_message("Nathália (Host)", text)
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Nathália", "text": text}).encode(),
                reliable=True,
            )
        )

    # 3. Saudação Inicial (Nathália)
    async def welcome_task():
        await asyncio.sleep(1) # Espera 1s para o áudio estabilizar
        user_name = blackboard.get_user_name()
        greeting = (
            f"Olá {user_name}! Sou a Nathália, sua apresentadora e mentor líder. "
            "Estamos aqui com nosso time de especialistas para acelerar seu negócio. "
            "Como podemos te ajudar hoje?"
        )
        logger.info(f"Enviando saudação da Nathália para {user_name}...")
        try:
            # Usando Native Audio do RealtimeModel
            await host_session.say(greeting, allow_interruptions=True)
        except Exception as e:
            logger.error(f"Erro na saudação (Realtime): {e}")
            # Fallback apenas texto
            await ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Nathália", "text": greeting}).encode(),
                reliable=True,
            )

    asyncio.create_task(welcome_task())

    # Mensagens de dados do frontend
    @ctx.room.on("data_received")
    def _on_data_received(dp: rtc.DataPacket) -> None:
        try:
            # Em LiveKit RTC 1.x, recebemos um DataPacket
            data = dp.data
            msg = json.loads(data.decode())
            if msg.get("type") == "end_session":
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        json.dumps({
                            "type": "session_end",
                            "transcript": blackboard.get_context_summary(),
                        }).encode(),
                        reliable=True,
                    )
                )
        except Exception as e:
            logger.warning(f"Erro ao processar dados: {e}")

    # Loop principal
    logger.info("=== Job em execução. Aguardando interação... ===")
    try:
        await host_session.wait_for_shutdown()
        logger.info("Sessão da Host finalizada.")
    except Exception as e:
        logger.error(f"Erro no loop principal: {e}")
    finally:
        logger.info("Encerrando o Job.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="mentoria-agent"
    ))
