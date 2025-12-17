from __future__ import annotations

import asyncio
import logging
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_URL = "https://duckduckgo.com/html/"
BING_SEARCH_URL = "https://www.bing.com/search"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
SEARCH_TIMEOUT = 8
PAGE_TIMEOUT_MS = 10000
MAX_SEARCH_RESULTS = 5
MIN_JOB_LINKS = 3
CAREER_KEYWORDS = ["career", "careers", "jobs", "join us", "work with us"]
CAREER_LINK_KEYWORDS = ["job", "career", "vacanc", "opportun", "opening", "join", "work"]
JOB_KEYWORDS = ["qa", "quality", "test", "testing", "sdet", "automation"]
EXCLUDED_TERMS = ["contract", "intern", "graduate", "no sponsorship"]
NAV_KEYWORDS = ["career", "careers", "jobs", "join", "work with us"]
SAFE_MODE_SUFFIXES = [" ltd", " limited", " europe", " uk"]
AGGREGATOR_DOMAINS = {
    "linkedin.com",
    "www.linkedin.com",
    "indeed.com",
    "www.indeed.com",
    "glassdoor.com",
    "www.glassdoor.com",
    "lever.co",
    "jobs.lever.co",
    "greenhouse.io",
    "boards.greenhouse.io",
    "myworkdayjobs.com",
    "workday.com",
    "workdayjobs.com",
    "smartrecruiters.com",
    "jobvite.com",
    "icims.com",
}
GOTO_SEMAPHORE = asyncio.Semaphore(3)


async def find_real_career_page(
    company_name: str, context: BrowserContext | None = None, max_results: int | None = None
) -> Optional[str]:
    """Locate a verifiable career page with staged fallbacks."""
    cleanup = None
    if context is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        cleanup = (playwright, browser, context)

    limit = max_results or MAX_SEARCH_RESULTS

    try:
        url = await _locate_via_strategies(company_name, context, limit)
        if url:
            return url
        trimmed = _safe_mode_variant(company_name)
        if trimmed and trimmed.lower() != company_name.lower():
            logger.info("Safe-mode retry for %s via %s", company_name, trimmed)
            return await _locate_via_strategies(trimmed, context, limit)
        logger.info("No valid career page found for %s", company_name)
        return None
    finally:
        if cleanup:
            playwright, browser, temp_context = cleanup
            await temp_context.close()
            await browser.close()
            await playwright.stop()


async def _locate_via_strategies(company_name: str, context: BrowserContext, limit: int) -> Optional[str]:
    search_strategies = [
        ("duckduckgo-html", lambda: _duckduckgo_search(f"{company_name} careers jobs", limit)),
        ("bing-html", lambda: _bing_search(f"{company_name} careers jobs", limit)),
    ]

    for label, fetch in search_strategies:
        try:
            candidates = fetch()
        except requests.RequestException as exc:
            logger.warning("Strategy %s failed for %s (%s)", label, company_name, exc)
            continue
        url = await _first_valid_candidate(company_name, candidates, context, label)
        if url:
            return url

    homepage = _discover_homepage(company_name, limit)
    if homepage and not _is_aggregator(homepage):
        nav_links = await _discover_nav_links(homepage, context)
        url = await _first_valid_candidate(company_name, nav_links, context, "homepage-nav")
        if url:
            return url
    return None


async def extract_qa_jobs(
    career_page_url: str, company_name: str, context: BrowserContext | None = None
) -> List[dict]:
    """Extract QA/SDET jobs from a validated career page."""
    cleanup = None
    if context is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        cleanup = (playwright, browser, context)

    job_entries: list[dict] = []
    try:
        page = await context.new_page()
        try:
            response = await _goto_with_limit(page, career_page_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Career page navigation failed for %s (%s)", career_page_url, exc)
            await page.close()
            return job_entries

        if not response or response.status != 200:
            logger.warning("Career page %s returned status %s", career_page_url, response.status if response else None)
            await page.close()
            return job_entries

        anchors = await page.query_selector_all("a")
        seen_urls: set[str] = set()
        for anchor in anchors:
            text = (await anchor.inner_text() or "").strip()
            href = await anchor.get_attribute("href")
            if not href:
                continue
            absolute_url = urljoin(response.url, href)
            if absolute_url in seen_urls or _is_aggregator(absolute_url):
                continue
            if not _looks_like_job_link(text.lower(), absolute_url.lower()):
                continue
            seen_urls.add(absolute_url)
            job_data = await _validate_job_link(context, absolute_url, company_name, career_page_url, fallback_title=text)
            if job_data:
                job_entries.append(job_data)
        await page.close()
        return job_entries
    finally:
        if cleanup:
            playwright, browser, temp_context = cleanup
            await temp_context.close()
            await browser.close()
            await playwright.stop()


def _duckduckgo_search(query: str, limit: int) -> list[str]:
    payload = {"q": query}
    response = requests.post(
        DUCKDUCKGO_HTML_URL, data=payload, headers=_search_headers(), timeout=SEARCH_TIMEOUT
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links: list[str] = []
    for anchor in soup.select("a.result__a"):
        href = anchor.get("href")
        if not href:
            continue
        cleaned = _normalize_search_result(href)
        if cleaned and not _is_aggregator(cleaned):
            links.append(cleaned)
        if len(links) >= limit:
            break
    return links


def _bing_search(query: str, limit: int) -> list[str]:
    response = requests.get(
        BING_SEARCH_URL,
        params={"q": query},
        headers=_search_headers(),
        timeout=SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links: list[str] = []
    for anchor in soup.select("li.b_algo h2 a"):
        href = anchor.get("href")
        if not href:
            continue
        cleaned = _normalize_search_result(href)
        if cleaned and not _is_aggregator(cleaned):
            links.append(cleaned)
        if len(links) >= limit:
            break
    return links


def _discover_homepage(company_name: str, limit: int) -> Optional[str]:
    try:
        candidates = _duckduckgo_search(company_name, limit)
    except requests.RequestException as exc:
        logger.warning("Homepage discovery failed for %s (%s)", company_name, exc)
        return None
    return next((url for url in candidates if not _is_aggregator(url)), None)


async def _first_valid_candidate(
    company_name: str, candidates: list[str], context: BrowserContext, strategy_name: str
) -> Optional[str]:
    for raw_url in candidates:
        normalized = _normalize_search_result(raw_url)
        if not normalized or _is_aggregator(normalized):
            continue
        if await _is_valid_career_page(normalized, context):
            logger.info("Strategy %s succeeded for %s with %s", strategy_name, company_name, normalized)
            return normalized
    logger.info("Strategy %s found no valid page for %s", strategy_name, company_name)
    return None


async def _is_valid_career_page(url: str, context: BrowserContext) -> bool:
    page = await context.new_page()
    try:
        response = await _goto_with_limit(page, url)
        if not response or response.status != 200:
            return False
        title = (await page.title() or "").lower()
        body = (await page.inner_text("body")).lower()
        if not any(term in title for term in CAREER_KEYWORDS) and not any(term in body for term in CAREER_KEYWORDS):
            return False
        anchors = await page.query_selector_all("a")
        job_links = 0
        for anchor in anchors:
            text = (await anchor.inner_text() or "").strip()
            href = await anchor.get_attribute("href") or ""
            if _looks_like_career_link(text.lower(), href.lower()):
                job_links += 1
                if job_links >= MIN_JOB_LINKS:
                    return True
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug("Career validation failed for %s: %s", url, exc)
        return False
    finally:
        await page.close()


async def _validate_job_link(
    context: BrowserContext,
    job_url: str,
    company_name: str,
    career_page_url: str,
    fallback_title: str | None = None,
) -> Optional[dict]:
    page = await context.new_page()
    try:
        response = await _goto_with_limit(page, job_url)
        if not response or response.status != 200:
            return None
        body_text = await page.inner_text("body")
        normalized = " ".join(body_text.split())
        if len(normalized) < 1000:
            return None
        lower_body = normalized.lower()
        if any(term in lower_body for term in EXCLUDED_TERMS):
            return None
        title = fallback_title or (await page.title() or "").strip()
        if not title:
            return None
        return {
            "company_name": company_name,
            "career_page_url": career_page_url,
            "job_title": title,
            "job_url": response.url,
            "job_description": normalized,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Job validation failed for %s: %s", job_url, exc)
        return None
    finally:
        await page.close()


async def _discover_nav_links(homepage_url: str, context: BrowserContext) -> list[str]:
    page = await context.new_page()
    links: list[str] = []
    try:
        response = await _goto_with_limit(page, homepage_url)
        if not response or response.status != 200:
            return links
        anchors = await page.query_selector_all("a")
        for anchor in anchors:
            text = (await anchor.inner_text() or "").strip().lower()
            href = await anchor.get_attribute("href")
            if not href:
                continue
            if any(keyword in text for keyword in NAV_KEYWORDS) or any(keyword in href.lower() for keyword in NAV_KEYWORDS):
                links.append(urljoin(response.url, href))
        return links
    except Exception as exc:  # noqa: BLE001
        logger.debug("Navigation discovery failed for %s: %s", homepage_url, exc)
        return links
    finally:
        await page.close()


def _safe_mode_variant(company_name: str) -> Optional[str]:
    lower = company_name.lower().strip()
    for suffix in SAFE_MODE_SUFFIXES:
        if lower.endswith(suffix):
            trimmed = company_name[: -len(suffix)].strip(" ,.-")
            if trimmed:
                return trimmed
    return None


def _normalize_search_result(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        params = parse_qs(parsed.query)
        redirect = params.get("uddg")
        if redirect:
            return unquote(redirect[0])
        return None
    return url


def _is_aggregator(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(domain == bad or domain.endswith(f".{bad}") for bad in AGGREGATOR_DOMAINS)


def _looks_like_job_link(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    return any(keyword in combined for keyword in JOB_KEYWORDS)


def _looks_like_career_link(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    return any(keyword in combined for keyword in CAREER_LINK_KEYWORDS)


def _search_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }


async def _goto_with_limit(page: Page, url: str):
    async with GOTO_SEMAPHORE:
        return await page.goto(url, wait_until="commit", timeout=PAGE_TIMEOUT_MS)
