# UK-Skilled-Worker-visa-sponsorable-Jobs

Production-grade Python tool to discover UK Skilled Worker visa-sponsorable QA / Automation roles, score them against multiple resumes, and output a ranked apply list.

## Features
- Downloads the UK Home Office Register of Licensed Sponsors automatically.
- Filters to technology/software-oriented sponsors offering the Skilled Worker route.
- Scrapes QA/SDET/Automation roles from career pages with Playwright.
- Rejects junior, manual-only, or contract roles and deduplicates across runs.
- Scores each job against every PDF resume in `./resumes` via LLM or heuristics, selecting the best match per job.
- Caps results per run using `DAILY_JOB_LIMIT` and exports `jobs_raw.csv`, `jobs_ranked.csv`, and `jobs_seen.json`.

## Quickstart
1. Install dependencies (Python 3.11):
   ```bash
   python3.11 -m pip install -r requirements.txt
   python3.11 -m playwright install chromium
   ```
2. Place one or more PDF resumes in the `resumes/` directory.
3. (Optional) Add `career_pages.json` mapping sponsor names to explicit career page URLs.
4. Run the pipeline:
   ```bash
   python3.11 main.py
   ```

## Configuration
Environment variables:
- `DAILY_JOB_LIMIT` (default `25`): max ranked jobs per run.
- `MAX_COMPANIES` (default `150`): number of tech sponsors to probe.
- `CONCURRENT_BROWSERS` (default `4`): Playwright concurrency.
- `SPONSOR_REGISTER_URL`: override Home Office CSV URL.
- `RESUMES_DIR`, `DATA_DIR`: custom input/output paths.
- `OPENAI_API_KEY`, `LLM_MODEL`: enable OpenAI scoring; otherwise heuristics are used.
- `CAREER_PAGES_FILE`: JSON file of `{ "Company Name": "https://example.com/careers" }` overrides.

## Outputs
- `data/jobs.csv`: filtered sponsor list (Skilled Worker tech companies + derived career URLs).
- `data/jobs_raw.csv`: all scraped QA-like links with metadata.
- `data/jobs_ranked.csv`: filtered, scored list ranked by resume match and QA relevance.
- `data/jobs_seen.json`: persisted deduplication store.

## Notes
- Playwright runs headless Chromium by default.
- LLM responses must be strict JSON matching: `{ "qa_relevance": 0-10, "visa_likelihood": "Low|Medium|High", "resume_match_score": 0-100, "reason": "max 2 lines" }`.
- The heuristic scorer activates automatically when `OPENAI_API_KEY` is not set.
