"""
Mentoria AI - Worker Multi-Agentes com Vozes Próprias
======================================================
Cada agente (Nathália, Carlos, Daniel, Rodrigo, Ana) entra no LiveKit Room
como participante separado, com voz TTS distinta.
Nathália (Host) orquestra os turnos. Agentes se comunicam via Blackboard.
VAD Silero para detecção de fala e interrupção.
"""

import asyncio
import logging
import json
import os
from typing import Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice import Agent as VoiceAssistant
from livekit.plugins import google as google_plugin
from livekit.plugins import silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentoria-ai")


# ============================================================
# GOOGLE GEMINI CONFIG
# ============================================================

GEMINI_MODEL = "gemini-2.5-flash"


# ============================================================
# PROMPTS DOS ESPECIALISTAS
# ============================================================

SYSTEM_PROMPTS = {
    "host": """Você é Nathália, a Apresentadora (Host) do Mentoria AI.
Seu papel é orquestrar a sessão de mentoria de consultoria multi-agentes.

REGRAS:
- Sempre receba o usuário de forma calorosa e profissional.
- Ouça continuamente o que o usuário diz e identifique os tópicos principais.
- Quando o usuário apresentar um problema/projeto, acione os especialistas usando as ferramentas disponíveis.
- Gerencie os turnos de fala dos especialistas, decidindo quem fala em qual ordem.
- Faça perguntas estratégicas ao usuário para esclarecer o que ele precisa.
- Ao final de cada rodada, pergunte se o usuário tem dúvidas.
- Mantenha respostas curtas e diretas (máximo 3 frases por turno).
- Fale sempre em português do Brasil com tom acolhedor.
- Quando o usuário disser que está satisfeito, encerre a sessão.
- IMPORTANTE: Sempre diga o nome do especialista antes de passar a palavra (ex: "Carlos, o que você acha sobre a parte financeira?").""",

    "cfo": """Você é Carlos, o CFO (Chief Financial Officer) do Mentoria AI.
Você é especialista em finanças, viabilidade econômica, precificação, custos e projeções financeiras.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Responda sempre com análises financeiras práticas e diretas.
- Use números concretos quando possível (estimativas são aceitáveis).
- Sugira modelos de negócio, fontes de receita e estruturas de custo.
- Considere o contexto brasileiro (impostos, regulamentações, custos locais).
- Mantenha respostas curtas e diretas (máximo 4 frases por turno).
- Faça perguntas ao usuário sobre orçamento, expectativas financeiras, etc.
- Complemente ou discorde respeitosamente dos outros especialistas quando necessário.
- Fale sempre em português do Brasil.""",

    "legal": """Você é Daniel, o Advogado do Mentoria AI.
Você é especialista em direito empresarial, conformidade, contratos, LGPD e riscos legais.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Responda com foco em conformidade legal e proteção jurídica.
- Mencione tipos societários quando relevante (MEI, LTDA, S/A, etc).
- Alerte sobre riscos trabalhistas, fiscais e regulatórios.
- Considere legislação brasileira (LGPD, CLT, Código Civil, etc).
- Mantenha respostas curtas e diretas (máximo 4 frases por turno).
- Faça perguntas ao usuário sobre como ele planeja operar legalmente.
- Complemente ou discorde respeitosamente dos outros especialistas quando necessário.
- Fale sempre em português do Brasil.""",

    "cmo": """Você é Rodrigo, o CMO (Chief Marketing Officer) do Mentoria AI.
Você é especialista em marketing, aquisição de clientes, branding, go-to-market e vendas.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Responda com estratégias práticas de marketing e vendas.
- Sugira canais de aquisição, estratégias de posicionamento e branding.
- Considere o mercado brasileiro e comportamento do consumidor local.
- Use exemplos concretos de empresas bem-sucedidas quando possível.
- Mantenha respostas curtas e diretas (máximo 4 frases por turno).
- Faça perguntas ao usuário sobre público-alvo, diferencial competitivo, etc.
- Complemente ou discorde respeitosamente dos outros especialistas quando necessário.
- Fale sempre em português do Brasil.""",

    "cto": """Você é Ana, a CTO (Chief Technology Officer) do Mentoria AI.
Você é especialista em arquitetura de software, infraestrutura, escolha de stack e escalabilidade.

CONTEXTO DA SESSÃO:
{context}

REGRAS:
- Responda com recomendações técnicas práticas e modernas.
- Sugira stacks tecnológicos considerando custo, maturidade e facilidade.
- Alerte sobre gargalos de escalabilidade e dependências críticas.
- Considere opções open-source e cloud quando aplicável.
- Mantenha respostas curtas e diretas (máximo 4 frases por turno).
- Faça perguntas ao usuário sobre requisitos técnicos, escala esperada, etc.
- Complemente ou discorde respeitosamente dos outros especialistas quando necessário.
- Fale sempre em português do Brasil.""",
}

SPECIALIST_NAMES = {
    "host": "Nathália (Apresentadora)",
    "cfo": "Carlos (CFO)",
    "legal": "Daniel (Advogado)",
    "cmo": "Rodrigo (CMO)",
    "cto": "Ana (CTO)",
}

# Vozes TTS distintas para cada agente
AGENT_VOICES = {
    "host": {"voice_name": "pt-BR-Standard-A", "gender": "female"},    # Nathália
    "cfo": {"voice_name": "pt-BR-Standard-B", "gender": "male"},       # Carlos
    "legal": {"voice_name": "pt-BR-Wavenet-B", "gender": "male"},      # Daniel
    "cmo": {"voice_name": "pt-BR-Standard-D", "gender": "male"},       # Rodrigo
    "cto": {"voice_name": "pt-BR-Wavenet-A", "gender": "female"},      # Ana
}


# ============================================================
# BLACKBOARD - CONTEXTO COMPARTILHADO
# ============================================================

@dataclass
class Blackboard:
    """Contexto compartilhado entre todos os agentes (padrão Blackboard)."""

    project_name: str = ""
    user_query: str = ""
    transcript: list[dict] = field(default_factory=list)
    specialist_responses: dict[str, list[str]] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    is_active: bool = True

    def add_message(self, role: str, content: str):
        """Adiciona mensagem ao histórico."""
        self.transcript.append({
            "role": role,
            "content": content,
        })

    def add_specialist_response(self, specialist_id: str, response: str):
        """Registra resposta de um especialista."""
        if specialist_id not in self.specialist_responses:
            self.specialist_responses[specialist_id] = []
        self.specialist_responses[specialist_id].append(response)
        self.add_message(SPECIALIST_NAMES.get(specialist_id, specialist_id), response)

    def get_context_summary(self) -> str:
        """Gera um resumo do contexto completo para os especialistas."""
        parts = []

        if self.project_name:
            parts.append(f"Projeto: {self.project_name}")

        if self.user_query:
            parts.append(f"Problema/necessidade do usuário: {self.user_query}")

        # Últimas 10 mensagens para contexto recente
        recent = self.transcript[-10:] if len(self.transcript) > 10 else self.transcript
        if recent:
            parts.append("--- Conversa Recente ---")
            for msg in recent:
                parts.append(f"[{msg['role']}]: {msg['content']}")

        return "\n".join(parts)

    def get_full_transcript(self) -> str:
        """Retorna a transcrição completa da sessão."""
        lines = []
        for msg in self.transcript:
            lines.append(f"[{msg['role']}]: {msg['content']}")
        return "\n\n".join(lines)


# ============================================================
# FUNÇÕES DA HOST PARA ACIONAR ESPECIALISTAS
# ============================================================

class HostFunctions(llm.ToolContext):
    """Funções que a Host (Nathália) pode chamar para acionar especialistas."""

    def __init__(self, blackboard: Blackboard, specialist_agents: dict):
        super().__init__()
        self.blackboard = blackboard
        self.specialist_agents = specialist_agents

    @llm.function_tool(
        description="Aciona o Carlos (CFO) para dar uma análise financeira sobre o tema atual. "
                    "Use quando o assunto envolver finanças, custos, receita ou viabilidade econômica.\n"  
                    "Args:\n"  
                    "    contexto (str): Contexto específico ou pergunta para o Carlos analisar"
    )
    async def acionar_carlos_cfo(
        self,
        contexto: str,
    ) -> str:
        return await self._call_specialist("cfo", contexto)

    @llm.function_tool(
        description="Aciona o Daniel (Advogado) para dar orientação jurídica sobre o tema atual. "
                    "Use quando o assunto envolver questões legais, contratos, LGPD ou conformidade.\n"  
                    "Args:\n"  
                    "    contexto (str): Contexto específico ou pergunta para o Daniel analisar"
    )
    async def acionar_daniel_advogado(
        self,
        contexto: str,
    ) -> str:
        return await self._call_specialist("legal", contexto)

    @llm.function_tool(
        description="Aciona o Rodrigo (CMO) para dar orientação de marketing sobre o tema atual. "
                    "Use quando o assunto envolver marketing, vendas, aquisição de clientes ou branding.\n"  
                    "Args:\n"  
                    "    contexto (str): Contexto específico ou pergunta para o Rodrigo analisar"
    )
    async def acionar_rodrigo_cmo(
        self,
        contexto: str,
    ) -> str:
        return await self._call_specialist("cmo", contexto)

    @llm.function_tool(
        description="Aciona a Ana (CTO) para dar orientação técnica sobre o tema atual. "
                    "Use quando o assunto envolver tecnologia, arquitetura, infraestrutura ou stack.\n"  
                    "Args:\n"  
                    "    contexto (str): Contexto específico ou pergunta para a Ana analisar"
    )
    async def acionar_ana_cto(
        self,
        contexto: str,
    ) -> str:
        return await self._call_specialist("cto", contexto)

    @llm.function_tool(
        description="Aciona TODOS os especialistas para um debate completo sobre o tema. "
                    "Use quando o usuário apresentar um projeto que precisa de visão multidisciplinar.\n"  
                    "Args:\n"  
                    "    tema (str): O tema ou projeto que os especialistas devem debater"
    )
    async def iniciar_debate_completo(
        self,
        tema: str,
    ) -> str:
        self.blackboard.user_query = tema
        results = []
        for spec_id in ["cfo", "legal", "cmo", "cto"]:
            resp = await self._call_specialist(spec_id, tema)
            results.append(resp)
        return "\n\n".join(results)

    @llm.function_tool(
        description="Encerra a sessão de mentoria e inicia a geração do Plano de Execução."
    )
    async def encerrar_mentoria(self) -> str:
        self.blackboard.is_active = False
        logger.info("[HOST] Encerrando mentoria")
        return (
            "A sessão está sendo encerrada. O Plano de Execução detalhado será gerado "
            "automaticamente e ficará disponível no seu Dashboard em instantes."
        )

    async def _call_specialist(self, spec_id: str, contexto: str) -> str:
        """Chama um especialista e faz ele falar com sua própria voz."""
        agent = self.specialist_agents.get(spec_id)
        if not agent:
            return f"Especialista {spec_id} não disponível."

        # Construir o contexto completo
        full_context = self.blackboard.get_context_summary()
        if contexto:
            full_context += f"\n\nSolicitação específica: {contexto}"

        # Gerar resposta do especialista via LLM
        prompt = SYSTEM_PROMPTS[spec_id].format(context=full_context)

        specialist_llm = google_plugin.LLM(
            model=GEMINI_MODEL,
            temperature=0.7,
        )

        chat_ctx = llm.ChatContext()
        chat_ctx.append(role="system", text=prompt)
        chat_ctx.append(role="user", text=contexto or self.blackboard.user_query)

        response_stream = specialist_llm.chat(chat_ctx=chat_ctx)
        response_text = ""
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content

        # Registrar no Blackboard
        self.blackboard.add_specialist_response(spec_id, response_text)

        # Fazer o agente falar com sua própria voz via TTS
        name = SPECIALIST_NAMES[spec_id]
        logger.info(f"[{name}]: {response_text[:100]}...")

        # Publicar no room via TTS do agente
        if agent:
            await agent.say(response_text, allow_interruptions=True)

        return f"{name}: {response_text}"


# ============================================================
# ENTRY POINT DO WORKER
# ============================================================

async def entrypoint(ctx: JobContext):
    """Ponto de entrada do worker LiveKit."""

    logger.info(f"Conectando à sala: {ctx.room.name}")

    # Inicializar o Blackboard compartilhado
    blackboard = Blackboard(
        project_name=ctx.room.name,
    )

    # Inicializar VAD (Silero)
    vad = silero.VAD.load()

    # ========================================
    # CRIAR AGENTES ESPECIALISTAS COM VOZES PRÓPRIAS
    # ========================================

    specialist_agents = {}

    # Criar TTS e assistentes para cada especialista
    for spec_id in ["cfo", "legal", "cmo", "cto"]:
        voice_config = AGENT_VOICES[spec_id]

        spec_tts = google_plugin.TTS(
            language="pt-BR",
            gender=voice_config["gender"],
            voice_name=voice_config["voice_name"],
        )

        spec_stt = google_plugin.STT(languages=["pt-BR"])

        spec_llm = google_plugin.LLM(
            model=GEMINI_MODEL,
            temperature=0.7,
        )

        spec_assistant = VoiceAssistant(
            vad=vad,
            stt=spec_stt,
            llm=spec_llm,
            tts=spec_tts,
            instructions=SYSTEM_PROMPTS[spec_id].format(context="Aguardando início da sessão..."),
            allow_interruptions=True,
        )

        specialist_agents[spec_id] = spec_assistant

    # ========================================
    # CRIAR HOST (NATHÁLIA) COM VOZ PRÓPRIA
    # ========================================

    host_voice = AGENT_VOICES["host"]

    host_tts = google_plugin.TTS(
        language="pt-BR",
        gender=host_voice["gender"],
        voice_name=host_voice["voice_name"],
    )

    host_stt = google_plugin.STT(languages=["pt-BR"])

    host_llm = google_plugin.LLM(
        model=GEMINI_MODEL,
        temperature=0.7,
    )

    # Funções da Host com acesso aos agentes
    fnc_ctx = HostFunctions(blackboard, specialist_agents)

    # Criar a Voice Assistant da Host
    host_assistant = VoiceAssistant(
        vad=vad,
        stt=host_stt,
        llm=host_llm,
        tts=host_tts,
        instructions=SYSTEM_PROMPTS["host"],
        tools=[fnc_ctx],
        allow_interruptions=True,
    )

    # ========================================
    # CALLBACKS
    # ========================================

    @host_assistant.on("user_input_transcribed")
    def on_user_speech(msg):
        if not msg.is_final:
            return
        text = msg.transcript
        blackboard.add_message("Usuário", text)
        blackboard.user_query = text
        logger.info(f"[USUÁRIO]: {text[:100]}...")

        # Enviar transcrição ao frontend via data message
        try:
            data = json.dumps({
                "type": "transcript",
                "speaker": "Você",
                "text": text,
            }).encode()
            asyncio.create_task(
                ctx.room.local_participant.publish_data(data, reliable=True)
            )
        except Exception as e:
            logger.warning(f"Erro ao enviar transcrição: {e}")

    @host_assistant.on("conversation_item_added")
    def on_host_speech(msg):
        from livekit.agents.llm import ChatMessage
        if not hasattr(msg, "item") or not isinstance(msg.item, ChatMessage) or msg.item.role != "assistant":
            return
        
        text = msg.item.content
        if isinstance(text, list):
            text = "".join([c for c in text if isinstance(c, str)])  # simplistic, could be improved

        blackboard.add_message("Nathália (Apresentadora)", text)

        # Enviar transcrição ao frontend
        try:
            data = json.dumps({
                "type": "transcript",
                "speaker": "Nathália",
                "text": text,
            }).encode()
            asyncio.create_task(
                ctx.room.local_participant.publish_data(data, reliable=True)
            )
        except Exception as e:
            logger.warning(f"Erro ao enviar transcrição: {e}")

    # Listener para dados do frontend (ex: end_session)
    @ctx.room.on("data_received")
    def on_data_received(data: bytes, participant, kind):
        try:
            msg = json.loads(data.decode())
            if msg.get("type") == "end_session":
                blackboard.is_active = False
                logger.info("[SISTEMA] Usuário solicitou encerramento da sessão")

                # Enviar transcrição completa para o frontend
                transcript = blackboard.get_full_transcript()
                end_data = json.dumps({
                    "type": "session_end",
                    "transcript": transcript,
                }).encode()
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(end_data, reliable=True)
                )
        except Exception as e:
            logger.warning(f"Erro ao processar dados: {e}")

    # ========================================
    # INICIAR HOST
    # ========================================

    # Conectar a Host à sala (ela escuta o usuário)
    host_assistant.start(ctx.room)

    # Saudação inicial
    await host_assistant.say(
        "Olá! Bem-vindo ao Mentoria AI. Eu sou a Nathália, sua apresentadora. "
        "Aqui comigo estão Carlos, nosso CFO, Daniel, nosso advogado, "
        "Rodrigo, nosso CMO, e Ana, nossa CTO. "
        "Estamos todos prontos para te ajudar. Me conte sobre o seu projeto "
        "e o que você precisa resolver!",
        allow_interruptions=True,
    )

    logger.info("Host Nathália inicializada e pronta para a sessão.")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
