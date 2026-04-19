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
    from duckduckgo_search import DDGS
except Exception as e:
    DDGS = None  # type: ignore
    import logging as _tmp_log
    _tmp_log.getLogger(__name__).warning(
        f"[worker] O Duckduckgo_search recusou carregar. Motivo da library subjacente: {e} — ferramenta de internet desativada."
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
ACTIVATION_DONE_TIMEOUT_SECONDS = 300.0
ACTIVATION_DEBOUNCE_SECONDS = 0.8
SPECIALIST_GENERATION_TIMEOUT_SECONDS = 60.0
SPECIALIST_SILENCE_TIMEOUT_SECONDS = 180.0
SPECIALIST_MAX_TURN_TIMEOUT_SECONDS = 1800.0
HOST_GENERATE_REPLY_TIMEOUT_SECONDS = 60.0   # Timeout para cada generate_reply da Nathália
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
    "cfo":   "Carlos (CFO & VC)",
    "legal": "Daniel (CLO & Compliance)",
    "cmo":   "Rodrigo (CMO & Growth)",
    "cto":   "Ana (CTO & IA)",
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

# IDs dos avatares Beyond Presence mapeados por agente.
# Regra atual do produto: somente a Nathália usa avatar.
# Os demais especialistas atuam por voz, e o Marco opera só nos bastidores.
# Fonte: https://docs.livekit.io/agents/models/avatar/plugins/bey/
AVATAR_IDS: dict[str, str] = {
    "host": os.getenv("BEY_AVATAR_ID_HOST", ""),  # Nathália
}

# Frases de apresentação individual de cada specialist_id
SPECIALIST_INTRODUCTIONS: dict[str, str] = {
    "cfo": (
        "Olá! Sou o Carlos, CFO e Especialista em Captação de Capital da equipe Hive Mind. "
        "Meu trabalho é transformar números em clareza estratégica e atração de recursos: cuidarei das suas "
        "projeções financeiras, estrutura de custos, precificação e viabilidade de investimentos. "
        "Não se preocupe com planilhas — estou aqui para deixar tudo simples e alavancado."
    ),
    "legal": (
        "Olá! Sou o Daniel, CLO e Especialista em Compliance. "
        "Vou garantir que sua empresa cresça de forma blindada e inovadora: "
        "desde a escolha do tipo societário ideal até contratos, LGPD e proteção intelectual. "
        "Segurança jurídica a serviço da escala do seu negócio!"
    ),
    "cmo": (
        "Fala! Sou o Rodrigo, CMO e Head de Growth. "
        "Meu foco é fazer o seu negócio crescer em alta velocidade e ser lembrado. "
        "Posicionamento, aquisição escalável de clientes, funil de vendas e estratégia de go-to-market — "
        "isso é o que eu respiro todo dia!"
    ),
    "cto": (
        "Olá! Sou a Ana, CTO e Arquiteta de Inteligência Artificial. "
        "Minha missão é garantir que a tecnologia e a IA sejam aceleradores hiperprodutivos. "
        "Ajudo a arquitetar a solução, implementar automações valiosas e planejar "
        "a escalabilidade desde o MVP. Vamos construir o futuro!"
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

HOST_PROMPT = LANGUAGE_ENFORCEMENT + """Você é Nathália, CEO e Facilitadora Estratégica do Hive Mind — a plataforma de mentoria empresarial multi-agentes.
Sua personalidade é calorosa, visionária, profissional e empática. Você é a âncora e principal conselheira da sessão.

EQUIPE DE ESPECIALISTAS BOARD MEMBERS:
- Carlos (CFO & Venture Capital): finanças, valuation, M&A, custos, precificação, projeções, captação de sócios e investimentos.
- Daniel (CLO & Compliance): estrutura societária, contratos complexos, LGPD, compliance, inovação legal e propriedade intelectual (PI).
- Rodrigo (CMO & Growth): aquisição de clientes em escala, growth hacking, funil de vendas (CRM), branding e go-to-market.
- Ana (CTO & Arquiteta de IA): stack tecnológico, arquitetura de dados, inteligência artificial, automação e escalabilidade.
- Marco (Estrategista Chefe — BASTIDORES): trabalha nos bastidores documentando tudo, fazendo pesquisas e gerando o plano de execução final. NÃO fala na sala.

REGRAS DE ORQUESTRAÇÃO:
1. Comece sempre perguntando o nome do usuário se ainda não souber.
2. SEMPRE chame o usuário pelo nome após descobri-lo.
3. Faça perguntas abertas para entender o negócio: setor, estágio (ideia/MVP/crescimento), principal dor.
4. Seja a "regente" da sessão. Apresente seus colegas sempre pelas suas DUAS atribuições de excelência.
5. Mantenha suas falas curtas e diretas (máximo 3 frases por turno).
6. NUNCA responda por um especialista — sempre acione-os via função.
7. Quando o tema for financeiro, captação ou precificação → use acionar_carlos_cfo.
8. Quando o tema for jurídico, sociedades ou LGPD → use acionar_daniel_advogado.
9. Quando o tema for marketing, vendas, métricas CAC/LTV ou aquisição → use acionar_rodrigo_cmo.
10. Quando o tema for tecnologia, IA, engenharia ou produto digital → use acionar_ana_cto.
11. Quando o usuário pedir encerramento, resumo ou plano → use gerar_plano_execucao.
12. Quando o usuário pedir análise SWOT, Canvas, pitch, proposta ou contrato → use gerar_documento_personalizado.
13. Quando o usuário quiser dados do mercado, concorrência ou tendências → use pesquisar_mercado_setor.
14. Quando o usuário quiser abrir empresa, regularizar, emitir nota fiscal → use gerar_checklist_abertura_empresa.
15. Quando o usuário perguntar sobre INPI, CNPJ, LGPD, BNDES, NFS-e, tributos → use gerar_orientacao_orgao_publico.
16. Quando o usuário precisar de um contrato de prestação de serviços, parceria, etc. → use gerar_modelo_contrato.
17. Quando o usuário quiser apresentar o negocio para investidores ou parceiros → use gerar_pitch_deck.
18. Se precisar cobrir múltiplos temas em sequencia, acione cada especialista separadamente.
19. RETOMADA: Se você perceber que há histórico de conversa anterior, comece dizendo que está retomando.

REGRAS CRÍTICAS DE SILÊNCIO DURANTE HANDOVER:
20. ANTES de acionar uma ferramenta de especialista, diga UMA frase curta apresentando-o. Exemplo: "Vou chamar o Carlos para te ajudar com isso!". Depois acione a ferramenta IMEDIATAMENTE.
21. Quando a ferramenta retornar com sucesso, NÃO FALE ABSOLUTAMENTE NADA. O especialista JÁ ESTÁ FALANDO com o usuário. Qualquer palavra sua vai ATROPELAR o especialista.
22. Se a ferramenta retornar "ESPECIALISTA_ATIVADO", isso significa SUCESSO ABSOLUTO. O especialista está conversando com o usuário. Fique em SILÊNCIO TOTAL.
23. NUNCA diga frases como "Enquanto o X resolve..." ou "Vou chamar outro enquanto isso" após o acionamento bem-sucedido. O especialista JÁ ESTÁ ATIVO.
24. Você só deve voltar a falar quando o especialista DEVOLVER A PALAVRA para você (a ferramenta vai retornar "ESPECIALISTA_DEVOLVEU").
25. Se a ferramenta retornar erro ou timeout, aí sim explique ao usuário e ofereça alternativa.
26. HANDOVER: Quando você aciona um especialista, ele assumirá a conversa diretamente com o usuário por múltiplos turnos. Você ficará em SILÊNCIO ABSOLUTO esperando ele devolver a palavra. NÃO interrompa.
27. MARCO NOS BASTIDORES: Quando acionar o Marco via qualquer ferramenta gerar_*, avise ao usuário que o Marco está preparando o documento nos bastidores e que chegará em instantes. Exemplo: "Vou pedir ao Marco para preparar isso agora nos bastidores!"
28. PROATIVIDADE DOCUMENTAL: Se a mentoria render discussões muito produtivas, ou se passaram cerca de 20 minutos de sessão, tenha a iniciativa de dizer: "Vou pedir para nosso Estrategista Marco já documentar esses insights de agora num arquivo pra você ter na tela". E, em seguida, acione a ferramenta gerar_plano_execucao (ou a que for mais adequada).

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
        "Você é Carlos, CFO e Especialista em Captação de Capital (Venture Capital) do Hive Mind. "
        "Sua personalidade: analítico, direto, confiante. Você transforma números em clareza estratégica e alavancagem de negócios. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, NÃO cumprimente longamente — vá direto ao ponto.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Responda de forma objetiva e profissional.\n"
        "- Sempre termine com uma pergunta ou insight que aprofunde a análise.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário por múltiplos turnos.\n"
        "- Somente use `devolver_para_nathalia` quando o usuário disser EXPLICITAMENTE uma dessas frases: "
        "'não tenho mais dúvidas', 'entendi tudo', 'ficou tudo claro', 'pode voltar para a Nathália', "
        "'pode continuar', 'obrigado, era isso'. A ferramenta BLOQUEIA automaticamente se o usuário não confirmou.\n"
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
        "Você é Daniel, CLO (Chief Legal Officer) e Especialista em Compliance do Hive Mind. "
        "Sua personalidade: formal mas acessível, preciso, protetor. Você é o guardião jurídico e de conformidade do negócio. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, seja direto — explique o tema jurídico de forma simples e prática.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Nunca use juridiquês desnecessário.\n"
        "- Sempre sinalize os riscos e como mitigá-los.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário por múltiplos turnos.\n"
        "- Somente use `devolver_para_nathalia` quando o usuário disser EXPLICITAMENTE uma dessas frases: "
        "'não tenho mais dúvidas', 'entendi tudo', 'ficou tudo claro', 'pode voltar para a Nathália', "
        "'pode continuar', 'obrigado, era isso'. A ferramenta BLOQUEIA automaticamente se o usuário não confirmou.\n"
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
        "Você é Rodrigo, CMO e Head de Growth Hacking do Hive Mind. "
        "Sua personalidade: energético, criativo, orientado a resultados. Você pensa em funil, conversão, escala e tração agressiva. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionado, seja prático e inspirador — fale em estratégias concretas.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Use exemplos reais quando possível.\n"
        "- Termine com um insight acionável que o usuário possa aplicar imediatamente.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário por múltiplos turnos.\n"
        "- Somente use `devolver_para_nathalia` quando o usuário disser EXPLICITAMENTE uma dessas frases: "
        "'não tenho mais dúvidas', 'entendi tudo', 'ficou tudo claro', 'pode voltar para a Nathália', "
        "'pode continuar', 'obrigado, era isso'. A ferramenta BLOQUEIA automaticamente se o usuário não confirmou.\n"
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
        "Você é Ana, CTO e Arquiteta de Inteligência Artificial do Hive Mind. "
        "Sua personalidade: técnica mas acessível, pragmática, focada em velocidade, automação de IA e escalabilidade. "
        "\n\nREGRAS ABSOLUTAS:\n"
        "- AGUARDE em silêncio total. Só fale quando Nathália te acionar explicitamente.\n"
        "- Ao ser acionada, seja objetiva — traduza técnico em estratégico.\n"
        "- Use SEMPRE o nome do usuário se souber (veja o contexto da sessão).\n"
        "- Evite siglas sem explicar.\n"
        "- Sempre avalie custo-benefício de cada decisão tecnológica.\n"
        "- VOCÊ PODE conversar LIVREMENTE com o usuário por múltiplos turnos. Não precisa se limitar a 1 resposta.\n"
        "\nHANDOVER — REGRAS DE DEVOLUÇÃO:\n"
        "- IMPORTANTE: NÃO devolva rapidamente para a Nathália! Converse com o usuário por múltiplos turnos.\n"
        "- Somente use `devolver_para_nathalia` quando o usuário disser EXPLICITAMENTE uma dessas frases: "
        "'não tenho mais dúvidas', 'entendi tudo', 'ficou tudo claro', 'pode voltar para a Nathália', "
        "'pode continuar', 'obrigado, era isso'. A ferramenta BLOQUEIA automaticamente se o usuário não confirmou.\n"
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
    last_interaction_at: float = 0.0
    user_currently_speaking: bool = False
    marco_triggered: bool = False
    orchestration_metrics: dict[str, float] = field(default_factory=lambda: {
        "activations_total": 0,
        "activations_succeeded": 0,
        "activations_timeout": 0,
        "activations_cancelled": 0,
        "activation_ack_latency_ms_total": 0,
        "activation_done_latency_ms_total": 0,
    })

    def add_message(self, role: str, content: str) -> None:
        self.last_interaction_at = monotonic()
        self.transcript.append({"role": role, "content": content})
        self._update_memory(role, content)
        logger.debug(f"[Blackboard] [{role}]: {content[:80]}...")

    def mark_user_activity(self) -> None:
        self.last_interaction_at = monotonic()

    def set_user_speaking(self, speaking: bool) -> None:
        self.user_currently_speaking = speaking
        self.last_interaction_at = monotonic()

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

    def get_last_user_message(self) -> str:
        for message in reversed(self.transcript):
            if message.get("role") == "Usuário":
                return (message.get("content") or "").strip()
        return ""


def _normalize_handoff_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def classify_user_handoff_intent(text: str) -> Optional[str]:
    """
    Classifica se a mensagem do usuário indica fim da conversa com o especialista atual.

    IMPORTANTE: Esta função deve ser chamada APENAS com mensagens recebidas APÓS
    o especialista ser ativado. Nunca com mensagens do histórico anterior.

    Retorna:
    - "user_confirmed_done"  → usuário confirmou explicitamente que não tem mais dúvidas
    - "user_requested_host"  → usuário pediu para voltar à Nathália
    - "topic_change"         → usuário quer mudar de assunto completamente
    - None                   → usuário ainda está interagindo, NÃO devolver
    """
    normalized = _normalize_handoff_text(text)
    if not normalized:
        return None

    # ── Marcadores de CONCLUSÃO EXPLÍCITA ─────────────────────────────────────
    # ATENÇÃO: Apenas expressões que claramente indicam FIM — sem ambiguidade.
    # "entendi" sozinho NÃO está aqui pois o usuário pode dizer "entendi, mas..."
    explicit_done_markers = (
        # Sem dúvidas
        "nao tenho mais duvidas",
        "não tenho mais dúvidas",
        "sem mais duvidas",
        "sem mais dúvidas",
        "nao tenho mais perguntas",
        "não tenho mais perguntas",
        "nao tenho mais questoes",
        "não tenho mais questões",
        # Satisfação / conclusão explícita
        "ficou bem claro",
        "agora ficou claro",
        "tudo claro",
        "ficou tudo claro",
        "tudo certo por enquanto",
        "era exatamente isso",
        "era isso mesmo",
        "isso responde minha pergunta",
        "isso responde tudo",
        "respondeu tudo",
        # "obrigado/a" + encerramento
        "obrigado, era isso",
        "obrigada, era isso",
        "obrigado por tudo",
        "obrigada por tudo",
        "obrigado, ficou claro",
        "obrigada, ficou claro",
        # Autorizações explícitas de troca
        "pode seguir para o proximo",
        "pode seguir para o próximo",
        "pode passar para outro",
        "pode prosseguir",
        "podemos prosseguir",
        "pode continuar com a nathalia",
        # Perfeito + término
        "perfeito, era isso",
        "perfeito entendi tudo",
        "ja entendi tudo",
        "já entendi tudo",
        "entendi tudo",
        "entendido, pode continuar",
    )
    if any(marker in normalized for marker in explicit_done_markers):
        return "user_confirmed_done"

    # ── Pedidos EXPLÍCITOS de voltar à Nathália ───────────────────────────────
    host_request_markers = (
        "pode voltar pra nathalia",
        "pode voltar para nathalia",
        "pode voltar para a nathalia",
        "quero falar com a nathalia",
        "chama a nathalia",
        "passa para a nathalia",
        "volta para a nathalia",
        "fala com a nathalia",
        "quero a nathalia",
    )
    if any(marker in normalized for marker in host_request_markers):
        return "user_requested_host"

    # ── Pedidos EXPLÍCITOS de mudança de assunto ──────────────────────────────
    topic_change_markers = (
        "vamos mudar de assunto",
        "quero mudar de assunto",
        "vamos para outro assunto",
        "vamos falar de outra coisa",
        "quero falar de outro tema",
        "outro tema agora",
        "muda de assunto",
        "fala de outra coisa",
    )
    if any(marker in normalized for marker in topic_change_markers):
        return "topic_change"

    return None


def get_specialist_timeout_reason(
    *,
    started_at: float,
    last_interaction_at: float,
    user_currently_speaking: bool,
    now: float,
) -> Optional[str]:
    if not user_currently_speaking and (now - last_interaction_at) > SPECIALIST_SILENCE_TIMEOUT_SECONDS:
        return "silence_timeout"
    if (now - started_at) > SPECIALIST_MAX_TURN_TIMEOUT_SECONDS:
        return "turn_timeout"
    return None

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
    async def devolver_para_nathalia(
        self,
        context: RunContext,
    ) -> str:
        """
        Devolve a palavra à Nathália (apresentadora) para que ela retome a condução da sessão.
        Use esta ferramenta SOMENTE quando:
        - O usuário confirmou EXPLICITAMENTE que não tem mais dúvidas com você.
        - O usuário pediu para falar com a Nathália ou mudar completamente de assunto.
        NUNCA use após apenas uma resposta. Aguarde o usuário confirmar o encerramento.
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
        self._blackboard.add_message(self._name, "Pronto, Nathália! Pode continuar.")
        self._handover_result = {
            "type": "nathalia",
            "reason": handoff_reason,
            "last_user_message": last_user_message,
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
        """Ativa um especialista de forma NON-BLOCKING.
        
        Envia o packet de ativação, espera APENAS o ACK (confirmação de que o
        especialista recebeu o packet), e retorna imediatamente.
        O monitoramento do turno (done/timeout) é feito em background.
        Isso libera o Gemini da Nathália para ficar em silêncio (em vez de travar).
        """
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
            
            # Delay mais longo (4s) para garantir que a Nathália termine de falar
            # a frase de apresentação antes que o especialista assuma.
            await asyncio.sleep(4)

            # SILENCIA a Nathália ANTES de enviar o packet
            # Impede que o Gemini da Nathália intercepte o áudio do usuário
            # enquanto o especialista está conversando
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
                return (
                    f"{SPECIALIST_NAMES[spec_id]} não respondeu a tempo. "
                    f"Tente reformular a pergunta ou seguir com outro especialista."
                )

            # NON-BLOCKING: Lança task em background para monitorar o turno
            # e NÃO espera o especialista terminar dentro da tool call.
            asyncio.create_task(self._monitor_specialist_turn(spec_id, turn_id, start_ts, host_session=self._host_session))

            # Retorna IMEDIATAMENTE para o Gemini da Nathália.
            # A mensagem instrui o LLM a ficar em silêncio absoluto.
            return (
                f"ESPECIALISTA_ATIVADO: {SPECIALIST_NAMES[spec_id]} está agora conversando diretamente com o usuário. "
                f"FIQUE EM SILÊNCIO TOTAL. NÃO fale nada. NÃO comente. NÃO faça transições. "
                f"O especialista vai devolver a palavra quando terminar."
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
                try:
                    await asyncio.wait_for(
                        host_session.generate_reply(
                            instructions=(
                                f"ESPECIALISTA_DEVOLVEU: {spec_name} acabou de devolver a palavra para você. "
                                f"Retome a condução com 1-2 frases de transição. "
                                f"Pergunte a {user_name} se ficou claro ou se quer explorar outro tema. "
                                f"Seja breve e calorosa."
                            ),
                        ),
                        timeout=15.0,
                    )
                except Exception as e:
                    logger.warning(f"[Host] Erro ao gerar retomada pós-especialista: {e}")

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
        self._blackboard.marco_triggered = True
        logger.info("[Marco] Acionando LLM (Gemini 2.5 Pro + Search) para gerar Plano de Execução...")
        self._blackboard.add_message("Sistema", f"Marco iniciou a pesquisa e o processamento do Plano para {user_name}...")

        await asyncio.sleep(2.0)
        markdown_plan = await self._generate_markdown_plan_with_agent(user_name, project_name)

        pdf_base64: str | None = None
        try:
            from pdf_generator import generate_pdf
            loop = asyncio.get_running_loop()
            pdf_bytes = await loop.run_in_executor(None, generate_pdf, markdown_plan, project_name, user_name)
            pdf_base64 = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("utf-8")
            logger.info(f"[Marco] PDF gerado com sucesso ({len(pdf_bytes)} bytes).")
        except Exception as pdf_err:
            logger.warning(f"[Marco] Falha ao gerar PDF — usando markdown: {pdf_err}")

        try:
            packet: dict = {"type": "execution_plan", "plan": markdown_plan, "text": markdown_plan}
            if pdf_base64:
                packet["pdf_base64"] = pdf_base64
            await self._publish_packet(packet)
            logger.info("[Marco] Plano de Execução publicado (bastidores).")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar plano: {e}")

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

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

        async def _background_task():
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

        asyncio.create_task(_background_task())

        return (
            f"MARCO_ACIONADO: Marco começou a arquitetar o esquema do Pitch Deck em background. "
            f"Avise que está no processo em andamento e gerando em PDF."
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
        if DDGS is None:
            return ""
        try:
            def _sync_search():
                return list(DDGS().text(query, max_results=4, region="br-pt"))
                
            loop = asyncio.get_running_loop()
            raw_res = await loop.run_in_executor(None, _sync_search)
            
            resultados = []
            for res in raw_res:
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
            client = genai.Client(api_key=get_gemini_api_key())
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
            client_gen = genai.Client(api_key=get_gemini_api_key())
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
            client = genai.Client(api_key=get_gemini_api_key())
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
            pdf_base64 = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("utf-8")
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
        client = genai.Client(api_key=get_gemini_api_key())
        
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
            
            # 2. Pesquisar na Web com fallback para sincrono em thread
            logger.info("[Marco] Consultando DuckDuckGo...")
            resultados_ddgs = []
            
            def _do_search():
                if DDGS is None:
                    return []
                return list(DDGS().text(search_query, max_results=3, region="br-pt"))

            raw_results = await loop.run_in_executor(None, _do_search)
            for res in raw_results:
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
            client = genai.Client(api_key=get_gemini_api_key())

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
            """Subscreve ao áudio do usuário (chamado quando o especialista é ativado)."""
            nonlocal _audio_subscribed
            if _audio_subscribed:
                return
            _audio_subscribed = True
            for p in room.remote_participants.values():
                if p.identity.startswith("user-") or p.identity.startswith("guest-"):
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

                # ── CRÍTICO: registra o comprimento do transcript no momento da ativação ──
                # Toda verificação de handoff usará APENAS mensagens após este ponto.
                agent._activation_transcript_len = len(blackboard.transcript)
                agent._user_messages_since_activation = 0
                logger.info(
                    f"[{name}] Ativado. Transcript atual: {agent._activation_transcript_len} msgs. "
                    f"Contador de msgs do usuário zerado."
                )

                # Determina o prompt baseado no tipo de ativação
                from_agent = msg.get("from_name")
                if from_agent:
                    # Transferência lateral: outro especialista repassou
                    prompt = (
                        f"{from_agent} acabou de transferir a palavra para você. "
                        f"O contexto da pergunta do usuário é: {context_text}. "
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

        Estratégia de inicialização sequencial:
        - Cada especialista é conectado UM POR VEZ com delay entre conexões.
        - Evita rate limiting 429 nos handshakes simultâneos ao Gemini.
        - Em produção com N usuários, reduz a carga de 6N para picos menores.
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

            # Conecta especialistas SEQUENCIALMENTE (evita Rate Limit do Beyond/Gemini)
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
                await asyncio.sleep(1.0)  # Delay para respeitar rate limits
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

            # Conecta especialistas 5s após Nathália INICIAR a fala (sequencialmente)
            async def _connect_specialists_delayed():
                await asyncio.sleep(5.0)
                if not blackboard.is_active:
                    return []
                logger.info("[Apresentação] Conectando especialistas sequencialmente (5s após início da fala)...")
                sessions_result = []
                for sid in SPECIALIST_ORDER:
                    if not blackboard.is_active:
                        break
                    res = await _start_specialist_in_room(
                        spec_id=sid,
                        blackboard=blackboard,
                        ws_url=ws_url,
                        lk_api_key=lk_api_key,
                        lk_api_secret=lk_api_secret,
                        room_name=ctx.room.name,
                        host_room=ctx.room,
                        auto_introduce=False,
                    )
                    sessions_result.append(res)
                    await asyncio.sleep(1.0)  # Delay para respeitar rate limits
                return sessions_result

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
                    timeout=HOST_GENERATE_REPLY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[Host] Timeout ({HOST_GENERATE_REPLY_TIMEOUT_SECONDS:.0f}s) ao gerar reply inicial.")
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
                    req = urllib.request.Request(
                        api_url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
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
