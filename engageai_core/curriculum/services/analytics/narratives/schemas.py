from typing import List, TypedDict


class SkillInsight(TypedDict):
    skill: str
    direction: str
    trend: float
    stability: float


class ExplainabilityInput(TypedDict):
    decision: str
    primary_reason: str
    supporting_factors: list
    skill_insights: List[SkillInsight]
    confidence: float


class NarrativeOutput(TypedDict):
    summary: str
    details: str
    recommendations: str
    confidence_note: str
