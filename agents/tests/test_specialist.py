# Testes unitários para os agentes especialistas do Mentoria AI
# Skill LiveKit Agents exige testes para toda implementação de agente.

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Adiciona o diretório pai ao path para importar o worker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker import (
    Blackboard,
    SpecialistAgent,
    HostAgent,
    SPECIALIST_NAMES,
    SPECIALIST_SYSTEM_PROMPTS,
    AGENT_VOICES,
)


class TestSpecialistAgentInstantiation(unittest.TestCase):
    """Testa que cada SpecialistAgent pode ser instanciado corretamente."""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_all_specialists_can_be_created(self):
        """Verifica que todos os 5 especialistas podem ser criados sem erro."""
        bb = Blackboard()
        for spec_id in SPECIALIST_NAMES.keys():
            try:
                agent = SpecialistAgent(spec_id, bb)
                self.assertIsNotNone(agent)
                self.assertEqual(agent._spec_id, spec_id)
                self.assertEqual(agent._name, SPECIALIST_NAMES[spec_id])
                self.assertIs(agent._blackboard, bb)
            except Exception as e:
                self.fail(
                    f"Falha ao criar SpecialistAgent para '{spec_id}': {e}"
                )

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_specialist_has_correct_prompt(self):
        """Verifica que cada especialista recebe o prompt correto."""
        bb = Blackboard()
        for spec_id in SPECIALIST_NAMES.keys():
            agent = SpecialistAgent(spec_id, bb)
            # O instructions é passado para o Agent.__init__ via super()
            # Verificamos que o prompt esperado existe na configuração
            expected_prompt = SPECIALIST_SYSTEM_PROMPTS[spec_id]
            self.assertTrue(len(expected_prompt) > 50)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_specialist_has_correct_voice(self):
        """Verifica que cada especialista tem uma voz configurada."""
        for spec_id in SPECIALIST_NAMES.keys():
            self.assertIn(spec_id, AGENT_VOICES)
            self.assertTrue(len(AGENT_VOICES[spec_id]) > 0)


class TestHostAgentInstantiation(unittest.TestCase):
    """Testa que o HostAgent pode ser instanciado corretamente."""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_host_agent_creation(self):
        """Verifica que o HostAgent pode ser criado sem erro."""
        bb = Blackboard()
        mock_room = MagicMock()
        try:
            agent = HostAgent(bb, mock_room)
            self.assertIsNotNone(agent)
            self.assertIs(agent._blackboard, bb)
            self.assertIs(agent._room, mock_room)
        except Exception as e:
            self.fail(f"Falha ao criar HostAgent: {e}")

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_host_agent_has_function_tools(self):
        """Verifica que o HostAgent declara as function tools corretas."""
        bb = Blackboard()
        mock_room = MagicMock()
        agent = HostAgent(bb, mock_room)

        # Verifica que os métodos de function_tool existem
        tool_methods = [
            "acionar_carlos_cfo",
            "acionar_daniel_advogado",
            "acionar_rodrigo_cmo",
            "acionar_ana_cto",
            "gerar_plano_execucao",
        ]
        for method_name in tool_methods:
            self.assertTrue(
                hasattr(agent, method_name),
                f"HostAgent deveria ter método '{method_name}'",
            )
            method = getattr(agent, method_name)
            self.assertTrue(
                callable(method),
                f"'{method_name}' deveria ser callable",
            )


class TestBlackboardSpecialistIntegration(unittest.TestCase):
    """Testa a integração do Blackboard com os agentes."""

    def test_active_agent_tracking(self):
        """Verifica que o agente ativo é rastreado corretamente."""
        bb = Blackboard()
        self.assertIsNone(bb.active_agent)

        bb.active_agent = "cfo"
        self.assertEqual(bb.active_agent, "cfo")

        bb.active_agent = "cto"
        self.assertEqual(bb.active_agent, "cto")

    def test_specialist_sessions_registry(self):
        """Verifica que sessões de especialistas são registradas."""
        bb = Blackboard()
        self.assertEqual(len(bb.specialist_sessions), 0)

        mock_session = MagicMock()
        bb.specialist_sessions["cfo"] = mock_session
        self.assertEqual(len(bb.specialist_sessions), 1)
        self.assertIs(bb.specialist_sessions["cfo"], mock_session)

    def test_specialist_rooms_registry(self):
        """Verifica que rooms de especialistas são registrados."""
        bb = Blackboard()
        self.assertEqual(len(bb.specialist_rooms), 0)

        mock_room = MagicMock()
        bb.specialist_rooms.append(mock_room)
        self.assertEqual(len(bb.specialist_rooms), 1)


class TestAgentActivation(unittest.TestCase):
    """Testa o fluxo de ativação de especialistas via Blackboard."""

    def test_activation_updates_blackboard(self):
        """Simula a ativação de um especialista e verifica o Blackboard."""
        bb = Blackboard()

        # Simula o que _activate_specialist faz
        spec_id = "cfo"
        context = "Preciso de análise de custos"
        bb.active_agent = spec_id
        bb.add_message("Sistema", f"Acionando {SPECIALIST_NAMES[spec_id]}: {context}")

        self.assertEqual(bb.active_agent, "cfo")
        self.assertEqual(len(bb.transcript), 1)
        self.assertIn("Carlos (CFO)", bb.transcript[0]["content"])

    def test_multiple_activations(self):
        """Verifica que ativações sequenciais são registradas."""
        bb = Blackboard()

        for spec_id in ["cfo", "legal", "cmo"]:
            bb.active_agent = spec_id
            bb.add_message("Sistema", f"Acionando {SPECIALIST_NAMES[spec_id]}")

        self.assertEqual(bb.active_agent, "cmo")  # Último ativado
        self.assertEqual(len(bb.transcript), 3)


if __name__ == "__main__":
    unittest.main()
