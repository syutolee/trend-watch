from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer

app = typer.Typer(
    name="trend-watch",
    help="Crawl any website, filter by keywords, and generate a local HTML report.",
    add_completion=False,
)

_KNOWN_PLATFORMS = {
    "ptt.cc": "PTT requires an over18 cookie - this is applied automatically.",
    "dcard.tw": "Dcard uses infinite scroll (React SPA); static crawl may return limited results.",
    "mamibuy.com.tw": "Mamibuy is server-rendered and generally works with the generic crawler.",
    "mombaby.com.tw": "Mombaby is server-rendered and generally works with the generic crawler.",
    "babyhome.com.tw": "Babyhome is server-rendered and generally works with the generic crawler.",
    "mamaclub.com": "Mamaclub is server-rendered and generally works with the generic crawler.",
}


def _warn_known_domain(url: str) -> None:
    netloc = urlparse(url).netloc.lstrip("www.")
    for domain, note in _KNOWN_PLATFORMS.items():
        if domain in netloc:
            typer.secho(f"[!] {note}", fg=typer.colors.YELLOW)
            break


def _check_ollama(base_url: str) -> bool:
    import requests
    try:
        requests.get(base_url.rstrip("/v1").rstrip("/"), timeout=3)
        return True
    except Exception:
        return False


def _print_keyword_hits_table(hits: list) -> None:
    typer.echo("\n[Keyword Hit Summary]")
    typer.echo("-" * 60)
    for h in hits:
        sent = h.sentiment_counts
        typer.echo(
            f"  {h.keyword:<20}  {h.n_posts:>4} articles  "
            f"{h.total_mentions:>5} mentions  "
            f"+{sent.get('positive', 0)} -{sent.get('negative', 0)} "
            f"~{sent.get('neutral', 0)}"
        )
        for p in h.top_posts[:2]:
            title = (p.title[:50] + "...") if len(p.title) > 50 else p.title
            typer.echo(f"      > {title}  (x{p.mention_count})")
    typer.echo()


def _apply_llm_env(params: dict) -> None:
    from trend_watch.config.settings import reset_settings
    llm = params["llm"]
    os.environ["LLM__PROVIDER"] = llm["provider"]
    os.environ["LLM__MODEL"] = llm["model"]
    if llm.get("base_url"):
        os.environ["LLM__BASE_URL"] = llm["base_url"]
    if llm.get("api_key"):
        os.environ["LLM__API_KEY"] = llm["api_key"]
    reset_settings()


def _run_watch(
    *,
    url: str,
    keywords: list[str],
    pages: int,
    output: Path,
    board: str,
    dict_dir: Path | None,
    config_dir: Path,
    use_local_llm: bool,
    llm_summary: bool,
    embed_plotly: bool,
) -> None:
    from trend_watch.analyzers.pipeline import AnalysisPipeline
    from trend_watch.collector.collector import GenericCollector
    from trend_watch.config.settings import get_settings
    from trend_watch.filter import build_keyword_hits, filter_docs_by_keywords
    from trend_watch.reporter.generator import HTMLReportGenerator
    from trend_watch.storage.storage import WatchStorage

    _warn_known_domain(url)

    cfg = get_settings()
    parsed = urlparse(url)
    if not board:
        board = (parsed.netloc + parsed.path).strip("/").replace("/", "_")[:50]

    cache_domain = parsed.netloc
    cached_config = (config_dir / f"{cache_domain}.json")
    if use_local_llm and cfg.llm.provider == "ollama" and not cached_config.exists():
        base = cfg.llm.base_url.rstrip("/v1").rstrip("/")
        if not _check_ollama(base):
            typer.secho(
                f"Error: Ollama not reachable at {base}. "
                "Please run `ollama serve` first.",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(1)

    # 1. Crawl
    typer.echo(f"Crawling {url!r}  (pages={pages}, board={board!r}) ...")
    collector = GenericCollector(config_dir=config_dir)
    docs = asyncio.run(collector.collect(url, pages=pages, board=board))

    if not docs:
        typer.secho(
            "Error: crawler returned 0 documents.\n"
            "Possible causes:\n"
            "  - The page requires JavaScript - try a static mirror or increase --pages\n"
            "  - Cloudflare/bot protection blocked the request\n"
            "  - CSS selector generation failed - delete "
            f"data/crawler-configs/{cache_domain}.json and retry",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"  Crawled {len(docs)} documents.")

    # 2. Persist raw
    storage = WatchStorage(output)
    raw_path = storage.save_raw(docs, board=board)
    typer.echo(f"  Raw saved: {raw_path}")

    # 3. Keyword filter
    filtered = filter_docs_by_keywords(docs, keywords)
    typer.echo(f"  Keyword filter: {len(filtered)}/{len(docs)} articles matched ({', '.join(keywords)})")

    if not filtered:
        typer.secho(
            "No articles matched. Suggestions:\n"
            "  - Check spelling / try synonyms\n"
            "  - Increase --pages to crawl more content\n"
            f"  Raw data kept at: {raw_path}",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    # 4. Analyse
    typer.echo("Running analysis...")
    extra_terms = {"watch_keywords": list(keywords)}
    pipeline = AnalysisPipeline(
        dict_dir=dict_dir,
        use_local_llm=use_local_llm,
        extra_terms=extra_terms,
    )
    result = pipeline.run(filtered)
    analyzed_path = storage.save_analysis(result, board=board)
    typer.echo(f"  Analysis saved: {analyzed_path}")

    # 5. Keyword hit stats
    hits = build_keyword_hits(filtered, list(keywords), result.sentiment)

    # 6. Optional LLM summary
    summary_text = ""
    if llm_summary:
        try:
            from trend_watch.reporter.llm_summary import generate_summary
            typer.echo("Generating LLM summary...")
            summary_text = generate_summary(filtered, result)
        except Exception as exc:
            typer.secho(f"  LLM summary skipped: {exc}", fg=typer.colors.YELLOW)

    # 7. HTML report
    typer.echo("Generating HTML report...")
    report_title = f"Watch Report - {board}"
    report_path = storage.report_path(board=board)
    HTMLReportGenerator().generate(
        filtered,
        result,
        report_path,
        board=board,
        summary_text=summary_text,
        embed_plotly=embed_plotly,
        keyword_hits=hits,
        report_title=report_title,
    )

    # 8. Summary
    _print_keyword_hits_table(hits)

    s = result.sentiment
    if s:
        typer.echo(
            f"Sentiment: +{s.positive_count} positive  "
            f"-{s.negative_count} negative  "
            f"~{s.neutral_count} neutral  "
            f"avg={s.avg_pn_score:.3f}"
        )

    typer.secho(f"\nReport ready: {report_path}", fg=typer.colors.GREEN)


@app.command()
def watch(
    url: Annotated[str | None, typer.Option("--url", "-u", help="Target website URL to crawl")] = None,
    keywords: Annotated[
        list[str],
        typer.Option("--keyword", "-k", help="Keyword to watch (repeatable)"),
    ] = [],
    pages: Annotated[int, typer.Option(help="Number of pages to crawl")] = 5,
    output: Annotated[Path, typer.Option(help="Output directory")] = Path("data-watch"),
    board: Annotated[str, typer.Option(help="Source label (defaults to URL domain)")] = "",
    dict_dir: Annotated[
        Path | None, typer.Option(help="Base dictionary directory for entity extraction")
    ] = None,
    config_dir: Annotated[
        Path, typer.Option(help="Crawler config cache directory")
    ] = Path("data/crawler-configs"),
    use_local_llm: Annotated[
        bool, typer.Option("--use-local-llm/--no-local-llm", help="Apply local LLM sentiment overlay")
    ] = True,
    llm_summary: Annotated[
        bool, typer.Option(help="Generate LLM insight summary (requires API key)")
    ] = False,
    embed_plotly: Annotated[
        bool, typer.Option(help="Embed Plotly JS for fully offline report")
    ] = False,
) -> None:
    """Crawl any website, filter by keywords, and generate a local HTML report."""
    # No-arg invocation -> interactive wizard
    if url is None and not keywords:
        from trend_watch.interactive import run_wizard
        params = run_wizard()
        _apply_llm_env(params)
        _run_watch(**params["watch"])
        return

    # CLI mode: validate required args
    if url is None:
        typer.secho("Error: --url / -u is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not keywords:
        typer.secho("Error: at least one --keyword / -k is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    _run_watch(
        url=url,
        keywords=list(keywords),
        pages=pages,
        output=output,
        board=board,
        dict_dir=dict_dir,
        config_dir=config_dir,
        use_local_llm=use_local_llm,
        llm_summary=llm_summary,
        embed_plotly=embed_plotly,
    )


if __name__ == "__main__":
    app()
