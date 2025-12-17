from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class JobOpportunity:
    company: str
    title: str
    location: str
    url: str
    source: str
    snippet: str
    qa_relevance: int | None = None
    visa_likelihood: str | None = None
    resume_match_score: int | None = None
    matched_resume: Optional[str] = None

    def job_id(self) -> str:
        return f"{self.company}|{self.title}|{self.url}"
