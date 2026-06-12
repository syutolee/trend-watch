"""LLM-guided CSS selector generator for unknown websites."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from trend_watch.collector.config import SiteConfig, _DEFAULT_CONFIG_DIR
from trend_watch.collector.evaluator import _HEADERS, evaluate_url
from trend_watch.utils.http import build_session, polite_get
from trend_watch.utils.logging import get_logger

log = get_logger(__name__)

_SELECTOR_PROMPT = """\
You are an expert web scraper. Analyze this HTML snippet from {url} and produce CSS selectors.

HTML (first 6 000 chars):
```html
{html}
```

Return ONLY a JSON object (no explanation) with these exact keys — use empty string if not found:
{{
  "list_selector":    "CSS selector to find article/topic links on a listing/index page",
  "title_selector":   "CSS selector for the article title inside an article page",
  "author_selector":  "CSS selector for the author or username",
  "time_selector":    "CSS selector for the publication date or time",
  "content_selector": "CSS selector for the main article body text",
  "comment_selector": "CSS selector for the comments or replies section",
  "next_page_selector": "CSS selector for the next-page button or link"
}}

Rules:
- Prefer id / class / aria attributes over positional selectors (nth-child etc.)
- Keep selectors short and robust
"""


async def generate_site_config(
    url: str,
    config_dir: Path = _DEFAULT_CONFIG_DIR,
    progress_cb=None,
) -> SiteConfig:
    """Return a SiteConfig for *url*, using the cached version if one exists."""
    parsed = urlparse(url)
    domain = parsed.netloc.lstrip("www.")

    existing = SiteConfig.load(domain, config_dir)
    if existing:
        if progress_cb:
            await progress_cb(f"Using cached config: {config_dir}/{domain}.json")
        return existing

    if progress_cb:
        await progress_cb(f"Analyzing page structure for {url}…")

    session = build_session(max_retries=2, backoff_factor=0.3)
    html_sample = ""
    try:
        resp = polite_get(session, url, min_delay=1.0, max_delay=2.0, timeout=20, headers=_HEADERS)
        html_sample = resp.text[:6000]
    except Exception as exc:
        log.warning("Cannot fetch %s for selector generation: %s", url, exc)

    selectors: dict[str, str] = {}
    if html_sample:
        if progress_cb:
            await progress_cb("LLM generating CSS selectors…")
        selectors = await _ask_llm(url, html_sample)

    crawl = evaluate_url(url)

    config = SiteConfig(
        domain=domain,
        site_type=crawl.site_type,
        needs_js=crawl.needs_js,
        has_cloudflare=crawl.has_cloudflare,
        list_selector=selectors.get("list_selector", ""),
        title_selector=selectors.get("title_selector", ""),
        author_selector=selectors.get("author_selector", ""),
        time_selector=selectors.get("time_selector", ""),
        content_selector=selectors.get("content_selector", ""),
        comment_selector=selectors.get("comment_selector", ""),
        next_page_selector=selectors.get("next_page_selector", ""),
        created_at=datetime.now(UTC).isoformat(),
    )

    saved_path = config.save(config_dir)
    if progress_cb:
        await progress_cb(f"✓ Selectors saved: {saved_path}")
    return config


async def _ask_llm(url: str, html_sample: str) -> dict[str, str]:
    from trend_watch.config.settings import get_settings
    cfg = get_settings()
    provider = cfg.llm.provider.lower()
    prompt = _SELECTOR_PROMPT.format(url=url, html=html_sample)

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=cfg.llm.api_key.get_secret_value())
            msg = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text if msg.content else "{}"
        else:
            from openai import AsyncOpenAI
            base_url = cfg.llm.base_url or "http://localhost:11434/v1"
            api_key = cfg.llm.api_key.get_secret_value() or "ollama"
            client_oa = AsyncOpenAI(base_url=base_url, api_key=api_key)
            resp = await client_oa.chat.completions.create(
                model=cfg.llm.model,
                max_tokens=512,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content or "{}"

        return _extract_json(raw)

    except Exception as exc:
        log.warning("LLM selector generation failed: %s", exc)
        return {}


def _extract_json(text: str) -> dict[str, str]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        return {k: str(v) for k, v in data.items() if isinstance(v, str)}
    except json.JSONDecodeError:
        log.debug("Could not parse LLM JSON response: %.200s", text)
        return {}
