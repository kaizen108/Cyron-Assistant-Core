"""Pydantic schemas for AI discovery scan, compile, and extract."""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

class ClassifiedChannel(BaseModel):
    id: str
    name: str
    category_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    reason: str | None = None


class ClassifiedChannels(BaseModel):
    knowledge: list[ClassifiedChannel] = Field(default_factory=list)
    announcements: list[ClassifiedChannel] = Field(default_factory=list)
    transcript: list[ClassifiedChannel] = Field(default_factory=list)
    ticket_history: list[ClassifiedChannel] = Field(default_factory=list)
    partnership: list[ClassifiedChannel] = Field(default_factory=list)
    selling: list[ClassifiedChannel] = Field(default_factory=list)


class RoleCandidate(BaseModel):
    id: str
    name: str
    score: float = 0.0
    reason: str | None = None


class PanelSummary(BaseModel):
    id: str
    name: str
    button_text: str | None = None
    button_emoji: str | None = None
    support_hours_enabled: bool = False
    category_hint: str | None = None


class VoiceTextRatio(BaseModel):
    text: int = 0
    voice: int = 0
    ratio_voice_heavy: bool = False


class CategoryScores(BaseModel):
    selling: float = 0.0
    saas: float = 0.0
    community: float = 0.0
    other: float = 0.0


class AiDiscoveryScanResult(BaseModel):
    proposed_category: str | None = None
    confidence: float = 0.0
    confidence_tier: str = "low"  # high | medium | low
    method: str = "heuristics"
    summary: str | None = None
    rationale: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    category_scores: CategoryScores = Field(default_factory=CategoryScores)
    classified_channels: ClassifiedChannels = Field(default_factory=ClassifiedChannels)
    role_candidates: list[RoleCandidate] = Field(default_factory=list)
    panels_found: list[PanelSummary] = Field(default_factory=list)
    description_draft: str | None = None
    partnership_detected: bool = False
    is_community_server: bool = False
    voice_text_ratio: VoiceTextRatio = Field(default_factory=VoiceTextRatio)
    channel_count: int = 0
    panel_count: int = 0


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

class WizardProblemSolution(BaseModel):
    problem: str
    solution: str


class CompileInput(BaseModel):
    category: str | None = None
    server_description: str | None = None
    tone: str | None = "Professional"
    emojis_allowed: bool | None = True
    language_mode: str | None = "auto"
    fixed_language: str | None = None
    fallback_language: str | None = "English"
    never_rules: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)
    escalation_roles: list[str] = Field(default_factory=list)
    escalation_users: list[str] = Field(default_factory=list)
    problem_solutions: list[WizardProblemSolution] = Field(default_factory=list)
    general_info_extra: str | None = None
    payment_info: str | None = None
    knowledge_sources: list[str] = Field(default_factory=list)
    rude_user_threshold: str | None = "1 warning"
    rude_user_message: str | None = None
    outside_hours_behavior: str | None = "try_resolve"
    skipped_steps: list[str] = Field(default_factory=list)
    activate: bool = False


class CompileKnowledgeEntry(BaseModel):
    title: str
    content: str
    section: str = "knowledge"


class CompileOutput(BaseModel):
    instructions: str
    general_info: str
    problems: list[WizardProblemSolution] = Field(default_factory=list)
    knowledge: list[CompileKnowledgeEntry] = Field(default_factory=list)
    enabled: bool = False
    context_id: str | None = None


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

class ExtractInput(BaseModel):
    channel_ids: list[str] = Field(default_factory=list)
    ticket_channel_ids: list[str] = Field(default_factory=list)
    html_contents: list[str] = Field(default_factory=list)
    max_problems: int = 5
    wait_seconds: int = 25


class ExtractedProblem(BaseModel):
    problem: str
    solution: str
    frequency: int = 1


class ExtractOutput(BaseModel):
    problems: list[ExtractedProblem] = Field(default_factory=list)
    sources_processed: int = 0
    message: str | None = None
