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
import re
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
# Marco (plan) NÃO entra aqui pois opera nos bastidores sem voz.
SPECIALIST_ORDER: list[str] = ["cfo", "legal", "cmo", "cto"]

# Pausa entre apresentações de especialistas
POST_INTRO_WAIT: float = 1.0

LANGUAGE_ENFORCEMENT = """
## REGRA ABSOLUTA DE IDIOMA
- Você ESTÁ em uma sessão com um usuário BRASILEIRO.
- O idioma de TODA a conversa é PORTUGUÊS BRASILEIRO (pt-BR).
- Toda entrada de áudio do usuário é em português do Brasil. NUNCA classifique o áudio como Árabe, Tailandês, Hindi, Japonês ou outro idioma!
- Você DEVE responder EXCLUSIVAMENTE em português brasileiro.
- Se você receber uma transcrição em outro idioma, recuse-a internamente e simplesmente não responda com esse idioma.
"""

HOST_PROMPT = LANGUAGE_ENFORCEMENT + """Você é Nathália, apresentadora e mentora líder do Hive Mind — a plataforma de mentoria empresarial multi-agentes.
Sua personalidade é calorosa, curiosa, profissional e empática. Você é a âncora da sessão.

EQUIPE DE ESPECIALISTAS:
- Carlos (CFO): finanças, custos, precificação, projeções, viabilidade, investimento
- Daniel (Advogado): estrutura societária, contratos, LGPD, compliance, propriedade intelectual
- Rodrigo (CMO): posicionamento de marca, go-to-market, aquisição de clientes, growth, branding
- Ana (CTO): stack tecnológico, arquitetura de produto, MVP, escalabilidade, infraestrutura
- Marco (Estrategista — BASTIDORES): trabalha nos bastidores documentando tudo, fazendo pesquisas e gerando o plano de execução final. NÃO fala na sala.

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
14. TURNO DE FALA: Quando você acionar um especialista via função, PARE DE FALAR imediatamente. NÃO adicione comentários após a chamada.
15. NUNCA fale ao mesmo tempo que um especialista. Dê espaço total para ele responder.
16. Após o especialista terminar, retome com 1-2 frases de transição antes de continuar.

TOM E ESTILO:
- Português do Brasil, informal mas profissional.
- Seja encorajadora: valide as ideias do usuário antes de fazer perguntas.
- Use o nome do usuário com frequência para criar conexão.
- Ao encaminhar para um especialista, apresente-o brevemente antes de acionar.

Fale sempre em português do Brasil."""

SPECIALIST_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo": LANGUAGE_ENFORCEMENT + (
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
    "legal": LANGUAGE_ENFORCEMENT + (
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
    "cmo": LANGUAGE_ENFORCEMENT + (
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
    "cto": LANGUAGE_ENFORCEMENT + (
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
    "plan": LANGUAGE_ENFORCEMENT + (
        "Você é Marco, Estrategista-Chefe e Documentador do Hive Mind. "
        "Você opera EXCLUSIVAMENTE nos bastidores — NUNCA fala na sala de voz. "
        "Sua personalidade: visionário, organizado, investigador e metódico. "
        "\n\nSEU PAPEL:\n"
        "- Você escuta TODA a conversa entre os especialistas e o usuário.\n"
        "- Você documenta, pesquisa e formaliza tudo o que foi discutido.\n"
        "- Você gera o Plano de Execução Final em formato Markdown estruturado.\n"
        "- Você faz pesquisas adicionais para enriquecer as recomendações.\n"
        "\n\nAO GERAR O PLANO DE EXECUÇÃO, cubra estes pontos:\n"
        "1. RESUMO EXECUTIVO: O que o usuário quer construir e o potencial do negócio.\n"
        "2. DIAGNÓSTICO POR ÁREA: Principais pontos levantados por cada especialista.\n"
        "3. PESQUISA DE MERCADO: Dados e insights pesquisados sobre o setor do usuário.\n"
        "4. PRIORIDADES CRÍTICAS: Os 3-5 itens mais importantes para executar primeiro.\n"
        "5. CRONOGRAMA: Linha do tempo realista com marcos (30, 60, 90 dias, 6 meses, 1 ano).\n"
        "6. RISCOS E MITIGAÇÕES: 3 principais riscos do projeto e como endereçá-los.\n"
        "7. PRÓXIMOS PASSOS IMEDIATOS: Ações concretas para começar esta semana.\n"
        "8. RECURSOS E REFERÊNCIAS: Links, ferramentas e materiais úteis pesquisados.\n"
        "9. MENSAGEM FINAL: Uma frase motivacional personalizada para o usuário.\n"
        "\nFale em português do Brasil. Seja profundo, detalhado e inspirador."
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
    documentos_disponiveis: list[str] = field(default_factory=list)

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
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        
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
                instructions=(
                    "IDIOMA OBRIGATÓRIO: Você DEVE falar e entender APENAS em português brasileiro (pt-BR). "
                    "Toda entrada de áudio do usuário é em português do Brasil. "
                    "NUNCA interprete como outro idioma. Responda SEMPRE em português do Brasil.\n"
                    "IMPORTANTE: Ignore ruídos (como '<noise>'), suspiros ou falas desconexas que resultam do microfone sempre aberto. Responda apenas se o usuário interagir com propósito."
                ),
                realtime_input_config=genai_types.RealtimeInputConfig(
                    automatic_activity_detection=genai_types.AutomaticActivityDetection(
                        disabled=False,
                        prefix_padding_ms=500,
                        silence_duration_ms=1500,
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
                    prefix_padding_ms=500,
                    silence_duration_ms=1500,
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
        Aciona Marco (Estrategista) nos bastidores para gerar o Plano de Execução final.
        Use quando o usuário quiser encerrar a sessão ou solicitar um plano estruturado.
        Marco não fala — ele trabalha silenciosamente e envia o documento.
        """
        user_name = self._blackboard.user_name or "empreendedor"
        project_name = self._blackboard.project_name or "seu projeto"

        # Marco trabalha nos bastidores — gera o documento usando o modelo de linguagem com Search
        logger.info("[Marco] Acionando LLM (Gemini 2.5 Pro + Search) para gerar Plano de Execução...")
        self._blackboard.add_message("Sistema", f"Marco iniciou a pesquisa e o processamento do Plano para {user_name}...")

        # Aguarda um pequeno momento para enviar a mensagem do sistema antes que o LLM comece
        await asyncio.sleep(2.0)

        # Gera o documento Markdown estruturado de forma inteligente
        markdown_plan = await self._generate_markdown_plan_with_agent(user_name, project_name)

        try:
            plan_payload = json.dumps({
                "type": "execution_plan",
                "plan": markdown_plan,
                "text": markdown_plan,
            }).encode()
            await self._room.local_participant.publish_data(plan_payload, reliable=True)
            logger.info("[Marco] Plano de Execução Markdown publicado como data packet (bastidores).")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar plano de execução: {e}")

        return (
            f"Marco preparou o Plano de Execução completo para {user_name} nos bastidores. "
            f"O documento já foi enviado para a tela do usuário. "
            f"Informe ao usuário que o plano está pronto e disponível para download."
        )

    async def _generate_markdown_plan_with_agent(self, user_name: str, project_name: str) -> str:
        """
        Invoca o Marco (gemini-2.5-pro com suporte a Google Search) 
        para gerar o plano de execução via LLM, nos bastidores.
        """
        from google import genai
        from google.genai import types

        full_transcript = self._blackboard.get_full_transcript()
        marco_prompt = SPECIALIST_SYSTEM_PROMPTS["plan"]

        prompt = (
            f"DIRETRIZES DA PERSONA:\n{marco_prompt}\n\n"
            f"INSTRUÇÃO DE EXECUÇÃO:\n"
            f"Você é o Marco. Através de todo o histórico da conversa entre os especialistas, "
            f"sintetize um plano estruturado e rico. O formato final deve ser EXCLUSIVAMENTE em MARKDOWN.\n"
            f"Use a ferramenta de PESAQUISA no GOOGLE para complementar ideias, analisar tendências atuais (ex: ferramentas, "
            f"estratégias de mercado recentes, legislações, frameworks recomendados) que se apliquem ao caso.\n"
            f"Usuário: {user_name}\n"
            f"Descrição do Projeto: {project_name}\n\n"
            f"--- TRANSCRIÇÃO DA CONVERSA ---\n"
            f"{full_transcript}\n"
            f"--- FIM DA TRANSCRIÇÃO ---\n\n"
            f"AGORA INICIE SUA RESPOSTA MANTENDO FORMATAÇÃO RICA EM MARKDOWN."
        )

        try:
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
            
            # Geração textual usa run_in_executor para não bloquear o event loop
            def _call_gemini():
                return client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        tools=[{"google_search": {}}],
                    )
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, _call_gemini)
            
            text_result = response.text
            # Limpa possíveis formatações excessivas de bloco de código do Gemini
            if text_result.startswith("```markdown"):
                text_result = text_result[11:]
            if text_result.startswith("```"):
                text_result = text_result[3:]
            if text_result.endswith("```"):
                text_result = text_result[:-3]

            return text_result.strip()
        except Exception as e:
            logger.error(f"[Marco] Erro na geração LLM: {e}. Fazendo fallback para versão estática.")
            # Fallback seguro
            return self._generate_markdown_plan(user_name, project_name)

    def _generate_markdown_plan(self, user_name: str, project_name: str) -> str:
        """Gera documento Markdown secundário apenas se o LLM falhar."""
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

        # C5: Handler assíncrono para ativação de especialista.
        # Extraído do callback síncrono para garantir await correto
        # em session.generate_reply() e agent.update_instructions().
        async def _handle_activation(msg: dict) -> None:
            """Processa ativação deste especialista de forma assíncrona."""
            try:
                ctx_summary = msg.get("transcript_summary", "")
                context_text = msg.get("context", "")

                # Atualiza instruções com contexto da sessão
                if ctx_summary:
                    new_instructions = (
                        SPECIALIST_SYSTEM_PROMPTS[spec_id]
                        + f"\n\n--- CONTEXTO ATUAL DA SESSÃO ---\n{ctx_summary}"
                    )
                    try:
                        result = agent.update_instructions(new_instructions)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as ui_err:
                        logger.warning(f"[{name}] Erro ao atualizar instruções: {ui_err}")

                # C5: Subscreve ao áudio do usuário
                _subscribe_user_audio()

                # Gera resposta com await correto
                prompt = (
                    f"Nathália acabou de te acionar. O contexto é: {context_text}. "
                    f"Responda de forma objetiva e profissional."
                )
                await session.generate_reply(instructions=prompt)
                logger.info(f"[{name}] ATIVADO via data packet — áudio ON + reply gerado.")
            except asyncio.CancelledError:
                logger.info(f"[{name}] Geração INTERROMPIDA (turno de outro agente).")
                _unsubscribe_user_audio()
            except Exception as e:
                logger.warning(f"[{name}] Erro na ativação assíncrona: {e}")

        # C5: Escuta data packets para ativação/desativação coordenada.
        # Callback síncrono delega lógica async para _handle_activation.
        # Rastreia a task de geração para cancelar ao desativar (turn-taking).
        _generation_task: Optional[asyncio.Task] = None

        @room.on("data_received")
        def _on_data(dp: rtc.DataPacket) -> None:
            nonlocal _generation_task
            try:
                msg = json.loads(dp.data.decode())
                if msg.get("type") == "activate_agent":
                    if msg.get("agent_id") == spec_id:
                        # Cancela geração anterior deste agente, se houver
                        if _generation_task and not _generation_task.done():
                            _generation_task.cancel()
                        # Delega para handler assíncrono e rastreia a task
                        _generation_task = asyncio.create_task(_handle_activation(msg))
                    else:
                        # === DESATIVAÇÃO: outro especialista foi chamado ===
                        # Cancela geração em andamento para parar de falar
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

    # Garante a subscrição manual APENAS no áudio do usuário principal
    for p in ctx.room.remote_participants.values():
        if p.identity.startswith("user-"):
            for pub in p.track_publications.values():
                if pub.kind == rtc.TrackKind.KIND_AUDIO:
                    pub.set_subscribed(True)
                    logger.info(f"[Host] Áudio de {p.identity} subscrito (init).")

    # Monitora novas tracks publicadas para caso o usuário entre depois do agente
    @ctx.room.on("track_published")
    def on_track_published(pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if participant.identity.startswith("user-") and pub.kind == rtc.TrackKind.KIND_AUDIO:
            pub.set_subscribed(True)
            logger.info(f"[Host] Áudio de {participant.identity} subscrito dinamicamente.")

    # Blackboard compartilhado
    blackboard = Blackboard(project_name=ctx.room.name)

    # Carregar documentos da API em background
    async def fetch_docs():
        import urllib.request
        import json
        api_url = os.getenv("NEXT_API_URL", "http://localhost:3000") + f"/api/projects/{ctx.room.name}/documents"
        def _get():
            try:
                req = urllib.request.Request(api_url)
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode())
                    return [d.get("content", "") for d in data if d.get("content")]
            except Exception as e:
                logger.warning(f"Erro ao buscar documentos da API: {e}")
                return []
        
        loop = asyncio.get_running_loop()
        docs = await loop.run_in_executor(None, _get)
        blackboard.documentos_disponiveis = docs
        logger.info(f"[Docs] Foram carregados {len(docs)} documentos para a sessão.")
        
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

    shutdown_event = asyncio.Event()

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

        text = ""
        if hasattr(event, "transcript"):
            text = event.transcript
        elif hasattr(event, "text"):
            text = event.text
        else:
            text = str(event)

        text = text.strip()
        if not text:
            return

        # ==========================================================
        # Filtro de Ruído / Alucinações (VAD/STT robustness)
        # ==========================================================
        lower_text = text.lower()

        # 1. Filtro de ruído explícito
        if lower_text in ["<noise>", "[noise]", "silence", "noise", "ruído", "interruption", "breath"]:
            logger.info(f"[Filtro] Ruído explícito descartado: {text}")
            return

        # 2. Filtro de Script Não-Latino (Thai, Arabic, Bengali, etc.)
        # O sistema é focado em pt-BR. Se houver scripts totalmente diferentes, é alucinação de ruído.
        # Range Thai: \u0e00-\u0e7f, Arabic: \u0600-\u06ff, Bengali: \u0980-\u09ff, etc.
        non_latin_pattern = re.compile(r"[\u0e00-\u0e7f\u0600-\u06ff\u0980-\u09ff\u0e80-\u0eff\uac00-\ud7af]")
        if non_latin_pattern.search(text):
            logger.info(f"[Filtro] Alucinação de idioma detectada e descartada: {text}")
            return

        # 3. Filtro de fragmentos curtíssimos sem vogais (ruído VAD)
        # Palavras em PT sempre têm vogais. "é", "o", "a" são válidos.
        if len(text) <= 3 and not any(v in lower_text for v in "aeiouáéíóúâêôãõ"):
             logger.info(f"[Filtro] Fragmento curto sem vogais (ruído) descartado: {text}")
             return

        # 4. Filtro de monossílabos suspeitos que não são pt-BR comuns
        common_pt_monos = {"oi", "é", "o", "a", "um", "eu", "se", "ir", "da", "do", "no", "na", "te", "me", "vc", "bj", "obg"}
        if len(text) <= 2 and lower_text not in common_pt_monos:
             logger.info(f"[Filtro] Monossílabo suspeito descartado: {text}")
             return

        # 5. Filtro de linguagem informal mas reconhecível (evita eco de agente)
        # Se o texto parece resposta do agente (não fala de usuário), descarte
        if lower_text.startswith("entendido") or lower_text.startswith("perfeito") or lower_text.startswith("claro"):
            logger.info(f"[Filtro] Possível eco de agente descartado: {text}")
            return
        # ==========================================================

        logger.info(f"[Usuário fala] {text}")
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

        Estratégia de inicialização sequencial:
        - Cada especialista é conectado UM POR VEZ com delay entre conexões.
        - Evita rate limiting 429 nos handshakes simultâneos ao Gemini.
        - Em produção com N usuários, reduz a carga de 6N para picos menores.
        """
        is_resuming = len(blackboard.transcript) > 0

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

            # Conecta especialistas PARALELAMENTE (mais rapido)
            logger.info("[Retomada] Conectando especialistas simultaneamente...")
            tasks = []
            for sid in SPECIALIST_ORDER:
                tasks.append(_start_specialist_in_room(
                    spec_id=sid,
                    blackboard=blackboard,
                    ws_url=ws_url,
                    lk_api_key=lk_api_key,
                    lk_api_secret=lk_api_secret,
                    room_name=ctx.room.name,
                    host_room=ctx.room,
                    auto_introduce=False,
                ))
            
            if blackboard.is_active:
                await asyncio.gather(*tasks, return_exceptions=True)
                
            logger.info("[Host] Retomada concluída. Todos os especialistas reconectados.")

        else:
            # ── MODO INICIAL ───────────────────────────────────────────
            # Fluxo: Nathália apresenta (sem perguntas) → 5s depois especialistas
            # começam a conectar → apresentações sequenciais → pergunta inicial.
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

            # Conecta especialistas 5s após Nathália INICIAR a fala (em paralelo)
            async def _connect_specialists_delayed():
                await asyncio.sleep(5.0)
                if not blackboard.is_active:
                    return []
                logger.info("[Apresentação] Conectando especialistas (5s após início da fala)...")
                tasks = []
                for sid in SPECIALIST_ORDER:
                    tasks.append(_start_specialist_in_room(
                        spec_id=sid,
                        blackboard=blackboard,
                        ws_url=ws_url,
                        lk_api_key=lk_api_key,
                        lk_api_secret=lk_api_secret,
                        room_name=ctx.room.name,
                        host_room=ctx.room,
                        auto_introduce=False,
                    ))
                return await asyncio.gather(*tasks, return_exceptions=True)

            # Dispara Nathália falando E conexão dos especialistas concorrentemente
            logger.info("[Host] Nathália enviando apresentação inicial (sem perguntas)...")
            connect_task = asyncio.create_task(_connect_specialists_delayed())

            try:
                await asyncio.wait_for(
                    host_session.generate_reply(
                        instructions=(
                            f"Apresente-se de forma calorosa e natural dizendo: {host_greeting} "
                            f"NÃO faça NENHUMA pergunta. Apenas apresente-se e anuncie o time. "
                            f"Encerre sua fala após a apresentação."
                        ),
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning("[Host] Timeout (30s) ao gerar reply inicial.")
            except Exception as e:
                logger.warning(f"[Host] Erro ao gerar reply inicial: {type(e).__name__}: {e}", exc_info=True)

            # Aguarda especialistas terminarem de conectar
            if not blackboard.is_active:
                connect_task.cancel()
                return
            sessions = await connect_task
            if not blackboard.is_active:
                return

            logger.info("[Apresentação] Conexões concluídas. Apresentando-se agora...")

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

                # Retry wrapper around generate_reply
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
                            timeout=30.0,
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

        # Desconecta especialistas com timeout máximo para evitar travamentos
        for spec_room in blackboard.specialist_rooms:
            try:
                await asyncio.wait_for(spec_room.disconnect(), timeout=2.0)
            except Exception as e:
                logger.warning(f"[Job] Erro/Timeout ao desconectar room de especialista: {e}")
            except asyncio.CancelledError:
                # O await dentro de task cancelada vai dar throw repetidamente.
                # Capturamos para não impedir as chamadas síncronas de baixo.
                pass

        room_name = getattr(ctx.job.room, "name", ctx.room.name) if getattr(ctx, "job", None) else ctx.room.name

        # Limpa o lock _active_rooms para permitir a mesma sala rodar outro job no futuro
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