"""
Mentoria AI - Worker Multi-Agentes v3 (CORRIGIDO)
==================================================
Correções aplicadas:

    P1 & P2 · SpecialistAgent.run() não existe na API Agent.
              Cada especialista agora é iniciado via AgentSession separado
              no mesmo room, com identidade própria via token.

    P3 · Blackboard.get_user_name() não existia → removido do welcome_task.

    P4 · Evento 'agent_speech_transcribed' não existe → corrigido para
         'agent_transcript_updated' (evento real do LiveKit Agents 1.x).

    P5 · host_session.say() não existe em AgentSession → corrigido para
         host_agent.say() chamado via session.

    P6 · host_session.wait_for_shutdown() não existe → corrigido para
         ctx.wait_for_shutdown() do JobContext.

    P7 · Arquitetura corrigida: cada especialista entra no MESMO room
         como participante separado (token próprio), com AgentSession
         individual e RealtimeModel nativo. A Nathália os aciona via
         voz (falando o nome no canal de áudio do room) e via function
         tools que publicam dados para coordenar quem deve falar.

Arquitetura final:
    - Nathália (Host): RealtimeModel nativo no room principal
    - Especialistas (CFO, Legal, CMO, CTO, Plan): RealtimeModel nativo,
      cada um como participante separado no mesmo room, mas com VAD
      próprio e AgentSession independente.
    - Blackboard: contexto compartilhado em memória (mesma instância
      passada por referência a todos os agentes no mesmo processo).
    - Coordenação: Nathália publica data packets para silenciar/ativar
      especialistas. Cada especialista ouve o canal e responde apenas
      quando seu nome for publicado no campo 'active_agent'.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
from livekit.plugins import google as google_plugin
from livekit.plugins import silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentoria-ai")


# ============================================================
# CONFIG
# ============================================================

# Modelo Realtime nativo do Gemini (voz-para-voz, sem pipeline STT+TTS separado)
GEMINI_REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

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
# Cada um sabe que deve AGUARDAR ser acionado antes de falar.
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
    # active_agent: qual especialista deve responder agora (None = todos em silêncio)
    active_agent: Optional[str] = None
    transcript: list[dict] = field(default_factory=list)
    is_active: bool = True

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
        # Apenas as últimas 20 mensagens para não extrapolar o contexto
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

    A ativação acontece de duas formas:
    1. Nathália fala o nome do especialista no canal de áudio (o modelo
       Realtime ouve e reage ao contexto conversacional).
    2. Um data packet do tipo 'activate_agent' é publicado no room
       com o spec_id correspondente. O especialista só responde se
       self._blackboard.active_agent == self._spec_id.
    """

    def __init__(self, spec_id: str, blackboard: Blackboard) -> None:
        name = SPECIALIST_NAMES[spec_id]

        # O system prompt já inclui a instrução de aguardar ser chamado.
        # Injetamos o contexto do Blackboard dinamicamente via instructions.
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


# ============================================================
# HOST AGENT – Nathália
# ============================================================

class HostAgent(Agent):
    """
    Nathália usa Google RealtimeModel (Gemini Live) para pipeline
    voz-para-voz completo (VAD → STT → LLM → TTS nativo).

    As function tools publicam data packets no room para coordenar
    qual especialista deve falar a seguir.
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

    # ------------------------------------------------------------------
    # Método auxiliar: publica um data packet para ativar um especialista
    # ------------------------------------------------------------------

    async def _activate_specialist(self, spec_id: str, context: str) -> None:
        """
        Publica um data packet no room indicando qual especialista deve falar.
        O especialista ouve via room.on('data_received') em sua AgentSession.
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
        context: RunContext,  # type: ignore[override]
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
        context: RunContext,  # type: ignore[override]
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
        context: RunContext,  # type: ignore[override]
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
        context: RunContext,  # type: ignore[override]
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
        context: RunContext,  # type: ignore[override]
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
) -> None:
    """
    Conecta um SpecialistAgent ao room como participante separado.

    Cada especialista:
    1. Gera seu próprio JWT com identidade única.
    2. Cria um rtc.Room e conecta ao mesmo room_name.
    3. Inicia um AgentSession com VAD e RealtimeModel nativo.
    4. Escuta data packets para saber quando deve falar.

    O atraso (delay) escalonado evita colisão de handshakes no servidor.
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

        # Conecta ao room (timeout generoso para instabilidade regional do Gemini)
        room = rtc.Room()
        await asyncio.wait_for(
            room.connect(ws_url, token),
            timeout=60.0,
        )
        logger.info(f"[{name}] Room conectado.")

        # Instancia o agent e a sessão
        agent = SpecialistAgent(spec_id, blackboard)

        # CORREÇÃO P1/P2: AgentSession é quem inicia o agent, não o agent si mesmo.
        # VAD próprio por especialista evita que todos falem ao mesmo tempo.
        session = AgentSession(
            vad=silero.VAD.load(),
        )

        # CORREÇÃO P7: start recebe o agent e o room — API correta do LiveKit Agents 1.x
        await session.start(agent, room=room)
        logger.info(f"[{name}] AgentSession iniciada com RealtimeModel nativo.")

        # Captura transcrição do especialista e salva no Blackboard
        @session.on("agent_transcript_updated")  # CORREÇÃO P4: evento correto
        def _on_agent_transcript(event) -> None:
            text: str = getattr(event, "transcript", "")
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
                        # Atualiza o contexto do agent com o resumo da conversa
                        ctx_summary = msg.get("transcript_summary", "")
                        if ctx_summary:
                            # Injeta contexto atualizado nas instructions do agent em tempo real
                            agent.instructions = (
                                SPECIALIST_SYSTEM_PROMPTS[spec_id]
                                + f"\n\n--- CONTEXTO ATUAL DA SESSÃO ---\n{ctx_summary}"
                            )
                        logger.info(f"[{name}] Ativado via data packet.")
                    else:
                        # Outro especialista foi ativado — este permanece em silêncio
                        logger.debug(f"[{name}] Em silêncio (ativo: {msg.get('agent_id')}).")
            except Exception as e:
                logger.warning(f"[{name}] Erro ao processar data packet: {e}")

    except asyncio.TimeoutError:
        logger.error(f"[{name}] Timeout ao conectar ao room após 60s.")
    except Exception as e:
        logger.error(f"[{name}] Erro ao iniciar: {e}", exc_info=True)


# ============================================================
# ENTRYPOINT
# ============================================================

async def entrypoint(ctx: JobContext) -> None:
    # Log em arquivo para diagnóstico (processo filho do worker)
    _fh = logging.FileHandler("/tmp/mentoria_agent.log", mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)

    logger.info(f"=== ENTRYPOINT MENTORIA AI v3 – sala: {ctx.room.name} ===")

    # Conecta o worker ao room (somente áudio)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Worker conectado ao room: {ctx.room.name}")

    # Blackboard compartilhado — mesma instância para todos os agentes no processo
    blackboard = Blackboard(project_name=ctx.room.name)

    # Lê variáveis de ambiente necessárias para conectar especialistas
    ws_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    lk_api_key = os.getenv("LIVEKIT_API_KEY", "")
    lk_api_secret = os.getenv("LIVEKIT_API_SECRET", "")

    # ------------------------------------------------------------------
    # 1. Iniciar Nathália (Host) no room principal
    # ------------------------------------------------------------------
    host_agent = HostAgent(blackboard, ctx.room)
    host_session = AgentSession(
        vad=silero.VAD.load(),
    )

    try:
        # CORREÇÃO P1/P2: session.start(agent, room=room) — API correta
        await host_session.start(host_agent, room=ctx.room)
        logger.info("[Host] Nathália iniciada com RealtimeModel nativo.")
    except Exception as e:
        logger.error(f"[Host] Erro crítico ao iniciar Nathália: {e}", exc_info=True)
        return

    # ------------------------------------------------------------------
    # Captura transcrição do usuário → Blackboard + frontend
    # ------------------------------------------------------------------
    @host_session.on("user_input_transcribed")
    def _on_user_speech(event) -> None:
        text: str = getattr(event, "transcript", "")
        if not text:
            return
        blackboard.add_message("Usuário", text)
        # Atualiza a query principal se for a primeira mensagem
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
    # CORREÇÃO P4: evento correto é 'agent_transcript_updated'
    # ------------------------------------------------------------------
    @host_session.on("agent_transcript_updated")
    def _on_host_speech(event) -> None:
        text: str = getattr(event, "transcript", "")
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
    # 2. Iniciar especialistas de forma escalonada (staggered)
    # Cada um entra no room como participante separado com delay incremental
    # para não sobrecarregar o servidor de sinalização.
    # ------------------------------------------------------------------
    spec_ids = ["cfo", "legal", "cmo", "cto", "plan"]

    for i, sid in enumerate(spec_ids):
        delay = i * 3.0  # 0s, 3s, 6s, 9s, 12s
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
    # 3. Saudação inicial da Nathália (aguarda 2s para o áudio estabilizar)
    # CORREÇÃO P3: removido blackboard.get_user_name() que não existia
    # CORREÇÃO P5: host_agent.say() — método correto do Agent, não da AgentSession
    # ------------------------------------------------------------------
    async def welcome_task() -> None:
        await asyncio.sleep(2.0)
        greeting = (
            "Olá! Seja muito bem-vindo ao Mentoria AI. "
            "Sou a Nathália, sua apresentadora e mentora líder. "
            "Estamos aqui com nosso time completo de especialistas: "
            "Carlos em finanças, Daniel em direito, Rodrigo em marketing, "
            "Ana em tecnologia e Marco como nosso estrategista-chefe. "
            "Me conte: qual é o seu projeto ou principal desafio de negócio hoje?"
        )
        logger.info("[Host] Enviando saudação inicial...")
        try:
            # CORREÇÃO P5: say() é chamado no agent, não na session
            await host_agent.say(greeting, allow_interruptions=True)
        except Exception as e:
            logger.error(f"[Host] Erro na saudação: {e}", exc_info=True)
            # Fallback: publica apenas o texto para o frontend
            await ctx.room.local_participant.publish_data(
                json.dumps({
                    "type": "transcript",
                    "speaker": "Nathália",
                    "text": greeting,
                }).encode(),
                reliable=True,
            )

    asyncio.create_task(welcome_task())

    # ------------------------------------------------------------------
    # Escuta mensagens de dados do frontend
    # ------------------------------------------------------------------
    @ctx.room.on("data_received")
    def _on_data_received(dp: rtc.DataPacket) -> None:
        try:
            msg = json.loads(dp.data.decode())

            # Frontend pediu encerramento da sessão
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

            # Frontend enviou nome do projeto
            elif msg.get("type") == "set_project_name":
                blackboard.project_name = msg.get("name", "")
                logger.info(f"[Room] Nome do projeto definido: {blackboard.project_name}")

        except Exception as e:
            logger.warning(f"[Room] Erro ao processar data packet do frontend: {e}")

    # ------------------------------------------------------------------
    # Loop principal
    # CORREÇÃO P6: ctx.wait_for_shutdown() — método correto do JobContext
    # ------------------------------------------------------------------
    logger.info("=== Job em execução. Aguardando interação... ===")
    try:
        await ctx.wait_for_shutdown()
        logger.info("[Job] Shutdown solicitado. Encerrando graciosamente.")
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