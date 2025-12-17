from __future__ import annotations
import logging
from typing import List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

SEARCH_URL = "https://duckduckgo.com/?q={query}&t=h_&ia=web"
MAX_SEARCH_RESULTS = 10
CAREER_KEYWORDS = ["career", "careers", "jobs", "join us", "work with us", "opportunities"]
JOB_KEYWORDS = ["qa", "quality", "test", "testing", "sdet", "automation"]
EXCLUDED_TERMS = ["contract", "intern", "graduate", "no sponsorship"]
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


async def find_real_career_page(company_name: str, context: BrowserContext | None = None) -> Optional[str]:
    """Locate a verifiable career page for the given company using DuckDuckGo search."""
    cleanup = None
    if context is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        cleanup = (playwright, browser, context)

    try:
        page = await context.new_page()
        query = quote_plus(f"{company_name} careers jobs")
        search_url = SEARCH_URL.format(query=query)
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Career search failed for %s (%s)", company_name, exc)
            await page.close()
            return None
        await page.wait_for_timeout(1000)
        candidates = await _collect_search_results(page)
        await page.close()

        for url in candidates:
            normalized = _normalize_search_result(url)
            if not normalized or _is_aggregator(normalized):
                continue
            if await _is_valid_career_page(normalized, context):
                logger.info("Using career page %s for %s", normalized, company_name)
                return normalized
        logger.info("No valid career page found for %s", company_name)
        return None
    finally:
        if cleanup:
            playwright, browser, temp_context = cleanup
            await temp_context.close()
            await browser.close()
            await playwright.stop()


async def extract_qa_jobs(
    career_page_url: str, company_name: str, context: BrowserContext | None = None
) -> List[dict]:
    """Extract individual QA/SDET job postings from a validated career page."""
    cleanup = None
    if context is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        cleanup = (playwright, browser, context)

    job_entries: list[dict] = []
    try:
        page = await context.new_page()
        response = await page.goto(career_page_url, wait_until="domcontentloaded", timeout=30000)
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
            lower_text = text.lower()
            if not _looks_like_job_link(lower_text, absolute_url):
                continue
            if absolute_url in seen_urls or _is_aggregator(absolute_url):
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


async def _collect_search_results(page: Page) -> list[str]:
    selectors = ["a.result__a", "a[data-testid='result-title-a']"]
    links: list[str] = []
    for selector in selectors:
        anchors = await page.query_selector_all(selector)
        for anchor in anchors:
            href = await anchor.get_attribute("href")
            if href:
                links.append(href)
            if len(links) >= MAX_SEARCH_RESULTS:
                break
        if len(links) >= MAX_SEARCH_RESULTS:
            break
    return links


async def _is_valid_career_page(url: str, context: BrowserContext) -> bool:
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if not response or response.status != 200:
            return False
        title = (await page.title() or "").lower()
        if any(term in title for term in CAREER_KEYWORDS):
            return True
        body = (await page.inner_text("body")).lower()
        return any(term in body for term in CAREER_KEYWORDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Career page validation failed for %s: %s", url, exc)
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
        response = await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
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


def _normalize_search_result(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        params = parse_qs(parsed.query)
        if "uddg" in params:
            return unquote(params["uddg"][0])
        return None
    return url


def _is_aggregator(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(domain == bad or domain.endswith(f".{bad}") for bad in AGGREGATOR_DOMAINS)


def _looks_like_job_link(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    return any(keyword in combined for keyword in JOB_KEYWORDS)
