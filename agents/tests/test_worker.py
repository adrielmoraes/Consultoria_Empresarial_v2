# Testes unitários para o Mentoria AI - Blackboard e constantes
# Skill LiveKit Agents exige testes para toda implementação de agente.

import sys
import os
import unittest

# Adiciona o diretório pai ao path para importar o worker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker import (
    Blackboard,
    SPECIALIST_NAMES,
    SPECIALIST_IDENTITIES,
    SPECIALIST_INTRODUCTIONS,
    SPECIALIST_SYSTEM_PROMPTS,
    SPECIALIST_ORDER,
    AGENT_VOICES,
    HOST_PROMPT,
    GEMINI_REALTIME_MODEL,
    GEMINI_REALTIME_CONFIG,
    SPECIALIST_SILENCE_TIMEOUT_SECONDS,
    SPECIALIST_MAX_TURN_TIMEOUT_SECONDS,
    classify_user_handoff_intent,
    get_specialist_timeout_reason,
)


class TestBlackboardAddMessage(unittest.TestCase):
    """Testa o método add_message do Blackboard."""

    def test_add_single_message(self):
        bb = Blackboard()
        bb.add_message("Usuário", "Olá, preciso de ajuda com meu projeto.")
        self.assertEqual(len(bb.transcript), 1)
        self.assertEqual(bb.transcript[0]["role"], "Usuário")
        self.assertEqual(bb.transcript[0]["content"], "Olá, preciso de ajuda com meu projeto.")

    def test_add_multiple_messages(self):
        bb = Blackboard()
        bb.add_message("Nathália", "Bem-vindo!")
        bb.add_message("Usuário", "Obrigado!")
        bb.add_message("Carlos (CFO)", "Vou analisar os custos.")
        self.assertEqual(len(bb.transcript), 3)
        self.assertEqual(bb.transcript[0]["role"], "Nathália")
        self.assertEqual(bb.transcript[2]["role"], "Carlos (CFO)")

    def test_add_empty_content(self):
        bb = Blackboard()
        bb.add_message("Sistema", "")
        self.assertEqual(len(bb.transcript), 1)
        self.assertEqual(bb.transcript[0]["content"], "")


class TestBlackboardGetContextSummary(unittest.TestCase):
    """Testa o método get_context_summary do Blackboard."""

    def test_empty_blackboard(self):
        bb = Blackboard()
        summary = bb.get_context_summary()
        self.assertEqual(summary, "")

    def test_with_project_name_only(self):
        bb = Blackboard(project_name="Meu SaaS")
        summary = bb.get_context_summary()
        self.assertIn("Projeto: Meu SaaS", summary)

    def test_with_user_query(self):
        bb = Blackboard(user_query="Como precificar meu produto?")
        summary = bb.get_context_summary()
        self.assertIn("Necessidade do usuário: Como precificar meu produto?", summary)

    def test_with_messages(self):
        bb = Blackboard(project_name="App de Delivery")
        bb.add_message("Usuário", "Preciso de ajuda com precificação.")
        bb.add_message("Nathália", "Vou acionar o Carlos.")
        summary = bb.get_context_summary()
        self.assertIn("Projeto: App de Delivery", summary)
        self.assertIn("Conversa Recente", summary)
        self.assertIn("[Usuário]: Preciso de ajuda com precificação.", summary)

    def test_limits_to_last_20_messages(self):
        bb = Blackboard()
        for i in range(30):
            bb.add_message(f"User{i}", f"Mensagem {i}")
        summary = bb.get_context_summary()
        # Deve conter as últimas 20 mensagens (10 a 29)
        self.assertIn("[User18]: Mensagem 18", summary)
        self.assertIn("[User29]: Mensagem 29", summary)
        self.assertNotIn("[User17]: Mensagem 17", summary)


class TestBlackboardGetFullTranscript(unittest.TestCase):
    """Testa o método get_full_transcript do Blackboard."""

    def test_empty_transcript(self):
        bb = Blackboard()
        self.assertEqual(bb.get_full_transcript(), "")

    def test_full_transcript_format(self):
        bb = Blackboard()
        bb.add_message("Nathália", "Olá!")
        bb.add_message("Usuário", "Oi!")
        result = bb.get_full_transcript()
        self.assertIn("[Nathália]: Olá!", result)
        self.assertIn("[Usuário]: Oi!", result)
        self.assertIn("\n\n", result)


class TestBlackboardLastUserMessage(unittest.TestCase):
    """Testa a recuperação da última fala do usuário."""

    def test_returns_empty_when_user_never_spoke(self):
        bb = Blackboard()
        bb.add_message("Nathália", "Olá!")
        self.assertEqual(bb.get_last_user_message(), "")

    def test_returns_latest_user_message(self):
        bb = Blackboard()
        bb.add_message("Usuário", "Primeira dúvida")
        bb.add_message("Daniel (Advogado)", "Posso te ajudar nisso.")
        bb.add_message("Usuário", "Mas e a cláusula de rescisão?")
        self.assertEqual(bb.get_last_user_message(), "Mas e a cláusula de rescisão?")


class TestBlackboardDefaults(unittest.TestCase):
    """Testa os valores padrão do Blackboard."""

    def test_default_values(self):
        bb = Blackboard()
        self.assertEqual(bb.project_name, "")
        self.assertEqual(bb.user_query, "")
        self.assertIsNone(bb.active_agent)
        self.assertEqual(bb.transcript, [])
        self.assertTrue(bb.is_active)
        self.assertEqual(bb.specialist_sessions, {})
        self.assertEqual(bb.specialist_rooms, [])

    def test_is_active_flag(self):
        bb = Blackboard()
        self.assertTrue(bb.is_active)
        bb.is_active = False
        self.assertFalse(bb.is_active)

    def test_user_activity_tracking_helpers(self):
        bb = Blackboard()
        bb.set_user_speaking(True)
        self.assertTrue(bb.user_currently_speaking)
        speaking_ts = bb.last_interaction_at
        self.assertGreater(speaking_ts, 0)

        bb.mark_user_activity()
        self.assertGreaterEqual(bb.last_interaction_at, speaking_ts)

        bb.set_user_speaking(False)
        self.assertFalse(bb.user_currently_speaking)


class TestConstantsAlignment(unittest.TestCase):
    """Verifica que todas as constantes de especialistas estão alinhadas."""

    EXPECTED_SPEC_IDS = {"cfo", "legal", "cmo", "cto", "plan"}

    def test_specialist_names_keys(self):
        self.assertEqual(set(SPECIALIST_NAMES.keys()), self.EXPECTED_SPEC_IDS)

    def test_specialist_identities_keys(self):
        self.assertEqual(set(SPECIALIST_IDENTITIES.keys()), self.EXPECTED_SPEC_IDS)

    def test_specialist_introductions_keys(self):
        self.assertEqual(set(SPECIALIST_INTRODUCTIONS.keys()), self.EXPECTED_SPEC_IDS)

    def test_specialist_system_prompts_keys(self):
        self.assertEqual(set(SPECIALIST_SYSTEM_PROMPTS.keys()), self.EXPECTED_SPEC_IDS)

    def test_specialist_order_contains_all_specialists(self):
        self.assertEqual(set(SPECIALIST_ORDER), {"cfo", "legal", "cmo", "cto"})

    def test_agent_voices_has_all_agents(self):
        expected_voices = {"host", "cfo", "legal", "cmo", "cto", "plan"}
        self.assertEqual(set(AGENT_VOICES.keys()), expected_voices)

    def test_identities_follow_pattern(self):
        for spec_id, identity in SPECIALIST_IDENTITIES.items():
            self.assertTrue(
                identity.startswith("agent-"),
                f"Identity '{identity}' para '{spec_id}' deveria começar com 'agent-'",
            )

    def test_order_is_correct(self):
        expected_order = ["cfo", "legal", "cmo", "cto"]
        self.assertEqual(SPECIALIST_ORDER, expected_order)


class TestPrompts(unittest.TestCase):
    """Verifica a integridade dos prompts."""

    def test_host_prompt_is_not_empty(self):
        self.assertTrue(len(HOST_PROMPT) > 100)

    def test_host_prompt_contains_specialists(self):
        self.assertIn("Carlos", HOST_PROMPT)
        self.assertIn("Daniel", HOST_PROMPT)
        self.assertIn("Rodrigo", HOST_PROMPT)
        self.assertIn("Ana", HOST_PROMPT)
        self.assertIn("Marco", HOST_PROMPT)

    def test_host_prompt_in_portuguese(self):
        self.assertIn("português do Brasil", HOST_PROMPT)

    def test_all_specialist_prompts_in_portuguese(self):
        for spec_id, prompt in SPECIALIST_SYSTEM_PROMPTS.items():
            self.assertIn(
                "português do Brasil",
                prompt,
                f"Prompt do especialista '{spec_id}' deveria ser em português do Brasil",
            )

    def test_specialist_prompts_include_role(self):
        # Cada prompt deve mencionar o nome do especialista
        expected_names = {
            "cfo": "Carlos",
            "legal": "Daniel",
            "cmo": "Rodrigo",
            "cto": "Ana",
            "plan": "Marco",
        }
        for spec_id, name in expected_names.items():
            self.assertIn(
                name,
                SPECIALIST_SYSTEM_PROMPTS[spec_id],
                f"Prompt do '{spec_id}' deveria mencionar '{name}'",
            )


class TestGeminiConfig(unittest.TestCase):
    """Verifica configurações do Gemini Realtime."""

    def test_model_name_is_set(self):
        self.assertTrue(len(GEMINI_REALTIME_MODEL) > 0)
        self.assertIn("gemini", GEMINI_REALTIME_MODEL.lower())

    def test_config_has_required_keys(self):
        self.assertIn("compression_trigger", GEMINI_REALTIME_CONFIG)
        self.assertIn("compression_sliding_window", GEMINI_REALTIME_CONFIG)
        self.assertIn("speech_config", GEMINI_REALTIME_CONFIG)

    def test_compression_values_are_positive(self):
        self.assertGreater(GEMINI_REALTIME_CONFIG["compression_trigger"], 0)
        self.assertGreater(GEMINI_REALTIME_CONFIG["compression_sliding_window"], 0)
        self.assertGreater(
            GEMINI_REALTIME_CONFIG["compression_trigger"],
            GEMINI_REALTIME_CONFIG["compression_sliding_window"],
            "trigger deve ser maior que sliding_window",
        )


class TestHandoffIntentClassification(unittest.TestCase):
    """Garante que o especialista só devolve o turno com sinal claro do usuário."""

    def test_detects_user_confirmed_done(self):
        self.assertEqual(
            classify_user_handoff_intent("Perfeito, agora ficou claro e não tenho mais dúvidas."),
            "user_confirmed_done",
        )

    def test_detects_user_requested_host(self):
        self.assertEqual(
            classify_user_handoff_intent("Pode voltar para a Nathália para seguirmos."),
            "user_requested_host",
        )

    def test_returns_none_when_user_still_has_questions(self):
        self.assertIsNone(
            classify_user_handoff_intent("Mas no meu caso a multa contratual continua valendo?")
        )


class TestSpecialistTurnTimeouts(unittest.TestCase):
    """Garante que fala longa não seja tratada como silêncio do usuário."""

    def test_does_not_timeout_while_user_is_still_speaking(self):
        reason = get_specialist_timeout_reason(
            started_at=0.0,
            last_interaction_at=0.0,
            user_currently_speaking=True,
            now=SPECIALIST_SILENCE_TIMEOUT_SECONDS + 30.0,
        )
        self.assertIsNone(reason)

    def test_silence_timeout_only_when_user_is_not_speaking(self):
        reason = get_specialist_timeout_reason(
            started_at=0.0,
            last_interaction_at=0.0,
            user_currently_speaking=False,
            now=SPECIALIST_SILENCE_TIMEOUT_SECONDS + 1.0,
        )
        self.assertEqual(reason, "silence_timeout")

    def test_absolute_turn_timeout_remains_as_last_resort(self):
        reason = get_specialist_timeout_reason(
            started_at=0.0,
            last_interaction_at=SPECIALIST_MAX_TURN_TIMEOUT_SECONDS - 10.0,
            user_currently_speaking=False,
            now=SPECIALIST_MAX_TURN_TIMEOUT_SECONDS + 1.0,
        )
        self.assertEqual(reason, "turn_timeout")


if __name__ == "__main__":
    unittest.main()
