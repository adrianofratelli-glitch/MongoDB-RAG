"""Unit tests for agent.py's pure aggregation-pipeline builders (no network)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URI", "mongodb://localhost/test")
os.environ.setdefault("VOYAGE_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from agent import _vector_pipeline, _lexical_pipeline, ALL_ACCESS


class TestVectorPipeline(unittest.TestCase):
    def test_includes_access_filter_when_levels_given(self):
        pipeline = _vector_pipeline([0.1, 0.2], top_k=10, access_levels=["publico"])
        vs = pipeline[0]["$vectorSearch"]
        self.assertEqual(vs["filter"], {"metadata.nivel_acesso": {"$in": ["publico"]}})
        self.assertEqual(vs["limit"], 10)
        self.assertEqual(vs["numCandidates"], 150)

    def test_no_filter_when_access_levels_empty(self):
        pipeline = _vector_pipeline([0.1], top_k=5, access_levels=[])
        vs = pipeline[0]["$vectorSearch"]
        self.assertNotIn("filter", vs)

    def test_all_access_grants_both_levels(self):
        self.assertEqual(set(ALL_ACCESS), {"publico", "restrito"})


class TestLexicalPipeline(unittest.TestCase):
    def test_includes_access_filter_when_levels_given(self):
        pipeline = _lexical_pipeline("prazo", top_k=8, access_levels=["publico", "restrito"])
        search = pipeline[0]["$search"]
        self.assertEqual(
            search["compound"]["filter"],
            [{"in": {"path": "metadata.nivel_acesso", "value": ["publico", "restrito"]}}],
        )

    def test_no_filter_when_access_levels_empty(self):
        pipeline = _lexical_pipeline("prazo", top_k=8, access_levels=[])
        search = pipeline[0]["$search"]
        self.assertEqual(search["compound"]["filter"], [])

    def test_limit_stage_matches_top_k(self):
        pipeline = _lexical_pipeline("q", top_k=3, access_levels=[])
        self.assertEqual(pipeline[1]["$limit"], 3)


if __name__ == "__main__":
    unittest.main()
