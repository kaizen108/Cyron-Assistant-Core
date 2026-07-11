"""Quick Phase 3 polish smoke tests (no DB required)."""

from types import SimpleNamespace

from backend.schemas.plans import DEFAULT_SYSTEM_PROMPT
from backend.services.prompt_builder import (
    build_effective_system_prompt,
    has_ai_configuration,
)


def _ctx(instructions: str, general_info: str = "") -> SimpleNamespace:
    return SimpleNamespace(instructions=instructions, general_info=general_info)


def test_legacy_prompt_skipped_when_default() -> None:
    prompt = build_effective_system_prompt(
        base_system_prompt=DEFAULT_SYSTEM_PROMPT,
        general_ai_enabled=True,
        general_context=_ctx("General Rules body"),
        panel_context=None,
    )
    assert "helpful AI support assistant" not in prompt
    assert "General Rules body" in prompt


def test_legacy_prompt_included_when_custom() -> None:
    custom = "Custom guild tone only for this server."
    prompt = build_effective_system_prompt(
        base_system_prompt=custom,
        general_ai_enabled=True,
        general_context=_ctx("GR"),
        panel_context=_ctx("Panel"),
    )
    assert custom in prompt
    assert "GR" in prompt
    assert "Panel" in prompt


def test_general_rules_disabled_unchanged() -> None:
    prompt = build_effective_system_prompt(
        base_system_prompt=DEFAULT_SYSTEM_PROMPT,
        general_ai_enabled=False,
        general_context=_ctx("Should not appear"),
        panel_context=_ctx("Panel only"),
    )
    assert "Should not appear" not in prompt
    assert "Panel only" in prompt


def test_has_ai_configuration_with_general_defaults() -> None:
    assert has_ai_configuration(
        general_ai_enabled=True,
        general_context=_ctx("# General Rules"),
        panel_context=None,
    )


if __name__ == "__main__":
    test_legacy_prompt_skipped_when_default()
    test_legacy_prompt_included_when_custom()
    test_general_rules_disabled_unchanged()
    test_has_ai_configuration_with_general_defaults()
    print("All Phase 3 polish tests passed.")
