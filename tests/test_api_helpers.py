"""Unit tests for backend/api.py's pure helper functions (no network)."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URI", "mongodb://localhost/test")
os.environ.setdefault("VOYAGE_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from backend.api import _clean, _levels_for


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

    def test_unknown_value_defaults_to_full_access(self):
        """Fails open on an unexpected value — matches current documented behavior,
        not necessarily the safest default; flags this if that default ever changes."""
        self.assertEqual(_levels_for("qualquer-coisa"), ["publico", "restrito"])


if __name__ == "__main__":
    unittest.main()
