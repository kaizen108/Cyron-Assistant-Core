"""Knowledge base schemas."""

from typing import Any, Literal

from uuid import UUID
from pydantic import BaseModel, Field


PersistMode = Literal["pipeline", "structured"]


class KnowledgeCreate(BaseModel):
    """Create knowledge entry."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="")
    main_content: str | None = None
    additional_context: str | None = None
    behavior_notes: str | None = None
    template_type: str = Field(default="general_knowledge", max_length=64)
    template_payload: dict[str, Any] | None = None
    source: str | None = Field(None, max_length=500)
    persist_mode: PersistMode = "pipeline"
    ai_context_id: UUID | None = None
    section: str | None = Field(None, max_length=32)  # "problems" | "knowledge"


class KnowledgeUpdate(BaseModel):
    """Update knowledge entry."""

    title: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None, min_length=1)
    main_content: str | None = Field(None, min_length=1)
    additional_context: str | None = None
    behavior_notes: str | None = None
    template_type: str | None = Field(None, max_length=64)
    template_payload: dict[str, Any] | None = None
    source: str | None = Field(None, max_length=500)
    persist_mode: PersistMode | None = None
    ai_context_id: UUID | None = None
    section: str | None = Field(None, max_length=32)


class KnowledgeResponse(BaseModel):
    """Knowledge entry response."""

    id: UUID
    guild_id: int
    title: str
    content: str
    main_content: str | None = None
    additional_context: str | None = None
    behavior_notes: str | None = None
    template_type: str = "general_knowledge"
    template_payload: dict[str, Any] | None = None
    source: str | None = None
    raw_content: str | None = None
    structured_chunks: list[dict[str, Any]] | None = None
    chunk_index: int | None = None
    ai_context_id: UUID | None = None
    section: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class KnowledgeFormatRequest(BaseModel):
    """AUTO FORMAT — returns structured fields for the dashboard (no DB write)."""

    raw_text: str = Field(..., min_length=1, description="Noisy pasted knowledge")
    template_type: str = Field(default="problem_solution", max_length=64)
    title_hint: str = Field(default="", max_length=500)


class KnowledgeFormatResponse(BaseModel):
    """Structured result to fill modals before SAVE."""

    title: str
    template_type: str
    main_content: str
    additional_context: str | None = None
    behavior_notes: str | None = None
    template_payload: dict[str, Any] | None = None
    content_markdown: str
