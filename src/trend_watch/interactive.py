from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import typer

_PLATFORM_URLS = {
    "PTT":   "https://www.ptt.cc/bbs/{board}/",
    "Dcard": "https://www.dcard.tw/f/{board}",
}

_ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
]

_OLLAMA_DEFAULT_MODEL = "gemma4:e4b"
_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"


def _choose(title: str, options: list[str], default: int = 1) -> int:
    typer.echo(f"\n{title}")
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        typer.echo(f"  {i}) {opt}{marker}")
    while True:
        raw = typer.prompt("Enter number", default=str(default))
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice
        except ValueError:
            pass
        typer.secho(f"Please enter a number between 1 and {len(options)}.", fg=typer.colors.YELLOW)


def _parse_keywords(raw: str) -> list[str]:
    parts = re.split(r"[,，]", raw)
    return [p.strip().strip("\"'") for p in parts if p.strip().strip("\"'")]


def _read_existing_api_key() -> str:
    key = os.environ.get("LLM__API_KEY", "")
    if key and key != "ollama":
        return key
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("LLM__API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val and val != "ollama":
                    return val
    return ""


def run_wizard() -> dict[str, Any]:
    typer.echo("=" * 60)
    typer.echo("  trend-watch  -- interactive setup")
    typer.echo("  (Tip: use --url / -k flags directly to skip this wizard)")
    typer.echo("=" * 60)

    # ── Step 1: Model ──────────────────────────────────────────
    provider_choice = _choose(
        "Step 1/4  LLM model",
        [
            "Local Ollama (free, requires `ollama serve`)",
            "Anthropic Claude API",
        ],
    )

    llm: dict[str, Any]
    if provider_choice == 1:
        model = typer.prompt("  Ollama model name", default=_OLLAMA_DEFAULT_MODEL)
        llm = {
            "provider": "ollama",
            "model": model,
            "base_url": _OLLAMA_DEFAULT_BASE_URL,
            "api_key": None,
        }
    else:
        model_choice = _choose("  Anthropic model", _ANTHROPIC_MODELS, default=1)
        model = _ANTHROPIC_MODELS[model_choice - 1]
        existing_key = _read_existing_api_key()
        if existing_key:
            typer.echo("  Found existing API key in .env / environment.")
            api_key = existing_key
        else:
            api_key = typer.prompt("  Anthropic API key (sk-ant-...)", hide_input=True)
        llm = {
            "provider": "anthropic",
            "model": model,
            "base_url": None,
            "api_key": api_key,
        }

    # ── Step 2: Platform & board ───────────────────────────────
    plat_names = list(_PLATFORM_URLS.keys())
    plat_opts = [*plat_names, "Other (custom URL)"]
    plat_choice = _choose("Step 2/4  Platform", plat_opts)

    url: str
    board: str
    if plat_choice <= len(plat_names):
        plat_name = plat_names[plat_choice - 1]
        board_hints = {
            "PTT":   "e.g. Gossiping, sex, Stock",
            "Dcard": "e.g. baby, relationship, mood",
        }
        board_input = typer.prompt(f"  Board name ({board_hints[plat_name]})")
        url = _PLATFORM_URLS[plat_name].format(board=board_input)
        board = f"{plat_name.lower()}_{board_input}"
        typer.echo(f"  URL: {url}")
    else:
        url = typer.prompt("  Full URL")
        board = ""

    # ── Step 3: Keywords ───────────────────────────────────────
    typer.echo("\nStep 3/4  Keywords")
    typer.echo("  Separate multiple keywords with commas.")
    typer.echo('  Example: apple, orange  or  "flying car","smart watch"')
    while True:
        raw_kw = typer.prompt("  Keywords")
        keywords = _parse_keywords(raw_kw)
        if keywords:
            typer.echo(f"  Parsed {len(keywords)} keyword(s): {', '.join(keywords)}")
            break
        typer.secho("  Please enter at least one keyword.", fg=typer.colors.YELLOW)

    # ── Step 4: Pages ─────────────────────────────────────────
    pages = typer.prompt("\nStep 4/4  Pages to crawl", default=5, type=int)

    # ── Confirmation ───────────────────────────────────────────
    typer.echo("\n" + "-" * 60)
    typer.echo("  Ready to crawl")
    typer.echo(f"  URL      : {url}")
    typer.echo(f"  Keywords : {', '.join(keywords)}")
    typer.echo(f"  Pages    : {pages}")
    typer.echo(f"  Model    : {llm['provider']} / {llm['model']}")
    typer.echo("-" * 60)
    if not typer.confirm("Start crawling?", default=True):
        raise typer.Exit(0)

    return {
        "llm": llm,
        "watch": {
            "url": url,
            "keywords": keywords,
            "pages": pages,
            "board": board,
            "output": Path("data-watch"),
            "dict_dir": None,
            "config_dir": Path("data/crawler-configs"),
            "use_local_llm": True,
            "llm_summary": False,
            "embed_plotly": True,
        },
    }
