"""
Mentoria AI — Blackboard (Repositório de Contexto Compartilhado)
================================================================
Classe central que mantém o estado da sessão em memória.
Todos os agentes compartilham a mesma instância.

Extraído de worker.py para manter o monólito enxuto.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from time import monotonic
from typing import Optional

from livekit import rtc
from livekit.agents import AgentSession

from models import (
    SPECIALIST_NAMES,
    CONTEXT_RECENT_WINDOW,
    SPECIALIST_SILENCE_TIMEOUT_SECONDS,
    SPECIALIST_MAX_TURN_TIMEOUT_SECONDS,
)

logger = logging.getLogger("mentoria-ai")


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


# ── Helpers de handoff ─────────────────────────────────────────────────────────

def _normalize_handoff_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def classify_user_handoff_intent(text: str) -> Optional[str]:
    """
    Classifica se a mensagem do usuário indica fim da conversa com o especialista atual.
    
    Usa padrões RegEx baseados em expressões regulares para maior cobertura 
    linguística de intenções e detecção robusta de frases de encerramento.
    """
    normalized = _normalize_handoff_text(text)
    if not normalized:
        return None

    # 1. Padrões de conclusão explícita (expressões amplas de fim de dúvida e satisfação)
    done_patterns = [
        r"n[aã]o\s+tenho\s+(mais\s+)?(d[uú]vida|pergunta|quest)",
        r"sem\s+(mais\s+)?(d[uú]vida|pergunta)",
        r"(ficou|est[aá])\s+(bem\s+)?claro",
        r"tudo\s+(claro|certo|ok|entendido)",
        r"era\s+(exatamente\s+)?isso",
        r"respondeu\s+(tudo|minha\s+pergunta)",
        r"obrigad[oa]\s*,?\s*(era\s+isso|ficou\s+claro|por\s+tudo|t[aá]\s+[oó]timo|t[aá]\s+bom|pode)",
        r"pode\s+(seguir|passar|prosseguir|continuar)",
        r"(j[aá]\s+)?entendi\s+tudo",
        r"entendido\s*,?\s*pode\s+continuar",
        r"estou\s+satisfeit[oa]",
        r"satisfez\s+minha\s+d[uú]vida",
        r"n[aã]o\s+preciso\s+de\s+mais\s+nada",
        r"por\s+enquanto\s+[ée]\s+s[oó]"
    ]
    if any(re.search(p, normalized) for p in done_patterns):
        return "user_confirmed_done"

    # 2. Padrões de retorno direto para a Nathália
    host_patterns = [
        r"pode\s+voltar\s+p(r|ar)a\s+a?\s*nath[aá]lia",
        r"quero\s+falar\s+com\s+a?\s*nath[aá]lia",
        r"chama\s+a?\s*nath[aá]lia",
        r"passa\s+p(r|ar)a\s+a?\s*nath[aá]lia",
        r"volta\s+p(r|ar)a\s+a?\s*nath[aá]lia",
        r"quero\s+a?\s*nath[aá]lia",
        r"fala\s+com\s+a\s+nath[aá]lia"
    ]
    if any(re.search(p, normalized) for p in host_patterns):
        return "user_requested_host"

    # 3. Padrões de mudança radical de assunto
    topic_patterns = [
        r"(vamos|quero)\s+mudar\s+de\s+assunto",
        r"vamos\s+(falar|ir)\s+p(r|ar)a\s+outro\s+(assunto|tema|ponto)",
        r"(falar|pensar)\s+de\s+outra\s+coisa",
        r"outro\s+tema\s+agora",
        r"muda\s+de\s+assunto"
    ]
    if any(re.search(p, normalized) for p in topic_patterns):
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
