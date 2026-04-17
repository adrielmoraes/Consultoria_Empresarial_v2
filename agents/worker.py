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
import base64
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from time import monotonic
from typing import Optional

try:
    from duckduckgo_search import AsyncDDGS
except ImportError:
    AsyncDDGS = None  # type: ignore
    import logging as _tmp_log
    _tmp_log.getLogger(__name__).warning(
        "[worker] duckduckgo_search não encontrado — ferramenta de busca na internet desativada."
    )

from dotenv import load_dotenv

load_dotenv()

# Mapeia GEMINI_API_KEY → GOOGLE_API_KEY para os plugins que leem essa variável
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = _gemini_key

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
                "voice_name": "Orus",
            }
        }
    }
}

DATA_PACKET_SCHEMA_VERSION = "1.0"
ACTIVATION_ACK_TIMEOUT_SECONDS = 8.0
ACTIVATION_DONE_TIMEOUT_SECONDS = 45.0
ACTIVATION_DEBOUNCE_SECONDS = 0.8
SPECIALIST_GENERATION_TIMEOUT_SECONDS = 35.0
CONTEXT_RECENT_WINDOW = 12

# Vozes por agente (Gemini TTS nativo)
AGENT_VOICES: dict[str, str] = {
    "host":  "Aoede",    # Nathália – feminina suave
    "cfo":   "Charon",   # Carlos   – masculina grave
    "legal": "Orus",   # Daniel   – masculina formal
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

# IDs dos avatares Beyond Presence mapeados por agente
# Cada variável de ambiente corresponde a um personagem específico.
# Fonte: https://docs.livekit.io/agents/models/avatar/plugins/bey/
AVATAR_IDS: dict[str, str] = {
    "host":  os.getenv("BEY_AVATAR_ID_HOST", ""),   # Nathália
    "legal": os.getenv("BEY_AVATAR_ID_LEGAL", ""),  # Daniel (Advogado)
    "cfo":   os.getenv("BEY_AVATAR_ID_CFO", ""),    # Carlos (CFO)
    "cmo":   os.getenv("BEY_AVATAR_ID_CMO", ""),    # Rodrigo (CMO)
    "cto":   os.getenv("BEY_AVATAR_ID_CTO", ""),    # Ana (CTO)
    # Marco (plan) não recebe avatar — opera exclusivamente nos bastidores
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
POST_INTRO_WAIT: float = 0.50

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
4. Seja a "regente" da sessão.
5. Mantenha suas falas curtas e diretas (máximo 3 frases por turno).
6. NUNCA responda por um especialista — sempre acione-os via função.
7. Quando o tema for financeiro → use acionar_carlos_cfo.
8. Quando o tema for jurídico → use acionar_daniel_advogado.
9. Quando o tema for marketing/vendas/clientes → use acionar_rodrigo_cmo.
10. Quando o tema for tecnologia/produto → use acionar_ana_cto.
11. Quando o usuário pedir encerramento, resumo ou plano → use gerar_plano_execucao.
12. Quando o usuário pedir análise SWOT, Canvas, pitch, proposta ou contrato → use gerar_documento_personalizado.
13. Quando o usuário quiser dados do mercado, concorrência ou tendências → use pesquisar_mercado_setor.
14. Quando o usuário quiser abrir empresa, regularizar, emitir nota fiscal → use gerar_checklist_abertura_empresa.
15. Quando o usuário perguntar sobre INPI, CNPJ, LGPD, BNDES, NFS-e, tributos → use gerar_orientacao_orgao_publico.
16. Quando o usuário precisar de um contrato de prestação de serviços, parceria, etc. → use gerar_modelo_contrato.
17. Quando o usuário quiser apresentar o negocio para investidores ou parceiros → use gerar_pitch_deck.
18. Se precisar cobrir múltiplos temas em sequencia, acione cada especialista separadamente.
19. RETOMADA: Se você perceber que há histórico de conversa anterior, comece dizendo que está retomando.
20. TURNO DE FALA: Quando você acionar um especialista via função, PARE DE FALAR imediatamente. NÃO adicione comentários após a chamada.
21. NUNCA fale ao mesmo tempo que um especialista. Dê espaço total para ele responder.
22. Após o especialista terminar (devolver a palavra a você), retome com 1-2 frases de transição antes de continuar.
23. HANDOVER: Quando você aciona um especialista, ele assumirá a conversa diretamente com o usuário por múltiplos turnos. Você ficará em SILÊNCIO ABSOLUTO esperando ele devolver a palavra. NÃO interrompa.
24. MARCO NOS BASTIDORES: Quando acionar o Marco via qualquer ferramenta gerar_*, avise ao usuário que o Marco está preparando o documento nos bastidores e que chegará em instantes. Exemplo: "Vou pedir ao Marco para preparar isso agora nos bastidores!"

MODO OUVINTE (SALA COM MÚLTIPLOS HUMANOS):
- A sala pode ter convidados (sócios, diretores) além do usuário principal.
- Se os humanos estiverem debatendo ideias livremente entre si, assuma postura de OUVINTE SILENCIOSA.
- NÃO interrompa debates humanos. Fale SOMENTE quando:
  a) Alguém se dirigir diretamente a você ou à equipe ("Nathália...", "Pessoal...", "O que vocês acham?").
  b) Houver um silêncio prolongado indicando que esperam sua intervenção.
  c) Um especialista devolver a palavra para você.

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
        "- Responda de forma objetiva e profissional.\n"
        "- Sempre termine com uma pergunta ou insight que aprofunde a análise.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário.\n"
        "- Somente use a ferramenta `devolver_para_nathalia` se o usuário disser e confirmar explicitamente que não tem mais dúvidas ou se ele próprio pedir para mudar de assunto.\n"
        "- Nas suas primeiras respostas, sempre termine perguntando algo (ex: 'Ficou claro?', 'Tem alguma dúvida sobre essa parte?').\n"
        "- EXCEÇÃO: Se o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro especialista "
        "(ex: jurídico, marketing, tecnologia), você pode usar `transferir_para_especialista` passando o ID do colega e o contexto da pergunta. "
        "Antes de transferir, FALE EM VOZ ALTA que vai repassar (ex: 'Vou repassar essa questão jurídica ao Daniel.').\n"
        "- IDs dos colegas: daniel_advogado (jurídico), rodrigo_cmo (marketing), ana_cto (tecnologia).\n"
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
        "- Nunca use juridiquês desnecessário.\n"
        "- Sempre sinalize os riscos e como mitigá-los.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário.\n"
        "- Somente use a ferramenta `devolver_para_nathalia` se o usuário disser e confirmar explicitamente que não tem mais dúvidas ou se ele próprio pedir para mudar de assunto.\n"
        "- Nas suas primeiras respostas, sempre termine perguntando algo (ex: 'Ficou claro?', 'Tem alguma dúvida sobre essa parte?').\n"
        "- EXCEÇÃO: Se o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro especialista "
        "(ex: finanças, marketing, tecnologia), você pode usar `transferir_para_especialista` passando o ID do colega e o contexto da pergunta. "
        "Antes de transferir, FALE EM VOZ ALTA que vai repassar (ex: 'Essa questão financeira é com o Carlos, vou passar pra ele.').\n"
        "- IDs dos colegas: carlos_cfo (finanças), rodrigo_cmo (marketing), ana_cto (tecnologia).\n"
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
        "- Use exemplos reais quando possível.\n"
        "- Termine com um insight acionável que o usuário possa aplicar imediatamente.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário.\n"
        "- Somente use a ferramenta `devolver_para_nathalia` se o usuário disser e confirmar explicitamente que não tem mais dúvidas ou se ele próprio pedir para mudar de assunto.\n"
        "- Nas suas primeiras respostas, sempre termine perguntando algo (ex: 'Ficou claro?', 'Tem alguma dúvida sobre essa parte?').\n"
        "- EXCEÇÃO: Se o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro especialista "
        "(ex: finanças, jurídico, tecnologia), você pode usar `transferir_para_especialista` passando o ID do colega e o contexto da pergunta. "
        "Antes de transferir, FALE EM VOZ ALTA que vai repassar (ex: 'Essa parte tecnológica é com a Ana, vou passar pra ela.').\n"
        "- IDs dos colegas: carlos_cfo (finanças), daniel_advogado (jurídico), ana_cto (tecnologia).\n"
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
        "- Evite siglas sem explicar.\n"
        "- Sempre avalie custo-benefício de cada decisão tecnológica.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário.\n"
        "- Somente use a ferramenta `devolver_para_nathalia` se o usuário disser e confirmar explicitamente que não tem mais dúvidas ou se ele próprio pedir para mudar de assunto.\n"
        "- Nas suas primeiras respostas, sempre termine perguntando algo (ex: 'Ficou claro?', 'Tem alguma dúvida sobre essa parte?').\n"
        "- EXCEÇÃO: Se o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro especialista "
        "(ex: finanças, jurídico, marketing), você pode usar `transferir_para_especialista` passando o ID do colega e o contexto da pergunta. "
        "Antes de transferir, FALE EM VOZ ALTA que vai repassar (ex: 'Essa questão de custos é com o Carlos, vou passar pra ele.').\n"
        "- IDs dos colegas: carlos_cfo (finanças), daniel_advogado (jurídico), rodrigo_cmo (marketing).\n"
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
        "- Você gera QUALQUER tipo de documento empresarial que o usuário precisar.\n"
        "- Você faz pesquisas adicionais para enriquecer as recomendações.\n"
        "- Para processos em órgãos públicos, você ORIENTA e EXPLICA — não gera documentos oficiais.\n"
        "\n\nDOCUMENTOS QUE VOCÊ PODE GERAR:\n"
        "1. Plano de Execução Estratégico completo (8 seções, KPIs, riscos, cronograma)\n"
        "2. Análise SWOT (forças, fraquezas, oportunidades, ameaças + cruzamentos estratégicos)\n"
        "3. Business Model Canvas (9 blocos completos com análise de viabilidade)\n"
        "4. Pitch Deck (12 slides estruturados para investidores/parceiros)\n"
        "5. Proposta Comercial (profissional, persuasiva, com SLA e garantias)\n"
        "6. Modelo de Contrato (prestacâo de servicos, parceria, confidencialidade etc.)\n"
        "7. Pesquisa de Mercado (TAM/SAM/SOM, PESTEL, competidores, ICP)\n"
        "8. Guias de Processos Públicos (CNPJ, INPI, LGPD, NFS-e, BNDES, Simples Nacional)\n"
        "\n\nPROCESSOS EM ÓRGÃOS PÚBLICOS (guias explicativos):\n"
        "- Abertura de empresa: CNPJ, Junta Comercial, Alvará, MEI/LTDA/SA\n"
        "- Registro de marca: INPI, classes NCL, prazos, custos\n"
        "- Enquadramento tributário: Simples Nacional, Lucro Presumido, MEI\n"
        "- Adequação LGPD: ANPD, encarregado, ROPA, base legal\n"
        "- Nota Fiscal: NFS-e, NF-e, regras por município\n"
        "- Crédito público: BNDES, Pronampe, Finep, Inova Simples\n"
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
    current_objective: str = ""
    last_user_question: str = ""
    user_pain_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    pending_items: list[str] = field(default_factory=list)
    is_active: bool = True
    specialist_sessions: dict[str, AgentSession] = field(default_factory=dict)
    specialist_rooms: list[rtc.Room] = field(default_factory=list)
    documentos_disponiveis: list[str] = field(default_factory=list)
    orchestration_metrics: dict[str, float] = field(default_factory=lambda: {
        "activations_total": 0,
        "activations_succeeded": 0,
        "activations_timeout": 0,
        "activations_cancelled": 0,
        "activation_ack_latency_ms_total": 0,
        "activation_done_latency_ms_total": 0,
    })

    def add_message(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content})
        self._update_memory(role, content)
        logger.debug(f"[Blackboard] [{role}]: {content[:80]}...")

    def _append_unique(self, bucket: list[str], value: str, max_size: int = 10) -> None:
        normalized = value.strip()
        if not normalized:
            return
        lowered = normalized.lower()
        if any(existing.lower() == lowered for existing in bucket):
            return
        bucket.append(normalized)
        if len(bucket) > max_size:
            del bucket[:-max_size]

    def _update_memory(self, role: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        role_lower = role.lower()
        if role_lower == "usuário":
            if not self.user_query:
                self.user_query = text
            if "?" in text:
                self.last_user_question = text
            lowered = text.lower()
            if any(k in lowered for k in ("dor", "dificuld", "problema", "trav", "desafio")):
                self._append_unique(self.user_pain_points, text, max_size=6)
            if any(k in lowered for k in ("objetivo", "meta", "quero", "preciso", "planejo")):
                self.current_objective = text
        elif role in SPECIALIST_NAMES.values() or role == "Nathália":
            lowered = text.lower()
            if any(k in lowered for k in ("decisão", "decid", "recomend", "sugiro", "prior")):
                self._append_unique(self.decisions, text, max_size=8)
            if any(k in lowered for k in ("próximo passo", "fazer", "ação", "execut", "pendente")):
                self._append_unique(self.pending_items, text, max_size=8)

    def get_context_summary(self) -> str:
        """Retorna um resumo do contexto atual para injetar nos prompts."""
        parts: list[str] = []
        if self.user_name:
            parts.append(f"Usuário: {self.user_name}")
        if self.project_name:
            parts.append(f"Projeto: {self.project_name}")
        if self.user_query:
            parts.append(f"Necessidade do usuário: {self.user_query}")
        if self.current_objective:
            parts.append(f"Objetivo atual: {self.current_objective}")
        if self.last_user_question:
            parts.append(f"Última pergunta do usuário: {self.last_user_question}")
        if self.decisions:
            parts.append("Decisões registradas:")
            for item in self.decisions[-4:]:
                parts.append(f"- {item}")
        if self.pending_items:
            parts.append("Pendências registradas:")
            for item in self.pending_items[-4:]:
                parts.append(f"- {item}")
        recent = self.transcript[-CONTEXT_RECENT_WINDOW:]
        if recent:
            parts.append("--- Conversa Recente ---")
            for msg in recent:
                parts.append(f"[{msg['role']}]: {msg['content']}")
        return "\n".join(parts)

    def get_structured_context(self) -> dict:
        return {
            "user_name": self.user_name,
            "project_name": self.project_name,
            "user_query": self.user_query,
            "current_objective": self.current_objective,
            "last_user_question": self.last_user_question,
            "pain_points": self.user_pain_points[-6:],
            "decisions": self.decisions[-8:],
            "pending_items": self.pending_items[-8:],
            "active_agent": self.active_agent,
            "recent_messages": self.transcript[-CONTEXT_RECENT_WINDOW:],
        }

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
        # Handover: evento para sinalizar fim do turno livre
        self._handover_event: asyncio.Event = asyncio.Event()
        # Resultado do handover: "nathalia" ou {"target": spec_id, "context": str}
        self._handover_result: Optional[dict] = None

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
    async def devolver_para_nathalia(
        self,
        context: RunContext,
    ) -> str:
        """
        Devolve a palavra à Nathália (apresentadora) para que ela retome a condução da sessão.
        Use esta ferramenta quando:
        - A dúvida da sua área de especialidade foi completamente respondida.
        - O usuário indicou que quer mudar de assunto.
        - Você sente que é hora de a Nathália continuar mediando.
        PRIORIDADE: Esta é a forma PADRÃO de encerrar seu turno.
        """
        logger.info(f"[{self._name}] Devolvendo palavra para Nathália.")
        self._blackboard.add_message(self._name, "Pronto, Nathália! Pode continuar.")
        self._handover_result = {"type": "nathalia"}
        self._handover_event.set()
        return "Palavra devolvida à Nathália com sucesso. Aguarde em silêncio."

    @function_tool
    async def transferir_para_especialista(
        self,
        context: RunContext,
        colega_id: str,
        contexto_pergunta: str,
    ) -> str:
        """
        Transfere a palavra diretamente para outro especialista da equipe SEM passar pela Nathália.
        Use SOMENTE quando o usuário fizer uma pergunta que pertence CLARAMENTE à área de outro colega.
        ANTES de usar esta ferramenta, FALE em voz alta para o usuário que vai repassar.

        Parâmetros:
        - colega_id: ID do colega destino. Valores válidos: carlos_cfo, daniel_advogado, rodrigo_cmo, ana_cto
        - contexto_pergunta: a pergunta ou contexto que deve ser repassado ao colega (para ele já iniciar respondendo)
        """
        target_spec_id = LATERAL_TRANSFER_MAP.get(colega_id)
        if not target_spec_id:
            return f"ID de colega inválido: {colega_id}. Use carlos_cfo, daniel_advogado, rodrigo_cmo ou ana_cto."

        target_name = SPECIALIST_NAMES.get(target_spec_id, colega_id)
        logger.info(f"[{self._name}] Transferindo palavra para {target_name} com contexto: {contexto_pergunta[:100]}")
        self._blackboard.add_message("Sistema", f"{self._name} transferiu a palavra para {target_name}.")
        self._handover_result = {
            "type": "transfer",
            "target": target_spec_id,
            "context": contexto_pergunta,
            "from_name": self._name,
        }
        self._handover_event.set()
        return f"Transferência para {target_name} registrada. Aguarde em silêncio."

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

    async def _publish_packet(self, payload: dict) -> None:
        base_payload = {
            "version": DATA_PACKET_SCHEMA_VERSION,
            "sent_at": monotonic(),
            **payload,
        }
        await self._room.local_participant.publish_data(
            json.dumps(base_payload).encode(),
            reliable=True,
        )

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

    # ------------------------------------------------------------------
    # Método auxiliar: publica um data packet para ativar um especialista
    # ------------------------------------------------------------------

    async def _activate_specialist(self, spec_id: str, context: str, _lateral_from_name: str = "") -> str:
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
            
            # Delay MÁGICO para evitar "atropelamento" de vozes:
            # Aguarda Nathália terminar de falar e processar no frontend (~4 seg)
            # antes de enviar o packet para o especialista.
            await asyncio.sleep(4.0)

            await self._publish_packet(packet)

            try:
                await asyncio.wait_for(
                    self._turn_events[turn_id]["activated"].wait(),
                    timeout=ACTIVATION_ACK_TIMEOUT_SECONDS,
                )
                ack_latency = (monotonic() - start_ts) * 1000
                self._blackboard.orchestration_metrics["activation_ack_latency_ms_total"] += ack_latency
            except asyncio.TimeoutError:
                self._blackboard.orchestration_metrics["activations_timeout"] += 1
                self._blackboard.active_agent = None
                self._turn_events.pop(turn_id, None)
                self._turn_status.pop(turn_id, None)
                logger.warning(f"[Host] Timeout aguardando ACK de {spec_id} no turno {turn_id}.")
                return (
                    f"{SPECIALIST_NAMES[spec_id]} não respondeu a tempo. "
                    f"Tente reformular a pergunta ou seguir com outro especialista."
                )

            try:
                await asyncio.wait_for(
                    self._turn_events[turn_id]["done"].wait(),
                    timeout=ACTIVATION_DONE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self._blackboard.orchestration_metrics["activations_timeout"] += 1
                self._blackboard.active_agent = None
                self._turn_events.pop(turn_id, None)
                self._turn_status.pop(turn_id, None)
                logger.warning(f"[Host] Timeout aguardando conclusão de {spec_id} no turno {turn_id}.")
                return (
                    f"{SPECIALIST_NAMES[spec_id]} demorou além do limite esperado. "
                    f"Você pode tentar novamente ou avançar para outro tema."
                )

            done_latency = (monotonic() - start_ts) * 1000
            self._blackboard.orchestration_metrics["activation_done_latency_ms_total"] += done_latency
            status_payload = self._turn_status.get(turn_id, {})
            status_type = status_payload.get("type")
            self._blackboard.active_agent = None
            self._turn_events.pop(turn_id, None)
            self._turn_status.pop(turn_id, None)

            if status_type == "agent_done":
                self._blackboard.orchestration_metrics["activations_succeeded"] += 1
                return f"{SPECIALIST_NAMES[spec_id]} concluiu a análise sobre: {context}"
            if status_type == "agent_cancelled":
                self._blackboard.orchestration_metrics["activations_cancelled"] += 1
                return f"{SPECIALIST_NAMES[spec_id]} teve o turno interrompido. Você pode repetir a solicitação."
            if status_type in ("agent_timeout", "agent_error"):
                self._blackboard.orchestration_metrics["activations_timeout"] += 1
                return f"{SPECIALIST_NAMES[spec_id]} encontrou instabilidade. Siga para outro especialista ou tente novamente."

            return f"{SPECIALIST_NAMES[spec_id]} foi acionado para analisar: {context}"

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
        return await self._activate_specialist("cfo", questao)

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
        return await self._activate_specialist("legal", questao)

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
        return await self._activate_specialist("cmo", questao)

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
        return await self._activate_specialist("cto", questao)

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

        # Gera o PDF profissional com a logomarca Hive Mind
        pdf_base64: str | None = None
        try:
            from pdf_generator import generate_pdf
            loop = asyncio.get_running_loop()
            pdf_bytes = await loop.run_in_executor(
                None,
                generate_pdf,
                markdown_plan,
                project_name,
                user_name,
            )
            pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
            logger.info(f"[Marco] PDF gerado com sucesso ({len(pdf_bytes)} bytes / {len(pdf_base64)} chars Base64).")
        except Exception as pdf_err:
            logger.warning(f"[Marco] Falha ao gerar PDF — apenas Markdown será enviado: {pdf_err}")

        try:
            packet: dict = {
                "type": "execution_plan",
                "plan": markdown_plan,
                "text": markdown_plan,
            }
            if pdf_base64:
                packet["pdf_base64"] = pdf_base64
            await self._publish_packet(packet)
            logger.info("[Marco] Plano de Execução publicado como data packet (bastidores).")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar plano de execução: {e}")

        return (
            f"Marco preparou o Plano de Execução completo para {user_name} nos bastidores. "
            f"O documento já foi enviado para a tela do usuário. "
            f"Informe ao usuário que o plano está pronto e disponível para download."
        )

    # ------------------------------------------------------------------
    # NOVAS FERRAMENTAS DO MARCO — Documentador Completo
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

        logger.info(f"[Marco] Gerando documento '{doc_type}' para {user_name}...")
        self._blackboard.add_message("Sistema", f"Marco iniciou geração de {doc_title} para {user_name}...")

        markdown_doc = await self._generate_custom_document(
            doc_type=doc_type,
            doc_title=doc_title,
            user_name=user_name,
            project_name=project_name,
            extra_context=descricao_contexto,
        )

        await self._publish_document_packet(
            doc_type=doc_type,
            doc_title=doc_title,
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco concluiu a {doc_title} para {user_name} nos bastidores. "
            f"O documento já foi enviado para a tela. "
            f"Informe ao usuário que o documento está disponível para download."
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

        logger.info(f"[Marco] Pesquisando mercado: {setor} | {pergunta_especifica}")
        self._blackboard.add_message("Sistema", f"Marco iniciou pesquisa de mercado sobre '{setor}'...")

        extra_context = f"Setor pesquisado: {setor}\nFoco da pesquisa: {pergunta_especifica}"
        markdown_doc = await self._generate_custom_document(
            doc_type="pesquisa_mercado",
            doc_title="Pesquisa de Mercado",
            user_name=user_name,
            project_name=project_name,
            extra_context=extra_context,
        )

        await self._publish_document_packet(
            doc_type="pesquisa_mercado",
            doc_title=f"Pesquisa de Mercado — {setor}",
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco concluiu a Pesquisa de Mercado sobre '{setor}' para {user_name}. "
            f"O relatório completo já está disponível na tela do usuário. "
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

        orgao_processo = f"Abertura de Empresa ({tipo_empresa})"
        logger.info(f"[Marco] Gerando guia de abertura de empresa: {tipo_empresa}")
        self._blackboard.add_message("Sistema", f"Marco iniciou guia de abertura de empresa ({tipo_empresa})...")

        markdown_doc = await self._generate_public_agency_guidance(
            orgao_processo=orgao_processo,
            contexto=f"Tipo de empresa: {tipo_empresa}. Contexto do negócio: {self._blackboard.get_context_summary()[:800]}",
            user_name=user_name,
            project_name=project_name,
        )

        await self._publish_document_packet(
            doc_type="orientacao_orgao",
            doc_title=f"Guia: Abertura de Empresa — {tipo_empresa}",
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco preparou o Guia de Abertura de Empresa ({tipo_empresa}) para {user_name}. "
            f"O documento explica passo a passo, custos, links e prazos. "
            f"Já está disponível na tela para download. "
            f"IMPORTANTE: Informe ao usuário que este é um guia orientativo — o CNPJ deve ser solicitado nos portais governamentais."
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

        logger.info(f"[Marco] Gerando orientação sobre: {orgao_processo}")
        self._blackboard.add_message("Sistema", f"Marco preparando guia sobre '{orgao_processo}'...")

        markdown_doc = await self._generate_public_agency_guidance(
            orgao_processo=orgao_processo,
            contexto=contexto_adicional,
            user_name=user_name,
            project_name=project_name,
        )

        await self._publish_document_packet(
            doc_type="orientacao_orgao",
            doc_title=f"Guia: {orgao_processo}",
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco concluiu o Guia sobre '{orgao_processo}' para {user_name}. "
            f"O documento já está disponível na tela com passo a passo, custos e links oficiais. "
            f"IMPORTANTE: Reforce ao usuário que este é um guia orientativo. "
            f"O processo oficial deve ser realizado diretamente nos portais governamentais indicados."
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

        logger.info(f"[Marco] Gerando modelo de contrato: {tipo_contrato} | partes: {partes_envolvidas}")
        self._blackboard.add_message("Sistema", f"Marco preparando modelo de contrato de {tipo_contrato}...")

        extra_context = (
            f"Tipo de contrato: {tipo_contrato}\n"
            f"Partes envolvidas: {partes_envolvidas}\n"
            f"Contexto do negócio: {self._blackboard.get_context_summary()[:600]}"
        )

        markdown_doc = await self._generate_custom_document(
            doc_type="modelo_contrato",
            doc_title=f"Modelo de Contrato — {tipo_contrato.title()}",
            user_name=user_name,
            project_name=project_name,
            extra_context=extra_context,
            extra_vars={
                "tipo_contrato": tipo_contrato,
                "tipo_contrato_upper": tipo_contrato.upper(),
                "partes": partes_envolvidas,
            },
        )

        await self._publish_document_packet(
            doc_type="modelo_contrato",
            doc_title=f"Modelo de Contrato — {tipo_contrato.title()}",
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco concluiu o Modelo de Contrato de {tipo_contrato.title()} para {user_name}. "
            f"O documento já está disponível na tela. "
            f"FUNDAMENTAL: Informe ao usuário que este é um modelo base e DEVE ser revisado "
            f"por um advogado especializado antes de ser assinado."
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

        logger.info(f"[Marco] Gerando Pitch Deck para {publico_alvo}...")
        self._blackboard.add_message("Sistema", f"Marco preparando Pitch Deck para {publico_alvo}...")

        extra_context = f"Público-alvo da apresentação: {publico_alvo}"
        markdown_doc = await self._generate_custom_document(
            doc_type="pitch_deck",
            doc_title="Pitch Deck",
            user_name=user_name,
            project_name=project_name,
            extra_context=extra_context,
            extra_vars={"publico": publico_alvo},
        )

        await self._publish_document_packet(
            doc_type="pitch_deck",
            doc_title=f"Pitch Deck — {project_name}",
            markdown_content=markdown_doc,
            user_name=user_name,
            project_name=project_name,
        )

        return (
            f"Marco criou o Pitch Deck de {project_name} para {user_name}! "
            f"O documento com os 12 slides já está disponível na tela para download. "
            f"Sugira ao usuário revisar os dados financeiros e personalizar com informações reais antes de apresentar."
        )

    # ------------------------------------------------------------------
    # MÉTODOS INTERNOS DO MARCO — Geração de documentos nos bastidores
    # ------------------------------------------------------------------

    async def _emit_marco_working(self, status: str, progress: int) -> None:
        """Publica um data packet de progresso para o frontend exibir feedback visual."""
        try:
            await self._publish_packet({
                "type": "marco_working",
                "status": status,
                "progress": max(0, min(100, progress)),
            })
        except Exception as e:
            logger.debug(f"[Marco] Erro ao emitir progresso: {e}")

    async def _run_web_search(self, query: str) -> str:
        """Executa pesquisa no DuckDuckGo e retorna os resultados como texto."""
        if AsyncDDGS is None:
            return ""
        try:
            resultados = []
            async with AsyncDDGS() as ddgs:
                async for res in ddgs.text(query, max_results=4, region="br-pt"):
                    resultados.append(f"Título: {res.get('title')}\nTrecho: {res.get('body')}")
            if resultados:
                return "\n\n--- DADOS PESQUISADOS NA WEB ---\n" + "\n\n".join(resultados)
        except Exception as e:
            logger.warning(f"[Marco] Erro na pesquisa web: {e}")
        return ""

    async def _generate_custom_document(
        self,
        doc_type: str,
        doc_title: str,
        user_name: str,
        project_name: str,
        extra_context: str = "",
        extra_vars: Optional[dict] = None,
    ) -> str:
        """
        Gerador polimórfico: recebe o tipo de documento, monta o prompt correto,
        faz pesquisa web e chama o Gemini para gerar o Markdown.
        """
        from google import genai
        from google.genai import types
        from pdf_generator import DOCUMENT_PROMPTS

        await self._emit_marco_working(f"Marco está pesquisando sobre {doc_title}...", 10)

        # Pesquisa web contextual
        full_transcript = self._blackboard.get_full_transcript()
        search_query_prompt = (
            f"Projeto '{project_name}', documento '{doc_title}'. "
            f"Contexto adicional: {extra_context[:300]}. "
            f"Gere APENAS UMA QUERY curta para busca no Google sobre este mercado/tema. SEM TEXTO ADICIONAL."
        )
        web_context = ""
        try:
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
            loop = asyncio.get_running_loop()

            def _get_query():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=search_query_prompt,
                    config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=30),
                )
            q_resp = await loop.run_in_executor(None, _get_query)
            search_q = q_resp.text.strip().replace('"', "").replace("'", "")[:100]
            logger.info(f"[Marco] Web search query para {doc_type}: {search_q}")
            web_context = await self._run_web_search(search_q)
        except Exception as e:
            logger.warning(f"[Marco] Erro ao gerar query de pesquisa: {e}")

        await self._emit_marco_working(f"Gerando {doc_title}...", 40)

        # Monta o transcript enriquecido
        transcript_enriched = (
            f"Usuário: {user_name}\n"
            f"Projeto: {project_name}\n"
            f"Informação adicional: {extra_context}\n"
            f"{web_context}\n\n"
            f"{full_transcript}"
        )

        # Recupera o prompt base para este tipo de documento
        prompt_template, _ = DOCUMENT_PROMPTS.get(doc_type, (None, None))
        if prompt_template is None:
            logger.warning(f"[Marco] Tipo de documento desconhecido: {doc_type}. Usando execution_plan.")
            prompt_template, _ = DOCUMENT_PROMPTS["execution_plan"]

        # Preenche variáveis do template
        fmt_vars = {
            "transcript": transcript_enriched,
            "projeto": project_name,
            "user_name": user_name,
            "setor": extra_context[:80] if extra_context else project_name,
            "publico": extra_vars.get("publico", "investidores") if extra_vars else "investidores",
            "tipo_contrato": extra_vars.get("tipo_contrato", "prestação de serviços") if extra_vars else "prestação de serviços",
            "tipo_contrato_upper": extra_vars.get("tipo_contrato_upper", "PRESTAÇÃO DE SERVIÇOS") if extra_vars else "PRESTAÇÃO DE SERVIÇOS",
            "partes": extra_vars.get("partes", "as partes envolvidas") if extra_vars else "as partes envolvidas",
            "orgao_processo": extra_context[:120] if extra_context else "processos empresariais",
        }
        try:
            prompt = prompt_template.format(**fmt_vars)
        except KeyError as ke:
            logger.warning(f"[Marco] Chave ausente no template {doc_type}: {ke}. Usando formato parcial.")
            prompt = prompt_template.replace("{transcript}", transcript_enriched)

        await self._emit_marco_working(f"Redigindo {doc_title} com IA...", 65)

        # Geração com Gemini
        markdown_result = ""
        try:
            client_gen = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
            loop = asyncio.get_running_loop()

            def _call_llm():
                return client_gen.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.65,
                        max_output_tokens=32000,
                    ),
                )
            resp = await loop.run_in_executor(None, _call_llm)
            markdown_result = resp.text.strip()
            # Remove wrapper de código se o LLM adicionar
            for prefix in ("```markdown", "```"):
                if markdown_result.startswith(prefix):
                    markdown_result = markdown_result[len(prefix):]
            if markdown_result.endswith("```"):
                markdown_result = markdown_result[:-3]
            markdown_result = markdown_result.strip()
            logger.info(f"[Marco] {doc_title} gerado: {len(markdown_result)} chars.")
        except Exception as e:
            logger.error(f"[Marco] Erro ao gerar {doc_title}: {e}")
            markdown_result = f"# {doc_title}\n\nErro ao gerar documento. Por favor, tente novamente.\n\nContexto: {project_name} — {user_name}"

        await self._emit_marco_working(f"Convertendo {doc_title} para PDF...", 85)
        return markdown_result

    async def _generate_public_agency_guidance(
        self,
        orgao_processo: str,
        contexto: str,
        user_name: str,
        project_name: str,
    ) -> str:
        """
        Gerador especializado para guias de órgãos públicos.
        Usa o ORIENTACAO_ORGAO_PROMPT com pesquisa web intensiva.
        """
        from google import genai
        from google.genai import types
        from pdf_generator import ORIENTACAO_ORGAO_PROMPT

        await self._emit_marco_working(f"Marco pesquisando sobre {orgao_processo}...", 15)

        # Pesquisa web direcionada ao processo público
        web_context = await self._run_web_search(f"{orgao_processo} Brasil 2024 passo a passo")
        web_context += await self._run_web_search(f"{orgao_processo} custos taxas portais oficiais")

        await self._emit_marco_working(f"Elaborando guia detalhado: {orgao_processo}...", 50)

        full_transcript = self._blackboard.get_full_transcript()
        transcript_enriched = (
            f"Usuário: {user_name}\n"
            f"Projeto: {project_name}\n"
            f"Processo solicitado: {orgao_processo}\n"
            f"Contexto adicional: {contexto}\n"
            f"{web_context}\n\n"
            f"{full_transcript[:3000]}"
        )

        fmt_vars = {
            "transcript": transcript_enriched,
            "orgao_processo": orgao_processo,
            "projeto": project_name,
            "user_name": user_name,
        }
        try:
            prompt = ORIENTACAO_ORGAO_PROMPT.format(**fmt_vars)
        except KeyError as ke:
            logger.warning(f"[Marco] Chave ausente em ORIENTACAO_ORGAO_PROMPT: {ke}")
            prompt = ORIENTACAO_ORGAO_PROMPT.replace("{transcript}", transcript_enriched)

        markdown_result = ""
        try:
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
            loop = asyncio.get_running_loop()

            def _call_llm():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.5,
                        max_output_tokens=24000,
                    ),
                )
            resp = await loop.run_in_executor(None, _call_llm)
            markdown_result = resp.text.strip()
            for prefix in ("```markdown", "```"):
                if markdown_result.startswith(prefix):
                    markdown_result = markdown_result[len(prefix):]
            if markdown_result.endswith("```"):
                markdown_result = markdown_result[:-3]
            markdown_result = markdown_result.strip()
            logger.info(f"[Marco] Guia '{orgao_processo}' gerado: {len(markdown_result)} chars.")
        except Exception as e:
            logger.error(f"[Marco] Erro ao gerar guia '{orgao_processo}': {e}")
            markdown_result = (
                f"# Guia: {orgao_processo}\n\n"
                f"Não foi possível gerar o guia completo neste momento. "
                f"Por favor, consulte o portal gov.br para informações oficiais sobre {orgao_processo}.\n\n"
                f"**Link:** https://www.gov.br"
            )

        await self._emit_marco_working(f"Finalizando guia...", 85)
        return markdown_result

    async def _publish_document_packet(
        self,
        doc_type: str,
        doc_title: str,
        markdown_content: str,
        user_name: str,
        project_name: str,
    ) -> None:
        """
        Converte o Markdown em PDF e publica o data packet 'document_ready'
        que o frontend usa para exibir o botão de download.
        """
        pdf_base64: Optional[str] = None
        try:
            from pdf_generator import generate_pdf
            loop = asyncio.get_running_loop()
            pdf_bytes = await loop.run_in_executor(
                None,
                lambda: generate_pdf(
                    markdown_content,
                    project_name,
                    user_name,
                    doc_type=doc_type,
                    doc_title=doc_title,
                ),
            )
            pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
            logger.info(f"[Marco] PDF '{doc_title}' gerado: {len(pdf_bytes)} bytes.")
        except Exception as e:
            logger.warning(f"[Marco] Falha ao gerar PDF para '{doc_title}': {e}")

        try:
            packet: dict = {
                "type": "document_ready",
                "doc_type": doc_type,
                "doc_title": doc_title,
                "plan": markdown_content,
                "text": markdown_content,
            }
            # Retrocompatibilidade: se for plano de execução, mantém o type antigo também
            if doc_type == "execution_plan":
                packet["type"] = "execution_plan"

            if pdf_base64:
                packet["pdf_base64"] = pdf_base64

            await self._publish_packet(packet)
            await self._emit_marco_working(f"{doc_title} pronto! ✅", 100)
            logger.info(f"[Marco] Data packet 'document_ready' publicado para '{doc_title}'.")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar document_ready para '{doc_title}': {e}")

    async def _generate_markdown_plan_with_agent(self, user_name: str, project_name: str) -> str:
        """
        Fluxo em 2 etapas para gerar o plano de execução com o Marco:

        ETAPA 1 — Draft: Gemini 2.5 Pro + Google Search sintetiza toda a sessão
                         e gera o Markdown estruturado com as 8 seções obrigatórias.

        ETAPA 2 — Revisão de Completude: Uma segunda chamada ao LLM verifica se
                  todas as seções críticas (Objetivos SMART, Orçamento concreto,
                  Cronograma, Responsabilidades, Riscos e Contingências) estão
                  bem preenchidas. Se não, o LLM detalha o que faltou antes de
                  retornar a versão final.
        """
        from google import genai
        from google.genai import types
        from pdf_generator import SUMMARIZATION_PROMPT

        full_transcript = self._blackboard.get_full_transcript()

        # ── PESQUISA DE MERCADO VIA DUCKDUCKGO ───────────────────────────────
        logger.info("[Marco] Obtendo query de pesquisa de mercado para DDGS...")
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        
        web_context = ""
        try:
            # 1. Obter termo de pesquisa adequado
            query_prompt = f"Com base no projeto '{project_name}' e nesta transcrição recente:\n{full_transcript[-1500:]}\nGere APENAS UMA QUERY muito curta (ex: 'mercado de tech no brasil tendências') para pesquisarmos no Google. NADA DE TEXTO ADICIONAL."
            
            def _call_query():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=query_prompt,
                    config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=30)
                )
                
            loop = asyncio.get_running_loop()
            query_resp = await loop.run_in_executor(None, _call_query)
            search_query = query_resp.text.strip().replace("\"", "").replace("'", "")
            logger.info(f"[Marco] Query gerada para web search: {search_query}")
            
            # 2. Pesquisar de forma assíncrona
            logger.info("[Marco] Consultando DuckDuckGo...")
            resultados_ddgs = []
            async with AsyncDDGS() as ddgs:
                async for res in ddgs.text(search_query, max_results=3, region="br-pt"):
                    resultados_ddgs.append(f"Título: {res.get('title')}\nTrecho: {res.get('body')}")
            
            if resultados_ddgs:
                web_context = "\n\n--- DADOS PESQUISADOS NA WEB EM TEMPO REAL ---\n" + "\n\n".join(resultados_ddgs)
                logger.info(f"[Marco] Encontrados {len(resultados_ddgs)} resultados na internet com DDGS.")
        except Exception as e:
            logger.warning(f"[Marco] Erro na pesquisa web via DDGS: {e}. Prosseguindo sem dados da internet.")
            
        # ── ETAPA 1: Geração do Draft ──────────────────────────────────────────
        logger.info("[Marco] ETAPA 1 — Gerando Draft com Gemini 3.1 flash-lite-preview + Google Search...")

        draft_prompt = SUMMARIZATION_PROMPT.format(
            transcript=(
                f"Usuário: {user_name}\n"
                f"Projeto: {project_name}\n"
                f"{web_context}\n\n"
                f"{full_transcript}"
            )
        )

        draft_text: str = ""
        try:
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

            def _call_draft():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=draft_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.65,
                        max_output_tokens=66000,
                        # tools=[{"google_search": {}}],  # Removido em favor do DDGS customizado
                    ),
                )

            loop = asyncio.get_running_loop()
            draft_resp = await loop.run_in_executor(None, _call_draft)
            draft_text = draft_resp.text.strip()
            # Remove wrapper de código se o LLM adicionar
            for prefix in ("```markdown", "```"):
                if draft_text.startswith(prefix):
                    draft_text = draft_text[len(prefix):]
            if draft_text.endswith("```"):
                draft_text = draft_text[:-3]
            draft_text = draft_text.strip()
            logger.info(f"[Marco] Draft gerado: {len(draft_text)} chars.")
        except Exception as e:
            logger.error(f"[Marco] ETAPA 1 falhou: {e}. Usando fallback estático.")
            return self._generate_markdown_plan(user_name, project_name)

        # ── ETAPA 2: Revisão de Completude ────────────────────────────────────
        logger.info("[Marco] ETAPA 2 — Executando revisão de completude e coerência...")

        VALIDATION_SECTIONS = [
            "Objetivos SMART (Específicos, Mensuráveis, Atingíveis, Relevantes, com Prazo)",
            "Roadmap Financeiro com valores concretos em R$",
            "Estrutura Jurídica Recomendada",
            "Estratégia de Marketing e Vendas com canais e métricas",
            "Arquitetura Técnica com stack e estimativa de tempo",
            "Cronograma de Execução com divisão de responsabilidades",
            "KPIs e Métricas de Sucesso com metas numéricas",
            "Riscos E seus Planos de Contingência (não apenas mitigação)",
            "Checklist de Ações Imediatas com responsável e prazo por ação",
        ]
        sections_list = "\n".join(f"  {idx+1}. {s}" for idx, s in enumerate(VALIDATION_SECTIONS))

        review_prompt = (
            f"Você é Marco, Estrategista-Chefe do Hive Mind, revisando seu próprio trabalho.\n\n"
            f"Abaixo está o PLANO que você gerou na etapa anterior.\n\n"
            f"## CHECKLIST DE COMPLETUDE OBRIGATÓRIO\n"
            f"Verifique ITEM A ITEM se as seguintes seções estão presentes, detalhadas e com dados concretos:\n"
            f"{sections_list}\n\n"
            f"## SUA TAREFA:\n"
            f"1. Para cada seção faltante ou superficial, DETALHE-A com dados precisos.\n"
            f"2. Garanta que valores financeiros têm números reais (não 'a definir').\n"
            f"3. Garanta que o cronograma tem responsáveis nomeados para cada ação.\n"
            f"4. Garanta que cada risco tem UM plano de mitigação E UM plano de contingência.\n\n"
            f"## INSTRUÇÃO FINAL:\n"
            f"Retorne O PLANO COMPLETO E CORRIGIDO em formato MARKDOWN.\n"
            f"Não adicione introdução, apenas o documento Markdown revisado.\n\n"
            f"--- PLANO ORIGINAL ---\n"
            f"{draft_text}\n"
            f"--- FIM DO PLANO ORIGINAL ---"
        )

        final_text = draft_text  # fallback: se revisão falhar, usa o draft
        try:
            def _call_review():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=review_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.5,
                        max_output_tokens=66000,
                    ),
                )

            review_resp = await loop.run_in_executor(None, _call_review)
            reviewed = review_resp.text.strip()
            for prefix in ("```markdown", "```"):
                if reviewed.startswith(prefix):
                    reviewed = reviewed[len(prefix):]
            if reviewed.endswith("```"):
                reviewed = reviewed[:-3]
            reviewed = reviewed.strip()
            if len(reviewed) >= len(draft_text) * 0.8:  # revisão deve ser ao menos 80% do draft
                final_text = reviewed
                logger.info(f"[Marco] Revisão aprovada: {len(final_text)} chars.")
            else:
                logger.warning("[Marco] Revisão muito curta — mantendo draft original.")
        except Exception as e:
            logger.warning(f"[Marco] ETAPA 2 (revisão) falhou: {e}. Usando Draft sem revisão.")

        return final_text

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
            "verifique as variáveis BEY_AVATAR_ID_* no .env"
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

        # Inicia o avatar Beyond Presence sincronizado com a voz do especialista
        asyncio.create_task(_start_avatar_session(spec_id, session, room))

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
                        "version": DATA_PACKET_SCHEMA_VERSION,
                        "type": "transcript",
                        "speaker": name,
                        "text": text,
                    }).encode(),
                    reliable=True,
                )
            )

        # C5: Handler assíncrono para ativação de especialista.
        # REFATORADO PARA HANDOVER PEER-TO-PEER:
        # O especialista gera a resposta inicial e mantém o áudio aberto,
        # conversando livremente com o usuário. O turno só encerra quando
        # a IA aciona devolver_para_nathalia ou transferir_para_especialista.
        HANDOVER_TIMEOUT_SECONDS = 300.0  # 5 minutos máximo por turno livre

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
                await room.local_participant.publish_data(
                    json.dumps(payload).encode(),
                    reliable=True,
                )

            try:
                ctx_summary = msg.get("transcript_summary", "")
                context_text = msg.get("context", "")
                context_state = msg.get("context_state") or {}
                context_state_str = json.dumps(context_state, ensure_ascii=False)

                if ctx_summary or context_state:
                    new_instructions = (
                        SPECIALIST_SYSTEM_PROMPTS[spec_id]
                        + f"\n\n--- CONTEXTO ATUAL DA SESSÃO ---\n{ctx_summary}"
                        + f"\n\n--- ESTADO ESTRUTURADO DA SESSÃO ---\n{context_state_str}"
                    )
                    try:
                        result = agent.update_instructions(new_instructions)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as ui_err:
                        logger.warning(f"[{name}] Erro ao atualizar instruções: {ui_err}")

                await _emit("agent_activated", {"activated_in_ms": int((monotonic() - started_at) * 1000)})
                _subscribe_user_audio()

                # Determina o prompt baseado no tipo de ativação
                from_agent = msg.get("from_name")
                if from_agent:
                    # Transferência lateral: outro especialista repassou
                    prompt = (
                        f"{from_agent} acabou de transferir a palavra para você. "
                        f"O contexto da pergunta do usuário é: {context_text}. "
                        f"Inicie sua fala reconhecendo o colega e respondendo diretamente à pergunta do usuário. "
                        f"Exemplo: 'Obrigado {from_agent.split(' ')[0]}. Sobre essa questão...'"
                    )
                else:
                    # Ativação normal pela Nathália
                    prompt = (
                        f"Nathália acabou de te acionar. O contexto é: {context_text}. "
                        f"Responda de forma objetiva e profissional. "
                        f"Continue conversando livremente com o usuário. "
                        f"Quando o assunto da sua área estiver esgotado, use a ferramenta devolver_para_nathalia."
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

                try:
                    await asyncio.wait_for(
                        agent._handover_event.wait(),
                        timeout=HANDOVER_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[{name}] Timeout do turno livre ({HANDOVER_TIMEOUT_SECONDS}s). Devolvendo para Nathália automaticamente.")
                    agent._handover_result = {"type": "nathalia"}

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
                    await _emit("agent_done", {"elapsed_ms": int((monotonic() - started_at) * 1000)})
                    logger.info(f"[{name}] Turno encerrado. Palavra devolvida à Nathália.")

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
    project_id = room_name.replace("mentoria-", "", 1) if room_name.startswith("mentoria-") else room_name

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

        api_url = os.getenv("NEXT_API_URL", "http://localhost:3000").rstrip("/") + f"/api/projects/{project_id}/resume-context"

        def _get():
            try:
                logger.info(f"[Resume] Tentando buscar contexto em: {api_url}")
                req = urllib.request.Request(api_url, headers={"User-Agent": "MentoriaAI-Worker/1.0"})
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
                blackboard.transcript = parsed_entries[-250:]
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
        api_url = os.getenv("NEXT_API_URL", "http://localhost:3000").rstrip("/") + f"/api/projects/{project_id}/documents"
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

    await fetch_resume_context()
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

    # Inicia o avatar Beyond Presence da Nathália no room principal
    asyncio.create_task(_start_avatar_session("host", host_session, ctx.room))

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
        elif participant.identity.startswith("guest-"):
            # Convidados podem sair sem afetar a sessão
            logger.info(f"[Room] Convidado {participant.identity} saiu da sala. Sessão continua normalmente.")

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
                json.dumps({
                    "version": DATA_PACKET_SCHEMA_VERSION,
                    "type": "transcript",
                    "speaker": "Você",
                    "text": text,
                }).encode(),
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
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        json.dumps({
                            "version": DATA_PACKET_SCHEMA_VERSION,
                            "type": "session_end",
                            "full_transcript": blackboard.get_full_transcript(),
                            "context_summary": blackboard.get_context_summary(),
                            "context_state": blackboard.get_structured_context(),
                        }).encode(),
                        reliable=True,
                    )
                )
                shutdown_event.set()

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

            api_url = os.getenv("NEXT_API_URL", "http://localhost:3000") + f"/api/projects/{project_id}/resume-context"
            payload = json.dumps({"transcript": transcript_snapshot}).encode("utf-8")

            def _post():
                try:
                    req = urllib.request.Request(
                        api_url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req):
                        return True
                except Exception as e:
                    logger.warning(f"[Resume] Falha ao persistir snapshot de retomada: {e}")
                    return False

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _post)

        await persist_resume_snapshot()

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
