#!/usr/bin/env python3
"""
Approach #7 — TA Internal Coherence

Cross-checks signals within and across TA tool outputs.
15 checks per asset (45 total for 3 assets).

Categories:
  TC-01..05  Signal direction consistency
  TC-06..08  S/R consistency
  TC-09..12  Cross-tool consistency
  TC-13..15  Stop-loss coherence

Usage:
    python ta_coherence_checker.py --input ../../taste/ta_output_v1.json
"""

import sys, os, json, argparse, time
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_RECORDS = _THIS / "records"
_RECORDS.mkdir(parents=True, exist_ok=True)


class Check:
    def __init__(self, check_id, asset, name, passed, expected, actual, detail,
                 severity="medium"):
        self.check_id = check_id
        self.asset = asset
        self.name = name
        self.passed = passed
        self.expected = expected
        self.actual = actual
        self.detail = detail
        self.severity = severity
    def to_dict(self):
        return vars(self)

class Report:
    def __init__(self):
        self.checks: list[Check] = []
        self.t0 = time.time()
    def add(self, c: Check):
        self.checks.append(c)
        icon = "\u2705" if c.passed else "\u274c"
        sev = c.severity.upper()[:4]
        print(f"  {icon} [{c.check_id}][{c.asset:5s}][{sev}] {c.name}")
        if not c.passed:
            print(f"       expected={c.expected}  actual={c.actual}")
    @property
    def summary(self):
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        return {
            "total": total, "passed": passed, "failed": total - passed,
            "pass_rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical": sum(1 for c in self.checks
                           if not c.passed and c.severity in ("critical","high")),
            "elapsed": f"{time.time()-self.t0:.1f}s",
        }
    def to_dict(self):
        return {"summary": self.summary,
                "all_checks": [c.to_dict() for c in self.checks]}


def run_asset_checks(asset: str, ad: dict, rpt: Report):
    """Run 15 coherence checks for one asset."""
    murphy = ad.get("murphy_full", {}).get("data", {})
    rsi_out = ad.get("rsi", {}).get("data", {})
    sr_out = ad.get("support_resistance", {}).get("data", {})
    bo_out = ad.get("breakout", {}).get("data", {})
    snap_out = ad.get("quick_snapshot", {}).get("data", {})
    sl_out = ad.get("stop_loss", {}).get("data", {})
    synth_out = ad.get("fundamental_synthesis", {}).get("data", {})

    price = murphy.get("current_price", 0) or sr_out.get("current_price", 0)
    comp = murphy.get("composite_signal", {})
    trend = murphy.get("1_trend", {})
    macd = murphy.get("5_macd", {})
    rsi_m = murphy.get("6_rsi", {})
    stoch = murphy.get("9_stochastic", {})
    bb = murphy.get("7_bollinger_bands", {})

    # ── TC-01: Composite signal vs trend direction ───────────
    comp_signal = comp.get("signal", "")
    trend_dir = trend.get("direction", "")
    compatible = True
    if "BULLISH" in comp_signal and "downtrend" in trend_dir:
        # Mild divergence is OK if score is moderate
        score = comp.get("score", 0)
        compatible = abs(score) < 0.5  # Weak bullish with downtrend is tolerable
    elif "BEARISH" in comp_signal and "uptrend" in trend_dir:
        score = comp.get("score", 0)
        compatible = abs(score) < 0.5
    rpt.add(Check("TC-01", asset, "Composite signal vs trend direction",
                   compatible,
                   f"compatible ({comp_signal} vs {trend_dir})",
                   f"signal={comp_signal}, trend={trend_dir}",
                   "Strong composite signal should not oppose strong trend", "medium"))

    # ── TC-02: MACD crossover vs histogram sign ──────────────
    hist = macd.get("histogram")
    xover = macd.get("crossover", "")
    if hist is not None:
        # Positive histogram = MACD > signal = bullish
        ok = True
        if hist > 0 and "BEARISH_CROSS" in xover.upper():
            ok = False
        elif hist < 0 and "BULLISH_CROSS" in xover.upper():
            ok = False
        rpt.add(Check("TC-02", asset, "MACD crossover vs histogram",
                       ok,
                       "consistent", f"hist={hist:.4f}, crossover={xover}",
                       "Histogram sign should match crossover type", "high"))
    else:
        rpt.add(Check("TC-02", asset, "MACD crossover vs histogram",
                       True, "skip", "N/A", "No MACD data", "low"))

    # ── TC-03: RSI vs Stochastic alignment ───────────────────
    rsi_val = rsi_m.get("rsi")
    stoch_k = stoch.get("percent_k")
    if rsi_val is not None and stoch_k is not None:
        # Both overbought or both oversold is most coherent
        rsi_extreme = "overbought" if rsi_val >= 70 else ("oversold" if rsi_val <= 30 else "mid")
        stoch_extreme = "overbought" if stoch_k >= 80 else ("oversold" if stoch_k <= 20 else "mid")
        contradiction = (rsi_extreme == "overbought" and stoch_extreme == "oversold") or \
                        (rsi_extreme == "oversold" and stoch_extreme == "overbought")
        rpt.add(Check("TC-03", asset, "RSI vs Stochastic alignment",
                       not contradiction,
                       "no contradiction",
                       f"RSI={rsi_val:.1f}({rsi_extreme}), %K={stoch_k:.1f}({stoch_extreme})",
                       "RSI and Stochastic should not have opposing extremes", "medium"))
    else:
        rpt.add(Check("TC-03", asset, "RSI vs Stochastic",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-04: Bollinger %B vs RSI coherence ─────────────────
    pct_b = bb.get("percent_b")
    if pct_b is not None and rsi_val is not None:
        # %B > 90 (near upper) + RSI < 30 is contradictory
        # %B < 10 (near lower) + RSI > 70 is contradictory
        contra = (pct_b > 90 and rsi_val < 30) or (pct_b < 10 and rsi_val > 70)
        rpt.add(Check("TC-04", asset, "Bollinger %B vs RSI",
                       not contra,
                       "no contradiction",
                       f"%B={pct_b:.1f}, RSI={rsi_val:.1f}",
                       "BB position and RSI should not be opposing extremes", "medium"))
    else:
        rpt.add(Check("TC-04", asset, "Bollinger %B vs RSI",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-05: Trend direction vs MA structure ───────────────
    ma = murphy.get("4_moving_averages", {})
    sma50 = ma.get("sma_50")
    sma200 = ma.get("sma_200")
    price_vs_50 = ma.get("price_vs_sma50", "")
    if sma50 is not None and sma200 is not None:
        # If price below SMA50 and SMA200, trend should not be uptrend
        both_below = price < sma50 and price < sma200
        both_above = price > sma50 and price > sma200
        contra = (both_below and "uptrend" in trend_dir) or \
                 (both_above and "downtrend" in trend_dir)
        rpt.add(Check("TC-05", asset, "Trend vs MA structure",
                       not contra,
                       "consistent",
                       f"price={price:.2f}, SMA50={sma50:.2f}, SMA200={sma200:.2f}, trend={trend_dir}",
                       "Price vs MAs should agree with trend direction", "high"))
    else:
        rpt.add(Check("TC-05", asset, "Trend vs MA",
                       True, "skip", "N/A", "No MA data", "low"))

    # ── TC-06: All supports < price < all resistances ────────
    supports = sr_out.get("supports", [])
    resistances = sr_out.get("resistances", [])
    sr_price = sr_out.get("current_price", price)
    if supports and resistances and sr_price > 0:
        # Allow 1% tolerance
        sups_ok = all(s <= sr_price * 1.01 for s in supports)
        res_ok = all(r >= sr_price * 0.99 for r in resistances)
        rpt.add(Check("TC-06", asset, "Supports < price < resistances",
                       sups_ok and res_ok,
                       f"all supports <= {sr_price*1.01:.2f}, all res >= {sr_price*0.99:.2f}",
                       f"supports={supports[:3]}, res={resistances[:3]}",
                       "S/R levels should be properly ordered around price", "high"))
    else:
        rpt.add(Check("TC-06", asset, "S/R ordering",
                       True, "skip", "N/A", "No S/R data", "low"))

    # ── TC-07: Murphy S/R vs standalone S/R match ────────────
    murphy_sr = murphy.get("2_support_resistance", {})
    m_sups = murphy_sr.get("supports", [])
    m_res = murphy_sr.get("resistances", [])
    sa_sups = sr_out.get("supports", [])
    sa_res = sr_out.get("resistances", [])
    if m_sups and sa_sups:
        # Nearest support should be the same (or very close)
        m_near = m_sups[0] if m_sups else None
        sa_near = sa_sups[0] if sa_sups else None
        if m_near and sa_near and price > 0:
            diff_pct = abs(m_near - sa_near) / price * 100
            rpt.add(Check("TC-07", asset, "Murphy vs standalone nearest support",
                           diff_pct < 2.0,
                           f"< 2% difference",
                           f"murphy={m_near:.2f}, standalone={sa_near:.2f} ({diff_pct:.2f}%)",
                           "Both tools should identify similar support levels", "medium"))
        else:
            rpt.add(Check("TC-07", asset, "Murphy vs standalone S/R",
                           True, "skip", "N/A", "No comparable levels", "low"))
    else:
        rpt.add(Check("TC-07", asset, "Murphy vs standalone S/R",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-08: S/R level spacing (no duplicates) ─────────────
    all_levels = sorted(supports + resistances)
    if len(all_levels) >= 2 and price > 0:
        min_spacing = min(abs(all_levels[i+1] - all_levels[i])
                          for i in range(len(all_levels)-1))
        min_spacing_pct = min_spacing / price * 100
        rpt.add(Check("TC-08", asset, "S/R levels have adequate spacing",
                       min_spacing_pct > 0.3,
                       "> 0.3% spacing",
                       f"min spacing = {min_spacing:.2f} ({min_spacing_pct:.2f}%)",
                       "S/R levels too close together are essentially duplicates", "low"))
    else:
        rpt.add(Check("TC-08", asset, "S/R spacing",
                       True, "skip", "N/A", "Insufficient levels", "low"))

    # ── TC-09: RSI murphy vs standalone RSI match ────────────
    rsi_murphy = rsi_m.get("rsi")
    rsi_standalone = rsi_out.get("rsi_14")
    if rsi_murphy is not None and rsi_standalone is not None:
        diff = abs(rsi_murphy - rsi_standalone)
        rpt.add(Check("TC-09", asset, "Murphy RSI vs standalone RSI",
                       diff < 0.1,
                       f"< 0.1 difference", f"murphy={rsi_murphy:.2f}, standalone={rsi_standalone:.2f}",
                       "Same RSI calculation should produce identical results", "high"))
    else:
        rpt.add(Check("TC-09", asset, "Murphy vs standalone RSI",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-10: Breakout vs trend direction ───────────────────
    bo_detected = bo_out.get("breakout_detected", False)
    bo_trend = bo_out.get("trend", {})
    bo_trend_dir = bo_trend.get("direction", "")
    if bo_detected:
        bo_type = bo_out.get("breakout_type", "")
        # Bullish breakout in downtrend or bearish breakout in uptrend is suspicious
        suspicious = ("BULLISH" in str(bo_type).upper() and "downtrend" in bo_trend_dir) or \
                     ("BEARISH" in str(bo_type).upper() and "uptrend" in bo_trend_dir)
        rpt.add(Check("TC-10", asset, "Breakout type vs trend",
                       not suspicious,
                       "compatible",
                       f"breakout={bo_type}, trend={bo_trend_dir}",
                       "Breakout should align with or precede trend change", "medium"))
    else:
        rpt.add(Check("TC-10", asset, "Breakout vs trend",
                       True, "no breakout — consistent",
                       f"detected=False, trend={bo_trend_dir}",
                       "No breakout is consistent with any trend", "low"))

    # ── TC-11: Breakout level in S/R list ────────────────────
    bo_nearest_res = bo_out.get("nearest_resistance")
    bo_nearest_sup = bo_out.get("nearest_support")
    sr_nearest_res = sr_out.get("nearest_resistance")
    sr_nearest_sup = sr_out.get("nearest_support")
    if bo_nearest_res is not None and sr_nearest_res is not None and price > 0:
        diff_pct = abs(bo_nearest_res - sr_nearest_res) / price * 100
        rpt.add(Check("TC-11", asset, "Breakout nearest_res matches S/R",
                       diff_pct < 1.0,
                       f"< 1% difference",
                       f"breakout={bo_nearest_res:.2f}, S/R={sr_nearest_res:.2f} ({diff_pct:.2f}%)",
                       "Both tools should find same nearest resistance", "medium"))
    else:
        rpt.add(Check("TC-11", asset, "Breakout vs S/R levels",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-12: quick_snapshot vs individual tools ────────────
    snap_rsi = snap_out.get("rsi", {}).get("rsi_14")
    if snap_rsi is not None and rsi_standalone is not None:
        diff = abs(snap_rsi - rsi_standalone)
        rpt.add(Check("TC-12", asset, "Snapshot RSI vs standalone RSI",
                       diff < 0.1,
                       f"< 0.1 difference",
                       f"snap={snap_rsi:.2f}, standalone={rsi_standalone:.2f}",
                       "Snapshot embeds same RSI calculation", "high"))
    else:
        rpt.add(Check("TC-12", asset, "Snapshot vs standalone",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TC-13: Stop below entry for longs ────────────────────
    if isinstance(sl_out, dict) and sl_out.get("direction") == "long":
        rec_stop = sl_out.get("recommended_stop", 0)
        entry = sl_out.get("entry_price", 0)
        if rec_stop > 0 and entry > 0:
            rpt.add(Check("TC-13", asset, "Long stop below entry",
                           rec_stop < entry,
                           f"< {entry:.2f}", f"{rec_stop:.2f}",
                           "Long position stop-loss must be below entry", "critical"))
        else:
            rpt.add(Check("TC-13", asset, "Stop-loss entry check",
                           True, "skip", "N/A", "No stop data", "low"))
    else:
        rpt.add(Check("TC-13", asset, "Stop-loss entry check",
                       True, "skip", "N/A", "No stop-loss data", "low"))

    # ── TC-14: Swing stop near S/R level ─────────────────────
    if isinstance(sl_out, dict) and sl_out.get("stop_levels"):
        swing_sl = sl_out["stop_levels"].get("swing_based", {})
        swing_level = swing_sl.get("level", 0)
        if swing_level > 0 and supports and price > 0:
            # Swing stop should be at or below nearest support
            nearest_sup = max(s for s in supports if s < price) if any(s < price for s in supports) else 0
            if nearest_sup > 0:
                diff_pct = abs(swing_level - nearest_sup) / price * 100
                rpt.add(Check("TC-14", asset, "Swing stop near S/R support",
                               diff_pct < 5.0,
                               f"within 5% of nearest support ({nearest_sup:.2f})",
                               f"swing_stop={swing_level:.2f} ({diff_pct:.1f}% away)",
                               "Swing stop should relate to nearby support level", "low"))
            else:
                rpt.add(Check("TC-14", asset, "Swing stop near S/R",
                               True, "skip", "N/A", "No support below price", "low"))
        else:
            rpt.add(Check("TC-14", asset, "Swing stop near S/R",
                           True, "skip", "N/A", "Missing data", "low"))
    else:
        rpt.add(Check("TC-14", asset, "Swing stop near S/R",
                       True, "skip", "N/A", "No stop data", "low"))

    # ── TC-15: Position sizing arithmetic ────────────────────
    if isinstance(sl_out, dict) and sl_out.get("position_sizing"):
        ps = sl_out["position_sizing"]
        risk_pct = ps.get("risk_per_trade_pct", 0)
        capital_risk = ps.get("capital_at_risk_per_unit", 0)
        entry = sl_out.get("entry_price", 0)
        rec_stop = sl_out.get("recommended_stop", 0)
        if entry > 0 and rec_stop > 0 and capital_risk > 0:
            expected_capital_risk = abs(entry - rec_stop)
            diff = abs(capital_risk - expected_capital_risk)
            rpt.add(Check("TC-15", asset, "Position sizing capital_at_risk",
                           diff < entry * 0.001,
                           f"{expected_capital_risk:.2f}",
                           f"{capital_risk:.2f}",
                           "capital_at_risk = |entry - stop|", "medium"))
        else:
            rpt.add(Check("TC-15", asset, "Position sizing arithmetic",
                           True, "skip", "N/A", "Missing data", "low"))
    else:
        rpt.add(Check("TC-15", asset, "Position sizing",
                       True, "skip", "N/A", "No position sizing data", "low"))


# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Approach #7: TA Coherence")
    parser.add_argument("--input", required=True, help="Path to ta_output_v1.json")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    print("=" * 70)
    print("  APPROACH #7: TA INTERNAL COHERENCE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    rpt = Report()
    for asset, ad in data["assets"].items():
        print(f"\n{'─' * 60}  {asset}")
        run_asset_checks(asset, ad, rpt)

    s = rpt.summary
    print(f"\n{'=' * 70}")
    print(f"  RESULTS: {s['total']} checks | {s['passed']} passed | "
          f"{s['failed']} failed | {s['pass_rate']}")
    if s["critical"]:
        print(f"  CRITICAL/HIGH failures: {s['critical']}")
    print(f"{'=' * 70}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {"approach": "7_ta_coherence", "timestamp": datetime.now().isoformat(),
           "results": rpt.to_dict()}
    jp = _RECORDS / f"approach7_{ts}.json"
    with open(jp, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  Saved: {jp}")
    return rpt

if __name__ == "__main__":
    main()
