#!/usr/bin/env python3
"""Tests for Phase 1 AI discovery scan heuristics and General Rules compiler."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from backend.schemas.ai_discovery import CompileInput, WizardProblemSolution
from backend.services.general_rules_compiler import (
    FIXED_SAFETY_RULES,
    compile_general_rules_deterministic,
)
from backend.services.ai_extraction_service import (
    parse_ticket_tool_html,
    _heuristic_extract_from_lines,
)
from backend.services.ai_discovery_service import _classify_channel, _score_text, _confidence_tier


def test_fixed_safety_rules_present():
    compiled = compile_general_rules_deterministic(CompileInput())
    for rule in FIXED_SAFETY_RULES:
        assert rule.split(".")[0][:20] in compiled.instructions or rule[:30] in compiled.instructions
    print("[OK] Fixed safety rules injected")


def test_compile_selling_server():
    body = CompileInput(
        category="selling",
        server_description="We sell digital game keys and Robux packages.",
        tone="Friendly",
        emojis_allowed=True,
        never_rules=["Never quote prices not in #listino"],
        escalation_rules=["Escalate payment disputes"],
        escalation_roles=["Support Team"],
        problem_solutions=[
            WizardProblemSolution(
                problem="Customer paid but received nothing",
                solution="Ask for order ID and payment proof, then escalate to staff",
            )
        ],
        payment_info="PayPal: shop@example.com | Crypto USDT TRC20: TXyz...",
    )
    out = compile_general_rules_deterministic(body)
    assert "NEVER confirm having received" in out.instructions
    assert "Friendly" in out.instructions
    assert "Support Team" in out.instructions
    assert "digital game keys" in out.general_info
    assert "PayPal" in out.general_info
    assert len(out.problems) == 1
    assert "order ID" in out.problems[0].solution
    print("[OK] Compile selling server")


def test_compile_skipped_sections():
    body = CompileInput(
        category="community",
        server_description="A gaming community server.",
        skipped_steps=["never_rules", "problems"],
    )
    out = compile_general_rules_deterministic(body)
    assert "Never take sides" not in out.instructions  # category nevers skipped via skipped_steps
    assert len(out.problems) == 0
    print("[OK] Compile respects skipped sections")


def test_score_text_selling():
    scores = _score_text("🛒 shop prices listino vouch")
    assert scores["selling"] > scores["saas"]
    assert scores["selling"] > scores["community"]
    print("[OK] Selling channel scoring")


def test_score_text_saas():
    scores = _score_text("bug-reports changelog api-docs status")
    assert scores["saas"] >= scores["community"]
    print("[OK] SaaS channel scoring")


def test_classify_ticket_channel():
    tags, reason = _classify_channel({"id": "1", "name": "ticket-0042", "category_name": "Tickets"})
    assert "ticket_history" in tags
    assert reason is not None
    print("[OK] Ticket channel classification")


def test_classify_knowledge_channel():
    tags, _ = _classify_channel({"id": "2", "name": "faq", "category_name": "Info"})
    assert "knowledge" in tags
    print("[OK] Knowledge channel classification")


def test_confidence_tiers():
    assert _confidence_tier(0.8) == "high"
    assert _confidence_tier(0.5) == "medium"
    assert _confidence_tier(0.2) == "low"
    print("[OK] Confidence tiers")


def test_parse_ticket_tool_html():
    html = """
    <html><body>
    <div class="message"><span>User:</span> How do I get a refund?</div>
    <div class="message"><span>Staff:</span> Please provide your order number and we will check.</div>
    </body></html>
    """
    lines = parse_ticket_tool_html(html)
    assert any("refund" in l.lower() for l in lines)
    print("[OK] HTML parser")


def test_heuristic_extract():
    lines = [
        "User: How do I get a refund?",
        "Staff: Please send your order ID and payment screenshot for verification.",
        "User: How do I get a refund?",
        "Staff: Send order ID to staff for review.",
    ]
    problems = _heuristic_extract_from_lines(lines, 5)
    assert len(problems) >= 1
    print("[OK] Heuristic extraction")


async def test_scan_with_mock_data():
    from backend.services.ai_discovery_service import run_discovery_scan

    guild = MagicMock()
    guild.name = "RobuxShop Premium"
    guild.id = 123

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=guild))
    )

    panels_result = MagicMock()
    panel = MagicMock()
    panel.id = "p1"
    panel.name = "Purchases"
    panel.button_text = "Buy Now"
    panel.button_emoji = "🛒"
    panel.support_hours_enabled = False
    panels_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[panel])))
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=guild)),
        panels_result,
    ]

    discovery = {
        "description": "Best robux shop with vouches",
        "channels": [
            {"id": "1", "name": "listino", "type": "text", "category_name": "🛒 Shop"},
            {"id": "2", "name": "vouch", "type": "text", "category_name": "🛒 Shop"},
            {"id": "3", "name": "general-chat", "type": "text", "category_name": "Community"},
        ],
        "categories": [{"id": "c1", "name": "🛒 Shop"}],
        "roles": [
            {"id": "r1", "name": "Support", "position": 5, "is_admin": False, "manage_guild": False, "manage_channels": True},
        ],
        "text_channel_count": 3,
        "voice_channel_count": 1,
        "is_community": False,
        "features": [],
    }

    redis = AsyncMock()
    redis.get = AsyncMock(
        side_effect=lambda key: json.dumps(discovery) if "discovery" in key else None
    )
    redis.set = AsyncMock()

    result = await run_discovery_scan(session, redis, 123)
    assert result.proposed_category == "selling"
    assert result.confidence > 0.3
    assert len(result.role_candidates) >= 1
    assert len(result.panels_found) == 1
    print(f"[OK] Scan selling server: category={result.proposed_category}, confidence={result.confidence}")


async def test_scan_community_server():
    from backend.services.ai_discovery_service import run_discovery_scan

    guild = MagicMock()
    guild.name = "Gaming Hub"
    guild.id = 456

    session = AsyncMock()
    panels_result = MagicMock()
    panels_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=guild)),
        panels_result,
    ]

    discovery = {
        "description": "Community for gamers",
        "channels": [
            {"id": "1", "name": "rules", "type": "text", "category_name": "Info"},
            {"id": "2", "name": "welcome", "type": "text", "category_name": "Info"},
            {"id": "3", "name": "Lobby 1", "type": "voice", "category_name": "Voice"},
            {"id": "4", "name": "Lobby 2", "type": "voice", "category_name": "Voice"},
            {"id": "5", "name": "Lobby 3", "type": "voice", "category_name": "Voice"},
        ],
        "categories": [],
        "roles": [],
        "text_channel_count": 2,
        "voice_channel_count": 3,
        "is_community": True,
        "features": ["COMMUNITY"],
    }

    redis = AsyncMock()
    redis.get = AsyncMock(
        side_effect=lambda key: json.dumps(discovery) if "discovery" in key else None
    )
    redis.set = AsyncMock()

    result = await run_discovery_scan(session, redis, 456)
    assert result.proposed_category in ("community", "other")
    assert result.is_community_server is True
    print(f"[OK] Scan community server: category={result.proposed_category}")


def main():
    print("Phase 1 AI Discovery + Compiler Tests")
    print("=" * 50)
    test_fixed_safety_rules_present()
    test_compile_selling_server()
    test_compile_skipped_sections()
    test_score_text_selling()
    test_score_text_saas()
    test_classify_ticket_channel()
    test_classify_knowledge_channel()
    test_confidence_tiers()
    test_parse_ticket_tool_html()
    test_heuristic_extract()
    asyncio.run(test_scan_with_mock_data())
    asyncio.run(test_scan_community_server())
    print("=" * 50)
    print("[OK] All Phase 1 tests passed!")


if __name__ == "__main__":
    main()
