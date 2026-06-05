"""
app/services/skills/fallbacks.py

Hardcoded fallback skill slugs used when no match is found for a suggested
slug. Category fallbacks are tried first, then generic fallbacks.
"""

from __future__ import annotations

CATEGORY_FALLBACKS: dict[str, list[str]] = {
    "engineering": ["code-review", "debugging", "git-helper"],
    "devops": ["deployment-helper", "docker-assist", "infra-review"],
    "research": ["deep-research", "summarization", "citation-finder"],
    "development": ["code-review", "deep-research", "git-helper"],
    "marketing": ["copywriting", "seo-helper", "content-planner"],
    "sales": ["crm-helper", "outreach-writer", "deal-analyzer"],
    "support": ["ticket-resolver", "knowledge-base", "escalation-guide"],
    "hr": ["job-description-writer", "interview-guide", "onboarding-helper"],
    "finance": ["budget-analyzer", "report-summarizer", "forecast-helper"],
    "legal": ["contract-reviewer", "compliance-checker", "legal-summarizer"],
    "product": ["roadmap-planner", "user-story-writer", "feedback-analyzer"],
    "design": ["ux-reviewer", "design-critic", "accessibility-checker"],
}

GENERIC_FALLBACKS: list[str] = [
    "web-search",
    "summarization",
    "deep-research",
]
