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
)
from livekit.agents.voice import Agent, AgentSession, RunContext
from livekit.agents.voice import room_io
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
- Acione os especialistas usando as ferramentas disponíveis.
- SEMPRE faça pelo menos uma pergunta ao usuário por interação.
- Após o especialista falar, resuma brevemente e pergunte ao usuário se tem dúvidas.
- Mantenha respostas curtas (máximo 3 frases por turno).
- Quando o usuário quiser encerrar ou pedir o plano, acione o Marco.
- Fale sempre em português do Brasil com tom acolhedor.
- IMPORTANTE: Avise antes de acionar cada especialista (ex: "Vou chamar Carlos, nosso CFO, para analisar isso.")."""

SPECIALIST_PROMPTS: dict[str, str] = {
    "cfo": """Você é Carlos, o CFO (Chief Financial Officer) do Mentoria AI.
Especialista em finanças, viabilidade econômica, precificação e projeções.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Análises financeiras práticas e diretas com números concretos.
- Sugira modelos de negócio, fontes de receita e estrutura de custos.
- Considere o contexto brasileiro (impostos, regulamentações locais).
- Máximo 4 frases por resposta.
- SEMPRE finalize com uma pergunta ao usuário sobre expectativas financeiras.
- Fale em português do Brasil.""",

    "legal": """Você é Daniel, o Advogado do Mentoria AI.
Especialista em direito empresarial, contratos, LGPD e conformidade.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Foco em conformidade legal e proteção jurídica.
- Mencione tipos societários quando relevante (MEI, LTDA, S/A).
- Alerte sobre riscos trabalhistas, fiscais e regulatórios (CLT, LGPD, Código Civil).
- Máximo 4 frases por resposta.
- SEMPRE finalize com uma pergunta ao usuário sobre aspectos legais.
- Fale em português do Brasil.""",

    "cmo": """Você é Rodrigo, o CMO (Chief Marketing Officer) do Mentoria AI.
Especialista em marketing, aquisição de clientes, branding e go-to-market.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Estratégias práticas de marketing e vendas com exemplos concretos.
- Sugira canais de aquisição e estratégias de posicionamento no mercado brasileiro.
- Máximo 4 frases por resposta.
- SEMPRE finalize com uma pergunta ao usuário sobre público-alvo ou diferencial.
- Fale em português do Brasil.""",

    "cto": """Você é Ana, a CTO (Chief Technology Officer) do Mentoria AI.
Especialista em arquitetura de software, infraestrutura e escolha de stack.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Recomendações técnicas práticas e modernas.
- Sugira stacks considerando custo, maturidade e facilidade de implementação.
- Alerte sobre gargalos de escalabilidade e dependências críticas.
- Máximo 4 frases por resposta.
- SEMPRE finalize com uma pergunta ao usuário sobre requisitos técnicos.
- Fale em português do Brasil.""",

    "plan": """Você é Marco, o Estrategista Chefe do Mentoria AI.
Sua missão é sintetizar toda a sessão e criar o PLANO DE EXECUÇÃO FINAL.

TRANSCRIÇÃO COMPLETA DA SESSÃO:
{context}

CRIE UM PLANO DE EXECUÇÃO COMPLETO QUE INCLUA:
1. **Resumo Executivo** – O projeto em 2-3 parágrafos
2. **Análise Financeira** – Custos, receita, ponto de equilíbrio
3. **Estrutura Jurídica** – Tipo societário, contratos, conformidade
4. **Estratégia de Marketing** – Canais, posicionamento, go-to-market
5. **Arquitetura Técnica** – Stack, infraestrutura, escalabilidade
6. **Cronograma de Execução** – Fases e prazos realistas
7. **Riscos e Mitigações** – Top 5 riscos e como mitigar
8. **Próximos Passos** – 5 ações concretas para esta semana

Seja específico, motivador e use o contexto completo da conversa.
Fale em português do Brasil.""",
}


# ============================================================
# BLACKBOARD – contexto compartilhado
# ============================================================

@dataclass
class Blackboard:
    project_name: str = ""
    user_query: str = ""
    transcript: list[dict] = field(default_factory=list)
    specialist_responses: dict[str, list[str]] = field(default_factory=dict)
    is_active: bool = True

    def add_message(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content})

    def add_specialist_response(self, spec_id: str, response: str) -> None:
        if spec_id not in self.specialist_responses:
            self.specialist_responses[spec_id] = []
        self.specialist_responses[spec_id].append(response)
        self.add_message(SPECIALIST_NAMES.get(spec_id, spec_id), response)

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
# SPECIALIST SPEAKER – TTS + áudio publicado no room
# ============================================================

class SpecialistSpeaker:
    """
    Gerencia a conexão e publicação de áudio TTS de um especialista.
    Cada especialista entra no room com sua própria identidade (participante separado).
    """

    def __init__(self, spec_id: str, room: rtc.Room) -> None:
        self._spec_id = spec_id
        self._room = room
        self._voice = AGENT_VOICES[spec_id]
        self._name = SPECIALIST_NAMES[spec_id]
        self._audio_source: Optional[rtc.AudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._speak_lock = asyncio.Lock()

    async def setup(self) -> None:
        """Cria AudioSource e publica track de áudio no room."""
        self._audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            f"audio-{self._spec_id}", self._audio_source
        )
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self._room.local_participant.publish_track(self._audio_track, options)
        logger.info(f"[{self._name}] Track de áudio publicado.")

    async def speak(self, text: str) -> float:
        """Gera TTS com voz própria, publica no room e retorna duração em segundos."""
        async with self._speak_lock:
            try:
                logger.info(f"[{self._name}] Gerando TTS ({len(text)} chars)...")
                audio_bytes = await self._generate_tts(text)
                logger.info(f"[{self._name}] TTS gerado: {len(audio_bytes)} bytes")
                await self._publish_pcm_audio(audio_bytes)
                # PCM 16-bit 24kHz mono → 2 bytes/sample × 24000 samples/s
                duration = len(audio_bytes) / (24000 * 2)
                return duration
            except Exception as e:
                logger.error(f"[{self._name}] Erro no TTS: {e}", exc_info=True)
                return 0.0

    async def _generate_tts(self, text: str) -> bytes:
        """Chama a API Gemini TTS e retorna áudio PCM 16-bit, 24kHz, mono."""
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        response = await client.aio.models.generate_content(
            model=GEMINI_TTS_MODEL,
            contents=text,
            config=genai_types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=genai_types.SpeechConfig(
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=self._voice
                        )
                    )
                ),
            ),
        )
        raw = response.candidates[0].content.parts[0].inline_data.data
        # A API retorna base64-encoded PCM
        if isinstance(raw, str):
            return base64.b64decode(raw)
        return bytes(raw)

    async def _publish_pcm_audio(self, audio_bytes: bytes, sample_rate: int = 24000) -> None:
        """Publica bytes PCM 16-bit como AudioFrame no LiveKit."""
        if not self._audio_source:
            logger.warning(f"[{self._name}] AudioSource não inicializado.")
            return
        # 16-bit PCM → 2 bytes por sample
        num_samples = len(audio_bytes) // 2
        if num_samples == 0:
            logger.warning(f"[{self._name}] Áudio PCM vazio, nada a publicar.")
            return
        # Criar AudioFrame passando os bytes diretamente ao construtor (evita erro de memoryview)
        frame = rtc.AudioFrame(
            data=audio_bytes,
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=num_samples,
        )
        await self._audio_source.capture_frame(frame)
        logger.info(f"[{self._name}] Áudio publicado: {num_samples} samples ({num_samples/sample_rate:.2f}s)")


# ============================================================
# HOST AGENT – Nathália orquestra os especialistas
# ============================================================

class HostAgent(Agent):
    """
    Nathália – usa Google RealtimeModel (Gemini Live) para STT+LLM+TTS.
    Aciona especialistas via function tools.
    """

    def __init__(
        self,
        blackboard: Blackboard,
        specialist_speakers: dict[str, SpecialistSpeaker],
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
        self._specialist_speakers = specialist_speakers
        self._room = room

    # ------ function tools ------

    @function_tool
    async def acionar_carlos_cfo(self, context: RunContext, questao: str) -> str:
        """Aciona Carlos (CFO) para dar análise financeira.
        Use quando o usuário precisar de análise financeira, custos, receita ou precificação.

        Args:
            questao: Pergunta ou contexto específico para Carlos analisar.
        """
        return await self._call_specialist("cfo", questao)

    @function_tool
    async def acionar_daniel_advogado(self, context: RunContext, questao: str) -> str:
        """Aciona Daniel (Advogado) para dar orientação jurídica.
        Use quando o usuário precisar de orientação legal, contratos, LGPD ou estrutura societária.

        Args:
            questao: Pergunta ou contexto específico para Daniel analisar.
        """
        return await self._call_specialist("legal", questao)

    @function_tool
    async def acionar_rodrigo_cmo(self, context: RunContext, questao: str) -> str:
        """Aciona Rodrigo (CMO) para dar estratégia de marketing.
        Use quando o usuário precisar de marketing, vendas, branding ou aquisição de clientes.

        Args:
            questao: Pergunta ou contexto específico para Rodrigo analisar.
        """
        return await self._call_specialist("cmo", questao)

    @function_tool
    async def acionar_ana_cto(self, context: RunContext, questao: str) -> str:
        """Aciona Ana (CTO) para dar orientação técnica.
        Use quando o usuário precisar de tecnologia, arquitetura, stack ou infraestrutura.

        Args:
            questao: Pergunta ou contexto específico para Ana analisar.
        """
        return await self._call_specialist("cto", questao)

    @function_tool
    async def debate_completo(self, context: RunContext, tema: str) -> str:
        """Inicia debate com TODOS os especialistas sobre o tema apresentado.
        Use quando o usuário apresentar um projeto novo que precisa de visão multidisciplinar.

        Args:
            tema: Tema ou projeto para debate completo.
        """
        self._blackboard.user_query = tema
        results: list[str] = []
        for spec_id in ["cfo", "legal", "cmo", "cto"]:
            result = await self._call_specialist(spec_id, tema)
            results.append(result)
            await asyncio.sleep(0.5)
        return "Debate completo realizado com todos os especialistas."

    @function_tool
    async def gerar_plano_execucao(self, context: RunContext) -> str:
        """Encerra a sessão e aciona Marco para gerar o Plano de Execução detalhado.
        Use quando o usuário estiver satisfeito e quiser encerrar, ou pedir o plano final.
        """
        self._blackboard.is_active = False
        full_transcript = self._blackboard.get_full_transcript()
        asyncio.create_task(self._generate_and_speak_plan(full_transcript))
        return "Marco está elaborando e apresentando seu Plano de Execução agora. Aguarde um momento."

    # ------ internals ------

    async def _call_specialist(self, spec_id: str, questao: str) -> str:
        """Gera a resposta do especialista via LLM e faz ele falar com voz própria."""
        context_summary = self._blackboard.get_context_summary()
        if questao:
            context_summary += f"\n\nQuestão específica: {questao}"

        prompt = SPECIALIST_PROMPTS[spec_id].format(context=context_summary)
        spec_llm = google_plugin.LLM(model=GEMINI_CHAT_MODEL, temperature=0.7)

        chat_ctx = llm.ChatContext()
        chat_ctx.append(role="system", text=prompt)
        chat_ctx.append(
            role="user",
            text=questao or self._blackboard.user_query or "Analise o projeto e dê sua contribuição.",
        )

        response_text = ""
        async for chunk in spec_llm.chat(chat_ctx=chat_ctx):
            if chunk.choices and chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content

        if not response_text.strip():
            response_text = "Preciso de mais informações para analisar este ponto."

        self._blackboard.add_specialist_response(spec_id, response_text)

        name = SPECIALIST_NAMES[spec_id]
        await self._publish_transcript(name, response_text)

        speaker = self._specialist_speakers.get(spec_id)
        if speaker:
            asyncio.create_task(speaker.speak(response_text))

        logger.info(f"[{name}] {response_text[:120]}...")
        return f"{name}: {response_text[:300]}"

    async def _generate_and_speak_plan(self, full_transcript: str) -> None:
        """Gera o plano de execução via Gemini e faz Marco apresentá-lo."""
        try:
            prompt = SPECIALIST_PROMPTS["plan"].format(context=full_transcript)
            plan_llm = google_plugin.LLM(model=GEMINI_CHAT_MODEL, temperature=0.3)

            chat_ctx = llm.ChatContext()
            chat_ctx.append(role="system", text=prompt)
            chat_ctx.append(
                role="user",
                text="Por favor, apresente o Plano de Execução completo agora.",
            )

            plan_text = ""
            async for chunk in plan_llm.chat(chat_ctx=chat_ctx):
                if chunk.choices and chunk.choices[0].delta.content:
                    plan_text += chunk.choices[0].delta.content

            if not plan_text.strip():
                plan_text = "Não foi possível gerar o plano de execução. Por favor, solicite novamente."

            self._blackboard.add_message("Marco (Estrategista)", plan_text)
            await self._publish_transcript("Marco (Estrategista)", plan_text)

            marco = self._specialist_speakers.get("plan")
            if marco:
                await marco.speak(plan_text)

            # Envia plano completo ao frontend
            payload = json.dumps({
                "type": "execution_plan",
                "speaker": "Marco",
                "plan": plan_text,
                "transcript": full_transcript,
            }).encode()
            await self._room.local_participant.publish_data(payload, reliable=True)

            logger.info(f"[Marco] Plano de execução gerado ({len(plan_text)} chars).")
        except Exception as e:
            logger.error(f"[Marco] Erro ao gerar plano: {e}")

    async def _publish_transcript(self, speaker: str, text: str) -> None:
        try:
            payload = json.dumps({"type": "transcript", "speaker": speaker, "text": text}).encode()
            await self._room.local_participant.publish_data(payload, reliable=True)
        except Exception as e:
            logger.warning(f"Erro ao publicar transcrição: {e}")


# ============================================================
# ENTRYPOINT
# ============================================================

async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"Iniciando worker – sala: {ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    blackboard = Blackboard(project_name=ctx.room.name)

    # URL do servidor LiveKit (para conexões adicionais dos especialistas)
    try:
        ws_url: str = ctx._info.url  # type: ignore[attr-defined]
    except AttributeError:
        ws_url = os.getenv("LIVEKIT_URL", os.getenv("NEXT_PUBLIC_LIVEKIT_URL", ""))

    # ========================================
    # CONECTAR E PREPARAR ESPECIALISTAS
    # ========================================

    specialist_speakers: dict[str, SpecialistSpeaker] = {}

    lk_api_key = os.getenv("LIVEKIT_API_KEY", "")
    lk_api_secret = os.getenv("LIVEKIT_API_SECRET", "")

    for spec_id in ["cfo", "legal", "cmo", "cto", "plan"]:
        try:
            token = (
                api.AccessToken(lk_api_key, lk_api_secret)
                .with_identity(f"agent-{spec_id}")
                .with_name(SPECIALIST_NAMES[spec_id])
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=ctx.room.name,
                        can_publish=True,
                        can_subscribe=False,
                    )
                )
                .to_jwt()
            )

            spec_room = rtc.Room()
            await spec_room.connect(ws_url, token)

            speaker = SpecialistSpeaker(spec_id, spec_room)
            await speaker.setup()
            specialist_speakers[spec_id] = speaker

            logger.info(f"[{SPECIALIST_NAMES[spec_id]}] Conectado e pronto.")

        except Exception as exc:
            logger.error(f"Erro ao conectar especialista {spec_id}: {exc}")

    # ========================================
    # HOST – Nathália
    # ========================================

    host_agent = HostAgent(blackboard, specialist_speakers, ctx.room)
    host_session = AgentSession(
        vad=silero.VAD.load(),
    )

    # Transcrição do usuário → blackboard + frontend
    @host_session.on("user_input_transcribed")
    def _on_user_speech(event) -> None:  # type: ignore[no-untyped-def]
        if not getattr(event, "is_final", True):
            return
        text: str = getattr(event, "transcript", "")
        if not text:
            return
        blackboard.add_message("Usuário", text)
        blackboard.user_query = text
        logger.info(f"[USUÁRIO] {text[:120]}")
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Você", "text": text}).encode(),
                reliable=True,
            )
        )

    # Fala da host → blackboard + frontend
    @host_session.on("conversation_item_added")
    def _on_host_speech(event) -> None:  # type: ignore[no-untyped-def]
        item = getattr(event, "item", None)
        if item is None:
            return
        role = getattr(item, "role", None)
        if role != "assistant":
            return
        # Tenta extrair texto via text_content (propriedade do ChatMessage)
        content = ""
        if hasattr(item, "text_content") and item.text_content:
            content = item.text_content
        else:
            raw_content = getattr(item, "content", "")
            if isinstance(raw_content, list):
                content = " ".join(str(c) for c in raw_content if c and not isinstance(c, bytes))
            elif isinstance(raw_content, str):
                content = raw_content
        if not content or not content.strip():
            return
        blackboard.add_message("Nathália (Apresentadora)", content)
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "transcript", "speaker": "Nathália", "text": content}).encode(),
                reliable=True,
            )
        )

    # Mensagens de dados do frontend
    # Assinatura correta para livekit-python 1.x: (data, participant, kind, topic)
    @ctx.room.on("data_received")
    def _on_data_received(data: bytes, participant=None, kind=None, topic=None) -> None:  # type: ignore[no-untyped-def]
        try:
            raw = bytes(data) if isinstance(data, (bytes, bytearray, memoryview)) else b""
            if not raw:
                return
            msg = json.loads(raw.decode())
            logger.info(f"Dados recebidos do frontend: {msg.get('type')}")
            if msg.get("type") == "end_session":
                blackboard.is_active = False
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        json.dumps({
                            "type": "session_end",
                            "transcript": blackboard.get_full_transcript(),
                        }).encode(),
                        reliable=True,
                    )
                )
        except Exception as e:
            logger.warning(f"Erro ao processar dados: {e}")

    # ========================================
    # DESCOBRIR NOME DO USUÁRIO
    # ========================================

    def _get_user_name() -> str:
        """Retorna o primeiro nome do participante humano na sala."""
        for participant in ctx.room.remote_participants.values():
            identity = participant.identity or ""
            name = participant.name or ""
            # Pula participantes agentes (identidade começa com "agent-")
            if not identity.startswith("agent-"):
                first_name = name.split()[0] if name.strip() else "amigo"
                return first_name
        return "amigo"

    # Se o usuário ainda não entrou, aguarda até 10s
    user_name = _get_user_name()
    if user_name == "amigo":
        try:
            user_joined = asyncio.Event()

            @ctx.room.once("participant_connected")
            def _on_first_participant(participant: rtc.RemoteParticipant) -> None:  # type: ignore[no-untyped-def]
                if not participant.identity.startswith("agent-"):
                    user_joined.set()

            await asyncio.wait_for(user_joined.wait(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            pass
        user_name = _get_user_name()

    blackboard.project_name = f"Sessão de {user_name}"
    logger.info(f"Usuário identificado: {user_name}")

    # ========================================
    # INICIAR SESSÃO DA HOST
    # ========================================

    await host_session.start(agent=host_agent, room=ctx.room)

    # ========================================
    # SEQUÊNCIA DE BOAS-VINDAS E APRESENTAÇÕES
    # ========================================

    async def run_introductions() -> None:
        """Nathália cumprimenta pelo nome e pede a cada especialista que se apresente."""

        # 1 – Nathália abre a sessão saudando o usuário pelo nome
        greeting = (
            f"Olá, {user_name}! Seja muito bem-vindo ao Mentoria AI! "
            "Eu sou a Nathália, sua apresentadora e guia durante toda essa sessão. "
            f"É uma honra ter você aqui, {user_name}! "
            "Hoje você vai contar com um time de cinco especialistas prontos para ajudar a transformar seu projeto em realidade. "
            "Vou pedir que cada um se apresente pessoalmente para você. "
            "Carlos, pode começar?"
        )
        await host_session.say(greeting, allow_interruptions=False)
        await asyncio.sleep(1.0)

        # 2 – Cada especialista se apresenta com sua própria voz, em sequência
        intro_order = [
            ("cfo",   "Daniel, é a sua vez!"),
            ("legal", "Rodrigo, pode se apresentar!"),
            ("cmo",   "Ana, apresente-se por favor!"),
            ("cto",   "E por último, Marco!"),
            ("plan",  None),
        ]

        for idx, (spec_id, next_prompt) in enumerate(intro_order):
            speaker = specialist_speakers.get(spec_id)
            if speaker:
                intro_text = SPECIALIST_INTROS[spec_id]
                # Publica transcrição da apresentação no frontend
                try:
                    payload = json.dumps({
                        "type": "transcript",
                        "speaker": SPECIALIST_NAMES[spec_id],
                        "text": intro_text,
                    }).encode()
                    await ctx.room.local_participant.publish_data(payload, reliable=True)
                except Exception:
                    pass
                duration = await speaker.speak(intro_text)
                # Aguarda o áudio terminar + pequena pausa entre apresentações
                await asyncio.sleep(max(duration, 1.0) + 0.8)

            # Nathália faz a ponte para o próximo (exceto depois do último)
            if next_prompt:
                await host_session.say(next_prompt, allow_interruptions=False)
                await asyncio.sleep(0.8)

        # 3 – Nathália fecha o round de apresentações e convida o usuário a falar
        closing = (
            f"Que time incrível, não é mesmo, {user_name}? "
            "Agora é a sua vez! Conta para a gente: qual é o seu projeto ou desafio empresarial? "
            "Estamos todos aqui para te ouvir e ajudar!"
        )
        await host_session.say(closing, allow_interruptions=True)

        logger.info("Sequência de apresentações concluída.")

    asyncio.create_task(run_introductions())

    logger.info("Sessão de mentoria iniciada com sucesso.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
