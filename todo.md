# Testing Agent — TODO

## Technical Analysis Evaluation Items

### P0 (High Priority)
- [ ] Store full bar count in `collect_ta_data.py` — match tool's `data_points` instead of fixed 250 to eliminate false RSI/Fibonacci failures
- [ ] Improve `<think>` tag parser in Approach #10 to increase LLM scoring rate from 67% (14/21) to >90% — MiniMax-M2.5 sometimes embeds scores only within reasoning blocks

### P1 (Medium Priority)
- [ ] Parameterise Fibonacci lookback in Approach #8 verifier to match tool's actual lookback window
- [ ] Add multi-timeframe tests for BTC (5min, 1H, 4H) since it's the only asset supporting multiple timeframes
- [ ] Test error handling for invalid tickers (e.g., `murphy_technical_analysis("INVALID")`)

### P2 (Low Priority)
- [ ] Extend asset coverage to commodities (crude_oil, silver), indices (SPY, QQQ), and volatile stocks (TSLA, NVDA)
- [ ] Add time-series regression tests — store reference outputs and detect drift over time
- [ ] Integrate with CI — run Approaches #7-#9 (deterministic) on each Financial Agent commit
