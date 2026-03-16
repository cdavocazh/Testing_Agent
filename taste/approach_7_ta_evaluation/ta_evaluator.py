"""
Approach 7: Technical Analysis Tool Evaluation

Verifies the 6 TA tools for:
  - Internal consistency (RSI zone matches RSI value, breakout confidence
    matches confirmations, etc.)
  - Cross-tool consistency (quick_ta_snapshot embeds RSI/S/R/breakout,
    fundamental_ta_synthesis embeds equity + TA — these should agree)
  - Signal plausibility (positions near support shouldn't be AT_RESISTANCE,
    overbought RSI shouldn't pair with BULLISH_BREAKOUT high-confidence)

Runs against live TA output for a configurable set of assets.

Usage:
    python ta_evaluator.py                          # Default assets (SPY, AAPL, gold, btc)
    python ta_evaluator.py --assets NVDA,TSLA,QQQ   # Custom assets
    python ta_evaluator.py --input ta_report.json   # Run against saved output
"""

import sys, os, json, time, argparse
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_TASTE_DIR = _THIS_DIR.parent
_TESTING_ROOT = _TASTE_DIR.parent
_RECORDS_DIR = _THIS_DIR / "records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent"),
)
sys.path.insert(0, _FA_ROOT)

DEFAULT_ASSETS = ["SPY", "AAPL", "gold", "btc"]


# ═════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═════════════════════════════════════════════════════════════════════

class TACheck:
    """A single TA evaluation result."""
    def __init__(self, check_id: str, asset: str, check_name: str,
                 passed: bool, expected, actual, detail: str,
                 severity: str = "medium"):
        self.check_id = check_id
        self.asset = asset
        self.check_name = check_name
        self.passed = passed
        self.expected = expected
        self.actual = actual
        self.detail = detail
        self.severity = severity

    def to_dict(self):
        return {
            "check_id": self.check_id,
            "asset": self.asset,
            "check_name": self.check_name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
            "severity": self.severity,
        }


class TAReport:
    """Collects all TA check results."""
    def __init__(self):
        self.checks: list[TACheck] = []
        self.start_time = time.time()

    def add(self, check: TACheck):
        self.checks.append(check)
        icon = "\u2705" if check.passed else "\u274c"
        if not check.passed:
            print(f"  {icon} [{check.severity.upper():8s}] [{check.asset:6s}] {check.check_name}")
            print(f"      Expected: {check.expected}")
            print(f"      Actual:   {check.actual}")
        else:
            print(f"  {icon} [{check.severity.upper():8s}] [{check.asset:6s}] {check.check_name}")

    @property
    def summary(self):
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        return {
            "total_checks": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": sum(
                1 for c in self.checks
                if not c.passed and c.severity in ("critical", "high")
            ),
            "elapsed": f"{time.time() - self.start_time:.1f}s",
        }

    def to_dict(self):
        return {
            "summary": self.summary,
            "failures": [c.to_dict() for c in self.checks if not c.passed],
            "all_checks": [c.to_dict() for c in self.checks],
        }


# ═════════════════════════════════════════════════════════════════════
# RSI CHECKS
# ═════════════════════════════════════════════════════════════════════

def check_rsi(asset: str, rsi_data: dict, tr: TAReport):
    """Verify RSI output internal consistency."""
    rsi_val = rsi_data.get("rsi") or rsi_data.get("rsi_14")
    zone = rsi_data.get("zone", "")
    signal = rsi_data.get("signal", "")

    if rsi_val is None:
        return

    # ── TA-R01: RSI value in [0, 100] ──
    tr.add(TACheck(
        "TA-R01", asset, "RSI in [0, 100]",
        0 <= rsi_val <= 100,
        "[0, 100]", rsi_val,
        f"RSI value must be between 0 and 100.",
        severity="critical",
    ))

    # ── TA-R02: RSI zone matches value ──
    zone_ranges = {
        "overbought": (70, 100),
        "bullish_momentum": (50, 70),
        "neutral": (40, 60),
        "bearish_momentum": (30, 50),
        "oversold": (0, 30),
    }
    expected_range = zone_ranges.get(zone.lower())
    if expected_range:
        in_range = expected_range[0] <= rsi_val <= expected_range[1]
        tr.add(TACheck(
            "TA-R02", asset, f"RSI zone '{zone}' matches value {rsi_val:.1f}",
            in_range,
            f"RSI {expected_range[0]}-{expected_range[1]} for '{zone}'", rsi_val,
            f"Zone '{zone}' expects RSI in [{expected_range[0]}, {expected_range[1]}]",
            severity="high",
        ))

    # ── TA-R03: Signal consistency ──
    if rsi_val >= 70 and "OVER" not in signal.upper() and "BEARISH" not in signal.upper():
        tr.add(TACheck(
            "TA-R03", asset, "Overbought RSI should have overbought signal",
            False,
            "OVERBOUGHT or STRONGLY_OVERBOUGHT", signal,
            f"RSI={rsi_val:.1f} is overbought but signal is '{signal}'",
            severity="medium",
        ))
    elif rsi_val <= 30 and "OVER" not in signal.upper() and "BULLISH" not in signal.upper():
        tr.add(TACheck(
            "TA-R03", asset, "Oversold RSI should have oversold signal",
            False,
            "OVERSOLD or STRONGLY_OVERSOLD", signal,
            f"RSI={rsi_val:.1f} is oversold but signal is '{signal}'",
            severity="medium",
        ))
    else:
        tr.add(TACheck(
            "TA-R03", asset, "RSI signal consistent with value",
            True,
            f"consistent with RSI={rsi_val:.1f}", signal,
            "RSI signal aligns with RSI value range.",
            severity="medium",
        ))

    # ── TA-R04: Multi-period ordering plausibility ──
    mp = rsi_data.get("multi_period", {})
    if isinstance(mp, dict) and mp:
        rsi_7 = mp.get("rsi_7")
        rsi_14 = rsi_data.get("rsi_14") or rsi_val
        rsi_21 = mp.get("rsi_21")
        if all(v is not None for v in [rsi_7, rsi_14, rsi_21]):
            all_in_range = all(0 <= v <= 100 for v in [rsi_7, rsi_14, rsi_21])
            tr.add(TACheck(
                "TA-R04", asset, "Multi-period RSI all in [0,100]",
                all_in_range,
                "all in [0, 100]", f"7={rsi_7:.1f}, 14={rsi_14:.1f}, 21={rsi_21:.1f}",
                "All RSI periods should be in valid range.",
                severity="medium",
            ))


# ═════════════════════════════════════════════════════════════════════
# SUPPORT/RESISTANCE CHECKS
# ═════════════════════════════════════════════════════════════════════

def check_support_resistance(asset: str, sr_data: dict, tr: TAReport):
    """Verify S/R output internal consistency."""
    price = sr_data.get("current_price")
    supports = sr_data.get("supports", [])
    resistances = sr_data.get("resistances", [])
    position = sr_data.get("position", "")
    nearest_support = sr_data.get("nearest_support")
    nearest_resistance = sr_data.get("nearest_resistance")

    if price is None:
        return

    # ── TA-S01: Supports are below price, resistances above ──
    supports_below = all(s < price * 1.01 for s in supports if s is not None)
    resistances_above = all(r > price * 0.99 for r in resistances if r is not None)
    tr.add(TACheck(
        "TA-S01", asset, "Supports below price, resistances above",
        supports_below and resistances_above,
        "supports < price < resistances",
        f"supports={supports[:3]}, price={price}, resistances={resistances[:3]}",
        "Support levels should be below current price, resistance levels above.",
        severity="high",
    ))

    # ── TA-S02: Nearest support < nearest resistance ──
    if nearest_support is not None and nearest_resistance is not None:
        tr.add(TACheck(
            "TA-S02", asset, "Nearest support < nearest resistance",
            nearest_support < nearest_resistance,
            f"support ({nearest_support}) < resistance ({nearest_resistance})",
            f"support={nearest_support}, resistance={nearest_resistance}",
            "Nearest support should always be below nearest resistance.",
            severity="high",
        ))

    # ── TA-S03: Position assessment plausibility ──
    if nearest_support is not None and nearest_resistance is not None and position:
        sup_dist = abs(price - nearest_support) / price * 100
        res_dist = abs(nearest_resistance - price) / price * 100

        if "AT_SUPPORT" in position.upper():
            tr.add(TACheck(
                "TA-S03", asset, f"AT_SUPPORT: distance to support < 1.5%",
                sup_dist < 1.5,
                "< 1.5% from support", f"{sup_dist:.2f}%",
                f"AT_SUPPORT requires being very close to support level.",
                severity="medium",
            ))
        elif "AT_RESISTANCE" in position.upper():
            tr.add(TACheck(
                "TA-S03", asset, f"AT_RESISTANCE: distance to resistance < 1.5%",
                res_dist < 1.5,
                "< 1.5% from resistance", f"{res_dist:.2f}%",
                f"AT_RESISTANCE requires being very close to resistance level.",
                severity="medium",
            ))
        elif "CLOSER_TO_SUPPORT" in position.upper():
            tr.add(TACheck(
                "TA-S03", asset, "CLOSER_TO_SUPPORT: sup_dist < res_dist",
                sup_dist < res_dist,
                f"support closer ({sup_dist:.1f}%) than resistance ({res_dist:.1f}%)",
                f"sup_dist={sup_dist:.1f}%, res_dist={res_dist:.1f}%",
                "Position says closer to support but resistance is actually closer.",
                severity="medium",
            ))
        elif "CLOSER_TO_RESISTANCE" in position.upper():
            tr.add(TACheck(
                "TA-S03", asset, "CLOSER_TO_RESISTANCE: res_dist < sup_dist",
                res_dist < sup_dist,
                f"resistance closer ({res_dist:.1f}%) than support ({sup_dist:.1f}%)",
                f"sup_dist={sup_dist:.1f}%, res_dist={res_dist:.1f}%",
                "Position says closer to resistance but support is actually closer.",
                severity="medium",
            ))


# ═════════════════════════════════════════════════════════════════════
# BREAKOUT CHECKS
# ═════════════════════════════════════════════════════════════════════

def check_breakout(asset: str, bo_data: dict, tr: TAReport):
    """Verify breakout analysis internal consistency."""
    detected = bo_data.get("breakout_detected", False)
    bo_type = bo_data.get("breakout_type")
    confidence = bo_data.get("confidence", "")
    confirmations_met = bo_data.get("confirmations_met", 0)
    confirmations_total = bo_data.get("confirmations_total", 4)
    false_warning = bo_data.get("false_breakout_warning", False)

    # ── TA-B01: No breakout → type should be null ──
    if not detected:
        tr.add(TACheck(
            "TA-B01", asset, "No breakout → breakout_type null",
            bo_type is None,
            "null", bo_type,
            "If breakout_detected=False, breakout_type should be null.",
            severity="medium",
        ))
    else:
        # ── TA-B02: Breakout detected → type must be set ──
        tr.add(TACheck(
            "TA-B02", asset, "Breakout detected → type set",
            bo_type is not None,
            "BULLISH_BREAKOUT or BEARISH_BREAKOUT", bo_type,
            "If breakout detected, type must be specified.",
            severity="high",
        ))

    # ── TA-B03: Confidence matches confirmation count ──
    conf_map = {"HIGH": (4, 99), "MODERATE": (3, 3), "LOW": (2, 2), "WEAK": (0, 1)}
    expected = conf_map.get(confidence.upper())
    if expected and confirmations_total > 0:
        in_range = expected[0] <= confirmations_met <= expected[1]
        tr.add(TACheck(
            "TA-B03", asset, f"Confidence '{confidence}' matches {confirmations_met}/{confirmations_total} confirmations",
            in_range,
            f"{expected[0]}-{expected[1]} confirmations for '{confidence}'",
            confirmations_met,
            f"Confidence '{confidence}' expects {expected[0]}-{expected[1]} confirmations.",
            severity="high",
        ))

    # ── TA-B04: False breakout warning → confidence should not be HIGH ──
    if false_warning and confidence.upper() == "HIGH":
        tr.add(TACheck(
            "TA-B04", asset, "False breakout warning with HIGH confidence",
            False,
            "confidence < HIGH when false_breakout_warning=True",
            f"confidence={confidence}, false_warning={false_warning}",
            "A false breakout warning contradicts HIGH confidence.",
            severity="high",
        ))


# ═════════════════════════════════════════════════════════════════════
# QUICK TA SNAPSHOT CROSS-CONSISTENCY
# ═════════════════════════════════════════════════════════════════════

def check_quick_snapshot(asset: str, snap: dict, tr: TAReport):
    """Verify quick_ta_snapshot embeds RSI/S/R/breakout consistently."""
    rsi_section = snap.get("rsi", {})
    sr_section = snap.get("support_resistance", {})
    breakout_section = snap.get("breakout", {})
    position = snap.get("position", "")
    action = snap.get("action", "")
    price = snap.get("current_price")

    if not isinstance(rsi_section, dict):
        return

    # ── TA-Q01: RSI zone consistency within snapshot ──
    rsi_val = rsi_section.get("rsi_14")
    zone = rsi_section.get("zone", "")
    if rsi_val is not None and zone:
        check_rsi(asset, {"rsi": rsi_val, "rsi_14": rsi_val, "zone": zone,
                          "signal": "", "multi_period": rsi_section}, tr)

    # ── TA-Q02: S/R data present ──
    tr.add(TACheck(
        "TA-Q02", asset, "Snapshot has S/R data",
        bool(sr_section.get("supports") or sr_section.get("resistances")),
        "supports/resistances present", sr_section,
        "Quick snapshot should include support and resistance levels.",
        severity="medium",
    ))

    # ── TA-Q03: Breakout section present ──
    tr.add(TACheck(
        "TA-Q03", asset, "Snapshot has breakout section",
        "detected" in breakout_section or "breakout_detected" in breakout_section,
        "breakout detection present", list(breakout_section.keys()),
        "Quick snapshot should include breakout detection results.",
        severity="medium",
    ))

    # ── TA-Q04: Action signal is valid enum ──
    valid_actions = {"ACTIONABLE", "CAUTION", "OPPORTUNITY", "WATCH", "NEUTRAL"}
    if action:
        tr.add(TACheck(
            "TA-Q04", asset, "Action signal is valid",
            action.upper() in valid_actions,
            valid_actions, action,
            f"Action '{action}' should be one of {valid_actions}",
            severity="medium",
        ))


# ═════════════════════════════════════════════════════════════════════
# COMPOSITE / MURPHY TA CHECKS
# ═════════════════════════════════════════════════════════════════════

def check_murphy_composite(asset: str, murphy: dict, tr: TAReport):
    """Verify murphy_technical_analysis composite signal."""
    comp = murphy.get("composite_signal", {})
    if not isinstance(comp, dict):
        return

    signal = comp.get("signal", "")
    confidence = comp.get("confidence", "")
    score = comp.get("score")
    bullish = comp.get("bullish_count", 0)
    bearish = comp.get("bearish_count", 0)
    total = comp.get("total_indicators", 0)
    breakdown = comp.get("framework_breakdown", [])

    # ── TA-M01: Signal matches score sign ──
    if score is not None:
        if score > 0 and "BEARISH" in signal.upper():
            tr.add(TACheck(
                "TA-M01", asset, "Positive score but BEARISH signal",
                False,
                "BULLISH or NEUTRAL for positive score", f"score={score}, signal={signal}",
                "Composite score > 0 should not produce BEARISH signal.",
                severity="high",
            ))
        elif score < 0 and "BULLISH" in signal.upper():
            tr.add(TACheck(
                "TA-M01", asset, "Negative score but BULLISH signal",
                False,
                "BEARISH or NEUTRAL for negative score", f"score={score}, signal={signal}",
                "Composite score < 0 should not produce BULLISH signal.",
                severity="high",
            ))
        else:
            tr.add(TACheck(
                "TA-M01", asset, "Composite signal matches score sign",
                True,
                f"consistent ({signal}, score={score})", f"{signal} / {score}",
                "Composite signal and score are consistent.",
                severity="high",
            ))

    # ── TA-M02: Confidence matches score magnitude ──
    if score is not None:
        abs_score = abs(score)
        if abs_score >= 0.6 and confidence.lower() != "high":
            tr.add(TACheck(
                "TA-M02", asset, "Strong score should have high confidence",
                False,
                "high", confidence,
                f"Score magnitude {abs_score:.2f} ≥ 0.6 should be 'high' confidence.",
                severity="medium",
            ))
        elif abs_score < 0.3 and confidence.lower() == "high":
            tr.add(TACheck(
                "TA-M02", asset, "Weak score should not have high confidence",
                False,
                "low or medium", confidence,
                f"Score magnitude {abs_score:.2f} < 0.3 should not be 'high' confidence.",
                severity="medium",
            ))
        else:
            tr.add(TACheck(
                "TA-M02", asset, "Confidence matches score magnitude",
                True,
                f"consistent (score={score:.2f}, conf={confidence})",
                f"{confidence}",
                "Confidence level aligns with score magnitude.",
                severity="medium",
            ))

    # ── TA-M03: Bullish + bearish ≤ total ──
    if total > 0:
        tr.add(TACheck(
            "TA-M03", asset, "bullish + bearish ≤ total indicators",
            bullish + bearish <= total,
            f"≤ {total}", f"{bullish} + {bearish} = {bullish + bearish}",
            "Sum of bullish and bearish counts should not exceed total.",
            severity="medium",
        ))

    # ── TA-M04: Framework breakdown has entries ──
    tr.add(TACheck(
        "TA-M04", asset, "Framework breakdown populated",
        isinstance(breakdown, list) and len(breakdown) >= 5,
        "≥ 5 framework entries", f"{len(breakdown)} entries",
        "Murphy TA should have at least 5 framework evaluations.",
        severity="low",
    ))


# ═════════════════════════════════════════════════════════════════════
# FUNDAMENTAL-TA SYNTHESIS CHECKS
# ═════════════════════════════════════════════════════════════════════

def check_fundamental_synthesis(asset: str, synth: dict, tr: TAReport):
    """Verify fundamental_ta_synthesis alignment logic."""
    fund = synth.get("fundamental", {})
    tech = synth.get("technical", {})
    synthesis = synth.get("synthesis", {})

    if not isinstance(synthesis, dict):
        return

    alignment = synthesis.get("alignment", "")
    conviction = synthesis.get("conviction", "")
    fund_signal = fund.get("signal", "") if isinstance(fund, dict) else ""
    tech_signal = tech.get("signal", "") if isinstance(tech, dict) else ""

    # ── TA-F01: Alignment matches component signals ──
    if fund_signal and tech_signal and alignment:
        fund_bull = "BULL" in fund_signal.upper()
        tech_bull = "BULL" in tech_signal.upper()
        fund_bear = "BEAR" in fund_signal.upper()
        tech_bear = "BEAR" in tech_signal.upper()

        if fund_bull and tech_bull:
            expected_alignment = "ALIGNED_BULLISH"
        elif fund_bear and tech_bear:
            expected_alignment = "ALIGNED_BEARISH"
        elif fund_bull and tech_bear:
            expected_alignment = "DIVERGENT_FUND_BULLISH"
        elif fund_bear and tech_bull:
            expected_alignment = "DIVERGENT_TA_BULLISH"
        else:
            expected_alignment = "NEUTRAL"

        tr.add(TACheck(
            "TA-F01", asset, "Synthesis alignment matches component signals",
            alignment.upper() == expected_alignment,
            expected_alignment, alignment,
            f"fund={fund_signal}, tech={tech_signal} → expected {expected_alignment}",
            severity="high",
        ))

    # ── TA-F02: Aligned signals → higher conviction than divergent ──
    if "ALIGNED" in alignment.upper() and conviction.upper() == "LOW":
        tr.add(TACheck(
            "TA-F02", asset, "Aligned signals should not have LOW conviction",
            False,
            "MODERATE or HIGH", conviction,
            "When fundamentals and technicals align, conviction should be at least MODERATE.",
            severity="medium",
        ))
    elif "DIVERGENT" in alignment.upper() and conviction.upper() == "HIGH":
        tr.add(TACheck(
            "TA-F02", asset, "Divergent signals should not have HIGH conviction",
            False,
            "MODERATE or LOW", conviction,
            "When fundamentals and technicals diverge, conviction should not be HIGH.",
            severity="medium",
        ))
    else:
        tr.add(TACheck(
            "TA-F02", asset, "Conviction appropriate for alignment",
            True,
            f"consistent (alignment={alignment}, conviction={conviction})",
            conviction,
            "Conviction level matches alignment type.",
            severity="medium",
        ))

    # ── TA-F03: Conviction is valid enum ──
    valid_convictions = {"HIGH", "MODERATE", "LOW"}
    if conviction:
        tr.add(TACheck(
            "TA-F03", asset, "Conviction is valid enum",
            conviction.upper() in valid_convictions,
            valid_convictions, conviction,
            f"Conviction '{conviction}' should be one of {valid_convictions}",
            severity="low",
        ))


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_ta_data(assets: list[str]) -> dict:
    """Run TA tools against each asset and collect outputs."""
    from tools.murphy_ta import (
        murphy_technical_analysis, calculate_rsi,
        find_support_resistance, analyze_breakout,
        quick_ta_snapshot, fundamental_ta_synthesis,
    )

    results = {}
    for asset in assets:
        print(f"\n  Collecting TA data for {asset}...")
        asset_data = {}

        # RSI
        try:
            raw = calculate_rsi(asset)
            asset_data["rsi"] = json.loads(raw)
            print(f"    calculate_rsi: OK")
        except Exception as e:
            print(f"    calculate_rsi: FAILED ({e})")

        # Support/Resistance
        try:
            raw = find_support_resistance(asset)
            asset_data["support_resistance"] = json.loads(raw)
            print(f"    find_support_resistance: OK")
        except Exception as e:
            print(f"    find_support_resistance: FAILED ({e})")

        # Breakout
        try:
            raw = analyze_breakout(asset)
            asset_data["breakout"] = json.loads(raw)
            print(f"    analyze_breakout: OK")
        except Exception as e:
            print(f"    analyze_breakout: FAILED ({e})")

        # Quick snapshot
        try:
            raw = quick_ta_snapshot(asset)
            asset_data["quick_snapshot"] = json.loads(raw)
            print(f"    quick_ta_snapshot: OK")
        except Exception as e:
            print(f"    quick_ta_snapshot: FAILED ({e})")

        # Murphy full TA (expensive — only for first asset or equity assets)
        if asset.isupper() and len(asset) <= 5:
            try:
                raw = murphy_technical_analysis(asset)
                asset_data["murphy"] = json.loads(raw)
                print(f"    murphy_technical_analysis: OK")
            except Exception as e:
                print(f"    murphy_technical_analysis: FAILED ({e})")

        # Fundamental-TA synthesis (only for equity tickers)
        if asset.isupper() and len(asset) <= 5 and asset not in ("SPY", "QQQ", "DIA"):
            try:
                raw = fundamental_ta_synthesis(asset)
                asset_data["fundamental_synthesis"] = json.loads(raw)
                print(f"    fundamental_ta_synthesis: OK")
            except Exception as e:
                print(f"    fundamental_ta_synthesis: FAILED ({e})")

        results[asset] = asset_data

    return results


# ═════════════════════════════════════════════════════════════════════
# RUN ALL CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_ta_checks(ta_data: dict) -> TAReport:
    """Run all TA checks across all assets."""
    tr = TAReport()

    for asset, data in ta_data.items():
        print(f"\n{'─' * 70}")
        print(f"  Checking: {asset}")
        print(f"{'─' * 70}")

        if "rsi" in data:
            check_rsi(asset, data["rsi"], tr)

        if "support_resistance" in data:
            check_support_resistance(asset, data["support_resistance"], tr)

        if "breakout" in data:
            check_breakout(asset, data["breakout"], tr)

        if "quick_snapshot" in data:
            check_quick_snapshot(asset, data["quick_snapshot"], tr)

        if "murphy" in data:
            check_murphy_composite(asset, data["murphy"], tr)

        if "fundamental_synthesis" in data:
            check_fundamental_synthesis(asset, data["fundamental_synthesis"], tr)

    return tr


# ═════════════════════════════════════════════════════════════════════
# RECORDS
# ═════════════════════════════════════════════════════════════════════

def save_record(tr: TAReport, ta_data: dict) -> Path:
    """Save TA evaluation results."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    record = {
        "timestamp": datetime.now().isoformat(),
        "assets": list(ta_data.keys()),
        "results": tr.to_dict(),
    }
    path = _RECORDS_DIR / f"ta_eval_{ts}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Record saved: {path}")

    # Markdown
    md = generate_markdown(tr)
    md_path = _RECORDS_DIR / f"ta_eval_{ts}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")
    return path


def generate_markdown(tr: TAReport) -> str:
    """Generate markdown report."""
    s = tr.summary
    failures = [c for c in tr.checks if not c.passed]
    lines = [
        "# TA Tool Evaluation Report",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Checks**: {s['total_checks']} | **Passed**: {s['passed']} | "
        f"**Failed**: {s['failed']} | **Rate**: {s['pass_rate']}",
        "",
    ]
    if failures:
        lines.append("## Failures\n")
        for c in failures:
            lines.append(f"### {c.check_id} [{c.asset}]: {c.check_name} [{c.severity.upper()}]\n")
            lines.append(f"- **Expected**: {c.expected}")
            lines.append(f"- **Actual**: {c.actual}")
            lines.append(f"- **Detail**: {c.detail}")
            lines.append("")

    lines.append("\n## All Checks\n")
    lines.append("| ID | Asset | Check | Status | Severity |")
    lines.append("|----|-------|-------|--------|----------|")
    for c in tr.checks:
        icon = "\u2705" if c.passed else "\u274c"
        name = c.check_name[:55] + "..." if len(c.check_name) > 55 else c.check_name
        lines.append(f"| {c.check_id} | {c.asset} | {name} | {icon} | {c.severity} |")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approach 7: TA Tool Evaluation")
    parser.add_argument("--assets", type=str, default=",".join(DEFAULT_ASSETS),
                        help="Comma-separated assets (default: SPY,AAPL,gold,btc)")
    parser.add_argument("--input", type=str, help="Path to saved TA report JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 7: TECHNICAL ANALYSIS TOOL EVALUATION")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if args.input:
        with open(args.input) as f:
            ta_data = json.load(f)
        print(f"\n  Loaded from: {args.input}")
    else:
        assets = [a.strip() for a in args.assets.split(",")]
        ta_data = collect_ta_data(assets)

    tr = run_ta_checks(ta_data)

    # Summary
    s = tr.summary
    print(f"\n{'=' * 70}")
    print(f"  TA EVALUATION RESULTS")
    print(f"  Checks: {s['total_checks']} | Passed: {s['passed']} | "
          f"Failed: {s['failed']} | Rate: {s['pass_rate']}")
    if s['critical_failures'] > 0:
        print(f"  \u26a0\ufe0f  Critical/High failures: {s['critical_failures']}")
    print(f"{'=' * 70}")

    save_record(tr, ta_data)
