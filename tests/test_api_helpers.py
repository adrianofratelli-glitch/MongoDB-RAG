"""Unit tests for backend/api.py's pure helper functions (no network)."""

import os
import sys
import unittest

from pydantic import ValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URI", "mongodb://localhost/test")
os.environ.setdefault("VOYAGE_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from backend.api import ChatBody, _clean, _is_obviously_out_of_scope, _levels_for, _scope_reply


class TestClean(unittest.TestCase):
    def test_strips_leading_emoji(self):
        self.assertEqual(_clean("📋 O que este documento aborda?"), "O que este documento aborda?")

    def test_no_emoji_unchanged(self):
        self.assertEqual(_clean("Quais são os prazos?"), "Quais são os prazos?")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(_clean("🎯  Objetivo  "), "Objetivo")


class TestLevelsFor(unittest.TestCase):
    def test_publico_sees_only_public(self):
        self.assertEqual(_levels_for("publico"), ["publico"])

    def test_restrito_sees_both(self):
        self.assertEqual(_levels_for("restrito"), ["publico", "restrito"])

    def test_unknown_value_defaults_to_public_only(self):
        """Default-deny: any value other than the exact "restrito" falls back to
        public-only access."""
        self.assertEqual(_levels_for("qualquer-coisa"), ["publico"])
        self.assertEqual(_levels_for(""), ["publico"])

    def test_chat_body_defaults_to_public_only(self):
        self.assertEqual(ChatBody(question="teste").access_level, "publico")

    def test_chat_body_rejects_oversized_total_history(self):
        with self.assertRaises(ValidationError):
            ChatBody(
                question="teste",
                messages=[{"role": "user", "content": "x" * 12_000}] * 5,
            )


class TestScopeRecovery(unittest.TestCase):
    def test_temperature_is_redirected_without_rag(self):
        self.assertTrue(_is_obviously_out_of_scope("Qual é a temperatura hoje?"))
        self.assertIn("Posso ajudar", _scope_reply())

    def test_document_question_stays_in_scope(self):
        self.assertFalse(_is_obviously_out_of_scope("Quais são os objetivos estratégicos?"))


if __name__ == "__main__":
    unittest.main()
