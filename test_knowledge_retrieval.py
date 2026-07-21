#!/usr/bin/env python3
"""Regression tests for amount-specific knowledge retrieval (robux pricing bug)."""

import sys
from pathlib import Path
from types import SimpleNamespace

project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from backend.services.knowledge_service import (
    _apply_lexical_rerank,
    _compress_for_query,
    _extract_numbers,
    query_has_specific_amount,
)


def _mock_knowledge(title: str, body: str):
    return SimpleNamespace(title=title, main_content=body, content=body)


def test_extract_numbers():
    assert "1700" in _extract_numbers("how much does 1,700 robux cost")
    assert "1000" in _extract_numbers("1000 robux")
    assert "800" in _extract_numbers("800 robux")
    print("[OK] extract_numbers")


def test_numeric_rerank_prefers_matching_amount():
    base = 0.45
    match = _apply_lexical_rerank(
        "how much does 1000 robux cost",
        "1000 Robux Pricing",
        "1000 Robux costs $12.99",
        base,
    )
    mismatch = _apply_lexical_rerank(
        "how much does 1000 robux cost",
        "1700 Robux Pricing",
        "1,700 Robux costs $18.99",
        base,
    )
    assert match > mismatch, f"match={match} should beat mismatch={mismatch}"
    print(f"[OK] numeric rerank: match={match:.2f} > mismatch={mismatch:.2f}")


def test_query_has_specific_amount():
    assert query_has_specific_amount("how much does 1000 robux cost")
    assert not query_has_specific_amount("how much does robux cost")
    print("[OK] query_has_specific_amount")


def test_compress_prefers_matching_sentence():
    body = (
        "800 Robux costs $9.99. "
        "1000 Robux costs $12.99. "
        "1,700 Robux costs $18.99."
    )
    out = _compress_for_query(body, "how much does 1000 robux cost", limit=200)
    assert "1000" in out or "12.99" in out
    assert "1700" not in out.replace(",", "") and "1,700" not in out
    print(f"[OK] compress_for_query: {out!r}")


def test_ranking_simulation():
    """Simulate search ranking across three robux tiers."""
    entries = [
        _mock_knowledge("1700 Robux", "1,700 Robux costs $18.99"),
        _mock_knowledge("1000 Robux", "1000 Robux costs $12.99"),
        _mock_knowledge("800 Robux", "800 Robux costs $9.99"),
    ]
    query = "how much does 1000 robux cost"
    base = 0.50
    scored = []
    for k in entries:
        sim = _apply_lexical_rerank(query, k.title, k.main_content, base)
        scored.append((sim, k.title))
    scored.sort(reverse=True)
    assert scored[0][1] == "1000 Robux", scored
    print(f"[OK] ranking simulation: winner={scored[0][1]}")


def main():
    print("Knowledge retrieval regression tests")
    print("=" * 50)
    test_extract_numbers()
    test_numeric_rerank_prefers_matching_amount()
    test_query_has_specific_amount()
    test_compress_prefers_matching_sentence()
    test_ranking_simulation()
    print("=" * 50)
    print("[OK] All retrieval regression tests passed!")


if __name__ == "__main__":
    main()
