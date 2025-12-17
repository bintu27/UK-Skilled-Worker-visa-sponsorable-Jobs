from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

JSON_SCHEMA = {
    "qa_relevance": "0-10",
    "visa_likelihood": "Low|Medium|High",
    "resume_match_score": "0-100",
    "reason": "max 2 lines",
}

PROMPT_TEMPLATE = """
You are assessing a job listing for a UK Skilled Worker visa sponsored QA/Automation position.
Return a STRICT JSON object with keys: {json_keys}.
Consider these filters:
- Reject junior, graduate, intern, contract, or manual-only roles.
- Focus on QA / SDET / Automation / QE / QA Manager responsibilities.
- Rate visa likelihood based on the company being a licensed sponsor.

Job detail:
Title: {title}
Company: {company}
Description: {description}
Resume excerpt: {resume_excerpt}
"""


class LLMEvaluator:
    def __init__(self, api_key: Optional[str], model: str):
        self.api_key = api_key
        self.model = model

    def evaluate(self, job: Dict[str, str], resume_text: str) -> Dict[str, str]:
        if not self.api_key:
            logger.info("OPENAI_API_KEY not set; using heuristic scoring")
            return self._heuristic_score(job, resume_text)
        return self._call_openai(job, resume_text)

    def _call_openai(self, job: Dict[str, str], resume_text: str) -> Dict[str, str]:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT_TEMPLATE.format(
                        json_keys=list(JSON_SCHEMA.keys()),
                        title=job.get("title", ""),
                        company=job.get("company", ""),
                        description=job.get("snippet", ""),
                        resume_excerpt=resume_text[:3000],
                    ),
                }
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = httpx.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _heuristic_score(self, job: Dict[str, str], resume_text: str) -> Dict[str, str]:
        title = job.get("title", "").lower()
        description = job.get("snippet", "").lower()
        resume_lower = resume_text.lower()
        keywords = [
            "automation",
            "selenium",
            "playwright",
            "cypress",
            "python",
            "pytest",
            "sdet",
            "qa",
        ]
        overlap = sum(word in resume_lower for word in keywords)
        qa_relevance = min(10, overlap + ("qa" in title) + ("sdet" in title))
        resume_score = min(100, 40 + overlap * 10)
        visa = "High"
        if "contract" in title or "contract" in description:
            visa = "Low"
        return {
            "qa_relevance": qa_relevance,
            "visa_likelihood": visa,
            "resume_match_score": resume_score,
            "reason": "Heuristic match without API",
        }
