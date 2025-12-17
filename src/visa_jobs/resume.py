from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import PyPDF2

logger = logging.getLogger(__name__)


def load_resumes(resume_dir: Path) -> Dict[str, str]:
    resumes: Dict[str, str] = {}
    for pdf_path in resume_dir.glob("*.pdf"):
        text = extract_pdf_text(pdf_path)
        resumes[pdf_path.name] = text
        logger.info("Loaded resume %s (%d chars)", pdf_path.name, len(text))
    if not resumes:
        logger.warning("No resumes found in %s", resume_dir)
    return resumes


def extract_pdf_text(path: Path) -> str:
    with path.open("rb") as file:
        reader = PyPDF2.PdfReader(file)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
