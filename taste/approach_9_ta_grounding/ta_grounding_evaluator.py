#!/usr/bin/env python3
"""
Approach #9 — TA Grounding (Label-to-Value Verification)

Verifies that textual labels/zones match their underlying indicator values.
12 checks per asset (36 total for 3 assets).

Threshold dictionary:
  RSI:          oversold=(0,30), bearish_momentum=(30,50), bullish_momentum=(50,70), overbought=(70,100)
  Stochastic:   oversold=(0,20), neutral=(20,80), overbought=(80,100)
  Bollinger %B: below_lower=(<0), near_lower=(0,20), within=(20,80), near_upper=(80,100), above_upper=(>100)
  Composite:    BEARISH=(<-0.3), NEUTRAL=(-0.3,0.3), BULLISH=(>0.3)

Usage:
    python ta_grounding_evaluator.py --input ../../taste/ta_output_v1.json
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


# ═══════════════════════════════════════════════════════════════════
# THRESHOLD DICTIONARIES
# ═══════════════════════════════════════════════════════════════════

RSI_ZONES = {
    "oversold":         (0, 30),
    "bearish_momentum": (30, 50),
    "bullish_momentum": (50, 70),
    "overbought":       (70, 100),
}

STOCH_ZONES = {
    "oversold":   (0, 20),
    "neutral":    (20, 80),
    "overbought": (80, 100),
}

BB_POSITIONS = {
    "below_lower_band": (-999, 0),
    "near_lower_band":  (0, 20),
    "within_bands":     (20, 80),
    "near_upper_band":  (80, 100),
    "above_upper_band": (100, 999),
}

COMPOSITE_THRESHOLDS = {
    "BEARISH":  (-1.0, -0.3),
    "NEUTRAL":  (-0.3, 0.3),
    "BULLISH":  (0.3, 1.0),
}

CONFIDENCE_THRESHOLDS = {
    "high":   (0.6, 1.0),
    "medium": (0.3, 0.6),
    "low":    (0.0, 0.3),
}


def run_asset_checks(asset: str, ad: dict, rpt: Report):
    """Run 12 grounding checks for one asset."""
    murphy = ad.get("murphy_full", {}).get("data", {})
    rsi_out = ad.get("rsi", {}).get("data", {})
    bo_out = ad.get("breakout", {}).get("data", {})
    snap_out = ad.get("quick_snapshot", {}).get("data", {})

    rsi_m = murphy.get("6_rsi", {})
    macd = murphy.get("5_macd", {})
    bb = murphy.get("7_bollinger_bands", {})
    stoch = murphy.get("9_stochastic", {})
    ma = murphy.get("4_moving_averages", {})
    comp = murphy.get("composite_signal", {})
    trend = murphy.get("1_trend", {})
    price = murphy.get("current_price", 0)

    # ── TG-01: RSI zone label matches value ──────────────────
    rsi_val = rsi_m.get("rsi")
    rsi_zone = rsi_m.get("zone", "")
    if rsi_val is not None and rsi_zone:
        expected_range = RSI_ZONES.get(rsi_zone)
        if expected_range:
            ok = expected_range[0] <= rsi_val <= expected_range[1]
            rpt.add(Check("TG-01", asset, f"RSI zone '{rsi_zone}' matches value {rsi_val:.1f}",
                           ok,
                           f"RSI in [{expected_range[0]},{expected_range[1]}]",
                           f"{rsi_val:.2f}",
                           f"Zone '{rsi_zone}' requires RSI in {expected_range}", "high"))
        else:
            rpt.add(Check("TG-01", asset, f"RSI zone '{rsi_zone}' is known",
                           False, "known zone", rsi_zone,
                           "Unknown RSI zone label", "medium"))
    else:
        rpt.add(Check("TG-01", asset, "RSI zone grounding",
                       True, "skip", "N/A", "No RSI data", "low"))

    # ── TG-02: RSI divergence label correct ──────────────────
    divergence = rsi_m.get("divergence")
    # Divergence should be None or a string describing bearish/bullish divergence
    if divergence is not None:
        ok = isinstance(divergence, str) and \
             ("BEARISH" in divergence.upper() or "BULLISH" in divergence.upper())
        rpt.add(Check("TG-02", asset, "RSI divergence label valid",
                       ok,
                       "BEARISH_DIVERGENCE or BULLISH_DIVERGENCE", str(divergence)[:60],
                       "Divergence label should contain direction", "medium"))
    else:
        # None = no divergence, which is a valid state
        rpt.add(Check("TG-02", asset, "RSI no divergence (valid null)",
                       True, "null (no divergence)", "null",
                       "Null divergence is valid — means no divergence detected", "low"))

    # ── TG-03: Stochastic zone label matches %K ─────────────
    stoch_k = stoch.get("percent_k")
    stoch_zone = stoch.get("zone", "")
    if stoch_k is not None and stoch_zone:
        expected_range = STOCH_ZONES.get(stoch_zone)
        if expected_range:
            ok = expected_range[0] <= stoch_k <= expected_range[1]
            rpt.add(Check("TG-03", asset, f"Stochastic zone '{stoch_zone}' matches %K={stoch_k:.1f}",
                           ok,
                           f"%K in [{expected_range[0]},{expected_range[1]}]",
                           f"{stoch_k:.2f}",
                           f"Zone '{stoch_zone}' requires %K in {expected_range}", "high"))
        else:
            rpt.add(Check("TG-03", asset, f"Stochastic zone '{stoch_zone}' is known",
                           False, "known zone", stoch_zone,
                           "Unknown stochastic zone label", "medium"))
    else:
        rpt.add(Check("TG-03", asset, "Stochastic zone grounding",
                       True, "skip", "N/A", "No stochastic data", "low"))

    # ── TG-04: Stochastic crossover label correct ────────────
    stoch_xover = stoch.get("crossover", "")
    stoch_d = stoch.get("percent_d")
    if stoch_k is not None and stoch_d is not None and stoch_xover:
        if "BULLISH_CROSS" in stoch_xover.upper():
            # Bullish cross = %K crossed above %D
            ok = stoch_k >= stoch_d or abs(stoch_k - stoch_d) < 3.0
            rpt.add(Check("TG-04", asset, "Stochastic BULLISH_CROSS: %K >= %D",
                           ok,
                           f"%K({stoch_k:.1f}) >= %D({stoch_d:.1f})",
                           f"%K={stoch_k:.1f}, %D={stoch_d:.1f}",
                           "Bullish cross means %K crossed above %D", "medium"))
        elif "BEARISH_CROSS" in stoch_xover.upper():
            ok = stoch_k <= stoch_d or abs(stoch_k - stoch_d) < 3.0
            rpt.add(Check("TG-04", asset, "Stochastic BEARISH_CROSS: %K <= %D",
                           ok,
                           f"%K({stoch_k:.1f}) <= %D({stoch_d:.1f})",
                           f"%K={stoch_k:.1f}, %D={stoch_d:.1f}",
                           "Bearish cross means %K crossed below %D", "medium"))
        else:
            # Generic description
            rpt.add(Check("TG-04", asset, "Stochastic crossover label present",
                           len(stoch_xover) > 0, "non-empty", stoch_xover,
                           "Some crossover description present", "low"))
    else:
        rpt.add(Check("TG-04", asset, "Stochastic crossover grounding",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TG-05: Bollinger squeeze label matches bandwidth ─────
    squeeze = bb.get("squeeze")
    bandwidth = bb.get("bandwidth_pct")
    if squeeze is not None and bandwidth is not None:
        # Squeeze typically means bandwidth in bottom 20th percentile
        # A general rule: bandwidth < 5% is likely squeeze
        if squeeze:
            ok = bandwidth < 10  # Generous threshold
            rpt.add(Check("TG-05", asset, "BB squeeze=True with low bandwidth",
                           ok,
                           "bandwidth < 10% for squeeze",
                           f"bandwidth={bandwidth:.2f}%",
                           "Squeeze should only trigger when bandwidth is low", "medium"))
        else:
            rpt.add(Check("TG-05", asset, "BB squeeze=False (not in squeeze)",
                           True, "no squeeze", f"bandwidth={bandwidth:.2f}%",
                           "Not in squeeze is always valid", "low"))
    else:
        rpt.add(Check("TG-05", asset, "BB squeeze grounding",
                       True, "skip", "N/A", "No BB data", "low"))

    # ── TG-06: Bollinger position label matches %B ───────────
    bb_position = bb.get("position", "")
    pct_b = bb.get("percent_b")
    if bb_position and pct_b is not None:
        # Extract base position (remove parenthetical)
        base_pos = bb_position.split("(")[0].strip().lower().replace(" ", "_")
        expected_range = BB_POSITIONS.get(base_pos)
        if expected_range:
            ok = expected_range[0] <= pct_b <= expected_range[1]
            rpt.add(Check("TG-06", asset, f"BB position '{base_pos}' matches %B={pct_b:.1f}",
                           ok,
                           f"%B in [{expected_range[0]},{expected_range[1]}]",
                           f"{pct_b:.2f}",
                           f"Position '{base_pos}' requires %B in {expected_range}", "high"))
        else:
            rpt.add(Check("TG-06", asset, f"BB position '{base_pos}' is known",
                           False, "known position", base_pos,
                           f"Unknown BB position label: {bb_position}", "medium"))
    else:
        rpt.add(Check("TG-06", asset, "BB position grounding",
                       True, "skip", "N/A", "No BB data", "low"))

    # ── TG-07: MACD crossover label matches histogram sign ───
    hist = macd.get("histogram")
    xover = macd.get("crossover", "")
    if hist is not None and xover:
        if "BULLISH" in xover.upper():
            ok = hist >= 0 or abs(hist) < 0.01  # Just crossed, hist near 0
            rpt.add(Check("TG-07", asset, "MACD BULLISH crossover: hist >= 0",
                           ok,
                           "histogram >= 0 for BULLISH", f"hist={hist:.4f}",
                           "Bullish crossover means MACD > signal (positive hist)", "high"))
        elif "BEARISH" in xover.upper():
            ok = hist <= 0 or abs(hist) < 0.01
            rpt.add(Check("TG-07", asset, "MACD BEARISH crossover: hist <= 0",
                           ok,
                           "histogram <= 0 for BEARISH", f"hist={hist:.4f}",
                           "Bearish crossover means MACD < signal (negative hist)", "high"))
        elif "bullish" in xover.lower():
            # generic "bullish" label (not BULLISH_CROSS)
            ok = hist >= 0
            rpt.add(Check("TG-07", asset, "MACD bullish: hist >= 0",
                           ok, "hist >= 0", f"hist={hist:.4f}",
                           "Bullish MACD state means positive histogram", "medium"))
        elif "bearish" in xover.lower():
            ok = hist <= 0
            rpt.add(Check("TG-07", asset, "MACD bearish: hist <= 0",
                           ok, "hist <= 0", f"hist={hist:.4f}",
                           "Bearish MACD state means negative histogram", "medium"))
        else:
            rpt.add(Check("TG-07", asset, "MACD crossover label",
                           True, "skip (N/A label)", xover, "Generic label", "low"))
    else:
        rpt.add(Check("TG-07", asset, "MACD crossover grounding",
                       True, "skip", "N/A", "No MACD data", "low"))

    # ── TG-08: Trend direction label matches swing structure ─
    trend_dir = trend.get("direction", "")
    recent_high = trend.get("recent_swing_high")
    recent_low = trend.get("recent_swing_low")
    if trend_dir and price > 0 and recent_high and recent_low:
        # In uptrend: price closer to recent high; in downtrend: closer to low
        dist_high = abs(price - recent_high) / price * 100
        dist_low = abs(price - recent_low) / price * 100
        if "uptrend" in trend_dir:
            ok = dist_high < dist_low * 2  # Should be closer to highs
        elif "downtrend" in trend_dir:
            ok = dist_low < dist_high * 2  # Should be closer to lows
        else:
            ok = True  # neutral/contracting_range is always fine
        rpt.add(Check("TG-08", asset, f"Trend '{trend_dir}' matches price vs swings",
                       ok,
                       f"price position consistent with {trend_dir}",
                       f"dist_high={dist_high:.1f}%, dist_low={dist_low:.1f}%",
                       "Price should be positioned consistently with trend", "medium"))
    else:
        rpt.add(Check("TG-08", asset, "Trend direction grounding",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TG-09: MA crossover label matches SMA values ─────────
    sma50 = ma.get("sma_50")
    sma200 = ma.get("sma_200")
    xover_label = ma.get("crossover", "")
    if sma50 is not None and sma200 is not None and xover_label:
        if "bullish" in xover_label.lower() or "above" in xover_label.lower():
            ok = sma50 >= sma200
            rpt.add(Check("TG-09", asset, "MA bullish alignment: SMA50 >= SMA200",
                           ok,
                           f"SMA50({sma50:.2f}) >= SMA200({sma200:.2f})",
                           f"SMA50={sma50:.2f}, SMA200={sma200:.2f}",
                           "Bullish MA alignment means SMA50 > SMA200", "high"))
        elif "bearish" in xover_label.lower() or "below" in xover_label.lower():
            ok = sma50 <= sma200
            rpt.add(Check("TG-09", asset, "MA bearish alignment: SMA50 <= SMA200",
                           ok,
                           f"SMA50({sma50:.2f}) <= SMA200({sma200:.2f})",
                           f"SMA50={sma50:.2f}, SMA200={sma200:.2f}",
                           "Bearish MA alignment means SMA50 < SMA200", "high"))
        else:
            rpt.add(Check("TG-09", asset, "MA crossover label present",
                           len(xover_label) > 0, "non-empty", xover_label,
                           "Some MA crossover description", "low"))
    else:
        rpt.add(Check("TG-09", asset, "MA crossover grounding",
                       True, "skip", "N/A", "Missing data", "low"))

    # ── TG-10: Composite signal label matches score ──────────
    signal = comp.get("signal", "")
    score = comp.get("score")
    if signal and score is not None:
        expected_range = COMPOSITE_THRESHOLDS.get(signal)
        if expected_range:
            ok = expected_range[0] <= score <= expected_range[1]
            rpt.add(Check("TG-10", asset, f"Composite '{signal}' matches score {score:.2f}",
                           ok,
                           f"score in [{expected_range[0]},{expected_range[1]}]",
                           f"{score:.3f}",
                           f"Signal '{signal}' requires score in {expected_range}", "critical"))
        else:
            rpt.add(Check("TG-10", asset, f"Composite signal '{signal}' is known",
                           False, "BULLISH/BEARISH/NEUTRAL", signal,
                           "Unknown composite signal", "high"))
    else:
        rpt.add(Check("TG-10", asset, "Composite signal grounding",
                       True, "skip", "N/A", "No composite data", "low"))

    # ── TG-11: Confidence label matches score magnitude ──────
    confidence = comp.get("confidence", "")
    if confidence and score is not None:
        abs_score = abs(score)
        expected_range = CONFIDENCE_THRESHOLDS.get(confidence)
        if expected_range:
            ok = expected_range[0] <= abs_score <= expected_range[1]
            rpt.add(Check("TG-11", asset, f"Confidence '{confidence}' matches |score|={abs_score:.2f}",
                           ok,
                           f"|score| in [{expected_range[0]},{expected_range[1]}]",
                           f"{abs_score:.3f}",
                           f"Confidence '{confidence}' requires |score| in {expected_range}", "medium"))
        else:
            rpt.add(Check("TG-11", asset, f"Confidence '{confidence}' is known",
                           False, "high/medium/low", confidence,
                           "Unknown confidence label", "medium"))
    else:
        rpt.add(Check("TG-11", asset, "Confidence grounding",
                       True, "skip", "N/A", "No data", "low"))

    # ── TG-12: Breakout confidence matches confirmation count ─
    bo = bo_out
    bo_conf = bo.get("confidence") or ""
    snap_bo = snap_out.get("breakout", {})
    conf_str = snap_bo.get("confirmations", "")
    if bo.get("breakout_detected") and bo_conf:
        conf_map = {"HIGH": (4, 99), "MODERATE": (3, 3), "LOW": (2, 2), "WEAK": (0, 1)}
        expected = conf_map.get(bo_conf.upper())
        if expected:
            # Parse "2/4" format
            try:
                met = int(conf_str.split("/")[0]) if conf_str else 0
            except (ValueError, IndexError):
                met = 0
            ok = expected[0] <= met <= expected[1]
            rpt.add(Check("TG-12", asset, f"Breakout '{bo_conf}' matches {conf_str} confirmations",
                           ok,
                           f"{expected[0]}-{expected[1]} confirmations",
                           f"{met} confirmations",
                           f"Confidence '{bo_conf}' requires {expected}", "medium"))
        else:
            rpt.add(Check("TG-12", asset, "Breakout confidence label",
                           True, "skip (unknown label)", bo_conf, "Unknown label", "low"))
    else:
        rpt.add(Check("TG-12", asset, "Breakout confidence grounding",
                       True, "no breakout", "N/A",
                       "No breakout detected — confidence N/A", "low"))


# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Approach #9: TA Grounding")
    parser.add_argument("--input", required=True, help="Path to ta_output_v1.json")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    print("=" * 70)
    print("  APPROACH #9: TA GROUNDING (Label-to-Value Verification)")
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
    out = {"approach": "9_ta_grounding", "timestamp": datetime.now().isoformat(),
           "results": rpt.to_dict()}
    jp = _RECORDS / f"approach9_{ts}.json"
    with open(jp, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  Saved: {jp}")
    return rpt

if __name__ == "__main__":
    main()
