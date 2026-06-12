"""GenericCollector — crawl any website using LLM-generated CSS selectors."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from trend_watch.collector.config import SiteConfig, _DEFAULT_CONFIG_DIR
from trend_watch.collector.extractor import generate_site_config
from trend_watch.models import Attitude, NormalizedDocument, Platform, Post, Reaction
from trend_watch.utils.http import build_session, polite_get
from trend_watch.utils.logging import LoggerMixin

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


class GenericCollector(LoggerMixin):
    """Crawl any public website using LLM-generated CSS selectors.

    On first run for a domain, LLM generates and caches a SiteConfig.
    Subsequent runs load the cached config without calling the LLM.
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR

    async def collect(
        self,
        url: str,
        pages: int = 3,
        board: str = "",
        progress_cb=None,
        config: SiteConfig | None = None,
    ) -> list[NormalizedDocument]:
        if config is None:
            config = await generate_site_config(url, self._config_dir, progress_cb)

        parsed = urlparse(url)
        board_name = board or parsed.path.strip("/").replace("/", "_") or parsed.netloc

        session = build_session(max_retries=2, backoff_factor=0.5)
        docs: list[NormalizedDocument] = []
        current_url: str | None = url

        for page_num in range(1, pages + 1):
            if not current_url:
                break
            if progress_cb:
                await progress_cb(f"Crawling page {page_num}/{pages}: {current_url[:80]}")

            try:
                resp = polite_get(
                    session, current_url,
                    min_delay=2.0, max_delay=4.0, timeout=30, headers=_HEADERS,
                )
            except Exception as exc:
                self.log.warning("Page %d fetch failed: %s", page_num, exc)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            links = self._extract_links(soup, config.list_selector, current_url)
            self.log.info("Page %d: found %d article links", page_num, len(links))

            for link_url, link_title in links[:20]:
                doc = self._fetch_article(session, link_url, link_title, config, board_name)
                if doc:
                    docs.append(doc)

            current_url = self._find_next_page(soup, config.next_page_selector, current_url)

        if progress_cb:
            await progress_cb(f"✓ Crawl complete: {len(docs)} articles")
        self.log.info("GenericCollector finished: %d docs from %s", len(docs), url)
        return docs

    def _extract_links(
        self, soup: BeautifulSoup, selector: str, base_url: str,
    ) -> list[tuple[str, str]]:
        if selector:
            elements = soup.select(selector)
        else:
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find(id=re.compile(r"content|main|post", re.I))
            )
            area = main or soup.body or soup
            elements = [
                a for a in area.find_all("a", href=True)  # type: ignore[union-attr]
                if len(a.get_text(strip=True)) > 8
            ]

        seen: set[str] = set()
        links: list[tuple[str, str]] = []
        for el in elements:
            href = el.get("href", "")
            title = el.get_text(strip=True)
            if not href or not title:
                continue
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue
            if urlparse(full_url).netloc != urlparse(base_url).netloc:
                continue
            if full_url not in seen:
                seen.add(full_url)
                links.append((full_url, title[:200]))

        return links

    def _fetch_article(
        self,
        session,
        url: str,
        fallback_title: str,
        config: SiteConfig,
        board: str,
    ) -> NormalizedDocument | None:
        try:
            resp = polite_get(
                session, url, min_delay=1.5, max_delay=3.5, timeout=30, headers=_HEADERS,
            )
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            self.log.debug("Article fetch failed %s: %s", url, exc)
            return None

        title = self._sel_text(soup, config.title_selector) or fallback_title
        author = self._sel_text(soup, config.author_selector) or "unknown"
        time_text = self._sel_text(soup, config.time_selector)
        content = self._sel_text(soup, config.content_selector)

        if not content or len(content) < 20:
            return None

        post_time = _parse_time(time_text)
        post_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

        post = Post(
            id=post_id,
            platform=Platform.GENERIC,
            board=board,
            title=title[:200],
            title_category="",
            author=author[:100],
            post_time=post_time,
            content=content[:8000],
            url=url,
            engagement={},
            collected_at=datetime.now(UTC),
        )

        reactions: list[Reaction] = []
        if config.comment_selector:
            for i, el in enumerate(soup.select(config.comment_selector)[:50]):
                ctext = el.get_text(separator=" ", strip=True)
                if ctext and len(ctext) > 5:
                    reactions.append(Reaction(
                        id=f"{post_id}_{i}",
                        post_id=post_id,
                        author="unknown",
                        content=ctext[:500],
                        reaction_time=None,
                        attitude=Attitude.NEUTRAL,
                        order=i,
                        raw_attitude="",
                    ))

        return NormalizedDocument(post=post, reactions=reactions)

    def _sel_text(self, soup: BeautifulSoup, selector: str) -> str:
        if not selector:
            return ""
        el = soup.select_one(selector)
        return el.get_text(separator=" ", strip=True) if el else ""

    def _find_next_page(
        self, soup: BeautifulSoup, selector: str, current_url: str,
    ) -> str | None:
        if not selector:
            return None
        el = soup.select_one(selector)
        if not el:
            return None
        href = el.get("href") if hasattr(el, "get") else None
        if not href:
            return None
        next_url = urljoin(current_url, str(href))
        return next_url if next_url != current_url else None


_TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)


def _parse_time(text: str | None) -> datetime:
    if not text:
        return datetime.utcnow()
    text = text.strip()[:19]
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return datetime.utcnow()
