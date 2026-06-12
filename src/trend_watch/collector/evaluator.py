"""CrawlabilityEvaluator — assess whether a URL can be crawled."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from trend_watch.utils.http import build_session, polite_get
from trend_watch.utils.logging import get_logger

log = get_logger(__name__)

_CLOUDFLARE_MARKERS = ["cf-ray", "cloudflare", "__cf_bm", "_cf_chl_opt"]
_CF_RESP_HEADER = "cf-ray"
_JS_MARKERS = ["__NEXT_DATA__", "__reactFiber", "window.__nuxt", "window.__REDUX_STATE__"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


@dataclass
class CrawlabilityResult:
    domain: str
    url: str
    robots_txt_ok: bool = True
    disallowed_paths: list[str] = field(default_factory=list)
    needs_js: bool = False
    has_cloudflare: bool = False
    site_type: str = "unknown"
    can_crawl: bool = False
    reason: str = ""
    html_sample: str = ""


def evaluate_url(url: str) -> CrawlabilityResult:
    parsed = urlparse(url)
    domain = parsed.netloc.lstrip("www.")
    result = CrawlabilityResult(domain=domain, url=url)
    session = build_session(max_retries=2, backoff_factor=0.3)

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = session.get(robots_url, timeout=10, headers=_HEADERS)
        if resp.status_code == 200:
            disallowed = _parse_disallowed(resp.text.lower())
            result.disallowed_paths = disallowed
            if "/" in disallowed or "/*" in disallowed:
                result.robots_txt_ok = False
                result.reason = "robots.txt disallows all crawlers (Disallow: /)"
    except Exception as exc:
        log.debug("robots.txt fetch failed for %s: %s", domain, exc)

    if not result.robots_txt_ok:
        return result

    try:
        resp = polite_get(session, url, min_delay=1.0, max_delay=2.0, timeout=20, headers=_HEADERS)
        html = resp.text
        result.html_sample = html[:6000]

        resp_headers_lower = {k.lower() for k in resp.headers}
        html_lower = html.lower()
        if _CF_RESP_HEADER in resp_headers_lower or any(m in html_lower for m in _CLOUDFLARE_MARKERS):
            result.has_cloudflare = True

        if any(m in html for m in _JS_MARKERS):
            result.needs_js = True

        result.site_type = _detect_site_type(html_lower, url)

        if result.has_cloudflare and resp.status_code in (403, 503):
            result.can_crawl = False
            result.reason = "Cloudflare protection (HTTP 403/503). Try cloudscraper or Playwright."
        elif result.needs_js:
            result.can_crawl = True
            result.reason = "SPA framework detected (React/Next.js). Static crawl may be limited."
        else:
            result.can_crawl = True
            result.reason = "Static HTML, no Cloudflare block detected."

    except Exception as exc:
        result.can_crawl = False
        result.reason = f"Connection failed: {type(exc).__name__}: {exc}"

    return result


def _parse_disallowed(robots_txt_lower: str) -> list[str]:
    paths: list[str] = []
    in_wildcard = False
    for line in robots_txt_lower.splitlines():
        line = line.strip()
        if line.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            in_wildcard = agent == "*"
        elif in_wildcard and line.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                paths.append(path)
    return paths


def _detect_site_type(html_lower: str, url: str) -> str:
    url_lower = url.lower()
    forum_signals = ["forum", "post", "thread", "topic", "留言", "回覆", "討論", "bbs", "board"]
    news_signals = ["article", "news", "reporter", "記者", "新聞", "editorial"]
    blog_signals = ["blog", "blogger", "wordpress"]

    score_forum = sum(1 for s in forum_signals if s in html_lower or s in url_lower)
    score_news = sum(1 for s in news_signals if s in html_lower or s in url_lower)
    score_blog = sum(1 for s in blog_signals if s in url_lower)

    if score_forum >= max(score_news, score_blog) and score_forum > 0:
        return "forum"
    if score_news > score_blog:
        return "news"
    if score_blog > 0:
        return "blog"
    return "unknown"
