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

import sys
import os as _os

# ── sys.path guard ─────────────────────────────────────────────────────────────
# Garante que o diretório que contém este arquivo (agents/) esteja no sys.path,
# independentemente de onde o processo é iniciado (ex: "python -m agents.worker"
# a partir da raiz do projeto). Sem isso, os imports lazy de pdf_generator falham.
_agents_dir = _os.path.dirname(_os.path.abspath(__file__))
if _agents_dir not in sys.path:
    sys.path.insert(0, _agents_dir)
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from time import monotonic
from typing import Optional

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception as e:
        DDGS = None  # type: ignore
        import logging as _tmp_log
        _tmp_log.getLogger(__name__).warning(
            f"[worker] ddgs/duckduckgo_search recusou carregar: {e} — ferramenta de internet desativada."
        )

from dotenv import load_dotenv

load_dotenv()

# Usa somente GEMINI_API_KEY e remove GOOGLE_API_KEY do ambiente para evitar
# que a SDK do Google escolha a variável errada e gere warnings ambíguos.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
os.environ.pop("GOOGLE_API_KEY", None)

if not GEMINI_API_KEY:
    logging.getLogger(__name__).warning(
        "[worker] GEMINI_API_KEY não definida. As integrações Gemini podem falhar."
    )


def get_gemini_api_key() -> str:
    return GEMINI_API_KEY

# BEY_API_KEY já está no .env com o nome correto (Beyond Presence SDK lê diretamente)

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

# ── Módulos extraídos (refatoração modular) ──────────────────────────────────
from models import (
    GEMINI_REALTIME_MODEL, GEMINI_REALTIME_CONFIG, DATA_PACKET_SCHEMA_VERSION,
    ACTIVATION_ACK_TIMEOUT_SECONDS, ACTIVATION_DONE_TIMEOUT_SECONDS,
    ACTIVATION_DEBOUNCE_SECONDS, SPECIALIST_GENERATION_TIMEOUT_SECONDS,
    SPECIALIST_SILENCE_TIMEOUT_SECONDS, SPECIALIST_MAX_TURN_TIMEOUT_SECONDS,
    HOST_GENERATE_REPLY_TIMEOUT_SECONDS, CONTEXT_RECENT_WINDOW,
    SPECIALIST_READY_WAIT_SECONDS, AGENT_VOICES, SPECIALIST_NAMES,
    SPECIALIST_IDENTITIES, AVATAR_IDS, SPECIALIST_ORDER, POST_INTRO_WAIT,
    LATERAL_TRANSFER_MAP,
)
from prompts import (
    LANGUAGE_ENFORCEMENT, HOST_PROMPT, SPECIALIST_SYSTEM_PROMPTS,
    SPECIALIST_INTRODUCTIONS,
)
from blackboard import Blackboard, classify_user_handoff_intent, get_specialist_timeout_reason
from marco_strategist import MarcoStrategist

# Import condicional do plugin Beyond Presence (bey)
# Degrada graciosamente se o pacote não estiver instalado.
try:
    from livekit.plugins import bey as bey_plugin  # type: ignore
    BEY_AVAILABLE = bool(os.getenv("BEY_API_KEY", ""))
except ImportError:
    bey_plugin = None  # type: ignore
    BEY_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "[worker] livekit-plugins-bey não encontrado — avatares Beyond Presence desativados. "
        "Instale com: pip install 'livekit-agents[bey]~=1.4'"
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mentoria-ai")

# Silenciar a telemetria interna do SDK (que a Railway confunde com erros)
logging.getLogger("livekit").setLevel(logging.WARNING)
logging.getLogger("root").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)

# ── Filtro anti-flood ──────────────────────────────────────────────────────────
# As mensagens "ignoring byte/text stream" do LiveKit SDK são emitidas centenas
# de vezes por segundo quando múltiplos agentes estão na mesma sala, saturando
# o event loop e impedindo o processamento de áudio/fala. Filtramos aqui.
class _IgnoringStreamFilter(logging.Filter):
    _SUPPRESSED = ("ignoring byte stream", "ignoring text stream")
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SUPPRESSED)

for _handler in logging.root.handlers:
    _handler.addFilter(_IgnoringStreamFilter())
logging.getLogger("root").addFilter(_IgnoringStreamFilter())
# ──────────────────────────────────────────────────────────────────────────────

# Rastreia salas que já possuem um job ativo para rejeitar dispatches duplicados.
_active_rooms: set[str] = set()

async def _safe_publish_data(participant: rtc.LocalParticipant, payload: dict, max_retries: int = 3) -> None:
    """Publica data packets de forma segura com sistema de retries automatizado."""
    data_bytes = json.dumps(payload).encode()
    for attempt in range(max_retries):
        try:
            await participant.publish_data(data_bytes, reliable=True)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                logger.error(f"Falha critica ao publicar data packet {payload.get('type')}: {e}")

async def _query_documents_with_llm(pergunta: str, documentos: list[str]) -> str:
    from google import genai
    from google.genai import types
    
    if not documentos:
        return "Nenhum documento anexado pela empresa."
        
    docs_text = "\n\n---\n\n".join(documentos)
    prompt = (
        f"Você é um assistente de extração de dados. Usando EXCLUSIVAMENTE os documentos fornecidos abaixo, "
        f"responda à pergunta do usuário. Não use conhecimento externo.\n\n"
        f"Pergunta: {pergunta}\n\n"
        f"Documentos:\n{docs_text}\n\n"
        f"Se a informação relacionada à pergunta não estiver explicitamente contida nos documentos, diga claramente que a informação não foi encontrada nos anexos."
    )
    
    try:
        client = genai.Client(api_key=get_gemini_api_key())
        
        def _call_gemini():
            return client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                )
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _call_gemini)
        return response.text.strip()
    except Exception as e:
        logger.error(f"[Docs RAG] Erro ao consultar documentos: {e}")
        return "Erro técnico ao tentar ler os documentos da empresa."


async def _query_transcript_with_llm(pergunta: str, transcript: list[dict]) -> str:
    """
    Busca informações no histórico completo da mentoria (todas as sessões)
    usando o Gemini Flash como motor de extração. Permite que os agentes de voz
    acessem dados de sessões anteriores sem sobrecarregar sua janela de contexto
    de áudio em tempo real.
    """
    from google import genai
    from google.genai import types

    if not transcript:
        return "Nenhum histórico de mentoria encontrado para este projeto."

    # Monta o histórico formatado (limita a ~100k caracteres para caber no contexto do Flash)
    formatted_lines = []
    for msg in transcript:
        role = msg.get("role", "Desconhecido")
        content = msg.get("content", "")
        if content.strip():
            formatted_lines.append(f"[{role}]: {content}")
    
    full_history = "\n".join(formatted_lines)
    # Limita para não ultrapassar o contexto do modelo
    if len(full_history) > 100000:
        full_history = full_history[-100000:]

    prompt = (
        f"Você é um assistente de memória de longo prazo de uma sessão de mentoria empresarial. "
        f"Abaixo está o HISTÓRICO COMPLETO de todas as sessões de mentoria deste projeto. "
        f"Usando EXCLUSIVAMENTE este histórico, responda à pergunta de forma precisa e detalhada.\n\n"
        f"Pergunta: {pergunta}\n\n"
        f"--- HISTÓRICO COMPLETO DA MENTORIA ---\n{full_history}\n--- FIM DO HISTÓRICO ---\n\n"
        f"Se a informação não estiver no histórico, diga claramente que não encontrou registros sobre o tema nas sessões anteriores. "
        f"Responda em português brasileiro de forma concisa mas completa."
    )

    try:
        client = genai.Client(api_key=get_gemini_api_key())

        def _call_gemini():
            return client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=2000,
                )
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _call_gemini)
        return response.text.strip()
    except Exception as e:
        logger.error(f"[Histórico RAG] Erro ao consultar histórico: {e}")
        return "Erro técnico ao tentar buscar informações no histórico da mentoria."

# ============================================================
# Mapeamento de IDs amigáveis para spec_ids internos (Lateral Transfer)
LATERAL_TRANSFER_MAP: dict[str, str] = {
    "carlos_cfo": "cfo",
    "daniel_advogado": "legal",
    "rodrigo_cmo": "cmo",
    "ana_cto": "cto",
}

class SpecialistAgent(Agent):
    """
    Cada especialista é um Agent independente com RealtimeModel nativo.
    Ele entra no mesmo room com identidade separada e aguarda ser ativado.

    Handover Peer-to-Peer:
    - O especialista conversa livremente com o usuário por múltiplos turnos.
    - Quando o tema se esgota, ele usa `devolver_para_nathalia` para retornar o controle.
    - Opcionalmente, pode usar `transferir_para_especialista` para passar direto a outro colega.
    - Um asyncio.Event (_handover_event) sinaliza o fim do turno para o loop de ativação.
    """

    def __init__(self, spec_id: str, blackboard: Blackboard, marco: MarcoStrategist = None) -> None:
        name = SPECIALIST_NAMES[spec_id]

        super().__init__(
            instructions=SPECIALIST_SYSTEM_PROMPTS[spec_id],
            llm=google_plugin.realtime.RealtimeModel(
                model=GEMINI_REALTIME_MODEL,
                api_key=get_gemini_api_key(),
                voice=AGENT_VOICES[spec_id],
                instructions=(
                    "IDIOMA OBRIGATÓRIO: Você DEVE falar e entender APENAS em português brasileiro (pt-BR). "
                    "Toda entrada de áudio do usuário é em português do Brasil. "
                    "NUNCA interprete como outro idioma. Responda SEMPRE em português do Brasil.\n"
                    "IMPORTANTE: Ignore ruídos (como '<noise>'), suspiros ou falas desconexas que resultam do microfone sempre aberto. Responda apenas se o usuário interagir com propósito."
                ),
                realtime_input_config=genai_types.RealtimeInputConfig(
                    automatic_activity_detection=genai_types.AutomaticActivityDetection(
                        disabled=False,
                        prefix_padding_ms=300,
                        silence_duration_ms=550,
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
        self._marco = marco
        # Handover: evento para sinalizar fim do turno livre
        self._handover_event: asyncio.Event = asyncio.Event()
        # Resultado do handover: "nathalia" ou {"target": spec_id, "context": str}
        self._handover_result: Optional[dict] = None
        # Tamanho do transcript no momento em que este especialista foi ativado.
        # CRÍTICO: garante que a verificação de handoff só considere mensagens
        # recebidas DEPOIS da ativação, nunca mensagens do histórico anterior.
        self._activation_transcript_len: int = 0
        # Conta quantas mensagens do usuário foram recebidas APÓS ativação.
        # Exigimos ao menos 1 mensagem real do usuário antes de permitir handoff.
        self._user_messages_since_activation: int = 0

    @function_tool
    async def consultar_documento_empresa(
        self,
        context: RunContext,
        pergunta: str,
    ) -> str:
        """
        Consulta os documentos e anexos do usuário para responder a uma pergunta.
        Use esta ferramenta sempre que precisar de contexto específico sobre a empresa,
        contratos, relatórios, números ou qualquer arquivo anexado.
        """
        logger.info(f"[{self._name}] Consultando documentos: {pergunta}")
        return await _query_documents_with_llm(pergunta, self._blackboard.documentos_disponiveis)

    @function_tool
    async def consultar_historico_mentoria(
        self,
        context: RunContext,
        pergunta: str,
    ) -> str:
        """
        Busca informações no histórico completo de TODAS as sessões de mentoria deste projeto.
        Use esta ferramenta quando o usuário perguntar sobre algo que foi discutido em sessões
        anteriores, ou quando precisar relembrar decisões, recomendações ou contextos passados.
        Exemplos: "o que conversamos sobre marketing?", "qual foi a recomendação do Daniel?",
        "quanto tempo atrás discutimos o pricing?"

        Parâmetros:
        - pergunta: A pergunta ou tema que deseja buscar no histórico
        """
        logger.info(f"[{self._name}] Consultando histórico da mentoria: {pergunta}")
        return await _query_transcript_with_llm(pergunta, self._blackboard.transcript)

    @function_tool
    async def devolver_para_nathalia(
        self,
        context: RunContext,
        resumo_interacao: str,
    ) -> str:
        """
        Devolve a palavra à Nathália (apresentadora) para que ela retome a condução da sessão.
        Use esta ferramenta SOMENTE quando:
        - O usuário confirmou EXPLICITAMENTE que não tem mais dúvidas com você.
        - O usuário pediu para falar com a Nathália ou mudar completamente de assunto.
        NUNCA use após apenas uma resposta. Aguarde o usuário confirmar o encerramento.
        
        Parâmetros:
        - resumo_interacao: Breve resumo (1-2 frases) do que foi resolvido ou combinado, para contextualizar a Nathália.
        """
        # ── GUARDA 1: O usuário precisa ter enviado ao menos 1 mensagem após ativação ─
        # Isso impede que o especialista retorne antes de ouvir o usuário mesmo uma vez.
        if self._user_messages_since_activation < 1:
            logger.info(
                f"[{self._name}] Devolução BLOQUEADA — usuário ainda não enviou nenhuma "
                f"mensagem desde a ativação. Continuando a conversa."
            )
            return (
                "CONTINUE_COM_USUARIO: o usuário ainda não respondeu nada para você. "
                "Aguarde a fala do usuário. Termine sua resposta com uma pergunta direta "
                "para engajá-lo na conversa."
            )

        # ── GUARDA 2: Só verifica mensagens APÓS a ativação deste especialista ────────
        # CRÍTICO: ignorar o histórico anterior evita o bug onde "entendi" dito à Nathália
        # antes da ativação libera o handoff prematuramente.
        messages_since_activation = self._blackboard.transcript[self._activation_transcript_len:]
        user_messages_since = [
            m for m in messages_since_activation if m.get("role") == "Usuário"
        ]

        last_user_message = (
            user_messages_since[-1].get("content", "").strip()
            if user_messages_since else ""
        )
        handoff_reason = classify_user_handoff_intent(last_user_message)

        if not handoff_reason:
            logger.info(
                f"[{self._name}] Devolução BLOQUEADA — última mensagem do usuário desde ativação "
                f"não indica encerramento: '{last_user_message[:80] or '<vazia>'}'. "
                f"Mensagens do usuário desde ativação: {len(user_messages_since)}."
            )
            return (
                "CONTINUE_COM_USUARIO: o usuário ainda não confirmou explicitamente "
                "que não tem mais dúvidas com você. Continue ajudando na sua área, "
                "aprofunde a resposta e termine com uma pergunta objetiva de acompanhamento. "
                "Somente devolva quando o usuário disser claramente que terminou."
            )

        logger.info(
            f"[{self._name}] ✅ Handoff aprovado → Nathália. "
            f"Motivo: {handoff_reason} | Última fala: '{last_user_message[:60]}'"
        )
        self._blackboard.add_message(self._name, f"Pronto, Nathália! Pode continuar. Resumo do meu atendimento: {resumo_interacao}")
        self._handover_result = {
            "type": "nathalia",
            "reason": handoff_reason,
            "last_user_message": last_user_message,
            "summary": resumo_interacao,
        }
        self._handover_event.set()
        return "Palavra devolvida à Nathália com sucesso. Aguarde em silêncio absoluto."

    @function_tool
    async def transferir_para_especialista(
        self,
        context: RunContext,
        colega_id: str,
        contexto_pergunta: str,
    ) -> str:
        """
        Transfere a palavra diretamente para outro especialista da equipe SEM passar pela Nathália.
        Use SOMENTE quando o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro colega
        E você já respondeu sua parte.
        ANTES de usar esta ferramenta, FALE em voz alta para o usuário que vai repassar.

        Parâmetros:
        - colega_id: ID do colega destino. Valores válidos: carlos_cfo, daniel_advogado, rodrigo_cmo, ana_cto
        - contexto_pergunta: a pergunta ou contexto que deve ser repassado ao colega
        """
        target_spec_id = LATERAL_TRANSFER_MAP.get(colega_id)
        if not target_spec_id:
            return f"ID de colega inválido: {colega_id}. Use carlos_cfo, daniel_advogado, rodrigo_cmo ou ana_cto."

        # Guarda: ao menos 1 mensagem do usuário deve ter sido recebida após ativação
        if self._user_messages_since_activation < 1:
            logger.info(
                f"[{self._name}] Transferência BLOQUEADA para {colega_id} — "
                f"usuário ainda não respondeu nada desde a ativação."
            )
            return (
                f"CONTINUE_COM_USUARIO: você ainda não ouviu o usuário responder nada. "
                f"Aguarde a resposta do usuário antes de transferir para {SPECIALIST_NAMES.get(target_spec_id, colega_id)}."
            )

        target_name = SPECIALIST_NAMES.get(target_spec_id, colega_id)
        logger.info(
            f"[{self._name}] ✅ Transferência lateral para {target_name}. "
            f"Contexto: {contexto_pergunta[:100]}"
        )
        self._blackboard.add_message("Sistema", f"{self._name} transferiu a palavra para {target_name}.")
        self._handover_result = {
            "type": "transfer",
            "target": target_spec_id,
            "context": contexto_pergunta,
            "from_name": self._name,
        }
        self._handover_event.set()
        return f"Transferência para {target_name} registrada. Aguarde em silêncio absoluto."

    # ------------------------------------------------------------------
    # FERRAMENTAS DO MARCO → Delegação ao MarcoStrategist
    # ------------------------------------------------------------------

    async def gerar_plano_forcado(self, user_name: str, project_name: str):
        """Aciona a geração do Plano de Execução pelo Marco (non-blocking via ProcessPool)."""
        self._blackboard.marco_triggered = True
        logger.info("[Marco] Delegando geração do Plano ao ProcessPool via MarcoStrategist...")
        if self._marco: await self._marco.gerar_plano_execucao(user_name, project_name)

    @function_tool
    async def gerar_plano_execucao(
        self,
        context: RunContext,
    ) -> str:
        """
        Aciona Marco (Estrategista) nos bastidores para gerar o Plano de Execução final.
        Use quando o usuário quiser encerrar a sessão ou solicitar um plano estruturado.
        Marco não fala — ele trabalha silenciosamente e envia o documento.
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        asyncio.create_task(self.gerar_plano_forcado(user_name, project_name))

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco nos bastidores. ELE JÁ ESTA TRABALHANDO no Plano de Execução para {user_name}. "
            f"Gere UMA NOVA FALA AVISANDO O USUÁRIO: diga exatamente que o Marco começou a redigir o plano nos bastidores, "
            f"fazendo pesquisas e em instantes chegará pronto na tela dele. Seja natural."
        )

    @function_tool
    async def gerar_documento_personalizado(
        self,
        context: RunContext,
        tipo_documento: str,
        descricao_contexto: str,
    ) -> str:
        """
        Aciona o Marco (bastidores) para gerar um documento empresarial personalizado.
        Use quando o usuário solicitar qualquer um destes documentos:
        - 'swot': Análise SWOT estratégica completa
        - 'canvas': Business Model Canvas (9 blocos)
        - 'proposta_comercial': Proposta comercial profissional
        - 'pesquisa_mercado': Relatório de pesquisa de mercado

        Parâmetros:
        - tipo_documento: Tipo do documento. Valores: swot, canvas, proposta_comercial, pesquisa_mercado
        - descricao_contexto: Contexto adicional sobre o que o usuário quer no documento
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"
        tipo_lower = tipo_documento.lower().strip().replace(" ", "_")

        tipo_map = {
            "swot": "swot",
            "analise_swot": "swot",
            "canvas": "canvas",
            "business_model_canvas": "canvas",
            "proposta": "proposta_comercial",
            "proposta_comercial": "proposta_comercial",
            "pesquisa": "pesquisa_mercado",
            "pesquisa_mercado": "pesquisa_mercado",
        }
        doc_type = tipo_map.get(tipo_lower, tipo_lower)

        titulos = {
            "swot": "Análise SWOT Estratégica",
            "canvas": "Business Model Canvas",
            "proposta_comercial": "Proposta Comercial",
            "pesquisa_mercado": "Pesquisa de Mercado",
        }
        doc_title = titulos.get(doc_type, tipo_documento.replace("_", " ").title())

        async def _bg():
            if self._marco: await self._marco.gerar_documento_personalizado(
                doc_type=doc_type, doc_title=doc_title,
                user_name=user_name, project_name=project_name,
                extra_context=descricao_contexto,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você acionou o Marco para preparar: {doc_title}. "
            f"Diga que ele já esta pesquisando e gerando o PDF nos bastidores e em instantes chegará para {user_name}."
        )

    @function_tool
    async def pesquisar_mercado_setor(
        self,
        context: RunContext,
        setor: str,
        pergunta_especifica: str,
    ) -> str:
        """
        Aciona o Marco para pesquisar dados de mercado em tempo real sobre um setor específico.
        Use quando o usuário quiser entender o mercado, concorrentes, tendências ou oportunidades.

        Parâmetros:
        - setor: Setor ou segmento de mercado a pesquisar (ex: 'SaaS B2B', 'e-commerce moda', 'healthtech')
        - pergunta_especifica: A dúvida ou foco da pesquisa (ex: 'principais players e market share')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            extra_context = f"Setor pesquisado: {setor}\\nFoco da pesquisa: {pergunta_especifica}"
            if self._marco: await self._marco.gerar_documento_personalizado(
                doc_type="pesquisa_mercado", doc_title="Pesquisa de Mercado",
                user_name=user_name, project_name=project_name,
                extra_context=extra_context,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: A pesquisa sobre '{setor}' já está rodando em paralelo. "
            f"Avise ao {user_name} que o Marco vai coletar os dados na Web e o relatório aparecerá na tela dele."
        )

    @function_tool
    async def gerar_checklist_abertura_empresa(
        self,
        context: RunContext,
        tipo_empresa: str,
    ) -> str:
        """
        Aciona o Marco para gerar um guia completo de abertura de empresa no Brasil.
        Use quando o usuário quiser formalizar seu negócio, abrir CNPJ ou escolher o tipo societário.

        Parâmetros:
        - tipo_empresa: Tipo de empresa desejado (ex: 'MEI', 'LTDA', 'SA', 'ainda não sei')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            orgao_processo = f"Abertura de Empresa ({tipo_empresa})"
            if self._marco: await self._marco.gerar_orientacao_orgao_publico(
                orgao_processo=orgao_processo,
                contexto=f"Tipo de empresa: {tipo_empresa}. Contexto: {self._blackboard.get_context_summary()[:800]}",
                user_name=user_name, project_name=project_name,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco para preparar o guia de Abertura ({tipo_empresa}). "
            f"Diga que ele compilara com links, prazos e custos na web, gerando e enviando em background para a tela."
        )

    @function_tool
    async def gerar_orientacao_orgao_publico(
        self,
        context: RunContext,
        orgao_processo: str,
        contexto_adicional: str,
    ) -> str:
        """
        Aciona o Marco para gerar um guia PRÁTICO sobre qualquer processo em órgão público brasileiro.
        Use quando o usuário perguntar sobre:
        - Registro de marca no INPI
        - Enquadramento tributário (Simples Nacional, MEI, Lucro Presumido)
        - Adequação à LGPD / ANPD
        - Emissão de Nota Fiscal (NFS-e, NF-e)
        - Acesso a crédito público (BNDES, Pronampe, Finep)
        - Outros processos burocráticos empresariais

        IMPORTANTE: O Marco NÃO gera o documento oficial. Ele explica como o usuário deve fazer.

        Parâmetros:
        - orgao_processo: Descrição do processo ou órgão (ex: 'Registro de marca no INPI', 'Simples Nacional')
        - contexto_adicional: Contexto específico do usuário para personalizar o guia
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            if self._marco: await self._marco.gerar_orientacao_orgao_publico(
                orgao_processo=orgao_processo, contexto=contexto_adicional,
                user_name=user_name, project_name=project_name,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco sobre '{orgao_processo}' e ele está extraindo as orientais na rede em background. "
            f"Diga que é bom o {user_name} aguardar pois o documento chegará pronto."
        )

    @function_tool
    async def gerar_modelo_contrato(
        self,
        context: RunContext,
        tipo_contrato: str,
        partes_envolvidas: str,
    ) -> str:
        """
        Aciona o Marco para gerar um modelo de contrato profissional adaptado ao contexto.
        Use quando o usuário precisar de um contrato base para revisar com seu advogado.
        Tipos comuns: prestação de serviços, parceria, confidencialidade (NDA), compra e venda,
        distribuição, locação, influencer/marketing, SaaS/licença de software.

        IMPORTANTE: Sempre reforce que o modelo deve ser revisado por advogado antes de assinar.

        Parâmetros:
        - tipo_contrato: Tipo do contrato (ex: 'prestação de serviços', 'parceria comercial', 'NDA')
        - partes_envolvidas: Quem são as partes (ex: 'empresa contratante e freelancer PJ')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            extra_context = (
                f"Tipo de contrato: {tipo_contrato}\\n"
                f"Partes envolvidas: {partes_envolvidas}\\n"
                f"Contexto do negócio: {self._blackboard.get_context_summary()[:600]}"
            )
            if self._marco: await self._marco.gerar_documento_personalizado(
                doc_type="modelo_contrato",
                doc_title=f"Modelo de Contrato — {tipo_contrato.title()}",
                user_name=user_name, project_name=project_name,
                extra_context=extra_context,
                extra_vars={"tipo_contrato": tipo_contrato, "tipo_contrato_upper": tipo_contrato.upper(), "partes": partes_envolvidas},
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você falou com Marco e ele já redigirá o modelo do contrato para os dados deste cenário. "
            f"Fale que ele está no backstage adaptando e em instantes chegará para {user_name} revisar com advogados reais."
        )

    @function_tool
    async def gerar_pitch_deck(
        self,
        context: RunContext,
        publico_alvo: str,
    ) -> str:
        """
        Aciona o Marco para criar um Pitch Deck profissional de 12 slides em formato documento.
        Use quando o usuário quiser apresentar seu negócio para investidores, parceiros ou clientes.

        Parâmetros:
        - publico_alvo: Para quem será apresentado (ex: 'investidores angel', 'parceiros estratégicos', 'clientes enterprise')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            if self._marco: await self._marco.gerar_documento_personalizado(
                doc_type="pitch_deck", doc_title="Pitch Deck",
                user_name=user_name, project_name=project_name,
                extra_context=f"Público-alvo da apresentação: {publico_alvo}",
                extra_vars={"publico": publico_alvo},
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Marco começou a arquitetar o esquema do Pitch Deck em background. "
            f"Avise que está no processo em andamento e gerando em PDF."
        )

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
            api_key=get_gemini_api_key(),
            voice=AGENT_VOICES["host"],
            instructions=(
                "IDIOMA OBRIGATÓRIO: Você DEVE falar e entender APENAS em português brasileiro (pt-BR). "
                "Toda entrada de áudio do usuário é em português do Brasil. "
                "NUNCA interprete como outro idioma. Responda SEMPRE em português do Brasil.\n"
                "IMPORTANTE: Você pode ocasionalmente escutar ruídos ou receber detecções como '<noise>' ou sílabas soltas devido ao microfone estar sempre aberto. "
                "Ignore sons de fundo ou falas desconexas que não façam sentido. Concentre-se nas frases completas ditas pelo usuário."
            ),
            realtime_input_config=genai_types.RealtimeInputConfig(
                automatic_activity_detection=genai_types.AutomaticActivityDetection(
                    disabled=False,
                    prefix_padding_ms=300,
                    silence_duration_ms=550,
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
        self._turn_lock = asyncio.Lock()
        self._turn_seq = 0
        self._turn_events: dict[int, dict[str, asyncio.Event]] = {}
        self._turn_status: dict[int, dict] = {}
        self._last_activation_at: dict[str, float] = {}
        self._host_audio_muted = False  # Controle de mute do áudio para silenciar durante turno de especialista
        self._host_session: Optional[AgentSession] = None  # Referência ao host_session (definida após start)
        # Rastreia quais especialistas já publicaram agent_ready (prontos para ativação)
        self._ready_specialists: set[str] = set()
        self._specialist_ready_events: dict[str, asyncio.Event] = {
            sid: asyncio.Event() for sid in ["cfo", "legal", "cmo", "cto"]
        }
        # Marco Strategist: geração de documentos desacoplada via ProcessPool
        self._marco = MarcoStrategist(blackboard, self._publish_packet)

    # ------------------------------------------------------------------
    # Controle de áudio da Nathália — silencia durante turno de especialista
    # ------------------------------------------------------------------
    def _mute_host_audio(self) -> None:
        """Dessubscreve o áudio do usuário na Nathália para silenciá-la durante turno de especialista."""
        if self._host_audio_muted:
            return
        self._host_audio_muted = True
        for p in self._room.remote_participants.values():
            if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                for pub in p.track_publications.values():
                    if pub.kind == rtc.TrackKind.KIND_AUDIO:
                        pub.set_subscribed(False)
        logger.info("[Host] Áudio do usuário DESSUBSCRITO — Nathália SILENCIADA durante turno de especialista.")

    def _unmute_host_audio(self) -> None:
        """Resubscreve o áudio do usuário na Nathália quando o turno do especialista terminar."""
        if not self._host_audio_muted:
            return
        self._host_audio_muted = False
        for p in self._room.remote_participants.values():
            if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                for pub in p.track_publications.values():
                    if pub.kind == rtc.TrackKind.KIND_AUDIO:
                        pub.set_subscribed(True)
        logger.info("[Host] Áudio do usuário RESUBSCRITO — Nathália ATIVA novamente.")

    async def _publish_packet(self, payload: dict) -> None:
        base_payload = {
            "version": DATA_PACKET_SCHEMA_VERSION,
            "sent_at": monotonic(),
            **payload,
        }
        await _safe_publish_data(self._room.local_participant, base_payload)

    def handle_specialist_signal(self, msg: dict) -> None:
        turn_id = msg.get("turn_id")
        if not isinstance(turn_id, int):
            return
        events = self._turn_events.get(turn_id)
        if not events:
            return
        msg_type = msg.get("type")
        if msg_type == "agent_activated":
            self._turn_status[turn_id] = msg
            events["activated"].set()
        elif msg_type in ("agent_done", "agent_timeout", "agent_cancelled", "agent_error"):
            self._turn_status[turn_id] = msg
            events["done"].set()

    @function_tool
    async def consultar_documento_empresa(
        self,
        context: RunContext,
        pergunta: str,
    ) -> str:
        """
        Consulta os documentos e anexos do usuário para responder a uma pergunta.
        Use esta ferramenta SEMPRE que precisar de contexto específico sobre a empresa,
        contratos, relatórios, números ou qualquer arquivo anexado pelo usuário.
        """
        logger.info(f"[Host] Consultando documentos: {pergunta}")
        return await _query_documents_with_llm(pergunta, self._blackboard.documentos_disponiveis)

    @function_tool
    async def consultar_historico_mentoria(
        self,
        context: RunContext,
        pergunta: str,
    ) -> str:
        """
        Busca informações no histórico completo de TODAS as sessões de mentoria deste projeto.
        Use esta ferramenta quando o usuário perguntar sobre algo que foi discutido em sessões
        anteriores, ou quando precisar relembrar decisões, recomendações ou contextos passados.
        Exemplos: "o que conversamos sobre marketing?", "qual foi a recomendação do Daniel?",
        "quanto tempo atrás discutimos o pricing?"

        Parâmetros:
        - pergunta: A pergunta ou tema que deseja buscar no histórico
        """
        logger.info(f"[Host] Consultando histórico da mentoria: {pergunta}")
        return await _query_transcript_with_llm(pergunta, self._blackboard.transcript)

    # ------------------------------------------------------------------
    # Método auxiliar: publica um data packet para ativar um especialista
    # ------------------------------------------------------------------

    async def _activate_specialist(self, spec_id: str, context: str, _lateral_from_name: str = "") -> str:
        """Ativa um especialista de forma NON-BLOCKING.
        
        Envia o packet de ativação, espera APENAS o ACK (confirmação de que o
        especialista recebeu o packet), e retorna imediatamente.
        O monitoramento do turno (done/timeout) é feito em background.
        Isso libera o Gemini da Nathália para ficar em silêncio (em vez de travar).
        """
        # ── READINESS GATE ──────────────────────────────────────────────────
        # Aguarda o especialista publicar agent_ready antes de tentar ativar.
        # Crítico na retomada de sessão, onde Nathália pode tentar ativar um
        # especialista antes do processo de reconexão sequencial terminar.
        # Este wait está FORA do turn_lock para não bloquear outras ativações.
        if spec_id not in self._ready_specialists:
            event = self._specialist_ready_events.get(spec_id)
            if event is not None:
                logger.info(
                    f"[Host] {SPECIALIST_NAMES.get(spec_id, spec_id)} ainda reconectando — "
                    f"aguardando agent_ready (máx {SPECIALIST_READY_WAIT_SECONDS:.0f}s)..."
                )
                try:
                    await asyncio.wait_for(event.wait(), timeout=SPECIALIST_READY_WAIT_SECONDS)
                    logger.info(f"[Host] {SPECIALIST_NAMES.get(spec_id, spec_id)} ficou pronto. Prosseguindo com ativação.")
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[Host] Timeout aguardando agent_ready de {spec_id} "
                        f"({SPECIALIST_READY_WAIT_SECONDS:.0f}s). Abortando ativação."
                    )
                    return (
                        f"{SPECIALIST_NAMES.get(spec_id, spec_id)} ainda está reconectando. "
                        f"Por favor, aguarde um instante e tente novamente."
                    )
        # ────────────────────────────────────────────────────────────────────
        async with self._turn_lock:
            now = monotonic()
            last_activation = self._last_activation_at.get(spec_id, 0.0)
            if now - last_activation < ACTIVATION_DEBOUNCE_SECONDS:
                logger.info(f"[Host] Ativação de {spec_id} ignorada por debounce.")
                return (
                    f"{SPECIALIST_NAMES[spec_id]} já está sendo acionado neste instante. "
                    f"Mantenha a conversa enquanto ele conclui o turno."
                )
            self._last_activation_at[spec_id] = now

            self._turn_seq += 1
            turn_id = self._turn_seq
            start_ts = monotonic()

            self._turn_events[turn_id] = {
                "activated": asyncio.Event(),
                "done": asyncio.Event(),
            }
            self._turn_status.pop(turn_id, None)
            self._blackboard.orchestration_metrics["activations_total"] += 1
            self._blackboard.active_agent = spec_id
            if _lateral_from_name:
                self._blackboard.add_message("Sistema", f"{_lateral_from_name} transferiu a palavra para {SPECIALIST_NAMES[spec_id]}: {context}")
            else:
                self._blackboard.add_message("Sistema", f"Acionando {SPECIALIST_NAMES[spec_id]}: {context}")

            packet = {
                "type": "activate_agent",
                "agent_id": spec_id,
                "turn_id": turn_id,
                "context": context,
                "transcript_summary": self._blackboard.get_context_summary(),
                "context_state": self._blackboard.get_structured_context(),
            }
            if _lateral_from_name:
                packet["from_name"] = _lateral_from_name
            
            logger.info(f"[Host] Acionando especialista: {spec_id} | turno={turn_id} | contexto: {context} | lateral_from={_lateral_from_name or 'Nathália'}")
            
            # Transforma a publicação do pacote e a espera do ACK em uma task separada,
            # para que a tool_call retorne IMEDIATAMENTE e a Nathália possa gerar e 
            # de fato falar a frase de transição completa SEM que o especialista já
            # comece a falar por cima dela.
            async def _deferred_activation():
                # Delay de 8.5s permite que a Nathália termine de ler a frase ("Vou chamar o Daniel...")
                # no TTS antes de ativarmos o microfone do Daniel.
                await asyncio.sleep(8.5)
                
                # SILENCIA a Nathália garantindo que ela não ouça o eco ou a fala do Especialista
                self._mute_host_audio()
                await self._publish_packet(packet)

                try:
                    await asyncio.wait_for(
                        self._turn_events[turn_id]["activated"].wait(),
                        timeout=ACTIVATION_ACK_TIMEOUT_SECONDS,
                    )
                    ack_latency = (monotonic() - start_ts) * 1000
                    self._blackboard.orchestration_metrics["activation_ack_latency_ms_total"] += ack_latency
                    logger.info(f"[Host] ACK recebido de {spec_id} em {ack_latency:.0f}ms. Especialista ATIVO.")
                except asyncio.TimeoutError:
                    self._blackboard.orchestration_metrics["activations_timeout"] += 1
                    self._blackboard.active_agent = None
                    self._turn_events.pop(turn_id, None)
                    self._turn_status.pop(turn_id, None)
                    self._unmute_host_audio()  # Reativa áudio em caso de falha
                    logger.warning(f"[Host] Timeout aguardando ACK de {spec_id} no turno {turn_id}.")

            asyncio.create_task(_deferred_activation())

            # NON-BLOCKING: Lança task em background para monitorar o turno
            # e NÃO espera o especialista terminar dentro da tool call.
            asyncio.create_task(self._monitor_specialist_turn(spec_id, turn_id, start_ts, host_session=self._host_session))

            # Retorna IMEDIATAMENTE para o Gemini da Nathália.
            # A mensagem instrui o LLM a ficar em silêncio absoluto.
            return (
                f"ESPECIALISTA_ATIVADO: {SPECIALIST_NAMES[spec_id]} está assumindo. "
                f"Você (Nathália) deve fazer UMA ÚNICA FRASE CURTA (ex: Vou transferir para o Daniel. Daniel, é com você!) "
                f"e depois FIQUE EM SILÊNCIO TOTAL. NÃO escute mais nada."
            )

    async def _monitor_specialist_turn(self, spec_id: str, turn_id: int, start_ts: float, host_session: Optional[AgentSession] = None) -> None:
        """Monitora o turno do especialista EM BACKGROUND (não bloqueia a Nathália)."""
        try:
            await asyncio.wait_for(
                self._turn_events[turn_id]["done"].wait(),
                timeout=ACTIVATION_DONE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._blackboard.orchestration_metrics["activations_timeout"] += 1
            logger.warning(f"[Host] Timeout aguardando conclusão de {spec_id} no turno {turn_id}.")
        finally:
            done_latency = (monotonic() - start_ts) * 1000
            self._blackboard.orchestration_metrics["activation_done_latency_ms_total"] += done_latency
            status_payload = self._turn_status.get(turn_id, {})
            status_type = status_payload.get("type")
            self._blackboard.active_agent = None
            self._turn_events.pop(turn_id, None)
            self._turn_status.pop(turn_id, None)

            if status_type == "agent_done":
                self._blackboard.orchestration_metrics["activations_succeeded"] += 1
            elif status_type == "agent_cancelled":
                self._blackboard.orchestration_metrics["activations_cancelled"] += 1
            elif status_type in ("agent_timeout", "agent_error"):
                self._blackboard.orchestration_metrics["activations_timeout"] += 1

            # REATIVA o áudio da Nathália quando o especialista devolver a palavra
            self._unmute_host_audio()
            logger.info(f"[Host] Turno de {SPECIALIST_NAMES[spec_id]} encerrado (status={status_type}). Nathália reativada.")

            # Faz a Nathália retomar a conversa proativamente
            handover_reason = status_payload.get("handover_reason")
            if host_session and status_type == "agent_done" and handover_reason in {
                "user_confirmed_done",
                "user_requested_host",
                "topic_change",
            }:
                spec_name = SPECIALIST_NAMES[spec_id]
                user_name = self._blackboard.user_name or "você"
                summary = status_payload.get("summary", "")
                summary_prompt = f" Resumo deixado pelo especialista para te contextualizar: '{summary}'." if summary else ""
                try:
                    await asyncio.wait_for(
                        host_session.generate_reply(
                            instructions=(
                                f"ESPECIALISTA_DEVOLVEU: {spec_name} acabou de devolver a palavra para você.{summary_prompt} "
                                f"Retome a condução com 1-2 frases de transição abordando o que foi falado. "
                                f"Pergunte a {user_name} se ficou claro ou se quer explorar outro tema. "
                                f"Seja breve e calorosa."
                            ),
                        ),
                        timeout=15.0,
                    )
                except Exception as e:
                    logger.warning(f"[Host] Erro ao gerar retomada pós-especialista: {e}")

            elif host_session and status_type in ("agent_timeout", "agent_error", None):
                # Especialista não respondeu a tempo ou teve erro. Nathália precisa retomar
                # explicitamente porque sua sessão LLM ainda carrega a instrução de silêncio.
                spec_name = SPECIALIST_NAMES.get(spec_id, spec_id)
                user_name = self._blackboard.user_name or "você"
                try:
                    await asyncio.wait_for(
                        host_session.generate_reply(
                            instructions=(
                                f"RETOMADA_FORÇADA: O especialista {spec_name} não conseguiu responder a tempo. "
                                f"Você está de volta no controle da conversa. PODE E DEVE FALAR normalmente. "
                                f"Peça desculpas de forma natural pelo silêncio, como se fosse uma pequena instabilidade técnica, "
                                f"e pergunte a {user_name} como pode ajudar ou se quer continuar o tema anterior. "
                                f"Seja breve, calorosa e mantenha a fluidez da conversa."
                            ),
                        ),
                        timeout=15.0,
                    )
                except Exception as e:
                    logger.warning(f"[Host] Erro ao gerar retomada pós-timeout de especialista: {e}")

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
        Aciona Carlos (CFO & Venture Capital) para análise de finanças e investimentos.
        Use quando o usuário precisar de: precificação, projeção de receita,
        viabilidade financeira, custos, valuation, M&A ou captação de recursos/sócios.
        """
        return await self._activate_specialist("cfo", questao)

    @function_tool
    async def acionar_daniel_advogado(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Daniel (CLO & Compliance) para orientação corporativa e legal.
        Use quando o usuário precisar de: tipo societário, contratos complexos,
        LGPD, inovação legal, compliance ou proteção de propriedade intelectual.
        """
        return await self._activate_specialist("legal", questao)

    @function_tool
    async def acionar_rodrigo_cmo(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Rodrigo (CMO & Growth) para estratégia agressiva de marketing e vendas.
        Use quando o usuário precisar de: aquisição em escala, funil de vendas,
        go-to-market, growth hacking, métricas (CAC/LTV), branding e posicionamento.
        """
        return await self._activate_specialist("cmo", questao)

    @function_tool
    async def acionar_ana_cto(
        self,
        context: RunContext,
        questao: str,
    ) -> str:
        """
        Aciona Ana (CTO & Arquiteta IA) para hiperautomação técnica e de produto.
        Use quando o usuário precisar de: IA Generativa, engenharia de dados, automação,
        stack tecnológico, arquitetura de software, infraestrutura ou escalabilidade.
        """
        return await self._activate_specialist("cto", questao)

    async def gerar_plano_forcado(self, user_name: str, project_name: str):
        """Aciona a geração do Plano de Execução pelo Marco (non-blocking via ProcessPool)."""
        self._blackboard.marco_triggered = True
        logger.info("[Marco] Delegando geração do Plano ao ProcessPool via MarcoStrategist...")
        await self._marco.gerar_plano_execucao(user_name, project_name)

    @function_tool
    async def gerar_plano_execucao(
        self,
        context: RunContext,
    ) -> str:
        """
        Aciona Marco (Estrategista) nos bastidores para gerar o Plano de Execução final.
        Use quando o usuário quiser encerrar a sessão ou solicitar um plano estruturado.
        Marco não fala — ele trabalha silenciosamente e envia o documento.
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        asyncio.create_task(self.gerar_plano_forcado(user_name, project_name))

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco nos bastidores. ELE JÁ ESTA TRABALHANDO no Plano de Execução para {user_name}. "
            f"Gere UMA NOVA FALA AVISANDO O USUÁRIO: diga exatamente que o Marco começou a redigir o plano nos bastidores, "
            f"fazendo pesquisas e em instantes chegará pronto na tela dele. Seja natural."
        )

    # ------------------------------------------------------------------
    # FERRAMENTAS DO MARCO → Delegação ao MarcoStrategist (ProcessPool)
    # ------------------------------------------------------------------

    @function_tool
    async def gerar_documento_personalizado(
        self,
        context: RunContext,
        tipo_documento: str,
        descricao_contexto: str,
    ) -> str:
        """
        Aciona o Marco (bastidores) para gerar um documento empresarial personalizado.
        Use quando o usuário solicitar qualquer um destes documentos:
        - 'swot': Análise SWOT estratégica completa
        - 'canvas': Business Model Canvas (9 blocos)
        - 'proposta_comercial': Proposta comercial profissional
        - 'pesquisa_mercado': Relatório de pesquisa de mercado

        Parâmetros:
        - tipo_documento: Tipo do documento. Valores: swot, canvas, proposta_comercial, pesquisa_mercado
        - descricao_contexto: Contexto adicional sobre o que o usuário quer no documento
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"
        tipo_lower = tipo_documento.lower().strip().replace(" ", "_")

        tipo_map = {
            "swot": "swot",
            "analise_swot": "swot",
            "canvas": "canvas",
            "business_model_canvas": "canvas",
            "proposta": "proposta_comercial",
            "proposta_comercial": "proposta_comercial",
            "pesquisa": "pesquisa_mercado",
            "pesquisa_mercado": "pesquisa_mercado",
        }
        doc_type = tipo_map.get(tipo_lower, tipo_lower)

        titulos = {
            "swot": "Análise SWOT Estratégica",
            "canvas": "Business Model Canvas",
            "proposta_comercial": "Proposta Comercial",
            "pesquisa_mercado": "Pesquisa de Mercado",
        }
        doc_title = titulos.get(doc_type, tipo_documento.replace("_", " ").title())

        async def _bg():
            await self._marco.gerar_documento_personalizado(
                doc_type=doc_type, doc_title=doc_title,
                user_name=user_name, project_name=project_name,
                extra_context=descricao_contexto,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você acionou o Marco para preparar: {doc_title}. "
            f"Diga que ele já esta pesquisando e gerando o PDF nos bastidores e em instantes chegará para {user_name}."
        )

    @function_tool
    async def pesquisar_mercado_setor(
        self,
        context: RunContext,
        setor: str,
        pergunta_especifica: str,
    ) -> str:
        """
        Aciona o Marco para pesquisar dados de mercado em tempo real sobre um setor específico.
        Use quando o usuário quiser entender o mercado, concorrentes, tendências ou oportunidades.

        Parâmetros:
        - setor: Setor ou segmento de mercado a pesquisar (ex: 'SaaS B2B', 'e-commerce moda', 'healthtech')
        - pergunta_especifica: A dúvida ou foco da pesquisa (ex: 'principais players e market share')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            extra_context = f"Setor pesquisado: {setor}\nFoco da pesquisa: {pergunta_especifica}"
            await self._marco.gerar_documento_personalizado(
                doc_type="pesquisa_mercado", doc_title="Pesquisa de Mercado",
                user_name=user_name, project_name=project_name,
                extra_context=extra_context,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: A pesquisa sobre '{setor}' já está rodando em paralelo. "
            f"Avise ao {user_name} que o Marco vai coletar os dados na Web e o relatório aparecerá na tela dele."
        )

    @function_tool
    async def gerar_checklist_abertura_empresa(
        self,
        context: RunContext,
        tipo_empresa: str,
    ) -> str:
        """
        Aciona o Marco para gerar um guia completo de abertura de empresa no Brasil.
        Use quando o usuário quiser formalizar seu negócio, abrir CNPJ ou escolher o tipo societário.

        Parâmetros:
        - tipo_empresa: Tipo de empresa desejado (ex: 'MEI', 'LTDA', 'SA', 'ainda não sei')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            orgao_processo = f"Abertura de Empresa ({tipo_empresa})"
            await self._marco.gerar_orientacao_orgao_publico(
                orgao_processo=orgao_processo,
                contexto=f"Tipo de empresa: {tipo_empresa}. Contexto: {self._blackboard.get_context_summary()[:800]}",
                user_name=user_name, project_name=project_name,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco para preparar o guia de Abertura ({tipo_empresa}). "
            f"Diga que ele compilara com links, prazos e custos na web, gerando e enviando em background para a tela."
        )

    @function_tool
    async def gerar_orientacao_orgao_publico(
        self,
        context: RunContext,
        orgao_processo: str,
        contexto_adicional: str,
    ) -> str:
        """
        Aciona o Marco para gerar um guia PRÁTICO sobre qualquer processo em órgão público brasileiro.
        Use quando o usuário perguntar sobre:
        - Registro de marca no INPI
        - Enquadramento tributário (Simples Nacional, MEI, Lucro Presumido)
        - Adequação à LGPD / ANPD
        - Emissão de Nota Fiscal (NFS-e, NF-e)
        - Acesso a crédito público (BNDES, Pronampe, Finep)
        - Outros processos burocráticos empresariais

        IMPORTANTE: O Marco NÃO gera o documento oficial. Ele explica como o usuário deve fazer.

        Parâmetros:
        - orgao_processo: Descrição do processo ou órgão (ex: 'Registro de marca no INPI', 'Simples Nacional')
        - contexto_adicional: Contexto específico do usuário para personalizar o guia
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            await self._marco.gerar_orientacao_orgao_publico(
                orgao_processo=orgao_processo, contexto=contexto_adicional,
                user_name=user_name, project_name=project_name,
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você avisou ao Marco sobre '{orgao_processo}' e ele está extraindo as orientais na rede em background. "
            f"Diga que é bom o {user_name} aguardar pois o documento chegará pronto."
        )

    @function_tool
    async def gerar_modelo_contrato(
        self,
        context: RunContext,
        tipo_contrato: str,
        partes_envolvidas: str,
    ) -> str:
        """
        Aciona o Marco para gerar um modelo de contrato profissional adaptado ao contexto.
        Use quando o usuário precisar de um contrato base para revisar com seu advogado.
        Tipos comuns: prestação de serviços, parceria, confidencialidade (NDA), compra e venda,
        distribuição, locação, influencer/marketing, SaaS/licença de software.

        IMPORTANTE: Sempre reforce que o modelo deve ser revisado por advogado antes de assinar.

        Parâmetros:
        - tipo_contrato: Tipo do contrato (ex: 'prestação de serviços', 'parceria comercial', 'NDA')
        - partes_envolvidas: Quem são as partes (ex: 'empresa contratante e freelancer PJ')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            extra_context = (
                f"Tipo de contrato: {tipo_contrato}\n"
                f"Partes envolvidas: {partes_envolvidas}\n"
                f"Contexto do negócio: {self._blackboard.get_context_summary()[:600]}"
            )
            await self._marco.gerar_documento_personalizado(
                doc_type="modelo_contrato",
                doc_title=f"Modelo de Contrato — {tipo_contrato.title()}",
                user_name=user_name, project_name=project_name,
                extra_context=extra_context,
                extra_vars={"tipo_contrato": tipo_contrato, "tipo_contrato_upper": tipo_contrato.upper(), "partes": partes_envolvidas},
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Você falou com Marco e ele já redigirá o modelo do contrato para os dados deste cenário. "
            f"Fale que ele está no backstage adaptando e em instantes chegará para {user_name} revisar com advogados reais."
        )

    @function_tool
    async def gerar_pitch_deck(
        self,
        context: RunContext,
        publico_alvo: str,
    ) -> str:
        """
        Aciona o Marco para criar um Pitch Deck profissional de 12 slides em formato documento.
        Use quando o usuário quiser apresentar seu negócio para investidores, parceiros ou clientes.

        Parâmetros:
        - publico_alvo: Para quem será apresentado (ex: 'investidores angel', 'parceiros estratégicos', 'clientes enterprise')
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        async def _bg():
            await self._marco.gerar_documento_personalizado(
                doc_type="pitch_deck", doc_title="Pitch Deck",
                user_name=user_name, project_name=project_name,
                extra_context=f"Público-alvo da apresentação: {publico_alvo}",
                extra_vars={"publico": publico_alvo},
            )
        asyncio.create_task(_bg())

        return (
            f"MARCO_ACIONADO: Marco começou a arquitetar o esquema do Pitch Deck em background. "
            f"Avise que está no processo em andamento e gerando em PDF."
        )

# =============================================================
# Helper: inicia uma AvatarSession da Beyond Presence para um agente
# Fonte verificada: https://docs.livekit.io/agents/models/avatar/plugins/bey/
# =============================================================
async def _start_avatar_session(
    spec_id: str,
    agent_session: AgentSession,
    room: rtc.Room,
) -> Optional[object]:
    """
    Cria e inicia um avatar Beyond Presence sincronizado com a voz do agente.

    - O avatar entra no room como participante separado (kind=Agent, lk.publish_on_behalf).
    - Retorna o AvatarSession ou None se não disponível / ocorrer erro.
    - Degrada graciosamente: se BEY_AVAILABLE=False, apenas loga e retorna None.
    """
    if not BEY_AVAILABLE:
        return None

    avatar_id = AVATAR_IDS.get(spec_id, "")
    if not avatar_id:
        logger.warning(
            f"[Avatar] avatar_id não definido para '{spec_id}' — "
            "verifique o mapeamento em AVATAR_IDS e as variáveis de ambiente do avatar"
        )
        return None

    agent_name = SPECIALIST_NAMES.get(spec_id, spec_id) if spec_id != "host" else "Nathália"
    try:
        # UNVERIFIED API signature confirmed at: https://docs.livekit.io/agents/models/avatar/plugins/bey/
        avatar = bey_plugin.AvatarSession(
            avatar_id=avatar_id,
            avatar_participant_name=agent_name,
            avatar_participant_identity=f"bey-{SPECIALIST_IDENTITIES.get(spec_id, spec_id)}",
        )
        await avatar.start(agent_session, room=room)
        logger.info(f"[Avatar] Avatar Beyond Presence iniciado para '{agent_name}' (id={avatar_id[:8]}...).")
        return avatar
    except Exception as e:
        logger.warning(f"[Avatar] Falha ao iniciar avatar para '{agent_name}': {e}")
        return None


def _prefetch_avatar_session(
    spec_id: str,
    agent_session: AgentSession,
    room: rtc.Room,
) -> Optional[asyncio.Task[Optional[object]]]:
    """
    Dispara o start do avatar em background para reduzir a latência percebida
    até a primeira fala do agente.
    """
    if not BEY_AVAILABLE or not AVATAR_IDS.get(spec_id, ""):
        return None
    return asyncio.create_task(
        _start_avatar_session(spec_id, agent_session, room),
        name=f"avatar-prefetch-{spec_id}",
    )

# ── Helpers de transcrição (módulo-nível) ─────────────────────────────────────
# Definidos aqui para serem acessíveis tanto por _start_specialist_in_room
# quanto por _run_entrypoint sem duplicação de código.

_NON_LATIN_RE = re.compile(
    r"[\u0e00-\u0e7f\u0600-\u06ff\u0980-\u09ff\u0e80-\u0eff\uac00-\ud7af]"
)
_COMMON_PT_MONOS = frozenset({
    "oi", "é", "o", "a", "um", "eu", "se", "ir", "da", "do",
    "no", "na", "te", "me", "vc", "bj", "obg",
})


def _extract_transcribed_text(event) -> str:
    """Extrai texto de um evento de transcrição de forma segura."""
    if hasattr(event, "transcript"):
        return (event.transcript or "").strip()
    if hasattr(event, "text"):
        return (event.text or "").strip()
    return str(event).strip()


def _should_ignore_user_transcript(text: str) -> bool:
    """
    Retorna True quando o texto é ruído, eco do agente ou alucinação de idioma,
    e portanto deve ser descartado do transcript do usuário.
    """
    lower_text = text.lower()

    if lower_text in {"<noise>", "[noise]", "silence", "noise", "ruído", "interruption", "breath"}:
        logger.info(f"[Filtro] Ruído explícito descartado: {text}")
        return True

    if _NON_LATIN_RE.search(text):
        logger.info(f"[Filtro] Alucinação de idioma detectada e descartada: {text}")
        return True

    if len(text) <= 3 and not any(v in lower_text for v in "aeiouáéíóúâêôãõ"):
        logger.info(f"[Filtro] Fragmento curto sem vogais (ruído) descartado: {text}")
        return True

    if len(text) <= 2 and lower_text not in _COMMON_PT_MONOS:
        logger.info(f"[Filtro] Monossílabo suspeito descartado: {text}")
        return True

    if lower_text.startswith("entendido") or lower_text.startswith("perfeito") or lower_text.startswith("claro"):
        logger.info(f"[Filtro] Possível eco de agente descartado: {text}")
        return True

    return False


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
            """Subscreve ao áudio do usuário com delay para sincronização com RealtimeModel."""
            nonlocal _audio_subscribed
            if _audio_subscribed:
                return
            _audio_subscribed = True

            # Delay sincroniza com RealtimeModel pronto para ouvir interrupções
            async def _do_subscribe():
                await asyncio.sleep(0.15)  # 150ms para RealtimeModel inicializar
                for p in room.remote_participants.values():
                    if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                        for pub in p.track_publications.values():
                            if pub.kind == rtc.TrackKind.KIND_AUDIO:
                                pub.set_subscribed(True)
                logger.info(f"[{name}] Áudio do usuário SUBSCRITO com sucesso (interrupções ATIVAS).")

            asyncio.create_task(_do_subscribe())

        def _unsubscribe_user_audio():
            """Dessubscreve do áudio do usuário (chamado quando outro especialista é ativado)."""
            nonlocal _audio_subscribed
            if not _audio_subscribed:
                return
            _audio_subscribed = False
            for p in room.remote_participants.values():
                if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                    for pub in p.track_publications.values():
                        if pub.kind == rtc.TrackKind.KIND_AUDIO:
                            pub.set_subscribed(False)
            logger.info(f"[{name}] Áudio do usuário DESSUBSCRITO (silenciado).")

        # Quando o usuário publicar áudio depois, subscreve SOMENTE se ativado
        def _on_track_published(publication, participant):
            if (
                _audio_subscribed
                and (participant.identity.startswith("user-") or participant.identity.startswith("guest-"))
                and publication.kind == rtc.TrackKind.KIND_AUDIO
            ):
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
                        "version": DATA_PACKET_SCHEMA_VERSION,
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

        # ── MICRO-SUBSCRIÇÃO TEMPORÁRIA (Pré-aquecimento do Pipeline de Áudio) ──
        # O Gemini Realtime precisa "ver" tracks de áudio durante session.start()
        # para acoplar corretamente os pinos VAD internos. Sem isso, o especialista
        # fica "surdo" quando ativado posteriormente via _subscribe_user_audio().
        logger.info(f"[{name}] Micro-subscrição: ativando áudio temporário para boot do pipeline...")
        for p in room.remote_participants.values():
            if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                for pub in p.track_publications.values():
                    if pub.kind == rtc.TrackKind.KIND_AUDIO:
                        pub.set_subscribed(True)

        async def _publish_packet(payload: dict) -> None:
            base_payload = {
                "version": DATA_PACKET_SCHEMA_VERSION,
                "sent_at": monotonic(),
                **payload,
            }
            await _safe_publish_data(host_room.local_participant, base_payload)
            
        marco = MarcoStrategist(blackboard, _publish_packet)

        # C2: Instancia agent + sessão com retry no start()
        agent = SpecialistAgent(spec_id, blackboard, marco)
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
                    agent = SpecialistAgent(spec_id, blackboard, marco)
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
                        "version": DATA_PACKET_SCHEMA_VERSION,
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

        # ── DESATIVA MICRO-SUBSCRIÇÃO (Retorno ao modo dormente) ──────────────
        # Pipeline inicializado com sucesso. Desliga o áudio para o especialista
        # ficar em silêncio até ser explicitamente ativado pela Nathália.
        for p in room.remote_participants.values():
            if p.identity.startswith("user-") or p.identity.startswith("guest-"):
                for pub in p.track_publications.values():
                    if pub.kind == rtc.TrackKind.KIND_AUDIO:
                        pub.set_subscribed(False)
        logger.info(f"[{name}] Micro-subscrição ENCERRADA. Especialista dormente até ativação.")

        # ATUALIZAÇÃO: Para evitar crash e estouro do limite grátis da Beyond Presence,
        # Nós DESATIVAMOS os avatares 3D dos especialistas (Eles viram Voice/Podcast).
        # Apenas a Nathália receberá o vídeo 3D.
        # asyncio.create_task(_start_avatar_session(spec_id, session, room))

        # Registra a sessão no Blackboard
        blackboard.specialist_sessions[spec_id] = session

        # C3: Publica health-check data packet para o frontend
        try:
            await host_room.local_participant.publish_data(
                json.dumps({
                    "version": DATA_PACKET_SCHEMA_VERSION,
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

            item = getattr(event, "item", None)
            if item is None:
                return
            
            role = getattr(item, "role", None)
            if role not in ("assistant", "user"):
                return  # Ignora outras mensagens

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

            if role == "assistant":
                blackboard.add_message(name, text)
                asyncio.create_task(
                    host_room.local_participant.publish_data(
                        json.dumps({
                            "version": DATA_PACKET_SCHEMA_VERSION,
                            "type": "transcript",
                            "speaker": name,
                            "text": text,
                        }).encode(),
                        reliable=True,
                    )
                )
            elif role == "user":
                if not _audio_subscribed:
                    return
                blackboard.mark_user_activity()
                if _should_ignore_user_transcript(text):
                    return

                logger.info(f"[{name}] Usuário fala (Gemini STT): {text}")
                blackboard.add_message("Usuário", text)
                if not blackboard.user_query:
                    blackboard.user_query = text
                
                asyncio.create_task(
                    host_room.local_participant.publish_data(
                        json.dumps({
                            "version": DATA_PACKET_SCHEMA_VERSION,
                            "type": "transcript",
                            "speaker": "Você",
                            "text": text,
                        }).encode(),
                        reliable=True,
                    )
                )
                agent._user_messages_since_activation += 1
                logger.debug(
                    f"[{name}] Msg do usuário #{agent._user_messages_since_activation} "
                    f"desde ativação: '{text[:60]}'"
                )

        @session.on("user_input_transcribed")
        def _on_specialist_user_speech(event) -> None:
            if not blackboard.is_active or not _audio_subscribed:
                return
            blackboard.mark_user_activity()
            if not getattr(event, "is_final", True):
                return

            text = _extract_transcribed_text(event)
            text = text.strip()
            if not text or _should_ignore_user_transcript(text):
                return

            # Registra no blackboard compartilhado (o host_room publica o transcript)
            logger.info(f"[{name}] Usuário fala: {text}")
            blackboard.add_message("Usuário", text)
            if not blackboard.user_query:
                blackboard.user_query = text
            # Publica transcrição no host_room para o frontend receber
            asyncio.create_task(
                host_room.local_participant.publish_data(
                    json.dumps({
                        "version": DATA_PACKET_SCHEMA_VERSION,
                        "type": "transcript",
                        "speaker": "Você",
                        "text": text,
                    }).encode(),
                    reliable=True,
                )
            )
            # Incrementa o contador de mensagens do usuário desde a ativação deste especialista.
            # Este contador é usado como guarda mínima em devolver_para_nathalia e
            # transferir_para_especialista para evitar handoff imediato após a primeira fala.
            agent._user_messages_since_activation += 1
            logger.debug(
                f"[{name}] Msg do usuário #{agent._user_messages_since_activation} "
                f"desde ativação: '{text[:60]}'"
            )

        @session.on("input_speech_started")
        def _on_specialist_input_speech_started(_event) -> None:
            if not blackboard.is_active or not _audio_subscribed:
                return
            blackboard.set_user_speaking(True)

        @session.on("input_speech_stopped")
        def _on_specialist_input_speech_stopped(_event) -> None:
            if not blackboard.is_active or not _audio_subscribed:
                return
            blackboard.set_user_speaking(False)

        # C5: Handler assíncrono para ativação de especialista.
        # REFATORADO PARA HANDOVER PEER-TO-PEER:
        # O especialista gera a resposta inicial e mantém o áudio aberto,
        # conversando livremente com o usuário. O turno só encerra quando
        # a IA aciona devolver_para_nathalia ou transferir_para_especialista.
        async def _handle_activation(msg: dict) -> None:
            """Processa ativação deste especialista de forma assíncrona (Peer-to-Peer)."""
            turn_id = msg.get("turn_id")
            started_at = monotonic()

            async def _emit(signal_type: str, extra: Optional[dict] = None) -> None:
                payload = {
                    "version": DATA_PACKET_SCHEMA_VERSION,
                    "type": signal_type,
                    "turn_id": turn_id,
                    "agent_id": spec_id,
                    "name": name,
                }
                if extra:
                    payload.update(extra)
                await _safe_publish_data(room.local_participant, payload)
            
            try:
                ctx_summary = msg.get("transcript_summary", "")
                context_text = msg.get("context", "")
                context_state = msg.get("context_state") or {}
                context_state_str = json.dumps(context_state, ensure_ascii=False)

                if ctx_summary or context_state:
                    # REMOVIDO: agent.update_instructions() causava fechamento do WebSocket (Erro 1007 WebRTC Gemini Native)
                    # devido à injeção abrupta de tokens gigantes na camada sistêmica de áudio.
                    # As instruções agora seguem via PROMPT simples do turno (generate_reply).
                    pass

                await _emit("agent_activated", {"activated_in_ms": int((monotonic() - started_at) * 1000)})
                _subscribe_user_audio()

                # ── CRÍTICO: registra o comprimento do transcript no momento da ativação ──
                # Toda verificação de handoff usará APENAS mensagens após este ponto.
                agent._activation_transcript_len = len(blackboard.transcript)
                agent._user_messages_since_activation = 0
                logger.info(
                    f"[{name}] Ativado. Transcript atual: {agent._activation_transcript_len} msgs. "
                    f"Contador de msgs do usuário zerado."
                )

                # Determina o prompt baseado no tipo de ativação injetando todo o contexto sem quebrar a VAD API
                from_agent = msg.get("from_name")
                if from_agent:
                    # Transferência lateral: outro especialista repassou
                    prompt = (
                        f"{from_agent} acabou de transferir a palavra para você. "
                        f"O contexto da pergunta do usuário é: {context_text}. "
                        f"O Resumo da conversa até agora é: {ctx_summary}. "
                        f"Inicie sua fala reconhecendo o colega e respondendo diretamente à pergunta do usuário.\n"
                        f"REGRAS ABSOLUTAS (violá-las vai causar erro):\n"
                        f"1. NUNCA acione ferramentas de handoff na sua PRIMEIRA fala. Responda e faça uma pergunta.\n"
                        f"2. Mantenha a conversa: ouça o usuário, aprofunde, pergunte.\n"
                        f"3. Somente use `devolver_para_nathalia` ou `transferir_para_especialista` DEPOIS que o usuário "
                        f"disser EXPLICITAMENTE que não tem mais perguntas para você (ex: 'entendi tudo', 'não tenho mais dúvidas', "
                        f"'pode voltar para a Nathália'). Se tentar antes, a ferramenta bloqueará automaticamente.\n"
                        f"4. Enquanto o usuário estiver interagindo (fazendo perguntas, comentando), CONTINUE a conversa."
                    )
                else:
                    # Ativação normal pela Nathália
                    prompt = (
                        f"Nathália acabou de te acionar. O contexto da pergunta do usuário é: {context_text}. "
                        f"O Resumo da conversa até agora é: {ctx_summary}. "
                        f"Responda a questão do usuário detalhando sua visão e experiência na sua área.\n"
                        f"REGRAS ABSOLUTAS (violá-las vai causar erro):\n"
                        f"1. NUNCA acione ferramentas de handoff na sua PRIMEIRA fala. Responda e faça uma pergunta.\n"
                        f"2. Mantenha a conversa por múltiplos turnos: escute o usuário, aprofunde, pergunte.\n"
                        f"3. Somente use `devolver_para_nathalia` DEPOIS que o usuário disser EXPLICITAMENTE que não tem "
                        f"mais perguntas para você (ex: 'entendi tudo', 'não tenho mais dúvidas', 'ficou tudo claro', "
                        f"'pode continuar'). A ferramenta bloqueará automaticamente se tentar muito cedo.\n"
                        f"4. Enquanto o usuário estiver interagindo, CONTINUE. Não encerre antes de ele autorizar."
                    )

                # Gera resposta inicial
                await asyncio.wait_for(
                    session.generate_reply(instructions=prompt),
                    timeout=SPECIALIST_GENERATION_TIMEOUT_SECONDS,
                )
                logger.info(f"[{name}] Resposta inicial gerada. Entrando em modo conversa livre (Peer-to-Peer).")

                # HANDOVER PEER-TO-PEER: Aguarda o agente decidir encerrar via ferramenta
                # O agente continua escutando o áudio do usuário e respondendo livremente
                # até acionar devolver_para_nathalia ou transferir_para_especialista.
                # Reset do evento de handover para este turno
                agent._handover_event.clear()
                agent._handover_result = None

                # Inicia tracking de inatividade (reseta agora para o tempo de fala não explodir)
                agent._blackboard.set_user_speaking(False)
                try:
                    while not agent._handover_event.is_set():
                        try:
                            await asyncio.wait_for(agent._handover_event.wait(), timeout=2.0)
                            break
                        except asyncio.TimeoutError:
                            pass

                        timeout_reason = get_specialist_timeout_reason(
                            started_at=started_at,
                            last_interaction_at=agent._blackboard.last_interaction_at,
                            user_currently_speaking=agent._blackboard.user_currently_speaking,
                            now=monotonic(),
                        )
                        if timeout_reason == "silence_timeout":
                            logger.warning(
                                f"[{name}] Silêncio prolongado detectado (>{SPECIALIST_SILENCE_TIMEOUT_SECONDS:.0f}s). "
                                "Devolvendo para Nathália."
                            )
                            agent._handover_result = {"type": "nathalia", "reason": timeout_reason}
                            break
                        if timeout_reason == "turn_timeout":
                            logger.warning(
                                f"[{name}] Limite do turno excedido ({SPECIALIST_MAX_TURN_TIMEOUT_SECONDS:.0f}s). "
                                "Devolvendo para Nathália."
                            )
                            agent._handover_result = {"type": "nathalia", "reason": timeout_reason}
                            break
                except Exception as handover_err:
                    logger.warning(f"[{name}] Erro ao monitorar handover: {handover_err}")

                # Processar resultado do handover
                handover = agent._handover_result or {"type": "nathalia"}

                if handover.get("type") == "transfer":
                    # Transferência lateral para outro especialista
                    target_id = handover["target"]
                    transfer_context = handover.get("context", context_text)
                    from_name = handover.get("from_name", name)
                    await _emit("agent_transferred", {
                        "elapsed_ms": int((monotonic() - started_at) * 1000),
                        "target_agent_id": target_id,
                        "transfer_context": transfer_context,
                        "from_name": from_name,
                    })
                    logger.info(f"[{name}] TRANSFERÊNCIA LATERAL para {target_id}. Contexto: {transfer_context[:80]}.")
                else:
                    # Devolução padrão para Nathália
                    handover_reason = handover.get("reason", "unspecified")
                    await _emit(
                        "agent_done",
                        {
                            "elapsed_ms": int((monotonic() - started_at) * 1000),
                            "handover_reason": handover_reason,
                            "last_user_message": handover.get("last_user_message", ""),
                        },
                    )
                    logger.info(
                        f"[{name}] Turno encerrado. Palavra devolvida à Nathália. "
                        f"Motivo={handover_reason}"
                    )

            except asyncio.CancelledError:
                asyncio.create_task(_emit("agent_cancelled", {"elapsed_ms": int((monotonic() - started_at) * 1000)}))
                logger.info(f"[{name}] Geração INTERROMPIDA (turno de outro agente).")
                raise
            except asyncio.TimeoutError:
                await _emit("agent_timeout", {"elapsed_ms": int((monotonic() - started_at) * 1000)})
                logger.warning(f"[{name}] Timeout na geração da resposta (turno={turn_id}).")
            except Exception as e:
                await _emit("agent_error", {"error": str(e)[:240]})
                logger.warning(f"[{name}] Erro na ativação assíncrona: {e}")
            finally:
                _unsubscribe_user_audio()

        _generation_task: Optional[asyncio.Task] = None
        _last_activation_at: float = 0.0
        _last_turn_id: int = -1

        @room.on("data_received")
        def _on_data(dp: rtc.DataPacket) -> None:
            nonlocal _generation_task, _last_activation_at, _last_turn_id
            try:
                msg = json.loads(dp.data.decode())
                msg_version = msg.get("version")
                msg_type = msg.get("type")

                if msg_version and msg_version != DATA_PACKET_SCHEMA_VERSION:
                    logger.warning(
                        f"[{name}] Data packet versão incompatível: {msg_version} "
                        f"(esperado: {DATA_PACKET_SCHEMA_VERSION})."
                    )

                if msg_type == "activate_agent":
                    turn_id = msg.get("turn_id")
                    if msg.get("agent_id") == spec_id:
                        if isinstance(turn_id, int) and turn_id <= _last_turn_id:
                            logger.info(f"[{name}] Turno ignorado por ordem antiga (turno={turn_id}).")
                            return
                        now = monotonic()
                        if now - _last_activation_at < ACTIVATION_DEBOUNCE_SECONDS:
                            logger.info(f"[{name}] Ativação ignorada por debounce.")
                            return
                        _last_activation_at = now
                        if isinstance(turn_id, int):
                            _last_turn_id = turn_id
                        if _generation_task and not _generation_task.done():
                            _generation_task.cancel()
                        _generation_task = asyncio.create_task(_handle_activation(msg))
                    else:
                        if _generation_task and not _generation_task.done():
                            _generation_task.cancel()
                            logger.info(f"[{name}] Geração CANCELADA (turno de {msg.get('agent_id')}).")
                        _generation_task = None
                        _unsubscribe_user_audio()
                        logger.debug(f"[{name}] DESATIVADO (ativo agora: {msg.get('agent_id')}).")
            except Exception as e:
                logger.warning(f"[{name}] Erro ao processar data packet: {e}")

        return session

    except Exception as e:
        logger.error(f"[{name}] Erro ao iniciar: {e}", exc_info=True)
        return None

async def entrypoint(ctx: JobContext) -> None:
    # Acessar nome da sala com segurança
    room_name = ctx.job.room.name if hasattr(ctx, "job") and ctx.job.room else ctx.room.name
    try:
        await _run_entrypoint(ctx)
    except asyncio.CancelledError:
        logger.info(f"[Job] Erro/Tarefa Cancelada no entrypoint (CancelledError). Sala: {room_name}")
    except Exception as e:
        logger.error(f"[Job] Erro crítico no entrypoint: {e}", exc_info=True)
    finally:
        _active_rooms.discard(room_name)
        logger.info(f"[Guard] Sala '{room_name}' liberada do guard após encerramento global da task. Salas ativas após limpeza: {_active_rooms}")

async def _run_entrypoint(ctx: JobContext) -> None:
    shutdown_event = asyncio.Event()
    
    # Log em arquivo para diagnóstico (compatível com Windows e Linux)
    log_path = os.path.join(tempfile.gettempdir(), "mentoria_agent.log")
    _fh = logging.FileHandler(log_path, mode="a")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)

    logger.info(f"=== ENTRYPOINT MENTORIA AI v5 – sala: {ctx.room.name} ===")

    # Conecta o worker ao room (HostAgent/Nathália) sem auto-subscribe para evitar
    # escutar a voz dos outros agentes e gerar confusão e interferência (mandarim/árabe).
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Worker conectado ao room: {ctx.room.name} [Host AUDIO_ONLY]")

    # Garante a subscrição manual no áudio do usuário principal e convidados
    for p in ctx.room.remote_participants.values():
        if p.identity.startswith("user-") or p.identity.startswith("guest-"):
            for pub in p.track_publications.values():
                if pub.kind == rtc.TrackKind.KIND_AUDIO:
                    pub.set_subscribed(True)
                    logger.info(f"[Host] Áudio de {p.identity} subscrito (init).")

    # Monitora novas tracks publicadas para caso o usuário ou convidado entre depois do agente
    @ctx.room.on("track_published")
    def on_track_published(pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if (participant.identity.startswith("user-") or participant.identity.startswith("guest-")) and pub.kind == rtc.TrackKind.KIND_AUDIO:
            pub.set_subscribed(True)
            logger.info(f"[Host] Áudio de {participant.identity} subscrito dinamicamente.")

    room_name = ctx.room.name
    # Extrair UUID do projeto a partir do _room name (ex: mentoria-<uuid>-<suffix>)
    project_uuid_match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", room_name, re.IGNORECASE)
    project_id = project_uuid_match.group(1) if project_uuid_match else room_name.replace("mentoria-", "", 1)

    # Blackboard compartilhado
    blackboard = Blackboard(project_name=project_id)

    def _parse_transcript(raw_transcript: str) -> list[dict]:
        entries: list[dict] = []
        for line in raw_transcript.splitlines():
            text_line = line.strip()
            if not text_line:
                continue
            match = re.match(r"^\[(.+?)\]:\s*(.*)$", text_line)
            if not match:
                continue
            role = match.group(1).strip()
            content = match.group(2).strip()
            if content:
                entries.append({"role": role, "content": content})
        return entries

    # Carregar contexto de retomada da API
    async def fetch_resume_context():
        import urllib.request
        import json

        api_url = os.getenv("NEXT_API_URL", "http://localhost:5000").rstrip("/") + f"/api/projects/{project_id}/resume-context"

        def _get():
            try:
                logger.info(f"[Resume] Tentando buscar contexto em: {api_url}")
                internal_secret = os.getenv("INTERNAL_API_SECRET", "")
                req = urllib.request.Request(api_url, headers={
                    "User-Agent": "MentoriaAI-Worker/1.0",
                    "X-Internal-Secret": internal_secret,
                })
                with urllib.request.urlopen(req) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                logger.warning(f"Erro ao buscar contexto de retomada na URL {api_url}: {e}")
                return None

        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(None, _get)
        if not payload:
            return

        project_info = payload.get("project") or {}
        last_session = payload.get("lastSession") or {}
        transcript = last_session.get("transcript") or ""

        blackboard.project_name = project_info.get("projectTitle") or blackboard.project_name
        blackboard.user_name = project_info.get("userName") or blackboard.user_name

        if transcript:
            parsed_entries = _parse_transcript(transcript)
            if parsed_entries:
                blackboard.transcript = parsed_entries[-1500:]
                for entry in blackboard.transcript:
                    role = (entry.get("role") or "").lower()
                    content = (entry.get("content") or "").strip()
                    if not content:
                        continue
                    blackboard._update_memory(entry.get("role", ""), content)
                    if not blackboard.user_query and role in ("usuário", "você", "user"):
                        blackboard.user_query = content
                logger.info(f"[Resume] Contexto de retomada carregado com {len(blackboard.transcript)} mensagens.")

        generated_docs = payload.get("generatedDocs") or []
        if generated_docs:
            for d in generated_docs:
                if d.get("markdownContent"):
                    doc_text = f"DOCUMENTO ANTERIOR GERADO: {d.get('title', 'Plano')}\n\n{d['markdownContent']}"
                    blackboard.documentos_disponiveis.append(doc_text)
            logger.info(f"[Resume] Carregados {len(generated_docs)} documentos gerados em sessoes anteriores.")

    # Carregar documentos da API em background
    async def fetch_docs():
        import urllib.request
        import json
        api_url = os.getenv("NEXT_API_URL", "http://localhost:5000").rstrip("/") + f"/api/projects/{project_id}/documents"
        def _get():
            try:
                logger.info(f"[Docs] Tentando buscar documentos em: {api_url}")
                req = urllib.request.Request(api_url, headers={"User-Agent": "MentoriaAI-Worker/1.0"})
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode())
                    return [d.get("content", "") for d in data if d.get("content")]
            except Exception as e:
                logger.warning(f"Erro ao buscar documentos da API na URL {api_url}: {e}")
                return []
        
        loop = asyncio.get_running_loop()
        docs = await loop.run_in_executor(None, _get)
        blackboard.documentos_disponiveis = docs
        logger.info(f"[Docs] Foram carregados {len(docs)} documentos para a sessão.")

    resume_task = asyncio.create_task(fetch_resume_context())
    asyncio.create_task(fetch_docs())

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

    host_avatar_task = _prefetch_avatar_session("host", host_session, ctx.room)
    if host_avatar_task:
        logger.info("[Host] Pré-aquecimento do avatar da Nathália iniciado em background.")

    # Guarda referência ao host_session no HostAgent para retomada automática
    host_agent._host_session = host_session

    # ------------------------------------------------------------------
    # 2. Fluxo de Apresentação ou Retomada de Sessão
    # ------------------------------------------------------------------
    async def welcome_and_introductions() -> None:
        """
        Se o Blackboard já tem histórico (retomada de sessão interrompida),
        Nathália retoma sem repetir apresentações.
        Caso contrário, executa o fluxo completo de boas-vindas.

        Estratégia de inicialização paralela:
        - Nathália fala enquanto os especialistas conectam em paralelo (asyncio.gather).
        - Quando Nathália terminar, todos os especialistas já estão prontos.
        - Apresentações ocorrem imediatamente em sequência, sem delay de conexão.
        """
        await resume_task
        is_resuming = len(blackboard.transcript) > 0

        # CORREÇÃO CRÍTICA: Aguarda o avatar da Nathália estar completamente pronto
        # ANTES de gerar qualquer reply de áudio. Se o avatar não estiver pronto,
        # o generate_reply descarta o áudio silenciosamente.
        if host_avatar_task:
            logger.info("[Host] Aguardando avatar da Nathália (Beyond Presence) concluir inicialização...")
            await host_avatar_task
            logger.info("[Host] Avatar da Nathália pronto. Aguardando estabilização do RealtimeModel...")
        else:
            logger.info("[Host] Avatar da Nathália indisponível ou desativado. Seguindo sem avatar.")

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

            # ── RECONEXÃO EM PARALELO COM O GREETING ──────────────────
            # CRÍTICO: A reconexão dos especialistas começa ANTES do generate_reply
            # para evitar deadlock: Nathália pode chamar _activate_specialist()
            # (como tool call) DURANTE generate_reply. O Readiness Gate aguardará
            # o evento de prontidão, que só é definido quando o especialista conecta.
            # Se a reconexão rodasse DEPOIS de generate_reply, haveria deadlock.
            async def _reconnect_sequentially():
                logger.info("[Retomada] Conectando especialistas sequencialmente para evitar rate limits...")
                for sid in SPECIALIST_ORDER:
                    if not blackboard.is_active:
                        break
                    await _start_specialist_in_room(
                        spec_id=sid,
                        blackboard=blackboard,
                        ws_url=ws_url,
                        lk_api_key=lk_api_key,
                        lk_api_secret=lk_api_secret,
                        room_name=ctx.room.name,
                        host_room=ctx.room,
                        auto_introduce=False,
                    )
                    # Sinaliza prontidão em-processo — desbloqueia o Readiness Gate.
                    host_agent._ready_specialists.add(sid)
                    ev = host_agent._specialist_ready_events.get(sid)
                    if ev is not None:
                        ev.set()
                    logger.info(f"[Retomada] {SPECIALIST_NAMES.get(sid, sid)} pronto e liberado para ativação.")
                    await asyncio.sleep(5.0)  # Delay para respeitar rate limits do Gemini
                logger.info("[Host] Retomada concluída. Todos os especialistas reconectados.")

            reconnect_task = asyncio.create_task(_reconnect_sequentially())

            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=(
                            f"Retome a sessão de forma calorosa dizendo: {resumption_msg} "
                            f"Contexto da sessão anterior para você: {resumption_context}"
                        ),
                    ),
                    timeout=HOST_GENERATE_REPLY_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.warning(
                    f"[Host] Erro ao retomar sessão: {type(e).__name__}: {e}",
                    exc_info=True,
                )

            # Aguarda a reconexão terminar (caso o greeting tenha sido mais rápido)
            if not reconnect_task.done():
                logger.info("[Retomada] Aguardando reconexão dos especialistas restantes...")
                await reconnect_task

        else:
            # ── MODO INICIAL ───────────────────────────────────────────
            # Fluxo: Nathália e especialistas conectam em PARALELO desde o início.
            # Enquanto Nathália fala, os especialistas já estão prontos.
            # Assim que Nathália terminar, cada especialista se apresenta
            # imediatamente em sequência — sem delay de conexão.
            host_greeting = (
                "Olá! Seja muito bem-vindo ao Hive Mind! "
                "Sou a Nathália, sua apresentadora e mentora líder desta sessão. "
                "Montei uma equipe completa de especialistas para te ajudar hoje: "
                "Carlos no financeiro, Daniel no jurídico, Rodrigo em marketing "
                "e Ana em tecnologia. "
                "Além deles, o Marco, nosso estrategista-chefe, está trabalhando nos bastidores "
                "documentando tudo e preparando um plano de execução completo para você! "
                "Eles vão se apresentar um a um agora. Fique à vontade!"
            )

            # Conecta os especialistas em CASCATA (1-2s entre cada) enquanto
            # Nathália já começa a falar. Evita rate limits do Gemini API
            # causados por múltiplos handshakes WebSocket simultâneos.
            async def _connect_sequentially() -> list:
                results = []
                for i, sid in enumerate(SPECIALIST_ORDER):
                    if not blackboard.is_active:
                        results.append(None)
                        continue
                    try:
                        result = await _start_specialist_in_room(
                            spec_id=sid,
                            blackboard=blackboard,
                            ws_url=ws_url,
                            lk_api_key=lk_api_key,
                            lk_api_secret=lk_api_secret,
                            room_name=ctx.room.name,
                            host_room=ctx.room,
                            auto_introduce=False,
                        )
                        results.append(result)
                    except Exception as e:
                        logger.warning(f"[Apresentação] Erro ao conectar {SPECIALIST_NAMES.get(sid, sid)}: {e}")
                        results.append(e)
                    # Delay escalonado (1.5s) para dar respiro ao Gemini API entre conexões
                    if i < len(SPECIALIST_ORDER) - 1:
                        await asyncio.sleep(1.5)
                return results

            logger.info("[Apresentação] Conectando especialistas em cascata (1-2s entre cada)...")
            connect_task = asyncio.create_task(_connect_sequentially())

            logger.info("[Host] Nathália enviando apresentação inicial (sem perguntas)...")
            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=(
                            f"Apresente-se de forma calorosa e natural dizendo: {host_greeting} "
                            f"NÃO faça NENHUMA pergunta. Apenas apresente-se e anuncie o time. "
                            f"Encerre sua fala após a apresentação."
                        ),
                    ),
                    timeout=HOST_GENERATE_REPLY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[Host] Timeout ({HOST_GENERATE_REPLY_TIMEOUT_SECONDS:.0f}s) ao gerar reply inicial.")
            except Exception as e:
                logger.warning(f"[Host] Erro ao gerar reply inicial: {type(e).__name__}: {e}", exc_info=True)

            # Aguarda as conexões (já devem estar prontas, pois conectam em ~2s)
            if not blackboard.is_active:
                connect_task.cancel()
                return
            sessions_raw = await connect_task
            sessions = list(sessions_raw)
            if not blackboard.is_active:
                return

            # Sinaliza prontidão para todos os especialistas conectados com sucesso
            for sid, result in zip(SPECIALIST_ORDER, sessions):
                if not isinstance(result, Exception) and result is not None:
                    host_agent._ready_specialists.add(sid)
                    ev = host_agent._specialist_ready_events.get(sid)
                    if ev is not None:
                        ev.set()
            logger.info("[Apresentação] Todos conectados. Iniciando apresentações imediatamente...")

            # Executa as apresentações sequencialmente — um por vez
            for sid, spec_session in zip(SPECIALIST_ORDER, sessions):
                if not blackboard.is_active:
                    logger.info("[Apresentação] Job encerrando, abortando sequência.")
                    return

                spec_name = SPECIALIST_NAMES[sid]

                if isinstance(spec_session, Exception) or not spec_session:
                    logger.warning(f"[Apresentação] {spec_name} falhou ao conectar. Pulando. (Err: {spec_session})")
                    continue

                intro_text = SPECIALIST_INTRODUCTIONS[sid]
                logger.info(f"[Apresentação] {spec_name} se apresentando...")

                for attempt in range(2):
                    try:
                        await asyncio.wait_for(
                            spec_session.generate_reply(
                                instructions=(
                                    f"Apresente-se de forma calorosa e natural dizendo: {intro_text} "
                                    f"Máximo 3 frases. Não faça perguntas ao usuário de forma alguma. "
                                    f"Apenas e unicamente se apresente e conclua a fala."
                                ),
                            ),
                            timeout=HOST_GENERATE_REPLY_TIMEOUT_SECONDS,
                        )
                        logger.info(f"[Apresentação] {spec_name} concluiu.")
                        await asyncio.sleep(POST_INTRO_WAIT)
                        break
                    except Exception as e:
                        if attempt == 0:
                            logger.warning(f"[Apresentação] Timeout/Erro na apresentação de {spec_name}. Tentando de novo... ({e})")
                            await asyncio.sleep(1.0)
                        else:
                            logger.error(f"[Apresentação] Falha final ao apresentar {spec_name}: {e}")

            logger.info("[Apresentação] Todos os especialistas foram apresentados.")

            if not blackboard.is_active:
                return

            # SOMENTE AGORA Nathália faz a primeira pergunta ao usuário
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

            logger.info("[Host] Nathália fazendo pergunta inicial (pós-apresentações)...")
            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=f"Faça a seguinte pergunta de forma calorosa e natural: {closing}",
                    ),
                    timeout=HOST_GENERATE_REPLY_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.warning(f"[Host] Erro na pergunta inicial: {e}")

            logger.info("[Host] Fluxo de abertura concluído.")

    # Iniciar o fluxo de apresentações paralelamente
    asyncio.create_task(welcome_and_introductions())

    @ctx.room.on("disconnected")
    def _on_room_disconnected(*args, **kwargs) -> None:
        logger.info("[Room] Room principal desconectado. Disparando shutdown.")
        shutdown_event.set()

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        if participant.identity.startswith("user-"):
            logger.info(f"[Room] Usuário principal {participant.identity} desconectou. Disparando shutdown para liberar a sala.")
            # Quando a aba é fechada ou reiniciada, garante que a sala sai do cache do worker
            shutdown_event.set()
        elif participant.identity.startswith("guest-"):
            # Convidados podem sair sem afetar a sessão
            logger.info(f"[Room] Convidado {participant.identity} saiu da sala. Sessão continua normalmente.")

    # _extract_transcribed_text e _should_ignore_user_transcript são módulo-nível.
    # Aqui apenas definimos _record_user_transcript que precisa do contexto local (ctx, blackboard).
    def _record_user_transcript(text: str, speaker_label: str = "Você") -> None:
        text = text.strip()
        if not text or _should_ignore_user_transcript(text):
            return

        logger.info(f"[Usuário fala] {text}")
        blackboard.add_message("Usuário", text)
        if not blackboard.user_query:
            blackboard.user_query = text

        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({
                    "version": DATA_PACKET_SCHEMA_VERSION,
                    "type": "transcript",
                    "speaker": speaker_label,
                    "text": text,
                }).encode(),
                reliable=True,
            )
        )

    # ------------------------------------------------------------------
    # Captura transcrição do usuário → Blackboard + frontend
    # ------------------------------------------------------------------
    @host_session.on("user_input_transcribed")
    def _on_user_speech(event) -> None:
        if not blackboard.is_active:
            return

        # ==========================================================
        # FILTRO 1: Apenas transcrições FINAIS são relevantes.
        # Transcrições parciais (is_final=False) são intermediárias
        # e podem conter ruído/alucinações. Ignoramos até ser final.
        # ==========================================================
        if not getattr(event, "is_final", True):
            return

        _record_user_transcript(_extract_transcribed_text(event))

    # ------------------------------------------------------------------
    # Captura transcrição da Nathália → Blackboard + frontend
    # ------------------------------------------------------------------
    @host_session.on("conversation_item_added")
    def _on_host_speech(event) -> None:
        if not blackboard.is_active:
            return

        item = getattr(event, "item", None)
        if item is None:
            return
            
        role = getattr(item, "role", None)
        if role != "assistant":
            return  # Ignora mensagens do usuário transcritas (ECHO fix)

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
                json.dumps({
                    "version": DATA_PACKET_SCHEMA_VERSION,
                    "type": "transcript",
                    "speaker": "Nathália",
                    "text": text,
                }).encode(),
                reliable=True,
            )
        )

    # ------------------------------------------------------------------
    # Escuta mensagens de dados do frontend
    # ------------------------------------------------------------------
    @ctx.room.on("data_received")
    def _on_data_received(dp: rtc.DataPacket) -> None:
        try:
            msg = json.loads(dp.data.decode())
            msg_type = msg.get("type")

            if msg_type in {"agent_activated", "agent_done", "agent_timeout", "agent_cancelled", "agent_error"}:
                host_agent.handle_specialist_signal(msg)
                return

            if msg_type == "agent_transferred":
                # Transferência lateral: um especialista transferiu para outro
                host_agent.handle_specialist_signal({**msg, "type": "agent_done"})
                target_id = msg.get("target_agent_id")
                transfer_context = msg.get("transfer_context", "")
                from_name = msg.get("from_name", "")
                if target_id:
                    logger.info(f"[Room] Transferência lateral de {msg.get('agent_id')} para {target_id}.")
                    # Acionar o especialista destino diretamente via HostAgent
                    async def _lateral_activate():
                        await host_agent._activate_specialist(
                            target_id,
                            transfer_context,
                            _lateral_from_name=from_name,
                        )
                    asyncio.create_task(_lateral_activate())
                return

            if msg_type == "end_session":
                logger.info("[Room] Pedido de encerramento recebido do frontend.")

                async def _end_session_flow():
                    if not blackboard.marco_triggered:
                        logger.info("[Room] Marco não foi acionado. Acionando geração automática forçada do plano.")
                        u_name = blackboard.user_name or "empreendedor"
                        p_name = blackboard.project_name or "seu projeto"
                        # Bloqueia a finalização da sessão até a emissão do PDF pelo Marco
                        try:
                            await host_agent.gerar_plano_forcado(u_name, p_name)
                        except Exception as e:
                            logger.error(f"[Room] Erro na geração automática forçada do Marco: {e}")

                    # Após Marco terminar a geração, publica o encerramento que fará o redirect final no Frontend
                    await ctx.room.local_participant.publish_data(
                        json.dumps({
                            "version": DATA_PACKET_SCHEMA_VERSION,
                            "type": "session_end",
                            "full_transcript": blackboard.get_full_transcript(),
                            "context_summary": blackboard.get_context_summary(),
                            "context_state": blackboard.get_structured_context(),
                        }).encode(),
                        reliable=True,
                    )
                    shutdown_event.set()

                asyncio.create_task(_end_session_flow())

            elif msg_type == "set_project_name":
                blackboard.project_name = msg.get("name", "")
                logger.info(f"[Room] Nome do projeto definido: {blackboard.project_name}")

            elif msg_type == "set_user_name":
                blackboard.user_name = msg.get("name", "")
                logger.info(f"[Room] Nome do usuário definido: {blackboard.user_name}")

            elif msg_type == "pause_ai":
                logger.info("[Room] IA pausada pelo anfitrião — modo debate humano.")
                async def _pause_ai():
                    try:
                        result = host_agent.update_instructions(
                            HOST_PROMPT + "\n\n## MODO SILÊNCIO ATIVADO\n"
                            "O anfitrião ativou o modo debate. Você DEVE ficar em SILÊNCIO ABSOLUTO. "
                            "NÃO fale sob nenhuma circunstância até receber a instrução de retomar."
                        )
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.warning(f"[Room] Erro ao pausar IA: {e}")
                asyncio.create_task(_pause_ai())

            elif msg_type == "resume_ai":
                logger.info("[Room] IA reativada pelo anfitrião — modo normal.")
                async def _resume_ai():
                    try:
                        result = host_agent.update_instructions(HOST_PROMPT)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.warning(f"[Room] Erro ao reativar IA: {e}")
                asyncio.create_task(_resume_ai())

        except Exception as e:
            logger.warning(f"[Room] Erro ao processar data packet do frontend: {e}")

    # ------------------------------------------------------------------
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

        async def persist_resume_snapshot() -> None:
            import urllib.request
            import json

            transcript_snapshot = blackboard.get_full_transcript().strip()
            if not transcript_snapshot:
                return

            api_url = os.getenv("NEXT_API_URL", "http://localhost:5000") + f"/api/projects/{project_id}/resume-context"
            payload = json.dumps({"transcript": transcript_snapshot}).encode("utf-8")

            def _post():
                try:
                    internal_secret = os.getenv("INTERNAL_API_SECRET", "")
                    req = urllib.request.Request(
                        api_url,
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-Internal-Secret": internal_secret,
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5.0):
                        return True
                except Exception as e:
                    logger.warning(f"[Resume] Falha ao persistir snapshot de retomada: {e}")
                    return False

            try:
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(loop.run_in_executor(None, _post), timeout=6.0)
            except Exception as e:
                logger.warning(f"[Resume] Timeout ao persistir snapshot: {e}")

        await persist_resume_snapshot()

        # Desconecta especialistas PARALELAMENTE para não estourar o tempo e segurar a sala no Guard
        disconnect_tasks = []
        for spec_room in blackboard.specialist_rooms:
            disconnect_tasks.append(asyncio.wait_for(spec_room.disconnect(), timeout=1.5))
        
        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        # Remove o room do Guard o mais rápido possível para liberar nova conexão do usuário 
        room_name = getattr(ctx.job.room, "name", ctx.room.name) if getattr(ctx, "job", None) else ctx.room.name
        _active_rooms.discard(room_name)

        # DESCONECTA O HOST E A SALA PRINCIPAL (Libera o ambiente)
        try:
            await asyncio.wait_for(ctx.room.disconnect(), timeout=2.0)
            logger.info("[Job] Sala principal forçadamente desconectada pelo agente Host.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[Job] Erro ao tentar desconectar sala principal: {e}")

        room_name = getattr(ctx.job.room, "name", ctx.room.name) if getattr(ctx, "job", None) else ctx.room.name

        metrics = blackboard.orchestration_metrics
        avg_ack_ms = (
            metrics["activation_ack_latency_ms_total"] / metrics["activations_total"]
            if metrics["activations_total"] else 0.0
        )
        avg_done_ms = (
            metrics["activation_done_latency_ms_total"] / metrics["activations_total"]
            if metrics["activations_total"] else 0.0
        )
        logger.info(
            "[Metrics] activations_total=%s succeeded=%s timeout=%s cancelled=%s avg_ack_ms=%.1f avg_done_ms=%.1f",
            int(metrics["activations_total"]),
            int(metrics["activations_succeeded"]),
            int(metrics["activations_timeout"]),
            int(metrics["activations_cancelled"]),
            avg_ack_ms,
            avg_done_ms,
        )

        _active_rooms.discard(room_name)
        
        logger.info(f"[Job] Encerrado com sucesso para a sala '{room_name}'. Salas ativas: {_active_rooms}")

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
