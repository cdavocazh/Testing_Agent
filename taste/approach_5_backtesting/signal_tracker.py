"""
Approach 5: Forward-Looking Signal Backtesting

Tracks every directional signal the Financial Agent generates and later
checks what actually happened. Did INFLATION_COOLING correspond to a
real CPI decrease? Did ISM_CONTRACTION persist?

Workflow:
    1. SNAPSHOT: Run /full_report, capture all signals with timestamp
    2. WAIT: 1-4-12 weeks
    3. VERIFY: Pull actual data, compare against predicted direction
    4. SCORE: Compute per-signal precision/recall/F1

This module handles all four phases. Start by taking snapshots regularly,
then run verification after sufficient time has passed.

Usage:
    python signal_tracker.py snapshot                        # Take snapshot from live agent
    python signal_tracker.py snapshot --input report.json    # Snapshot from saved JSON
    python signal_tracker.py verify                          # Verify all matured snapshots
    python signal_tracker.py verify --horizon 4w             # Verify at 4-week horizon
    python signal_tracker.py report                          # Generate accuracy report
    python signal_tracker.py status                          # Show snapshot inventory
"""

import sys, os, json, time, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── Path setup ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_TASTE_DIR = _THIS_DIR.parent
_TESTING_ROOT = _TASTE_DIR.parent
_RECORDS_DIR = _THIS_DIR / "records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
_SNAPSHOTS_DIR = _RECORDS_DIR / "snapshots"
_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
_VERIFICATIONS_DIR = _RECORDS_DIR / "verifications"
_VERIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)

_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent")
)
sys.path.insert(0, _FA_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_TESTING_ROOT, ".env"))
_fa_env = os.path.join(_FA_ROOT, ".env")
if os.path.exists(_fa_env):
    load_dotenv(_fa_env, override=False)


# ═════════════════════════════════════════════════════════════════════
# SIGNAL DEFINITIONS — What each signal predicts & how to verify
# ═════════════════════════════════════════════════════════════════════

SIGNAL_DEFINITIONS = {
    # ── Inflation signals ──
    "INFLATION_HOT": {
        "category": "inflation",
        "direction": "up",
        "description": "Inflation is running above target",
        "verification": {
            "metric": "CPI YoY",
            "condition": "next CPI print > current or stays above 3%",
            "horizon_weeks": [4, 12],
            "fred_series": "CPIAUCSL",
        },
    },
    "INFLATION_COOLING": {
        "category": "inflation",
        "direction": "down",
        "description": "Inflation is cooling toward target",
        "verification": {
            "metric": "CPI YoY",
            "condition": "next CPI print < current or moves toward 2%",
            "horizon_weeks": [4, 12],
            "fred_series": "CPIAUCSL",
        },
    },
    "INFLATION_STABLE": {
        "category": "inflation",
        "direction": "neutral",
        "description": "Inflation is anchored near target",
        "verification": {
            "metric": "CPI YoY",
            "condition": "CPI stays within 1.5-2.5%",
            "horizon_weeks": [4, 12],
            "fred_series": "CPIAUCSL",
        },
    },

    # ── Growth signals ──
    "GROWTH_EXPANSION": {
        "category": "growth",
        "direction": "up",
        "description": "Economy expanding (ISM > 50)",
        "verification": {
            "metric": "ISM Manufacturing PMI",
            "condition": "ISM stays above 50",
            "horizon_weeks": [4],
            "fred_series": "MANEMP",
        },
    },
    "GROWTH_SLOWING": {
        "category": "growth",
        "direction": "down",
        "description": "Growth decelerating",
        "verification": {
            "metric": "ISM Manufacturing PMI",
            "condition": "ISM moves toward or below 50",
            "horizon_weeks": [4, 12],
        },
    },
    "GROWTH_CONTRACTION": {
        "category": "growth",
        "direction": "down",
        "description": "ISM in contraction territory (<50)",
        "verification": {
            "metric": "ISM Manufacturing PMI",
            "condition": "ISM stays below 50 or GDP growth turns negative",
            "horizon_weeks": [4, 12],
        },
    },
    "ISM_CONTRACTION": {
        "category": "growth",
        "direction": "down",
        "description": "ISM Manufacturing below 50",
        "verification": {
            "metric": "ISM Manufacturing PMI",
            "condition": "ISM remains below 50",
            "horizon_weeks": [4],
        },
    },

    # ── Labor signals ──
    "LABOR_TIGHT": {
        "category": "labor",
        "direction": "strong",
        "description": "Labor market is tight (low unemployment)",
        "verification": {
            "metric": "Unemployment Rate",
            "condition": "unemployment stays below 4.5%",
            "horizon_weeks": [4, 12],
            "fred_series": "UNRATE",
        },
    },
    "LABOR_LOOSENING": {
        "category": "labor",
        "direction": "weakening",
        "description": "Labor market loosening",
        "verification": {
            "metric": "Unemployment Rate",
            "condition": "unemployment rises or claims increase",
            "horizon_weeks": [4, 12],
            "fred_series": "UNRATE",
        },
    },

    # ── Fed policy signals ──
    "FED_TIGHTENING": {
        "category": "fed_policy",
        "direction": "hawkish",
        "description": "Fed in tightening mode",
        "verification": {
            "metric": "Fed Funds Rate",
            "condition": "rates stay elevated or increase",
            "horizon_weeks": [4, 12],
            "fred_series": "FEDFUNDS",
        },
    },
    "FED_EASING": {
        "category": "fed_policy",
        "direction": "dovish",
        "description": "Fed in easing mode",
        "verification": {
            "metric": "Fed Funds Rate",
            "condition": "rates decrease or cuts announced",
            "horizon_weeks": [4, 12],
            "fred_series": "FEDFUNDS",
        },
    },
    "FED_NEUTRAL": {
        "category": "fed_policy",
        "direction": "neutral",
        "description": "Fed in hold/neutral stance",
        "verification": {
            "metric": "Fed Funds Rate",
            "condition": "rates unchanged",
            "horizon_weeks": [4],
            "fred_series": "FEDFUNDS",
        },
    },
    "FED_RESTRICTIVE": {
        "category": "fed_policy",
        "direction": "hawkish",
        "description": "Monetary policy is restrictive",
        "verification": {
            "metric": "Fed Funds Rate",
            "condition": "real policy rate positive and above neutral",
            "horizon_weeks": [4, 12],
        },
    },

    # ── Credit signals ──
    "CREDIT_LOOSE": {
        "category": "credit",
        "direction": "easy",
        "description": "Credit conditions loose (tight spreads)",
        "verification": {
            "metric": "HY OAS",
            "condition": "HY OAS stays below 300bps",
            "horizon_weeks": [4],
            "fred_series": "BAMLH0A0HYM2",
        },
    },
    "CREDIT_TIGHT": {
        "category": "credit",
        "direction": "tight",
        "description": "Credit conditions tightening",
        "verification": {
            "metric": "HY OAS",
            "condition": "HY OAS stays above 400bps or widens further",
            "horizon_weeks": [4, 12],
            "fred_series": "BAMLH0A0HYM2",
        },
    },
    "CREDIT_STRESS": {
        "category": "credit",
        "direction": "stress",
        "description": "Credit markets under stress",
        "verification": {
            "metric": "HY OAS",
            "condition": "HY OAS remains elevated or default rates rise",
            "horizon_weeks": [4, 12],
        },
    },

    # ── Volatility signals ──
    "VIX_HOME_RUN": {
        "category": "volatility",
        "direction": "elevated",
        "description": "VIX 20-25 range (buying opportunity)",
        "verification": {
            "metric": "VIX",
            "condition": "VIX mean-reverts lower (buying opportunity confirmed)",
            "horizon_weeks": [1, 4],
        },
    },
    "VIX_CAREER_PNL": {
        "category": "volatility",
        "direction": "high",
        "description": "VIX 25-35 (major buying opportunity)",
        "verification": {
            "metric": "VIX",
            "condition": "VIX reverts, SPX higher in 4 weeks",
            "horizon_weeks": [1, 4],
        },
    },
    "VIX_COMPLACENCY": {
        "category": "volatility",
        "direction": "low",
        "description": "VIX unusually low (<12)",
        "verification": {
            "metric": "VIX",
            "condition": "VIX eventually spikes or SPX corrects",
            "horizon_weeks": [4, 12],
        },
    },

    # ── Breakeven signals ──
    "BREAKEVEN_RISING": {
        "category": "inflation",
        "direction": "up",
        "description": "Inflation expectations rising",
        "verification": {
            "metric": "Breakeven inflation",
            "condition": "breakevens stay elevated or rise further",
            "horizon_weeks": [4, 12],
        },
    },
    "BREAKEVEN_FALLING": {
        "category": "inflation",
        "direction": "down",
        "description": "Inflation expectations falling",
        "verification": {
            "metric": "Breakeven inflation",
            "condition": "breakevens continue to decline",
            "horizon_weeks": [4, 12],
        },
    },
    "BREAKEVEN_MIXED": {
        "category": "inflation",
        "direction": "neutral",
        "description": "Breakeven inflation signals mixed across tenors",
        "verification": {
            "metric": "Breakeven inflation",
            "condition": "breakevens remain range-bound",
            "horizon_weeks": [4],
        },
    },

    # ── Curve signals ──
    "CURVE_INVERSION_WARNING": {
        "category": "rates",
        "direction": "inverted",
        "description": "Yield curve inverted (10Y-2Y < 0)",
        "verification": {
            "metric": "10Y-2Y Spread",
            "condition": "recession follows within 6-18 months OR curve un-inverts",
            "horizon_weeks": [12, 52],
            "fred_series": "T10Y2Y",
        },
    },
    "CURVE_STEEPENING": {
        "category": "rates",
        "direction": "steepening",
        "description": "Yield curve steepening",
        "verification": {
            "metric": "10Y-2Y Spread",
            "condition": "spread continues to widen",
            "horizon_weeks": [4, 12],
        },
    },

    # ── Regime signals ──
    "RISK_OFF_REGIME": {
        "category": "regime",
        "direction": "risk_off",
        "description": "Risk-off conditions prevailing",
        "verification": {
            "metric": "SPX returns",
            "condition": "equities flat/negative, bonds rally, gold up",
            "horizon_weeks": [1, 4],
        },
    },
    "FLIGHT_TO_SAFETY": {
        "category": "regime",
        "direction": "risk_off",
        "description": "Capital flowing to safe havens",
        "verification": {
            "metric": "Treasury yields",
            "condition": "yields decline or gold rises",
            "horizon_weeks": [1, 4],
        },
    },

    # ── Housing signals ──
    "HOUSING_WEAK": {
        "category": "housing",
        "direction": "down",
        "description": "Housing market showing weakness",
        "verification": {
            "metric": "Existing home sales, housing starts",
            "condition": "housing data continues to weaken",
            "horizon_weeks": [4, 12],
            "fred_series": "EXHOSLUSM495S",
        },
    },
    "SALES_PLUNGING": {
        "category": "housing",
        "direction": "down",
        "description": "Existing home sales plunging",
        "verification": {
            "metric": "Existing home sales",
            "condition": "sales remain depressed or decline further",
            "horizon_weeks": [4, 12],
        },
    },
    "EXISTING_SALES_PLUNGING": {
        "category": "housing",
        "direction": "down",
        "description": "Existing home sales plunging",
        "verification": {
            "metric": "Existing home sales",
            "condition": "sales remain depressed or decline further",
            "horizon_weeks": [4, 12],
        },
    },
    "AFFORDABILITY_STRESSED": {
        "category": "housing",
        "direction": "down",
        "description": "Housing affordability under stress",
        "verification": {
            "metric": "Mortgage rate, median price",
            "condition": "affordability metrics remain stressed",
            "horizon_weeks": [4, 12],
        },
    },
    "HOUSING_LEADING_DOWNTURN": {
        "category": "housing",
        "direction": "down",
        "description": "Housing leading indicators signaling downturn",
        "verification": {
            "metric": "Permits, starts",
            "condition": "leading indicators continue declining",
            "horizon_weeks": [4, 12],
        },
    },
    "HOUSING_CAUTION": {
        "category": "housing",
        "direction": "down",
        "description": "Housing caution — demand-side weakness",
        "verification": {
            "metric": "Existing home sales, permits, starts",
            "condition": "housing weakness persists",
            "horizon_weeks": [4, 12],
        },
    },

    # ── Equity-specific signals ──
    "EQUITY_RISK_PREMIUM_LOW": {
        "category": "equity",
        "direction": "expensive",
        "description": "Equity risk premium compressed",
        "verification": {
            "metric": "ERP (earnings yield - 10Y)",
            "condition": "equities underperform or ERP widens",
            "horizon_weeks": [12],
        },
    },
    "EQUITY_RISK_PREMIUM_HIGH": {
        "category": "equity",
        "direction": "cheap",
        "description": "Equity risk premium elevated (attractive)",
        "verification": {
            "metric": "ERP",
            "condition": "equities outperform or ERP narrows",
            "horizon_weeks": [12],
        },
    },
    "REAL_YIELD_HEADWIND": {
        "category": "equity",
        "direction": "negative",
        "description": "Rising real yields pressuring equities",
        "verification": {
            "metric": "Real yield and SPX",
            "condition": "if real yields keep rising, SPX struggles",
            "horizon_weeks": [4, 12],
        },
    },
    "REAL_YIELD_TAILWIND": {
        "category": "equity",
        "direction": "positive",
        "description": "Falling real yields supporting equities",
        "verification": {
            "metric": "Real yield and SPX",
            "condition": "falling real yields coincide with SPX gains",
            "horizon_weeks": [4, 12],
        },
    },
}


# ═════════════════════════════════════════════════════════════════════
# SNAPSHOT — Capture current signals
# ═════════════════════════════════════════════════════════════════════

def take_snapshot(report_data: dict) -> dict:
    """Extract all signals from a /full_report and create a snapshot."""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
        "signals": [],
        "key_metrics": {},
        "verification_status": "pending",  # pending, partially_verified, verified
    }

    # Extract signals from all tools
    all_signals = set()
    for tool_name, data in report_data.items():
        if not isinstance(data, dict):
            continue
        for s in data.get("signals", []):
            if isinstance(s, str):
                all_signals.add(s)
                signal_def = SIGNAL_DEFINITIONS.get(s, {})
                snapshot["signals"].append({
                    "signal": s,
                    "source_tool": tool_name,
                    "category": signal_def.get("category", "unknown"),
                    "direction": signal_def.get("direction", "unknown"),
                    "description": signal_def.get("description", s),
                    "known_signal": s in SIGNAL_DEFINITIONS,
                    "verification_horizons": signal_def.get("verification", {}).get("horizon_weeks", []),
                })

    # Capture key metrics at snapshot time for later comparison
    stress = report_data.get("analyze_financial_stress", {})
    regime = report_data.get("analyze_macro_regime", {})
    equity = report_data.get("analyze_equity_drivers", {})
    bond = report_data.get("analyze_bond_market", {})
    consumer = report_data.get("analyze_consumer_health", {})
    late = report_data.get("detect_late_cycle_signals", {})
    scan = report_data.get("scan_all_indicators", {})

    # Stress
    snapshot["key_metrics"]["stress_score"] = stress.get("composite_score")
    snapshot["key_metrics"]["stress_level"] = stress.get("stress_level")

    # VIX
    vix_comp = stress.get("components", {}).get("vix", {})
    if isinstance(vix_comp, dict):
        snapshot["key_metrics"]["vix"] = vix_comp.get("value")

    # Late-cycle
    snapshot["key_metrics"]["late_cycle_count"] = late.get("count")
    snapshot["key_metrics"]["late_cycle_confidence"] = late.get("confidence_level")

    # Credit
    cel = equity.get("credit_equity_link", {})
    if isinstance(cel, dict):
        snapshot["key_metrics"]["hy_oas_bps"] = cel.get("hy_oas_bps")

    # Real yield
    ryi = equity.get("real_yield_impact", {})
    if isinstance(ryi, dict):
        snapshot["key_metrics"]["real_yield_10y"] = ryi.get("real_yield_10y")

    # Inflation
    inf_detail = regime.get("inflation_detail", {})
    cpi_data = inf_detail.get("cpi", {}) if isinstance(inf_detail, dict) else {}
    if isinstance(cpi_data, dict):
        snapshot["key_metrics"]["cpi_yoy"] = cpi_data.get("latest_value")

    # Consumer
    snapshot["key_metrics"]["consumer_health_score"] = consumer.get("composite_score")

    # Regime + fed funds rate
    regimes = regime.get("regimes", {})
    for k, v in regimes.items():
        if isinstance(v, dict):
            snapshot["key_metrics"][f"regime_{k}"] = v.get("classification", str(v))
            if k == "rates":
                ff = v.get("fed_funds", v.get("value"))
                if ff is not None:
                    snapshot["key_metrics"]["fed_funds_rate"] = ff
        else:
            snapshot["key_metrics"][f"regime_{k}"] = v

    # Breakeven inflation
    bond_data = report_data.get("analyze_bond_market", {})
    be_data = bond_data.get("breakevens", {})
    if isinstance(be_data, dict):
        for k, v in be_data.items():
            if "10" in str(k) and isinstance(v, dict):
                be_val = v.get("latest", v.get("value"))
                if be_val is not None:
                    snapshot["key_metrics"]["breakeven_10y"] = be_val
                break

    # Market prices from scan
    for ind in scan.get("flagged_indicators", []):
        if isinstance(ind, dict):
            key = ind.get("key", "")
            if key in ("es_futures", "gold", "crude_oil", "dxy"):
                snapshot["key_metrics"][f"price_{key}"] = ind.get("latest")

    # Summary
    snapshot["summary"] = {
        "total_signals": len(snapshot["signals"]),
        "known_signals": sum(1 for s in snapshot["signals"] if s["known_signal"]),
        "unknown_signals": sum(1 for s in snapshot["signals"] if not s["known_signal"]),
        "categories": dict(sorted(
            defaultdict(int, {s["category"]: 0 for s in snapshot["signals"]}).items()
        )),
    }
    # Count per category
    for s in snapshot["signals"]:
        snapshot["summary"]["categories"][s["category"]] = (
            snapshot["summary"]["categories"].get(s["category"], 0) + 1
        )

    return snapshot


def save_snapshot(snapshot: dict) -> Path:
    """Save a signal snapshot to the snapshots directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _SNAPSHOTS_DIR / f"snapshot_{ts}.json"
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"  Snapshot saved: {path}")
    return path


# ═════════════════════════════════════════════════════════════════════
# VERIFY — Check signal outcomes against actual data
# ═════════════════════════════════════════════════════════════════════

def load_snapshots() -> list[dict]:
    """Load all saved snapshots, sorted by date."""
    snapshots = []
    for f in sorted(_SNAPSHOTS_DIR.glob("snapshot_*.json")):
        with open(f) as fh:
            snap = json.load(fh)
            snap["_path"] = str(f)
            snapshots.append(snap)
    return snapshots


def get_matured_snapshots(horizon_weeks: int = 4) -> list[dict]:
    """Get snapshots that are old enough to verify at the given horizon."""
    cutoff = datetime.now() - timedelta(weeks=horizon_weeks)
    matured = []
    for snap in load_snapshots():
        snap_date = datetime.fromisoformat(snap["timestamp"])
        if snap_date < cutoff:
            matured.append(snap)
    return matured


def verify_snapshot(old_snapshot: dict, current_data: dict,
                    horizon_weeks: int) -> dict:
    """Compare an old snapshot's signals against current reality.

    This is a *directional* verification:
    - INFLATION_HOT at snapshot → did CPI stay elevated or rise?
    - GROWTH_CONTRACTION at snapshot → did growth continue to weaken?

    Returns verification results with per-signal outcomes.
    """
    verification = {
        "snapshot_date": old_snapshot.get("snapshot_date"),
        "verification_date": datetime.now().strftime("%Y-%m-%d"),
        "horizon_weeks": horizon_weeks,
        "signal_outcomes": [],
    }

    old_metrics = old_snapshot.get("key_metrics", {})

    # Current metrics from current_data
    cur_stress = current_data.get("analyze_financial_stress", {})
    cur_regime = current_data.get("analyze_macro_regime", {})
    cur_equity = current_data.get("analyze_equity_drivers", {})
    cur_scan = current_data.get("scan_all_indicators", {})

    cur_metrics = {}
    cur_metrics["stress_score"] = cur_stress.get("composite_score")
    vix_comp = cur_stress.get("components", {}).get("vix", {})
    if isinstance(vix_comp, dict):
        cur_metrics["vix"] = vix_comp.get("value")
    cel = cur_equity.get("credit_equity_link", {})
    if isinstance(cel, dict):
        cur_metrics["hy_oas_bps"] = cel.get("hy_oas_bps")
    ryi = cur_equity.get("real_yield_impact", {})
    if isinstance(ryi, dict):
        cur_metrics["real_yield_10y"] = ryi.get("real_yield_10y")
    inf_detail = cur_regime.get("inflation_detail", {})
    cpi_data = inf_detail.get("cpi", {}) if isinstance(inf_detail, dict) else {}
    if isinstance(cpi_data, dict):
        cur_metrics["cpi_yoy"] = cpi_data.get("latest_value")
    for ind in cur_scan.get("flagged_indicators", []):
        if isinstance(ind, dict):
            key = ind.get("key", "")
            if key in ("es_futures", "gold", "crude_oil"):
                cur_metrics[f"price_{key}"] = ind.get("latest")

    # Verify each signal
    for sig_entry in old_snapshot.get("signals", []):
        signal_name = sig_entry.get("signal", "")
        sig_def = SIGNAL_DEFINITIONS.get(signal_name, {})

        outcome = {
            "signal": signal_name,
            "category": sig_entry.get("category", "unknown"),
            "direction": sig_entry.get("direction", "unknown"),
            "outcome": "unverifiable",  # correct, incorrect, inconclusive, unverifiable
            "evidence": "",
        }

        # Inflation signals
        if signal_name in ("INFLATION_HOT", "INFLATION_COOLING", "INFLATION_STABLE"):
            old_cpi = old_metrics.get("cpi_yoy")
            cur_cpi = cur_metrics.get("cpi_yoy")
            if old_cpi is not None and cur_cpi is not None:
                delta = cur_cpi - old_cpi
                if signal_name == "INFLATION_HOT":
                    outcome["outcome"] = "correct" if cur_cpi > 3.0 or delta > 0 else "incorrect"
                elif signal_name == "INFLATION_COOLING":
                    outcome["outcome"] = "correct" if delta < 0 or cur_cpi < old_cpi else "incorrect"
                elif signal_name == "INFLATION_STABLE":
                    outcome["outcome"] = "correct" if abs(delta) < 0.3 else "incorrect"
                outcome["evidence"] = f"CPI: {old_cpi:.2f}% -> {cur_cpi:.2f}% (delta={delta:+.2f})"

        # Growth signals
        elif signal_name in ("GROWTH_CONTRACTION", "ISM_CONTRACTION"):
            # Can check if stress increased or growth regime deteriorated
            old_stress = old_metrics.get("stress_score")
            cur_stress_val = cur_metrics.get("stress_score")
            if old_stress is not None and cur_stress_val is not None:
                outcome["outcome"] = "correct" if cur_stress_val >= old_stress else "inconclusive"
                outcome["evidence"] = f"Stress: {old_stress:.1f} -> {cur_stress_val:.1f}"

        # VIX signals
        elif signal_name in ("VIX_HOME_RUN", "VIX_CAREER_PNL"):
            old_vix = old_metrics.get("vix")
            cur_vix = cur_metrics.get("vix")
            old_es = old_metrics.get("price_es_futures")
            cur_es = cur_metrics.get("price_es_futures")
            if old_vix and cur_vix:
                vix_declined = cur_vix < old_vix
                es_up = (cur_es or 0) > (old_es or 0) if old_es and cur_es else None
                if vix_declined and es_up:
                    outcome["outcome"] = "correct"
                elif not vix_declined:
                    outcome["outcome"] = "incorrect"
                else:
                    outcome["outcome"] = "inconclusive"
                outcome["evidence"] = (
                    f"VIX: {old_vix:.1f} -> {cur_vix:.1f}, "
                    f"ES: {old_es} -> {cur_es}"
                )

        # Credit signals
        elif signal_name in ("CREDIT_LOOSE", "CREDIT_TIGHT", "CREDIT_STRESS"):
            old_oas = old_metrics.get("hy_oas_bps")
            cur_oas = cur_metrics.get("hy_oas_bps")
            if old_oas is not None and cur_oas is not None:
                if signal_name == "CREDIT_LOOSE":
                    outcome["outcome"] = "correct" if cur_oas < 300 else "incorrect"
                elif signal_name in ("CREDIT_TIGHT", "CREDIT_STRESS"):
                    outcome["outcome"] = "correct" if cur_oas > 350 else "incorrect"
                outcome["evidence"] = f"HY OAS: {old_oas} -> {cur_oas} bps"

        # Real yield signals
        elif signal_name == "REAL_YIELD_HEADWIND":
            old_ry = old_metrics.get("real_yield_10y")
            cur_ry = cur_metrics.get("real_yield_10y")
            old_es = old_metrics.get("price_es_futures")
            cur_es = cur_metrics.get("price_es_futures")
            if old_ry and cur_ry:
                ry_still_high = cur_ry > 1.5
                es_flat_down = (cur_es or 0) <= (old_es or 0) * 1.02 if old_es and cur_es else None
                if ry_still_high and es_flat_down is not None and es_flat_down:
                    outcome["outcome"] = "correct"
                elif not ry_still_high:
                    outcome["outcome"] = "incorrect"
                else:
                    outcome["outcome"] = "inconclusive"
                outcome["evidence"] = f"Real yield: {old_ry:.2f}% -> {cur_ry:.2f}%, ES: {old_es} -> {cur_es}"

        # Risk-off signals
        elif signal_name in ("RISK_OFF_REGIME", "FLIGHT_TO_SAFETY"):
            old_es = old_metrics.get("price_es_futures")
            cur_es = cur_metrics.get("price_es_futures")
            old_gold = old_metrics.get("price_gold")
            cur_gold = cur_metrics.get("price_gold")
            if old_es and cur_es:
                eq_down = cur_es < old_es
                gold_up = (cur_gold or 0) > (old_gold or 0) if old_gold and cur_gold else None
                if eq_down:
                    outcome["outcome"] = "correct"
                else:
                    outcome["outcome"] = "incorrect"
                outcome["evidence"] = f"ES: {old_es} -> {cur_es}, Gold: {old_gold} -> {cur_gold}"

        # Housing
        elif signal_name == "HOUSING_WEAK":
            # Use consumer score as proxy
            old_cs = old_metrics.get("consumer_health_score")
            cur_cs_val = None
            cur_consumer = current_data.get("analyze_consumer_health", {})
            if isinstance(cur_consumer, dict):
                cur_cs_val = cur_consumer.get("composite_score")
            if old_cs and cur_cs_val:
                outcome["outcome"] = "correct" if cur_cs_val <= old_cs else "inconclusive"
                outcome["evidence"] = f"Consumer score: {old_cs:.1f} -> {cur_cs_val:.1f}"

        # Fed signals — use fed_funds from key_metrics if available
        elif signal_name in ("FED_TIGHTENING", "FED_EASING", "FED_NEUTRAL", "FED_RESTRICTIVE"):
            old_ff = old_metrics.get("fed_funds_rate")
            cur_regime_rates = cur_metrics.get("regime_rates", "")
            if old_ff is not None:
                # Try to get current fed funds from regime data
                cur_regimes = current_data.get("analyze_macro_regime", {}).get("regimes", {})
                cur_rate_info = cur_regimes.get("rates", {})
                if isinstance(cur_rate_info, dict):
                    cur_ff = cur_rate_info.get("fed_funds", cur_rate_info.get("value"))
                else:
                    cur_ff = None
                if cur_ff is not None:
                    delta = cur_ff - old_ff
                    if signal_name == "FED_EASING":
                        outcome["outcome"] = "correct" if delta < -0.1 else ("inconclusive" if abs(delta) < 0.1 else "incorrect")
                    elif signal_name in ("FED_TIGHTENING", "FED_RESTRICTIVE"):
                        outcome["outcome"] = "correct" if delta >= 0 or cur_ff > 3.5 else "incorrect"
                    elif signal_name == "FED_NEUTRAL":
                        outcome["outcome"] = "correct" if abs(delta) < 0.25 else "incorrect"
                    outcome["evidence"] = f"Fed funds: {old_ff:.2f}% -> {cur_ff:.2f}% (delta={delta:+.2f})"
                else:
                    outcome["outcome"] = "unverifiable"
                    outcome["evidence"] = "Current fed funds rate not available for comparison"
            else:
                outcome["outcome"] = "unverifiable"
                outcome["evidence"] = "Snapshot did not capture fed_funds_rate"

        # Breakeven signals
        elif signal_name in ("BREAKEVEN_RISING", "BREAKEVEN_FALLING", "BREAKEVEN_MIXED"):
            old_be = old_metrics.get("breakeven_10y")
            cur_bond = current_data.get("analyze_bond_market", {})
            cur_be_data = cur_bond.get("breakevens", {})
            cur_be = None
            if isinstance(cur_be_data, dict):
                for k, v in cur_be_data.items():
                    if "10" in str(k) and isinstance(v, dict):
                        cur_be = v.get("latest", v.get("value"))
                        break
            if old_be is not None and cur_be is not None:
                delta = cur_be - old_be
                if signal_name == "BREAKEVEN_RISING":
                    outcome["outcome"] = "correct" if delta > 0 else "incorrect"
                elif signal_name == "BREAKEVEN_FALLING":
                    outcome["outcome"] = "correct" if delta < 0 else "incorrect"
                elif signal_name == "BREAKEVEN_MIXED":
                    outcome["outcome"] = "correct" if abs(delta) < 0.15 else "inconclusive"
                outcome["evidence"] = f"10Y breakeven: {old_be:.2f}% -> {cur_be:.2f}% (delta={delta:+.2f})"

        # Housing distress signals
        elif signal_name in ("SALES_PLUNGING", "EXISTING_SALES_PLUNGING",
                             "AFFORDABILITY_STRESSED", "HOUSING_LEADING_DOWNTURN",
                             "HOUSING_CAUTION"):
            old_cs = old_metrics.get("consumer_health_score")
            cur_consumer = current_data.get("analyze_consumer_health", {})
            cur_cs_val = cur_consumer.get("composite_score") if isinstance(cur_consumer, dict) else None
            cur_housing = current_data.get("analyze_housing_market", {})
            cur_h_signals = cur_housing.get("signals", []) if isinstance(cur_housing, dict) else []
            # Check if housing weakness persisted
            still_distressed = any(
                "PLUNGING" in str(s) or "STRESSED" in str(s) or "DOWNTURN" in str(s)
                for s in cur_h_signals
            )
            if still_distressed:
                outcome["outcome"] = "correct"
                outcome["evidence"] = f"Housing distress persists: {[s for s in cur_h_signals if any(w in str(s) for w in ('PLUNGING','STRESSED','DOWNTURN'))][:3]}"
            elif old_cs and cur_cs_val:
                outcome["outcome"] = "correct" if cur_cs_val <= old_cs else "inconclusive"
                outcome["evidence"] = f"Consumer score: {old_cs:.1f} -> {cur_cs_val:.1f}"
            else:
                outcome["outcome"] = "unverifiable"
                outcome["evidence"] = "Insufficient data for housing verification"

        verification["signal_outcomes"].append(outcome)

    # Summary statistics
    outcomes = [o["outcome"] for o in verification["signal_outcomes"]]
    verification["summary"] = {
        "total_signals": len(outcomes),
        "correct": outcomes.count("correct"),
        "incorrect": outcomes.count("incorrect"),
        "inconclusive": outcomes.count("inconclusive"),
        "unverifiable": outcomes.count("unverifiable"),
    }
    verifiable = verification["summary"]["correct"] + verification["summary"]["incorrect"]
    if verifiable > 0:
        verification["summary"]["accuracy"] = f"{verification['summary']['correct']/verifiable*100:.1f}%"
    else:
        verification["summary"]["accuracy"] = "N/A (no verifiable signals)"

    return verification


def save_verification(verification: dict) -> Path:
    """Save verification results."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_date = verification.get("snapshot_date", "unknown")

    path = _VERIFICATIONS_DIR / f"verify_{snap_date}_at_{ts}.json"
    with open(path, "w") as f:
        json.dump(verification, f, indent=2, default=str)
    print(f"  Verification saved: {path}")

    # Markdown
    md = generate_verification_markdown(verification)
    md_path = _VERIFICATIONS_DIR / f"verify_{snap_date}_at_{ts}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")

    return path


# ═════════════════════════════════════════════════════════════════════
# ACCURACY REPORT — Aggregate across all verifications
# ═════════════════════════════════════════════════════════════════════

def generate_accuracy_report() -> dict:
    """Aggregate all verification results into a signal accuracy report."""
    signal_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0,
                                         "inconclusive": 0, "unverifiable": 0})
    category_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0,
                                           "inconclusive": 0, "unverifiable": 0})

    verification_files = sorted(_VERIFICATIONS_DIR.glob("verify_*.json"))
    if not verification_files:
        return {"error": "No verification records found. Take snapshots and wait for maturation."}

    total_verifications = 0
    for f in verification_files:
        with open(f) as fh:
            v = json.load(fh)
        total_verifications += 1
        for outcome in v.get("signal_outcomes", []):
            sig = outcome["signal"]
            cat = outcome.get("category", "unknown")
            result = outcome["outcome"]
            signal_stats[sig][result] += 1
            category_stats[cat][result] += 1

    # Compute per-signal accuracy
    signal_accuracy = {}
    for sig, stats in signal_stats.items():
        verifiable = stats["correct"] + stats["incorrect"]
        signal_accuracy[sig] = {
            **stats,
            "total": sum(stats.values()),
            "verifiable": verifiable,
            "accuracy": f"{stats['correct']/verifiable*100:.1f}%" if verifiable > 0 else "N/A",
        }

    # Compute per-category accuracy
    category_accuracy = {}
    for cat, stats in category_stats.items():
        verifiable = stats["correct"] + stats["incorrect"]
        category_accuracy[cat] = {
            **stats,
            "total": sum(stats.values()),
            "verifiable": verifiable,
            "accuracy": f"{stats['correct']/verifiable*100:.1f}%" if verifiable > 0 else "N/A",
        }

    # Overall
    total_correct = sum(s["correct"] for s in signal_stats.values())
    total_incorrect = sum(s["incorrect"] for s in signal_stats.values())
    total_verifiable = total_correct + total_incorrect

    report = {
        "timestamp": datetime.now().isoformat(),
        "total_verifications": total_verifications,
        "overall": {
            "total_signals_tracked": sum(s["total"] for s in signal_accuracy.values()),
            "total_verifiable": total_verifiable,
            "total_correct": total_correct,
            "total_incorrect": total_incorrect,
            "overall_accuracy": f"{total_correct/total_verifiable*100:.1f}%" if total_verifiable > 0 else "N/A",
        },
        "by_signal": dict(sorted(signal_accuracy.items())),
        "by_category": dict(sorted(category_accuracy.items())),
    }

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _RECORDS_DIR / f"accuracy_report_{ts}.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Accuracy report: {path}")

    md = generate_accuracy_markdown(report)
    md_path = _RECORDS_DIR / f"accuracy_report_{ts}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")

    return report


# ═════════════════════════════════════════════════════════════════════
# MARKDOWN GENERATION
# ═════════════════════════════════════════════════════════════════════

def generate_verification_markdown(verification: dict) -> str:
    """Generate markdown for a single verification."""
    s = verification.get("summary", {})
    lines = [
        "# Signal Verification Report",
        "",
        f"**Snapshot Date**: {verification.get('snapshot_date')}",
        f"**Verification Date**: {verification.get('verification_date')}",
        f"**Horizon**: {verification.get('horizon_weeks')} weeks",
        f"**Signals**: {s.get('total_signals', 0)}",
        f"**Accuracy**: {s.get('accuracy', 'N/A')}",
        "",
        "## Results\n",
        "| Signal | Category | Direction | Outcome | Evidence |",
        "|--------|----------|-----------|---------|----------|",
    ]
    for o in verification.get("signal_outcomes", []):
        icon = {"correct": "\u2705", "incorrect": "\u274c",
                "inconclusive": "\u2753", "unverifiable": "\u2796"}.get(o["outcome"], "?")
        lines.append(
            f"| {o['signal']} | {o.get('category', '')} | {o.get('direction', '')} "
            f"| {icon} {o['outcome']} | {o.get('evidence', '')[:80]} |"
        )
    return "\n".join(lines)


def generate_accuracy_markdown(report: dict) -> str:
    """Generate markdown for the aggregate accuracy report."""
    o = report.get("overall", {})
    lines = [
        "# Signal Accuracy Report (Aggregate)",
        "",
        f"**Date**: {report.get('timestamp', '')[:19]}",
        f"**Verifications analyzed**: {report.get('total_verifications', 0)}",
        f"**Total signals tracked**: {o.get('total_signals_tracked', 0)}",
        f"**Overall accuracy**: {o.get('overall_accuracy', 'N/A')}",
        "",
        "## Accuracy by Category\n",
        "| Category | Correct | Incorrect | Inconclusive | Accuracy |",
        "|----------|---------|-----------|-------------|----------|",
    ]
    for cat, stats in report.get("by_category", {}).items():
        lines.append(
            f"| {cat} | {stats['correct']} | {stats['incorrect']} "
            f"| {stats['inconclusive']} | {stats['accuracy']} |"
        )

    lines.append("\n## Accuracy by Signal\n")
    lines.append("| Signal | Correct | Incorrect | Accuracy | Total |")
    lines.append("|--------|---------|-----------|----------|-------|")
    for sig, stats in report.get("by_signal", {}).items():
        lines.append(
            f"| {sig} | {stats['correct']} | {stats['incorrect']} "
            f"| {stats['accuracy']} | {stats['total']} |"
        )

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# STATUS
# ═════════════════════════════════════════════════════════════════════

def show_status():
    """Show inventory of snapshots and verifications."""
    snapshots = load_snapshots()
    verifications = sorted(_VERIFICATIONS_DIR.glob("verify_*.json"))

    print(f"\n  Snapshots: {len(snapshots)}")
    if snapshots:
        for snap in snapshots:
            age = datetime.now() - datetime.fromisoformat(snap["timestamp"])
            signals = snap.get("summary", {}).get("total_signals", "?")
            status = snap.get("verification_status", "?")
            print(f"    {snap['snapshot_date']} | {signals} signals | "
                  f"age: {age.days}d | status: {status}")

    print(f"\n  Verifications: {len(verifications)}")
    for f in verifications:
        with open(f) as fh:
            v = json.load(fh)
        s = v.get("summary", {})
        print(f"    {f.stem} | accuracy: {s.get('accuracy', 'N/A')} | "
              f"correct: {s.get('correct', 0)}/{s.get('total_signals', 0)}")

    # Maturation status
    print(f"\n  Maturation status:")
    for horizon in [1, 4, 12]:
        matured = get_matured_snapshots(horizon)
        print(f"    {horizon}w horizon: {len(matured)} snapshots ready for verification")


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_full_report() -> dict:
    """Execute all 8 /full_report tools."""
    from tools.macro_data import scan_all_indicators
    from tools.macro_market_analysis import (
        analyze_macro_regime, analyze_bond_market, analyze_equity_drivers)
    from tools.market_regime_enhanced import (
        analyze_financial_stress, detect_late_cycle_signals)
    from tools.consumer_housing_analysis import (
        analyze_consumer_health, analyze_housing_market)

    print("  Collecting /full_report data...")
    tools = [
        ("scan_all_indicators", lambda: scan_all_indicators("short")),
        ("analyze_macro_regime", analyze_macro_regime),
        ("analyze_financial_stress", analyze_financial_stress),
        ("detect_late_cycle_signals", detect_late_cycle_signals),
        ("analyze_equity_drivers", lambda: analyze_equity_drivers("both")),
        ("analyze_bond_market", analyze_bond_market),
        ("analyze_consumer_health", analyze_consumer_health),
        ("analyze_housing_market", analyze_housing_market),
    ]
    report = {}
    for name, fn in tools:
        report[name] = json.loads(fn())
        print(f"    {name}: OK")
    return report


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Approach 5: Forward-Looking Signal Backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  snapshot    Take a signal snapshot (from live agent or saved JSON)
  verify      Verify matured snapshots against current data
  report      Generate aggregate accuracy report
  status      Show snapshot/verification inventory
        """)
    parser.add_argument("command", choices=["snapshot", "verify", "verify-now", "report", "status"],
                        help="Action to perform (verify-now skips maturation check)")
    parser.add_argument("--input", type=str,
                        help="Path to saved full_report JSON")
    parser.add_argument("--horizon", type=str, default="4w",
                        help="Verification horizon (e.g., '1w', '4w', '12w')")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 5: FORWARD-LOOKING SIGNAL BACKTESTING")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Parse horizon
    horizon_weeks = 4
    if args.horizon:
        h = args.horizon.lower().rstrip("w")
        try:
            horizon_weeks = int(h)
        except ValueError:
            print(f"  Invalid horizon: {args.horizon}. Using 4w.")

    if args.command == "snapshot":
        print(f"\n{'─' * 70}")
        print("  Taking signal snapshot...")
        print(f"{'─' * 70}\n")

        if args.input:
            with open(args.input) as f:
                report_data = json.load(f)
            print(f"  Loaded from: {args.input}")
        else:
            report_data = collect_full_report()

        snapshot = take_snapshot(report_data)
        path = save_snapshot(snapshot)

        s = snapshot["summary"]
        print(f"\n  Snapshot captured:")
        print(f"    Total signals: {s['total_signals']}")
        print(f"    Known signals: {s['known_signals']}")
        print(f"    Categories: {dict(s['categories'])}")
        print(f"    Key metrics captured: {len(snapshot['key_metrics'])}")

    elif args.command in ("verify", "verify-now"):
        skip_maturation = args.command == "verify-now"
        print(f"\n{'─' * 70}")
        if skip_maturation:
            print(f"  Verifying ALL snapshots (skipping maturation check)...")
        else:
            print(f"  Verifying at {horizon_weeks}-week horizon...")
        print(f"{'─' * 70}\n")

        if skip_maturation:
            matured = load_snapshots()
        else:
            matured = get_matured_snapshots(horizon_weeks)

        if not matured:
            if skip_maturation:
                print("  No snapshots found. Take one first with 'snapshot'.")
            else:
                print(f"  No snapshots are {horizon_weeks}+ weeks old yet.")
                print("  Use 'verify-now' to skip maturation, or wait for maturation.")
        else:
            # Collect current data for comparison
            if args.input:
                with open(args.input) as f:
                    current_data = json.load(f)
            else:
                current_data = collect_full_report()

            for snap in matured:
                print(f"\n  Verifying snapshot from {snap['snapshot_date']}...")
                result = verify_snapshot(snap, current_data, horizon_weeks)
                save_verification(result)

                s = result["summary"]
                print(f"    Signals: {s['total_signals']} | "
                      f"Correct: {s['correct']} | Incorrect: {s['incorrect']} | "
                      f"Accuracy: {s['accuracy']}")

    elif args.command == "report":
        print(f"\n{'─' * 70}")
        print("  Generating accuracy report...")
        print(f"{'─' * 70}\n")
        report = generate_accuracy_report()
        if "error" in report:
            print(f"  {report['error']}")
        else:
            o = report["overall"]
            print(f"\n  Overall: {o['overall_accuracy']} accuracy")
            print(f"  ({o['total_correct']}/{o['total_verifiable']} verifiable signals correct)")

    elif args.command == "status":
        show_status()
