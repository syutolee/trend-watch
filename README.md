# trend-watch

A lightweight CLI tool that crawls any website, filters articles by your target keywords, runs sentiment and entity analysis, and produces a self-contained HTML report — all locally, with no external database required.

## Features

- **One-command workflow** — supply a URL and one or more keywords, get a report
- **LLM-powered crawling** — CSS selector generation via local Ollama (gemma4:e4b or any model); config is cached per domain so the first crawl pays the LLM cost only once
- **Keyword-focused analysis** — only articles mentioning at least one keyword proceed to analysis; a dedicated "Keyword Watch" section in the report shows per-keyword sentiment distribution and top articles
- **Local sentiment overlay** — posts with no engagement signal (no push/boo) receive batch sentiment scoring via local Ollama at zero API cost
- **Full analysis suite** — sentiment, entity extraction, time-series, anomaly detection, KOL/KOC profiling, topic clustering
- **Offline-capable reports** — pass `--embed-plotly` to bundle Plotly.js in the HTML for fully offline viewing

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.12 |
| [uv](https://docs.astral.sh/uv/) | any recent |
| [Ollama](https://ollama.com/) | any recent |

Pull the model used for CSS selector generation and sentiment scoring:

```bash
ollama pull gemma4:e4b
```

## Installation

```bash
git clone https://github.com/syutolee/trend-watch
cd trend-watch
uv sync
```

## Quick Start

### Interactive mode (recommended)

Run with no arguments to enter the step-by-step wizard:

```bash
ollama serve      # make sure Ollama is running
uv run trend-watch
```

The wizard will ask for your LLM model, platform (PTT / Dcard / Mobile01 / Reddit / custom URL), board, keywords, and number of pages — then start crawling automatically.

Leave the keyword prompt blank to enable **unfiltered mode**: every crawled article is analyzed and included in the report (no keyword filter applied).

### CLI mode (advanced)

```bash
# With keywords (filtered mode)
trend-watch \
    --url https://forum.example.com/board \
    --keyword "baby formula" \
    --keyword "diaper rash" \
    --pages 5

# Without keywords (unfiltered mode — analyze all articles)
trend-watch --url https://www.ptt.cc/bbs/Stock/ --pages 5
```

The report is saved to `data-watch/reports/watch_<board>_<ts>_report.html` and the path is printed at the end.

## CLI Reference

### `trend-watch`

```
trend-watch [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--url` / `-u` | str | **required** | Target website URL |
| `--keyword` / `-k` | str | **required** | Keyword to watch (repeatable) |
| `--pages` | int | `5` | Number of pages to crawl |
| `--output` | path | `data-watch/` | Output root directory |
| `--board` | str | auto (from URL) | Source label used in filenames and report title |
| `--dict-dir` | path | `None` | Base dictionary directory for entity extraction (optional) |
| `--config-dir` | path | `data/crawler-configs/` | Crawler config cache directory |
| `--use-local-llm` / `--no-local-llm` | flag | on | Apply local LLM sentiment overlay to posts with no engagement signal |
| `--llm-summary` | flag | off | Generate an LLM insight summary (requires `LLM__API_KEY` for Anthropic, or Ollama) |
| `--embed-plotly` | flag | off | Embed Plotly.js in the HTML for fully offline viewing |

### Examples

```bash
# Basic watch — 3 keywords, 10 pages
trend-watch \
    --url https://www.dcard.tw/f/baby \
    -k 配方奶 -k 尿布 -k 副食品 \
    --pages 10

# Offline report (no CDN needed)
trend-watch \
    --url https://forum.example.com \
    -k keyword \
    --embed-plotly

# Custom output directory and source label
trend-watch \
    --url https://community.example.com/topics \
    -k "product recall" \
    --board "example-community" \
    --output results/

# Skip LLM sentiment overlay (faster, no Ollama required after first crawl)
trend-watch \
    --url https://example.com \
    -k keyword \
    --no-local-llm
```

## Output Structure

```
data-watch/
├── raw/
│   └── watch_<board>_<ts>.json        # All crawled articles (unfiltered)
├── analyzed/
│   └── <board>_<ts>.json              # Analysis result for keyword-matched articles
└── reports/
    └── watch_<board>_<ts>_report.html # Interactive HTML report

data/
└── crawler-configs/
    └── <domain>.json                  # Cached CSS selectors (reused on subsequent crawls)
```

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

Key settings:

| Variable | Default | Description |
|---|---|---|
| `LLM__PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `LLM__MODEL` | `gemma4:e4b` | Model name |
| `LLM__BASE_URL` | `http://localhost:11434/v1` | Ollama base URL |
| `LLM__API_KEY` | `ollama` | Set to `sk-ant-...` when using Anthropic |

## How It Works

```
URL + keywords
      │
      ▼
 GenericCollector          LLM generates CSS selectors on first visit;
 (async HTTP crawler)      config cached per domain in data/crawler-configs/
      │
      ▼  all crawled docs saved to data-watch/raw/
      │
 filter_docs_by_keywords   OR logic — keep articles mentioning any keyword
      │
      ▼  0 matches → exit with suggestions; raw data kept
      │
 AnalysisPipeline
   1. PN-ratio sentiment
   2. LLM sentiment overlay (posts with no engagement signal, via Ollama)
   3. Entity extraction   ← keywords injected as "watch_keywords" category
   4. Time-series volume
   5. Anomaly detection
   6. KOL / KOC profiling
   7. Topic clustering
      │
      ▼
 build_keyword_hits         per-keyword: article count, mentions, sentiment breakdown
      │
      ▼
 HTMLReportGenerator        Jinja2 + Plotly — includes Keyword Watch section
      │
      ▼
 data-watch/reports/watch_<board>_<ts>_report.html
```

## Architecture

```
src/trend_watch/
├── main.py                    # CLI entry point (Typer) — watch command
├── models.py                  # NormalizedDocument, Post, Reaction, Attitude, Platform
├── filter.py                  # Keyword filtering + KeywordHit statistics
├── config/
│   └── settings.py            # LLMSettings + CrawlerSettings (Pydantic)
├── collector/
│   ├── config.py              # SiteConfig model (CSS selectors, pagination)
│   ├── evaluator.py           # LLM-based CSS selector generation
│   ├── extractor.py           # HTML → NormalizedDocument extraction
│   └── collector.py           # GenericCollector (async HTTP, cached config)
├── analyzers/
│   ├── pipeline.py            # AnalysisPipeline → AnalysisResult
│   ├── sentiment/
│   │   ├── pn_ratio.py        # Push/boo ratio sentiment (Tier 1)
│   │   └── llm_batch.py       # Local LLM batch sentiment (Tier 2, cached)
│   ├── entity/
│   │   ├── dictionary.py      # DictionaryManager (loads .txt files + add_terms)
│   │   └── extractor.py       # EntityExtractor (dynamic categories from dict_dir)
│   ├── kol.py                 # KOLIdentifier → KOLReport
│   ├── koc.py                 # KOCAnalyzer → KOCReport (Key Opinion Consumer)
│   ├── anomaly.py             # AnomalyDetector → AnomalyReport
│   ├── time_series.py         # TimeSeriesAnalyzer → TimeSeriesReport
│   └── topic/
│       ├── embedding.py       # TF-IDF vectorizer
│       ├── clustering.py      # K-Means topic clustering
│       └── wordcloud.py       # Keyword extraction
├── reporter/
│   ├── generator.py           # HTMLReportGenerator (Jinja2)
│   ├── charts.py              # Plotly chart builders (includes keyword_hits_bar)
│   └── templates/
│       └── dashboard.html     # Report template
├── storage/
│   └── storage.py             # WatchStorage (raw JSON + analysis JSON)
├── llm/
│   ├── client.py              # LLMClient (Ollama native + OpenAI-compatible + Anthropic)
│   └── cache.py               # Content-hash JSON cache
└── utils/
    ├── http.py                # Polite HTTP session with rate limiting
    ├── logging.py             # LoggerMixin
    └── text.py                # Text cleaning utilities
```

## Testing

```bash
uv run pytest              # full suite
uv run pytest --no-cov -q  # fast, no coverage report
```

## Notes on Website Compatibility

The generic crawler uses plain HTTP requests — it works well on server-rendered forums and discussion boards. Pages that require:

- **JavaScript rendering** (React/Vue SPAs) — the crawler will return few or no articles; consider using a headless browser or a site mirror
- **Cloudflare protection** — requests may be blocked; some sites work with a custom `User-Agent` set in `.env`

If the first crawl fails due to poor CSS selector generation, delete `data/crawler-configs/<domain>.json` and retry. The LLM will generate new selectors.

### Known Sites

| Site | Domain | Status | Notes |
|---|---|---|---|
| PTT | ptt.cc | ✅ Works | `over18=1` cookie applied automatically |
| Dcard | dcard.tw | ⚠️ Limited | React SPA with infinite scroll; static crawl returns partial results |
| Mobile01 | mobile01.com | ⚠️ Limited | Behind Akamai WAF; requests may be blocked (403) |
| Reddit | reddit.com | ⚠️ Limited | Uses old.reddit.com; plain HTTP may be rate-limited or blocked |

## License

MIT

---

# trend-watch（中文說明）

一個輕量級 CLI 工具，可爬取任意網站、依目標關鍵字篩選文章、執行情感分析與實體萃取，並產生獨立的 HTML 報告——完全在本地端運行，無需外部資料庫。

## 功能特色

- **單一指令工作流** — 提供網址與關鍵字，即可獲得報告
- **LLM 驅動爬取** — 透過本地 Ollama（gemma4:e4b 或任意模型）自動生成 CSS 選擇器；設定依網域快取，首次爬取後不再重複支付 LLM 成本
- **關鍵字精準分析** — 僅有提及至少一個關鍵字的文章才進入分析；報告內含「關鍵字監看」專區，顯示每個關鍵字的情感分佈與熱門文章
- **本地情感補全** — 無互動訊號（無推文/噓聲）的貼文，透過本地 Ollama 批次情感評分，零 API 費用
- **完整分析套件** — 情感分析、實體萃取、時間序列、異常偵測、KOL/KOC 側寫、主題聚類
- **離線報告** — 加上 `--embed-plotly` 可將 Plotly.js 內嵌至 HTML，支援完全離線瀏覽

## 環境需求

| 需求 | 版本 |
|---|---|
| Python | ≥ 3.12 |
| [uv](https://docs.astral.sh/uv/) | 任意近期版本 |
| [Ollama](https://ollama.com/) | 任意近期版本 |

拉取用於 CSS 選擇器生成與情感評分的模型：

```bash
ollama pull gemma4:e4b
```

## 安裝

```bash
git clone https://github.com/syutolee/trend-watch
cd trend-watch
uv sync
```

## 快速開始

### 互動模式（推薦）

不帶任何參數直接執行，進入逐步引導精靈：

```bash
ollama serve        # 確認 Ollama 正在執行
uv run trend-watch
```

精靈會依序詢問 LLM 模型、平台（PTT / Dcard / Mobile01 / Reddit / 自訂網址）、版面、關鍵字、爬取頁數，確認後自動開始爬取。

關鍵字欄位留空可啟用**無篩選模式**：所有爬取的文章都會納入分析，報告中不顯示關鍵字命中區塊。

### 指令模式（進階）

```bash
# 帶關鍵字（篩選模式）
trend-watch \
    --url https://forum.example.com/board \
    --keyword "嬰兒奶粉" \
    --keyword "尿布疹" \
    --pages 5

# 不帶關鍵字（無篩選模式—分析所有文章）
trend-watch --url https://www.ptt.cc/bbs/Stock/ --pages 5
```

報告儲存於 `data-watch/reports/watch_<board>_<ts>_report.html`，執行結束後會印出完整路徑。

## CLI 參考

### `trend-watch`

```
trend-watch [OPTIONS]
```

| 選項 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `--url` / `-u` | str | **必填** | 目標網站 URL |
| `--keyword` / `-k` | str | **必填** | 監看關鍵字（可重複使用） |
| `--pages` | int | `5` | 爬取頁數 |
| `--output` | path | `data-watch/` | 輸出根目錄 |
| `--board` | str | 自動（從 URL 取得） | 用於檔名與報告標題的來源標籤 |
| `--dict-dir` | path | `None` | 實體萃取用的基礎詞典目錄（選填） |
| `--config-dir` | path | `data/crawler-configs/` | 爬蟲設定快取目錄 |
| `--use-local-llm` / `--no-local-llm` | 旗標 | 開啟 | 對無互動訊號的貼文套用本地 LLM 情感補全 |
| `--llm-summary` | 旗標 | 關閉 | 生成 LLM 洞察摘要（需設定 Anthropic 的 `LLM__API_KEY` 或使用 Ollama） |
| `--embed-plotly` | 旗標 | 關閉 | 將 Plotly.js 內嵌至 HTML，支援完全離線瀏覽 |

### 使用範例

```bash
# 基本監看 — 3 個關鍵字，10 頁
trend-watch \
    --url https://www.dcard.tw/f/baby \
    -k 配方奶 -k 尿布 -k 副食品 \
    --pages 10

# 離線報告（不依賴 CDN）
trend-watch \
    --url https://forum.example.com \
    -k 關鍵字 \
    --embed-plotly

# 自訂輸出目錄與來源標籤
trend-watch \
    --url https://community.example.com/topics \
    -k "產品召回" \
    --board "example-community" \
    --output results/

# 跳過 LLM 情感補全（更快，首次爬取後不需要 Ollama）
trend-watch \
    --url https://example.com \
    -k 關鍵字 \
    --no-local-llm
```

## 輸出結構

```
data-watch/
├── raw/
│   └── watch_<board>_<ts>.json        # 所有爬取文章（未篩選）
├── analyzed/
│   └── <board>_<ts>.json              # 關鍵字命中文章的分析結果
└── reports/
    └── watch_<board>_<ts>_report.html # 互動式 HTML 報告

data/
└── crawler-configs/
    └── <domain>.json                  # 快取的 CSS 選擇器（後續爬取時重複使用）
```

## 設定

將 `.env.example` 複製為 `.env` 並依需求編輯：

```bash
cp .env.example .env
```

主要設定：

| 變數 | 預設值 | 說明 |
|---|---|---|
| `LLM__PROVIDER` | `ollama` | `ollama` 或 `anthropic` |
| `LLM__MODEL` | `gemma4:e4b` | 模型名稱 |
| `LLM__BASE_URL` | `http://localhost:11434/v1` | Ollama 基礎 URL |
| `LLM__API_KEY` | `ollama` | 使用 Anthropic 時填入 `sk-ant-...` |

## 運作原理

```
URL + 關鍵字
      │
      ▼
 GenericCollector          首次造訪時 LLM 生成 CSS 選擇器；
 （非同步 HTTP 爬蟲）      設定依網域快取於 data/crawler-configs/
      │
      ▼  所有爬取文件儲存至 data-watch/raw/
      │
 filter_docs_by_keywords   OR 邏輯 — 保留提及任一關鍵字的文章
      │
      ▼  0 筆命中 → 附建議後結束；原始資料保留
      │
 AnalysisPipeline
   1. PN 比率情感分析
   2. LLM 情感補全（對無互動訊號的貼文，透過 Ollama）
   3. 實體萃取   ← 關鍵字注入為「watch_keywords」類別
   4. 時間序列量體
   5. 異常偵測
   6. KOL / KOC 側寫
   7. 主題聚類
      │
      ▼
 build_keyword_hits         每個關鍵字：文章數、提及次數、情感分佈
      │
      ▼
 HTMLReportGenerator        Jinja2 + Plotly — 含關鍵字監看專區
      │
      ▼
 data-watch/reports/watch_<board>_<ts>_report.html
```

## 架構

```
src/trend_watch/
├── main.py                    # CLI 進入點（Typer）— watch 指令
├── models.py                  # NormalizedDocument、Post、Reaction、Attitude、Platform
├── filter.py                  # 關鍵字篩選 + KeywordHit 統計
├── config/
│   └── settings.py            # LLMSettings + CrawlerSettings（Pydantic）
├── collector/
│   ├── config.py              # SiteConfig 模型（CSS 選擇器、分頁）
│   ├── evaluator.py           # 基於 LLM 的 CSS 選擇器生成
│   ├── extractor.py           # HTML → NormalizedDocument 萃取
│   └── collector.py           # GenericCollector（非同步 HTTP、快取設定）
├── analyzers/
│   ├── pipeline.py            # AnalysisPipeline → AnalysisResult
│   ├── sentiment/
│   │   ├── pn_ratio.py        # 推文/噓聲比率情感（第一層）
│   │   └── llm_batch.py       # 本地 LLM 批次情感（第二層，快取）
│   ├── entity/
│   │   ├── dictionary.py      # DictionaryManager（載入 .txt 檔 + add_terms）
│   │   └── extractor.py       # EntityExtractor（從 dict_dir 動態分類）
│   ├── kol.py                 # KOLIdentifier → KOLReport
│   ├── koc.py                 # KOCAnalyzer → KOCReport（關鍵意見消費者）
│   ├── anomaly.py             # AnomalyDetector → AnomalyReport
│   ├── time_series.py         # TimeSeriesAnalyzer → TimeSeriesReport
│   └── topic/
│       ├── embedding.py       # TF-IDF 向量化
│       ├── clustering.py      # K-Means 主題聚類
│       └── wordcloud.py       # 關鍵字萃取
├── reporter/
│   ├── generator.py           # HTMLReportGenerator（Jinja2）
│   ├── charts.py              # Plotly 圖表建構器（含 keyword_hits_bar）
│   └── templates/
│       └── dashboard.html     # 報告模板
├── storage/
│   └── storage.py             # WatchStorage（原始 JSON + 分析 JSON）
├── llm/
│   ├── client.py              # LLMClient（Ollama 原生 + OpenAI 相容 + Anthropic）
│   └── cache.py               # 內容雜湊 JSON 快取
└── utils/
    ├── http.py                # 帶速率限制的禮貌性 HTTP session
    ├── logging.py             # LoggerMixin
    └── text.py                # 文字清理工具
```

## 測試

```bash
uv run pytest              # 完整測試套件
uv run pytest --no-cov -q  # 快速執行，不產生覆蓋率報告
```

## 網站相容性說明

通用爬蟲使用純 HTTP 請求——適用於伺服器端渲染的論壇與討論板。以下類型的頁面可能有問題：

- **需要 JavaScript 渲染**（React/Vue SPA）— 爬蟲回傳的文章數量極少或為零；請考慮使用無頭瀏覽器或站台鏡像
- **Cloudflare 保護** — 請求可能被封鎖；部分網站可在 `.env` 中設定自訂 `User-Agent` 來繞過

若首次爬取因 CSS 選擇器生成不佳而失敗，請刪除 `data/crawler-configs/<domain>.json` 後重試，LLM 將重新生成選擇器。

### 已知論壇相容性

| 論壇 | 網域 | 狀態 | 備註 |
|---|---|---|---|
| PTT | ptt.cc | ✅ 可用 | 自動帶入 `over18=1` cookie |
| Dcard | dcard.tw | ⚠️ 有限 | React SPA 無限捲動，靜態爬取僅能取得部分文章 |
| Mobile01 | mobile01.com | ⚠️ 有限 | 受 Akamai WAF 保護，自動化請求可能被封鎖（403） |
| Reddit | reddit.com | ⚠️ 有限 | 使用 old.reddit.com；純 HTTP 爬取可能被速率限制或封鎖 |

## 授權

MIT
