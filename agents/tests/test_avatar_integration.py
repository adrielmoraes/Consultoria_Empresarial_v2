"""
Testes de integração — Avatares Beyond Presence
=================================================
Verifica:
 1. Que AVATAR_IDS mapeia corretamente todos os agentes.
 2. Que _start_avatar_session retorna None graciosamente quando BEY_AVAILABLE=False.
 3. Que _start_avatar_session chama bey_plugin.AvatarSession com os parâmetros corretos.
 4. Que erros na API Beyond são capturados sem derrubar o worker.
"""

from __future__ import annotations

import sys
import os
import asyncio
import importlib
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Garante que o diretório /agents está no path para importar worker.py
# ---------------------------------------------------------------------------
_AGENTS_DIR = os.path.dirname(os.path.dirname(__file__))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)


# ---------------------------------------------------------------------------
# Fixture: carrega constantes do worker sem executar o entrypoint
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def worker_module():
    """Importa o módulo worker com variáveis de ambiente mockadas."""
    env_patch = {
        "BEY_API_KEY": "sk-test-key",
        "BEY_AVATAR_ID_HOST":  "694c83e2-8895-4a98-bd16-56332ca3f449",
        "BEY_AVATAR_ID_LEGAL": "b63ba4e6-d346-45d0-ad28-5ddffaac0bd0_v2",
        "BEY_AVATAR_ID_CFO":   "2ed7477f-3961-4ce1-b331-5e4530c55a57",
        "BEY_AVATAR_ID_CMO":   "7124071d-480e-4fdc-ad0e-a2e0680f1378",
        "BEY_AVATAR_ID_CTO":   "2bc759ab-a7e5-4b91-941d-9e42450d6546",
        "GEMINI_API_KEY":      "AIza-test",
        "LIVEKIT_URL":         "wss://test.livekit.cloud",
        "LIVEKIT_API_KEY":     "APItest",
        "LIVEKIT_API_SECRET":  "secrettest",
    }
    with patch.dict(os.environ, env_patch):
        # Remove cache para forçar re-importação com novo env
        if "worker" in sys.modules:
            del sys.modules["worker"]
        import worker as w
        yield w


# ---------------------------------------------------------------------------
# Testes: AVATAR_IDS
# ---------------------------------------------------------------------------

class TestAvatarIds:
    """Verifica que AVATAR_IDS mapeia corretamente todos os agentes esperados."""

    EXPECTED_AGENTS = {"host", "legal", "cfo", "cmo", "cto"}
    EXPECTED_IDS = {
        "host":  "694c83e2-8895-4a98-bd16-56332ca3f449",
        "legal": "b63ba4e6-d346-45d0-ad28-5ddffaac0bd0_v2",
        "cfo":   "2ed7477f-3961-4ce1-b331-5e4530c55a57",
        "cmo":   "7124071d-480e-4fdc-ad0e-a2e0680f1378",
        "cto":   "2bc759ab-a7e5-4b91-941d-9e42450d6546",
    }

    def test_avatar_ids_contém_todos_os_agentes(self, worker_module):
        assert self.EXPECTED_AGENTS.issubset(set(worker_module.AVATAR_IDS.keys())), (
            f"AVATAR_IDS faltando agentes: {self.EXPECTED_AGENTS - set(worker_module.AVATAR_IDS.keys())}"
        )

    def test_avatar_ids_valor_correto_host(self, worker_module):
        assert worker_module.AVATAR_IDS["host"] == self.EXPECTED_IDS["host"]

    def test_avatar_ids_valor_correto_legal(self, worker_module):
        assert worker_module.AVATAR_IDS["legal"] == self.EXPECTED_IDS["legal"]

    def test_avatar_ids_valor_correto_cfo(self, worker_module):
        assert worker_module.AVATAR_IDS["cfo"] == self.EXPECTED_IDS["cfo"]

    def test_avatar_ids_valor_correto_cmo(self, worker_module):
        assert worker_module.AVATAR_IDS["cmo"] == self.EXPECTED_IDS["cmo"]

    def test_avatar_ids_valor_correto_cto(self, worker_module):
        assert worker_module.AVATAR_IDS["cto"] == self.EXPECTED_IDS["cto"]

    def test_marco_nao_tem_avatar(self, worker_module):
        """Marco opera nos bastidores e NÃO deve ter avatar."""
        assert "plan" not in worker_module.AVATAR_IDS or worker_module.AVATAR_IDS.get("plan", "") == "", (
            "Marco (plan) não deve ter avatar configurado."
        )


# ---------------------------------------------------------------------------
# Testes: _start_avatar_session — fallback quando BEY_AVAILABLE=False
# ---------------------------------------------------------------------------

class TestStartAvatarSessionFallback:
    """Quando BEY_AVAILABLE=False, _start_avatar_session deve retornar None sem erros."""

    @pytest.mark.anyio
    async def test_retorna_none_quando_bey_indisponivel(self, worker_module):
        mock_session = MagicMock()
        mock_room = MagicMock()

        original = worker_module.BEY_AVAILABLE
        try:
            worker_module.BEY_AVAILABLE = False
            result = await worker_module._start_avatar_session("host", mock_session, mock_room)
            assert result is None, "Deve retornar None quando BEY_AVAILABLE=False"
        finally:
            worker_module.BEY_AVAILABLE = original

    @pytest.mark.anyio
    async def test_retorna_none_para_agente_sem_avatar_id(self, worker_module):
        """Se o spec_id não tiver avatar_id, retorna None graciosamente."""
        mock_session = MagicMock()
        mock_room = MagicMock()

        original = worker_module.BEY_AVAILABLE
        original_ids = dict(worker_module.AVATAR_IDS)
        try:
            worker_module.BEY_AVAILABLE = True
            worker_module.AVATAR_IDS["host"] = ""  # simula ID vazio
            result = await worker_module._start_avatar_session("host", mock_session, mock_room)
            assert result is None
        finally:
            worker_module.BEY_AVAILABLE = original
            worker_module.AVATAR_IDS.update(original_ids)


# ---------------------------------------------------------------------------
# Testes: _start_avatar_session — fluxo feliz com mock do plugin bey
# ---------------------------------------------------------------------------

class TestStartAvatarSessionHappyPath:
    """Verifica que a função chama bey_plugin corretamente quando disponível."""

    @pytest.mark.anyio
    async def test_chama_avatar_session_com_parametros_corretos(self, worker_module):
        mock_session = MagicMock()
        mock_room = MagicMock()

        mock_avatar = MagicMock()
        mock_avatar.start = AsyncMock(return_value=None)

        mock_bey = MagicMock()
        mock_bey.AvatarSession.return_value = mock_avatar

        original_bey = worker_module.bey_plugin
        original_available = worker_module.BEY_AVAILABLE
        try:
            worker_module.bey_plugin = mock_bey
            worker_module.BEY_AVAILABLE = True

            result = await worker_module._start_avatar_session("cfo", mock_session, mock_room)

            mock_bey.AvatarSession.assert_called_once()
            call_kwargs = mock_bey.AvatarSession.call_args.kwargs
            assert call_kwargs["avatar_id"] == worker_module.AVATAR_IDS["cfo"]
            assert "Carlos" in call_kwargs.get("avatar_participant_name", "")
            mock_avatar.start.assert_awaited_once_with(mock_session, room=mock_room)
            assert result == mock_avatar
        finally:
            worker_module.bey_plugin = original_bey
            worker_module.BEY_AVAILABLE = original_available

    @pytest.mark.anyio
    async def test_captura_excecao_sem_propagar(self, worker_module):
        """Erros da API Beyond não devem derrubar o worker."""
        mock_session = MagicMock()
        mock_room = MagicMock()

        mock_bey = MagicMock()
        mock_bey.AvatarSession.side_effect = RuntimeError("Conexão recusada pela API Beyond")

        original_bey = worker_module.bey_plugin
        original_available = worker_module.BEY_AVAILABLE
        try:
            worker_module.bey_plugin = mock_bey
            worker_module.BEY_AVAILABLE = True

            result = await worker_module._start_avatar_session("cmo", mock_session, mock_room)
            assert result is None, "Exceção deve ser capturada e retornar None"
        finally:
            worker_module.bey_plugin = original_bey
            worker_module.BEY_AVAILABLE = original_available
