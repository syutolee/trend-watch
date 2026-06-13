#!/usr/bin/env bash
# smoke_test.sh — end-to-end CLI smoke tests for trend-watch
# Run from the project root: bash scripts/smoke_test.sh
# Reddit excluded (HTTP 403 from WAF). Mobile01 skipped on WAF 403.
# Each case PASSES when output has "Report ready:" or "No articles matched".
# FAILS on "Traceback" or "returned 0 documents".

set -euo pipefail

PASS=0
FAIL=0
SKIP=0
RESULTS=()

run_case() {
    local id="$1"
    local label="$2"
    shift 2
    local cmd=("$@")

    echo ""
    echo "=== Case $id: $label ==="
    output=$("${cmd[@]}" 2>&1) || true

    if echo "$output" | grep -q "Traceback"; then
        status="FAIL (Traceback)"
        FAIL=$((FAIL + 1))
    elif echo "$output" | grep -q "returned 0 documents"; then
        # Check if it's a WAF block (403) — skip rather than fail
        if echo "$output" | grep -qiE "403|Access Denied|Akamai|WAF"; then
            status="SKIP (WAF/403)"
            SKIP=$((SKIP + 1))
        else
            status="FAIL (0 documents)"
            FAIL=$((FAIL + 1))
        fi
    elif echo "$output" | grep -qE "Report ready:|No articles matched"; then
        status="PASS"
        PASS=$((PASS + 1))
    else
        status="FAIL (no expected output)"
        FAIL=$((FAIL + 1))
    fi

    RESULTS+=("[$status]  Case $id: $label")
    echo "--- output (last 20 lines) ---"
    echo "$output" | tail -20
    echo "--- result: $status ---"
}

# ── PTT tests ──────────────────────────────────────────────────────────
run_case 1 "PTT sex / single keyword" \
    uv run trend-watch \
    --url "https://www.ptt.cc/bbs/sex/" \
    -k "推薦" --pages 3

run_case 2 "PTT sex / multiple keywords" \
    uv run trend-watch \
    --url "https://www.ptt.cc/bbs/sex/" \
    -k "推薦" -k "心得" --pages 3

run_case 3 "PTT sex / unfiltered (no keywords)" \
    uv run trend-watch \
    --url "https://www.ptt.cc/bbs/sex/" \
    --pages 2

# ── Dcard tests ────────────────────────────────────────────────────────
run_case 4 "Dcard baby / single keyword" \
    uv run trend-watch \
    --url "https://www.dcard.tw/f/baby" \
    -k "配方奶" --pages 2

run_case 5 "Dcard baby / unfiltered" \
    uv run trend-watch \
    --url "https://www.dcard.tw/f/baby" \
    --pages 1

# ── Mobile01 tests (may be skipped if WAF blocks) ─────────────────────
run_case 6 "Mobile01 638 / single keyword" \
    uv run trend-watch \
    --url "https://www.mobile01.com/topiclist.php?f=638" \
    -k "手機" --pages 2

run_case 7 "Mobile01 638 / multiple keywords" \
    uv run trend-watch \
    --url "https://www.mobile01.com/topiclist.php?f=638" \
    -k "手機" -k "評測" --pages 2

run_case 8 "Mobile01 638 / unfiltered" \
    uv run trend-watch \
    --url "https://www.mobile01.com/topiclist.php?f=638" \
    --pages 1

# ── Wizard smoke checks (piped stdin) ─────────────────────────────────
# Menu order: 1)PTT 2)Dcard 3)Mobile01 4)Reddit 5)Other
# Provider: 1)Ollama 2)Anthropic
# Input: provider=1, model=default, platform=1(PTT), board=sex, keyword=(blank)=unfiltered, pages=2, confirm=y

echo ""
echo "=== Wizard Case W1: PTT, blank keyword (unfiltered) ==="
wizard_output=$(printf '1\ngemma4:e4b\n1\nsex\n\n2\ny\n' | uv run trend-watch 2>&1) || true
if echo "$wizard_output" | grep -q "Traceback"; then
    wiz1="FAIL (Traceback)"
    FAIL=$((FAIL + 1))
elif echo "$wizard_output" | grep -qE "Report ready:|No articles matched|analyze all"; then
    wiz1="PASS"
    PASS=$((PASS + 1))
else
    wiz1="FAIL (unexpected output)"
    FAIL=$((FAIL + 1))
fi
RESULTS+=("[$wiz1]  Case W1: Wizard PTT blank keyword")
echo "$wizard_output" | tail -10
echo "--- result: $wiz1 ---"

echo ""
echo "=== Wizard Case W2: Dcard, single keyword ==="
wizard_output2=$(printf '1\ngemma4:e4b\n2\nbaby\n配方奶\n2\ny\n' | uv run trend-watch 2>&1) || true
if echo "$wizard_output2" | grep -q "Traceback"; then
    wiz2="FAIL (Traceback)"
    FAIL=$((FAIL + 1))
elif echo "$wizard_output2" | grep -qE "Report ready:|No articles matched"; then
    wiz2="PASS"
    PASS=$((PASS + 1))
else
    wiz2="FAIL (unexpected output)"
    FAIL=$((FAIL + 1))
fi
RESULTS+=("[$wiz2]  Case W2: Wizard Dcard single keyword")
echo "$wizard_output2" | tail -10
echo "--- result: $wiz2 ---"

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  SMOKE TEST SUMMARY"
echo "=========================================="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo "------------------------------------------"
echo "  PASS: $PASS  FAIL: $FAIL  SKIP: $SKIP"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
