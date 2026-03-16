# Testing Records — Financial Analysis Agent

> Comprehensive record of all bugs, issues, and fixes discovered during development and testing. Excludes deployment/VPS-specific issues (see `VPS_TROUBLESHOOTING.md` for those).

---

## Bug Index

| # | Bug | Version | Severity | Status |
|---|-----|---------|----------|--------|
| 1 | [DST mixed-timezone dropping newest data](#1-dst-mixed-timezone-dropping-newest-data) | v2.6.1 | Critical | Fixed |
| 2 | [/metadata showing "?" for indicators](#2-metadata-showing--for-indicators) | v2.6.1 | Medium | Fixed |
| 3 | [Telegram bot no conversation memory](#3-telegram-bot-no-conversation-memory) | v2.6.1 | Medium | Fixed |
| 4 | [Indicator name aliases not recognized](#4-indicator-name-aliases-not-recognized) | v2.6.1 | Medium | Fixed |
| 5 | [Volume confirmation fails for close-only assets](#5-volume-confirmation-fails-for-close-only-assets) | v2.6.1 | Medium | Fixed |
| 6 | [russell_2000 column mismatch](#6-russell_2000-column-mismatch) | v2.6.1 | Low | Fixed |
| 7 | [/macro output shows "?" placeholders](#7-macro-output-shows--placeholders) | v2.5 | Medium | Fixed |
| 8 | [/ta composite signal missing confidence field](#8-ta-composite-signal-missing-confidence-field) | v2.5 | Low | Fixed |
| 9 | [/graham hangs on yfinance timeout](#9-graham-hangs-on-yfinance-timeout) | v2.5 | High | Fixed |
| 10 | [Excessive decimal places in macro data](#10-excessive-decimal-places-in-macro-data) | v2.5 | Low | Fixed |
| 11 | [scheduled_scan.py broken with stale key names](#11-scheduled_scanpy-broken-with-stale-key-names) | v2.0.1 | High | Fixed |
| 12 | [Telegram bot issues (v1.3)](#12-telegram-bot-issues-v13) | v1.3 | Medium | Fixed |

---

## Detailed Records

### 1. DST Mixed-Timezone Dropping Newest Data

**Version**: v2.6.1
**Date discovered**: 2026-03-10
**Severity**: Critical — silently drops the most recent data points
**Commit**: `b611bc9`

**Symptom**: Oil data (and 11 other indicators) showed March 6th as latest data point, even though the CSV contained March 9th data.

**Root cause**: During DST transitions, CSV timestamps switch between UTC offsets (e.g., `-05:00` EST to `-04:00` EDT). `pd.to_datetime(errors="coerce")` locks onto the first timezone offset it encounters and coerces all rows with a different offset to `NaT` (Not a Time), silently dropping them from the DataFrame.

**Affected files**:
- `tools/macro_data.py` — `_load_csv()`
- `tools/fred_data.py` — `_try_local_csv()`

**Affected CSVs** (12 total):
`crude_oil.csv`, `gold_spot.csv`, `silver_spot.csv`, `copper_futures.csv`, `es_futures.csv`, `rty_futures.csv`, `dxy_index.csv`, `usd_jpy.csv`, `vix_move.csv`, `cboe_skew.csv`, `10y_treasury_yield.csv`, `2y_treasury_yield.csv`

**Fix**: Added `utc=True` parameter to `pd.to_datetime()` calls for timestamp columns, which normalizes all timezone-aware timestamps to UTC before comparison.

```python
# macro_data.py — _load_csv()
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

# fred_data.py — _try_local_csv()
use_utc = date_col == "timestamp"
df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=use_utc)
```

**How to verify**:
```python
from tools.macro_data import _load_csv
df = _load_csv('crude_oil.csv')
print(df.tail(3))  # Should show the most recent date, not skip it
```

**Lesson**: Always use `utc=True` when parsing timestamps that may span DST boundaries. The `errors="coerce"` parameter is dangerous with mixed timezone offsets because it silently produces `NaT` instead of raising an error.

---

### 2. /metadata Showing "?" for Indicators

**Version**: v2.6.1
**Date discovered**: 2026-03-10
**Severity**: Medium — cosmetic but hides data freshness info
**Commit**: `8da0ccf`

**Symptom**: Telegram `/metadata` command returned `indicators: ?` instead of showing per-indicator data freshness details (last date, row counts).

**Root cause**: The handler in `telegram_bot.py` iterated over top-level JSON keys from `read_data_metadata()`. The `indicators` value is a nested dict containing 91 indicator entries, but the handler treated it as a single opaque entry. `info.get("last_extracted")` missed because the actual key is `last_date`, causing the fallback to `"?"`.

**Fix**: Properly parse the nested `indicators` sub-dict:

```python
indicators = result.get("indicators", {})
if isinstance(indicators, dict) and indicators:
    lines.append("Indicators:")
    for key, info in indicators.items():
        if isinstance(info, dict):
            name = info.get("indicator", key)
            last_date = info.get("last_date", "?")
            rows = info.get("rows", "?")
            lines.append(f"  - {name}: {last_date} ({rows} rows)")
```

**Lesson**: When formatting nested API responses for display, always inspect the actual data structure rather than assuming flat key-value pairs.

---

### 3. Telegram Bot No Conversation Memory

**Version**: v2.6.1
**Date discovered**: 2026-03-10
**Severity**: Medium — bot can't handle follow-up questions
**Commit**: `a67047d`

**Symptom**: After asking the Telegram bot to scan macro indicators, follow-up questions like "tell me more about VIX" or "yes, continue" had no context — the bot treated every message as independent.

**Root cause**: No conversation history was maintained between messages. Each message was processed in isolation without any prior context being passed to the LLM.

**Fix**: Implemented a multi-part conversation memory system:

1. **Per-chat rolling history** (10 turns max) stored in `context.chat_data`:
   ```python
   MAX_HISTORY_TURNS = 10
   def _add_to_history(context, user_msg, bot_response):
       hist = context.chat_data.setdefault("history", [])
       hist.append(("user", user_msg))
       hist.append(("assistant", bot_response[:2000]))
       if len(hist) > MAX_HISTORY_TURNS * 2:
           context.chat_data["history"] = hist[-(MAX_HISTORY_TURNS * 2):]
   ```

2. **Auto-recording in `_send_long()`**: All 48 `_send_long` calls updated to pass `context=context`, enabling automatic history recording.

3. **Pre-handler middleware** (`_record_pending_user_msg`, group=-1) captures user command text before handlers execute.

4. **LangChain agent history**: `run_agent()` accepts `history: list | None` parameter, converting to `HumanMessage`/`AIMessage` objects.

**Lesson**: For Telegram bots, `context.chat_data` is the correct per-chat state container. Using a centralized auto-recording mechanism (`_send_long`) is cleaner than adding explicit `_add_to_history` calls in every handler.

---

### 4. Indicator Name Aliases Not Recognized

**Version**: v2.6.1
**Date discovered**: 2026-03-09
**Severity**: Medium — users must know exact CSV key names
**Commit**: Part of `9d87d2d`

**Symptom**: Asking the agent about "VIX" or "10Y yield" returned errors because the tool expected exact CSV key names like `vix_move` or `10y_treasury_yield`.

**Root cause**: `analyze_indicator_changes()` and `read_indicator_data()` performed exact key matching against CSV filenames, with no alias resolution.

**Fix**: Added `INDICATOR_ALIASES` dict (~30 common name mappings) and `_resolve_indicator_key()` function to `tools/macro_data.py`:

```python
INDICATOR_ALIASES = {
    "vix": "vix_move",
    "10y_yield": "10y_treasury_yield",
    "10y": "10y_treasury_yield",
    "2y_yield": "2y_treasury_yield",
    "pmi": "ism_pmi",
    "dollar": "dxy_index",
    "yen": "usd_jpy",
    # ... ~30 aliases total
}
```

**Lesson**: User-facing tools should always accept natural language variants and normalize internally.

---

### 5. Volume Confirmation Fails for Close-Only Assets

**Version**: v2.6.1
**Date discovered**: 2026-03-09
**Severity**: Medium — false confidence reduction on breakout signals
**Commit**: Part of `9d87d2d`

**Symptom**: Breakout analysis for macro assets (gold, crude oil, DXY, etc.) always reported low confidence because volume confirmation consistently failed.

**Root cause**: Close-only macro assets (loaded from CSV with only a `close` column) have `volume=0`. The breakout analyzer checked for volume surge as one of 4 confirmation signals, which always failed for these assets, capping confidence at 3/4 max.

**Fix**: Added `has_volume` detection. When an asset has no volume data, the volume check is skipped entirely and `max_confirmations` is adjusted from 4 to 3:

```python
has_volume = df["volume"].sum() > 0
if has_volume:
    # Check volume surge (4 confirmations max)
else:
    # Skip volume, adjust to 3 confirmations max
```

**Lesson**: Technical analysis tools must handle heterogeneous data availability. Not all assets have OHLCV — some are close-only. Scoring systems should adapt their denominators accordingly.

---

### 6. russell_2000 Column Mismatch

**Version**: v2.6.1
**Date discovered**: 2026-03-09
**Severity**: Low — Russell 2000 TA analysis fails
**Commit**: Part of `9d87d2d`

**Symptom**: Murphy technical analysis for Russell 2000 returned empty results or errors.

**Root cause**: `ASSET_DATA_MAP` in `murphy_ta.py` specified `"col": "russell_2000"` but the actual CSV column name is `"russell_2000_value"`.

**Fix**: Changed mapping to `"col": "russell_2000_value"`.

**Lesson**: Column name mismatches between code and CSV files are silent failures. Validate mappings against actual CSV headers during development.

---

### 7. /macro Output Shows "?" Placeholders

**Version**: v2.5
**Date discovered**: 2026-03-07
**Severity**: Medium — macro regime analysis shows incomplete output
**Commit**: Part of `9d87d2d`

**Symptom**: Telegram `/macro` command showed `?` in place of actual values for timestamp and regime classification.

**Root cause**: Key mismatch between the tool output and the Telegram formatter. The tool returned `timestamp` and `classification`, but the formatter expected `as_of` and `state`.

**Fix**: Updated key references in `telegram_bot.py` formatter to match actual tool output structure.

**Lesson**: When tool output structures change, all consumers (CLI, Telegram, scheduled scripts) must be updated in sync.

---

### 8. /ta Composite Signal Missing Confidence Field

**Version**: v2.5
**Date discovered**: 2026-03-07
**Severity**: Low — no confidence scoring on TA signals
**Commit**: Part of `9d87d2d`

**Symptom**: Murphy technical analysis output included a composite signal (BULLISH/BEARISH/NEUTRAL) but no confidence level, making it hard to gauge signal strength.

**Root cause**: Confidence scoring was not computed in the composite signal aggregation.

**Fix**: Added confidence scoring (HIGH/MODERATE/LOW) based on framework agreement percentage and a `framework_breakdown` section showing individual framework signals.

---

### 9. /graham Hangs on yfinance Timeout

**Version**: v2.5
**Date discovered**: 2026-03-07
**Severity**: High — command hangs indefinitely
**Commit**: Part of `9d87d2d`

**Symptom**: `/graham AAPL` command would hang for 30+ seconds or indefinitely when yfinance was slow to respond.

**Root cause**: yfinance's `timeout` parameter only applies to the initial HTTP connection, not the full data download. A slow or stalled download would block the event loop indefinitely.

**Fix**: Wrapped yfinance calls in `concurrent.futures.ThreadPoolExecutor` with a hard 8-second timeout:

```python
with concurrent.futures.ThreadPoolExecutor() as pool:
    future = pool.submit(yf.Ticker(ticker).info.get, "currentPrice")
    try:
        price = future.result(timeout=8)
    except concurrent.futures.TimeoutError:
        price = None
```

**Lesson**: Library-level timeout parameters don't always provide the guarantees they suggest. Use external timeout wrappers (ThreadPoolExecutor, asyncio.wait_for) for hard guarantees.

---

### 10. Excessive Decimal Places in Macro Data

**Version**: v2.5
**Date discovered**: 2026-03-07
**Severity**: Low — cosmetic
**Commit**: Part of `9d87d2d`

**Symptom**: Macro data output showed values like `4.283749182749` instead of `4.28`.

**Root cause**: No rounding was applied to computed metric values (changes, z-scores, percentages).

**Fix**: Added `_r2()` helper function to round all metric values to 2 decimal places throughout `macro_data.py`.

---

### 11. scheduled_scan.py Broken with Stale Key Names

**Version**: v2.0.1
**Date discovered**: 2026-03-03
**Severity**: High — automated scans stop working
**Commit**: Part of `9d87d2d`

**Symptom**: `scheduled_scan.py` (cron-driven 3x/day macro scans) failed silently because it couldn't parse the scan results.

**Root cause**: The output structure of `scan_all_indicators()` was changed during v2.0 refactoring, but `scheduled_scan.py` still referenced the old key names.

**Fix**: Updated `scheduled_scan.py` to use the actual `scan_all_indicators()` output structure.

**Lesson**: Automated consumers (cron jobs, scheduled tasks) are easy to forget when refactoring tool output structures. Keep a checklist of all consumers when changing return types.

---

### 12. Telegram Bot Issues (v1.3)

**Version**: v1.3
**Date discovered**: 2026-02-25
**Severity**: Medium
**Commit**: `ce357cf`

**Symptom**: Various Telegram bot formatting and response issues during the comprehensive equity analysis enhancement.

**Root cause**: Telegram bot message formatting did not account for new equity analysis output fields added in v1.3.

**Fix**: Updated Telegram bot formatters as part of the v1.3 comprehensive equity analysis enhancement commit.

---

## Known Limitations (Not Bugs)

These are documented limitations, not bugs — they represent design constraints or external dependencies.

| Limitation | Detail |
|-----------|--------|
| Data freshness depends on external job | Macro CSVs updated by `/macro_2/scheduled_extract.py` (launchd). If the job doesn't run, data goes stale. |
| Sparse data for some indicators | GDP is quarterly, ISM PMI is monthly — anomaly detection windows may be too short. |
| Twitter API costs | TwitterAPI.io charges per call. Human-in-the-loop prevents runaway spending. |
| MiniMax think tags | MiniMax M2.5 sometimes emits `<think>...</think>` tags that need stripping. |
| Forward P/E unreliable | Forward P/E and put/call ratio data sources in macro_2 return 403 errors. |
| yfinance rate limits | yfinance can be slow or rate-limited, especially during market hours. 30-min TTL cache mitigates this. |
| Close-only assets | Gold, crude oil, DXY, etc. are close-only from CSV — no intraday OHLCV unless fetched via yfinance. |

---

## Testing Checklist for Future Releases

Before releasing a new version, verify:

- [ ] `scan` and `scan_full` complete without errors
- [ ] All 27 indicators return data with correct latest dates (check for DST issues around March/November)
- [ ] `/metadata` shows per-indicator freshness details
- [ ] `/macro`, `/bonds`, `/drivers`, `/stress`, `/latecycle` produce formatted output without `?` placeholders
- [ ] `/ta` works for BTC, gold, crude_oil, es_futures, and at least one stock ticker (e.g., AAPL)
- [ ] `/graham` responds within 10 seconds (yfinance timeout protection)
- [ ] Telegram bot handles follow-up questions ("tell me more", "what about VIX?")
- [ ] `scheduled_scan.py` parses scan output correctly (test with `python scheduled_scan.py --dry-run` if available)
- [ ] All decimal values rounded to 2dp in user-facing output
- [ ] Breakout confidence shows correct max (3/3 for close-only, 4/4 for OHLCV assets)
