"""Unit tests never reach the embedding service: the semantic rule check finds nothing by default."""
import pytest

from harness import rule_semantics


@pytest.fixture(autouse=True)
def _no_semantic_rule_check(monkeypatch):
    async def classify_many(texts, embed=None):
        return [None] * len(texts)

    monkeypatch.setattr(rule_semantics, "classify_many", classify_many)
