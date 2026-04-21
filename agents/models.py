"""
Mentoria AI — Constantes e Configurações do Sistema
=====================================================
Contém todas as constantes de configuração, vozes, nomes,
identidades, timeouts e marcadores de estado compartilhados.

Extraído de worker.py para manter o monólito enxuto.
"""

import os

# ── Modelo Gemini Realtime ─────────────────────────────────────────────────────
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

# ── Versão do protocolo de data packets ────────────────────────────────────────
DATA_PACKET_SCHEMA_VERSION = "1.0"

# ── Timeouts e Limites ─────────────────────────────────────────────────────────
ACTIVATION_ACK_TIMEOUT_SECONDS = 8.0
ACTIVATION_DONE_TIMEOUT_SECONDS = 300.0
ACTIVATION_DEBOUNCE_SECONDS = 0.8
SPECIALIST_GENERATION_TIMEOUT_SECONDS = 60.0
SPECIALIST_SILENCE_TIMEOUT_SECONDS = 60.0
SPECIALIST_MAX_TURN_TIMEOUT_SECONDS = 1800.0
HOST_GENERATE_REPLY_TIMEOUT_SECONDS = 60.0   # Timeout para cada generate_reply da Nathália
CONTEXT_RECENT_WINDOW = 12
SPECIALIST_READY_WAIT_SECONDS = 70.0  # Tempo máximo aguardando agent_ready (especialistas levam até ~60s na retomada)

# ── Vozes por agente (Gemini TTS nativo) ───────────────────────────────────────
AGENT_VOICES: dict[str, str] = {
    "host":  "Aoede",    # Nathália – feminina suave
    "cfo":   "Charon",   # Carlos   – masculina grave
    "legal": "Orus",     # Daniel   – masculina formal
    "cmo":   "Puck",     # Rodrigo  – masculina dinâmica
    "cto":   "Kore",     # Ana      – feminina técnica
    "plan":  "Fenrir",   # Marco    – masculina autoritativa (reusa Fenrir pois o Gemini tem 5 vozes)
}

# ── Nomes de exibição para cada agente ─────────────────────────────────────────
SPECIALIST_NAMES: dict[str, str] = {
    "cfo":   "Carlos (CFO & VC)",
    "legal": "Daniel (CLO & Compliance)",
    "cmo":   "Rodrigo (CMO & Growth)",
    "cto":   "Ana (CTO & IA)",
    "plan":  "Marco (Estrategista)",
}

# ── IDs de identity no LiveKit para cada especialista ──────────────────────────
SPECIALIST_IDENTITIES: dict[str, str] = {
    "cfo":   "agent-cfo",
    "legal": "agent-legal",
    "cmo":   "agent-cmo",
    "cto":   "agent-cto",
    "plan":  "agent-plan",
}

# ── IDs dos avatares Beyond Presence mapeados por agente ───────────────────────
# Regra atual do produto: somente a Nathália usa avatar.
# Os demais especialistas atuam por voz, e o Marco opera só nos bastidores.
# Fonte: https://docs.livekit.io/agents/models/avatar/plugins/bey/
AVATAR_IDS: dict[str, str] = {
    "host": os.getenv("BEY_AVATAR_ID_HOST", ""),  # Nathália
}

# ── Ordem de entrada dos especialistas na apresentação sequencial ──────────────
# Marco (plan) NÃO entra aqui pois opera nos bastidores sem voz.
SPECIALIST_ORDER: list[str] = ["cfo", "legal", "cmo", "cto"]

# ── Pausa entre apresentações de especialistas ─────────────────────────────────
POST_INTRO_WAIT: float = 0.50

# ── Mapeamento de IDs amigáveis para spec_ids internos (Lateral Transfer) ──────
LATERAL_TRANSFER_MAP: dict[str, str] = {
    "carlos_cfo": "cfo",
    "daniel_advogado": "legal",
    "rodrigo_cmo": "cmo",
    "ana_cto": "cto",
}
