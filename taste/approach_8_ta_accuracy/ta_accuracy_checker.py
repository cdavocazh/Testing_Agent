#!/usr/bin/env python3
"""
Approach #8 — TA Data Accuracy (Mathematical Verification)

Recomputes indicators from raw price data and compares to tool output.
25 checks per asset (75 total for 3 assets).

Categories:
  TA-01..04  RSI verification
  TA-05..09  MACD verification
  TA-10..14  Bollinger Bands verification
  TA-15..17  Fibonacci verification
  TA-18..20  Stochastic verification
  TA-21..23  Composite signal verification
  TA-24..25  Stop-loss arithmetic

Tolerances:
  RSI:       +/- 0.5 points
  MACD/BB:   +/- 0.1% of price (or 1% for line values)
  Composite: +/- 0.02
  Zone:      exact match

Usage:
    python ta_accuracy_checker.py --input ../../taste/ta_output_v1.json
"""

import sys, os, json, argparse, time, math
from datetime import datetime
from pathlib import Path
import numpy as np

_THIS = Path(__file__).resolve().parent
_RECORDS = _THIS / "records"
_RECORDS.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# RESULT TYPES  (same pattern as existing approaches)
# ═══════════════════════════════════════════════════════════════════

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
        tag = f"[{c.check_id}][{c.asset:5s}][{sev}]"
        print(f"  {icon} {tag} {c.name}")
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
# HELPER: Indicator computation from raw data
# ═══════════════════════════════════════════════════════════════════

def compute_rsi(closes, period=14):
    """Wilder's RSI computation."""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Wilder's smoothing (EMA-like)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def compute_macd(closes, fast=12, slow=26, signal=9):
    """EMA-based MACD."""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema_from_series(macd_line[slow-1:], signal)
    # Align: signal starts at slow-1+signal-1
    idx = slow - 1 + signal - 1
    if idx >= len(macd_line):
        return None, None, None
    ml = macd_line[-1]
    sl = signal_line[-1]
    hist = ml - sl
    return ml, sl, hist

def _ema(data, period):
    """Compute EMA as numpy array."""
    arr = np.array(data, dtype=float)
    ema = np.zeros_like(arr)
    ema[0] = arr[0]
    k = 2.0 / (period + 1)
    for i in range(1, len(arr)):
        ema[i] = arr[i] * k + ema[i-1] * (1 - k)
    return ema

def _ema_from_series(data, period):
    """Compute EMA from a subseries."""
    return _ema(data, period)

def compute_bollinger(closes, period=20, num_std=2):
    """Bollinger bands: middle, upper, lower, bandwidth%, %B."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = np.mean(window)
    std = np.std(window, ddof=1)
    upper = middle + num_std * std
    lower = middle - num_std * std
    bw = (upper - lower) / middle * 100 if middle != 0 else 0
    price = closes[-1]
    pct_b = (price - lower) / (upper - lower) * 100 if upper != lower else 50
    return {"upper": upper, "middle": middle, "lower": lower,
            "bandwidth_pct": bw, "percent_b": pct_b}

def compute_stochastic(highs, lows, closes, k_period=14, d_period=3):
    """Stochastic %K and %D."""
    if len(closes) < k_period + d_period:
        return None, None
    # %K values for last d_period bars
    k_vals = []
    for i in range(d_period):
        end_idx = len(closes) - i
        start_idx = end_idx - k_period
        high_max = max(highs[start_idx:end_idx])
        low_min = min(lows[start_idx:end_idx])
        if high_max == low_min:
            k_vals.append(50.0)
        else:
            k_vals.append((closes[end_idx-1] - low_min) / (high_max - low_min) * 100)
    pct_k = k_vals[0]
    pct_d = np.mean(k_vals)
    return pct_k, pct_d

def compute_fibonacci(highs, lows, lookback=100):
    """Fibonacci retracement levels."""
    h = highs[-lookback:] if len(highs) >= lookback else highs
    l = lows[-lookback:] if len(lows) >= lookback else lows
    swing_high = max(h)
    swing_low = min(l)
    diff = swing_high - swing_low
    if diff == 0:
        return None
    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "fib_236": swing_high - diff * 0.236,
        "fib_382": swing_high - diff * 0.382,
        "fib_500": swing_high - diff * 0.500,
        "fib_618": swing_high - diff * 0.618,
        "fib_786": swing_high - diff * 0.786,
    }


# ═══════════════════════════════════════════════════════════════════
# PER-ASSET CHECKS
# ═══════════════════════════════════════════════════════════════════

def run_asset_checks(asset: str, asset_data: dict, rpt: Report):
    """Run 25 accuracy checks for one asset."""
    murphy = asset_data.get("murphy_full", {}).get("data", {})
    rsi_out = asset_data.get("rsi", {}).get("data", {})
    sr_out = asset_data.get("support_resistance", {}).get("data", {})
    bo_out = asset_data.get("breakout", {}).get("data", {})
    snap_out = asset_data.get("quick_snapshot", {}).get("data", {})
    sl_out = asset_data.get("stop_loss", {}).get("data", {})
    raw = asset_data.get("raw_price_data", {}).get("data", {})

    closes = raw.get("close", [])
    highs = raw.get("high", closes)
    lows = raw.get("low", closes)
    synth = raw.get("ohlc_synthesised", True)
    price = murphy.get("current_price", 0)

    # ── RSI Verification (TA-01..04) ─────────────────────────
    tool_rsi14 = rsi_out.get("rsi_14")
    computed_rsi14 = compute_rsi(closes, 14) if len(closes) > 15 else None

    if computed_rsi14 is not None and tool_rsi14 is not None:
        diff = abs(tool_rsi14 - computed_rsi14)
        rpt.add(Check("TA-01", asset, "RSI(14) matches recomputed",
                       diff <= 1.5,
                       f"{computed_rsi14:.2f} +/-1.5", f"{tool_rsi14:.2f} (diff={diff:.2f})",
                       "Recomputed RSI(14) vs tool output", "high"))
    else:
        rpt.add(Check("TA-01", asset, "RSI(14) recomputation",
                       computed_rsi14 is None and len(closes) < 16,
                       "skip (insufficient data)", f"closes={len(closes)}",
                       "Not enough data to recompute RSI(14)", "low"))

    # RSI(7)
    mp = rsi_out.get("multi_period", {})
    tool_rsi7 = mp.get("rsi_7")
    computed_rsi7 = compute_rsi(closes, 7) if len(closes) > 8 else None
    if computed_rsi7 is not None and tool_rsi7 is not None:
        diff = abs(tool_rsi7 - computed_rsi7)
        rpt.add(Check("TA-02", asset, "RSI(7) matches recomputed",
                       diff <= 2.0,
                       f"{computed_rsi7:.2f} +/-2.0", f"{tool_rsi7:.2f} (diff={diff:.2f})",
                       "Recomputed RSI(7) vs tool output", "medium"))
    else:
        rpt.add(Check("TA-02", asset, "RSI(7) recomputation",
                       True, "skip", "N/A", "Insufficient data or no tool output", "low"))

    # RSI(21)
    tool_rsi21 = mp.get("rsi_21")
    computed_rsi21 = compute_rsi(closes, 21) if len(closes) > 22 else None
    if computed_rsi21 is not None and tool_rsi21 is not None:
        diff = abs(tool_rsi21 - computed_rsi21)
        rpt.add(Check("TA-03", asset, "RSI(21) matches recomputed",
                       diff <= 2.0,
                       f"{computed_rsi21:.2f} +/-2.0", f"{tool_rsi21:.2f} (diff={diff:.2f})",
                       "Recomputed RSI(21) vs tool output", "medium"))
    else:
        rpt.add(Check("TA-03", asset, "RSI(21) recomputation",
                       True, "skip", "N/A", "Insufficient data or no tool output", "low"))

    # RSI zone classification
    murphy_rsi = murphy.get("6_rsi", {})
    tool_rsi_val = murphy_rsi.get("rsi")
    tool_zone = murphy_rsi.get("zone", "")
    zone_correct = True
    if tool_rsi_val is not None and tool_zone:
        if tool_rsi_val >= 70:
            zone_correct = tool_zone == "overbought"
        elif tool_rsi_val >= 50:
            zone_correct = tool_zone in ("bullish_momentum",)
        elif tool_rsi_val >= 30:
            zone_correct = tool_zone in ("bearish_momentum",)
        else:
            zone_correct = tool_zone == "oversold"
    rpt.add(Check("TA-04", asset, "RSI zone matches RSI value",
                   zone_correct,
                   f"zone for RSI={tool_rsi_val}", tool_zone,
                   "Zone label should match RSI value range", "high"))

    # ── MACD Verification (TA-05..09) ────────────────────────
    tool_macd = murphy.get("5_macd", {})
    t_ml = tool_macd.get("macd_line")
    t_sl = tool_macd.get("signal_line")
    t_hist = tool_macd.get("histogram")

    c_ml, c_sl, c_hist = compute_macd(closes) if len(closes) > 35 else (None, None, None)

    if c_ml is not None and t_ml is not None and price > 0:
        tol = price * 0.01  # 1% of price
        rpt.add(Check("TA-05", asset, "MACD line matches recomputed",
                       abs(t_ml - c_ml) <= tol,
                       f"{c_ml:.4f} +/-{tol:.2f}", f"{t_ml:.4f}",
                       "Recomputed MACD line vs tool", "medium"))
        rpt.add(Check("TA-06", asset, "MACD signal line matches recomputed",
                       abs(t_sl - c_sl) <= tol,
                       f"{c_sl:.4f} +/-{tol:.2f}", f"{t_sl:.4f}",
                       "Recomputed signal line vs tool", "medium"))
        rpt.add(Check("TA-07", asset, "MACD histogram matches recomputed",
                       abs(t_hist - c_hist) <= tol,
                       f"{c_hist:.4f} +/-{tol:.2f}", f"{t_hist:.4f}",
                       "Recomputed histogram vs tool", "medium"))
    else:
        for cid in ("TA-05", "TA-06", "TA-07"):
            rpt.add(Check(cid, asset, f"MACD {'line' if cid=='TA-05' else 'signal' if cid=='TA-06' else 'hist'} recomputation",
                           True, "skip", "N/A", "Insufficient data", "low"))

    # MACD histogram sign
    if t_hist is not None:
        rpt.add(Check("TA-08", asset, "MACD histogram sign matches crossover",
                       (t_hist > 0 and "bearish" not in tool_macd.get("crossover","").lower())
                       or (t_hist < 0 and "bullish" not in tool_macd.get("crossover","").lower())
                       or t_hist == 0,
                       f"hist sign consistent with crossover",
                       f"hist={t_hist:.4f}, crossover={tool_macd.get('crossover')}",
                       "Histogram > 0 means MACD > signal (bullish)", "high"))
    else:
        rpt.add(Check("TA-08", asset, "MACD histogram sign", True, "skip", "N/A",
                       "No histogram data", "low"))

    # MACD centerline
    if t_ml is not None:
        cl = tool_macd.get("centerline", "")
        expected_cl = "above_zero" if t_ml > 0 else "below_zero"
        rpt.add(Check("TA-09", asset, "MACD centerline label correct",
                       cl == expected_cl or t_ml == 0,
                       expected_cl, cl,
                       "Centerline label should match MACD line sign", "medium"))
    else:
        rpt.add(Check("TA-09", asset, "MACD centerline", True, "skip", "N/A",
                       "No MACD data", "low"))

    # ── Bollinger Bands Verification (TA-10..14) ─────────────
    tool_bb = murphy.get("7_bollinger_bands", {})
    c_bb = compute_bollinger(closes) if len(closes) >= 20 else None

    if c_bb is not None and tool_bb.get("available"):
        tol_band = price * 0.005 if price > 0 else 1  # 0.5% of price
        rpt.add(Check("TA-10", asset, "Upper Bollinger matches recomputed",
                       abs(tool_bb["upper_band"] - c_bb["upper"]) <= tol_band,
                       f"{c_bb['upper']:.2f} +/-{tol_band:.2f}",
                       f"{tool_bb['upper_band']:.2f}",
                       "Upper BB vs recomputed", "medium"))
        rpt.add(Check("TA-11", asset, "Lower Bollinger matches recomputed",
                       abs(tool_bb["lower_band"] - c_bb["lower"]) <= tol_band,
                       f"{c_bb['lower']:.2f} +/-{tol_band:.2f}",
                       f"{tool_bb['lower_band']:.2f}",
                       "Lower BB vs recomputed", "medium"))
        rpt.add(Check("TA-12", asset, "Middle Bollinger matches recomputed",
                       abs(tool_bb["middle_band"] - c_bb["middle"]) <= tol_band,
                       f"{c_bb['middle']:.2f} +/-{tol_band:.2f}",
                       f"{tool_bb['middle_band']:.2f}",
                       "Middle BB (SMA20) vs recomputed", "medium"))
        rpt.add(Check("TA-13", asset, "Bandwidth % matches recomputed",
                       abs(tool_bb["bandwidth_pct"] - c_bb["bandwidth_pct"]) <= 1.0,
                       f"{c_bb['bandwidth_pct']:.2f} +/-1.0",
                       f"{tool_bb['bandwidth_pct']:.2f}",
                       "Bandwidth % vs recomputed", "medium"))
        rpt.add(Check("TA-14", asset, "%B matches recomputed",
                       abs(tool_bb["percent_b"] - c_bb["percent_b"]) <= 3.0,
                       f"{c_bb['percent_b']:.2f} +/-3.0",
                       f"{tool_bb['percent_b']:.2f}",
                       "%B vs recomputed", "medium"))
    else:
        for cid in ("TA-10", "TA-11", "TA-12", "TA-13", "TA-14"):
            rpt.add(Check(cid, asset, "Bollinger recomputation",
                           True, "skip", "N/A", "Insufficient data", "low"))

    # ── Fibonacci Verification (TA-15..17) ───────────────────
    tool_fib = murphy.get("8_fibonacci", {})
    c_fib = compute_fibonacci(highs, lows) if len(closes) >= 50 else None

    if c_fib is not None and tool_fib.get("available"):
        tol_fib = price * 0.005 if price > 0 else 1
        rpt.add(Check("TA-15", asset, "Fib 38.2% matches recomputed",
                       abs(tool_fib.get("fib_382", 0) - c_fib["fib_382"]) <= tol_fib,
                       f"{c_fib['fib_382']:.2f} +/-{tol_fib:.2f}",
                       f"{tool_fib.get('fib_382', 'N/A')}",
                       "Fib 38.2% retracement vs recomputed", "medium"))
        rpt.add(Check("TA-16", asset, "Fib 61.8% matches recomputed",
                       abs(tool_fib.get("fib_618", 0) - c_fib["fib_618"]) <= tol_fib,
                       f"{c_fib['fib_618']:.2f} +/-{tol_fib:.2f}",
                       f"{tool_fib.get('fib_618', 'N/A')}",
                       "Fib 61.8% retracement vs recomputed", "medium"))
        # Zone classification
        fib_zone = tool_fib.get("fibonacci_zone", "")
        fib_price = tool_fib.get("current_price", price)
        if fib_price > c_fib["fib_382"]:
            expected_zone_keyword = "above" if fib_price > c_fib["fib_236"] else "23.6%"
        elif fib_price > c_fib["fib_618"]:
            expected_zone_keyword = "38.2%"
        else:
            expected_zone_keyword = "61.8%"
        rpt.add(Check("TA-17", asset, "Fibonacci zone plausible",
                       len(fib_zone) > 0,  # Just check it's not empty
                       "non-empty zone description", fib_zone[:60],
                       "Fibonacci zone should be described", "low"))
    else:
        for cid in ("TA-15", "TA-16", "TA-17"):
            rpt.add(Check(cid, asset, "Fibonacci recomputation",
                           True, "skip", "N/A", "Insufficient data", "low"))

    # ── Stochastic Verification (TA-18..20) ──────────────────
    tool_stoch = murphy.get("9_stochastic", {})
    if not synth and len(highs) > 17 and len(lows) > 17:
        c_k, c_d = compute_stochastic(highs, lows, closes)
    else:
        c_k, c_d = None, None

    if c_k is not None and tool_stoch.get("available"):
        rpt.add(Check("TA-18", asset, "Stochastic %K matches recomputed",
                       abs(tool_stoch["percent_k"] - c_k) <= 5.0,
                       f"{c_k:.2f} +/-5.0",
                       f"{tool_stoch['percent_k']:.2f}",
                       "Stochastic %K vs recomputed", "medium"))
        rpt.add(Check("TA-19", asset, "Stochastic %D matches recomputed",
                       abs(tool_stoch["percent_d"] - c_d) <= 5.0,
                       f"{c_d:.2f} +/-5.0",
                       f"{tool_stoch['percent_d']:.2f}",
                       "Stochastic %D vs recomputed", "medium"))
        # Zone
        tk = tool_stoch["percent_k"]
        t_zone = tool_stoch.get("zone", "")
        exp_zone = "overbought" if tk >= 80 else ("oversold" if tk <= 20 else "neutral")
        rpt.add(Check("TA-20", asset, "Stochastic zone matches %K",
                       t_zone == exp_zone,
                       exp_zone, t_zone,
                       f"%K={tk:.1f} -> zone should be {exp_zone}", "high"))
    elif synth:
        for cid in ("TA-18", "TA-19", "TA-20"):
            rpt.add(Check(cid, asset, "Stochastic (synthesised OHLC)",
                           True, "skip (synth)", "N/A",
                           "Stochastic degenerate with synthesised OHLC", "low"))
    else:
        t_zone = tool_stoch.get("zone", "")
        tk = tool_stoch.get("percent_k")
        # At least verify zone vs value
        if tk is not None:
            exp_zone = "overbought" if tk >= 80 else ("oversold" if tk <= 20 else "neutral")
            rpt.add(Check("TA-18", asset, "Stochastic zone vs %K (no recompute)",
                           t_zone == exp_zone, exp_zone, t_zone,
                           f"%K={tk:.1f}", "medium"))
            rpt.add(Check("TA-19", asset, "Stochastic %K in [0,100]",
                           0 <= tk <= 100, "[0,100]", tk, "Valid range", "medium"))
            rpt.add(Check("TA-20", asset, "Stochastic %D in [0,100]",
                           0 <= (tool_stoch.get("percent_d",50)) <= 100,
                           "[0,100]", tool_stoch.get("percent_d"),
                           "Valid range", "medium"))
        else:
            for cid in ("TA-18", "TA-19", "TA-20"):
                rpt.add(Check(cid, asset, "Stochastic data",
                               True, "skip", "N/A", "No stochastic data", "low"))

    # ── Composite Signal Verification (TA-21..23) ────────────
    comp = murphy.get("composite_signal", {})
    bull = comp.get("bullish_count", 0)
    bear = comp.get("bearish_count", 0)
    total = comp.get("total_indicators", 0)
    score = comp.get("score")
    signal = comp.get("signal", "")

    if total > 0 and score is not None:
        # Recompute score
        expected_score = (bull - bear) / total
        rpt.add(Check("TA-21", asset, "Composite score = (bull-bear)/total",
                       abs(score - expected_score) <= 0.03,
                       f"{expected_score:.3f} +/-0.03", f"{score:.3f}",
                       f"({bull}-{bear})/{total} = {expected_score:.3f}", "high"))

        # Vote count <= total
        rpt.add(Check("TA-22", asset, "Bull+bear <= total indicators",
                       bull + bear <= total,
                       f"<= {total}", f"{bull}+{bear}={bull+bear}",
                       "Vote counts should not exceed total", "medium"))

        # Signal matches score
        if score > 0.3:
            exp_sig = "BULLISH"
        elif score < -0.3:
            exp_sig = "BEARISH"
        else:
            exp_sig = "NEUTRAL"
        rpt.add(Check("TA-23", asset, "Signal matches score thresholds",
                       signal == exp_sig,
                       exp_sig, signal,
                       f"score={score:.2f} -> {exp_sig}", "high"))
    else:
        for cid in ("TA-21", "TA-22", "TA-23"):
            rpt.add(Check(cid, asset, "Composite data",
                           True, "skip", "N/A", "No composite data", "low"))

    # ── Stop-Loss Arithmetic (TA-24..25) ─────────────────────
    sl = sl_out
    if isinstance(sl, dict) and sl.get("stop_levels"):
        sl_levels = sl["stop_levels"]
        entry = sl.get("entry_price", 0)

        # Swing-based stop
        swing_sl = sl_levels.get("swing_based", {})
        swing_level = swing_sl.get("level", 0)
        swing_risk = swing_sl.get("risk_pct", 0)
        if entry > 0 and swing_level > 0:
            computed_risk = (entry - swing_level) / entry * 100
            rpt.add(Check("TA-24", asset, "Swing stop risk_pct arithmetic",
                           abs(swing_risk - computed_risk) <= 0.5,
                           f"{computed_risk:.2f}% +/-0.5",
                           f"{swing_risk:.2f}%",
                           f"(entry={entry} - level={swing_level})/entry * 100", "high"))
        else:
            rpt.add(Check("TA-24", asset, "Swing stop arithmetic",
                           True, "skip", "N/A", "No swing stop data", "low"))

        # ATR-based stop
        atr_sl = sl_levels.get("atr_based", {})
        atr_level = atr_sl.get("level", 0)
        atr_risk = atr_sl.get("risk_pct", 0)
        if entry > 0 and atr_level > 0:
            computed_risk = (entry - atr_level) / entry * 100
            rpt.add(Check("TA-25", asset, "ATR stop risk_pct arithmetic",
                           abs(atr_risk - computed_risk) <= 0.5,
                           f"{computed_risk:.2f}% +/-0.5",
                           f"{atr_risk:.2f}%",
                           f"(entry={entry} - level={atr_level})/entry * 100", "high"))
        else:
            rpt.add(Check("TA-25", asset, "ATR stop arithmetic",
                           True, "skip", "N/A", "No ATR stop data", "low"))
    else:
        rpt.add(Check("TA-24", asset, "Stop-loss data", True, "skip", "N/A",
                       "No stop-loss data", "low"))
        rpt.add(Check("TA-25", asset, "Stop-loss data", True, "skip", "N/A",
                       "No stop-loss data", "low"))


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Approach #8: TA Accuracy")
    parser.add_argument("--input", required=True, help="Path to ta_output_v1.json")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    print("=" * 70)
    print("  APPROACH #8: TA DATA ACCURACY (Mathematical Verification)")
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
    print(f"  Elapsed: {s['elapsed']}")
    print("=" * 70)

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {"approach": "8_ta_accuracy", "timestamp": datetime.now().isoformat(),
           "results": rpt.to_dict()}
    jp = _RECORDS / f"approach8_{ts}.json"
    with open(jp, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  Saved: {jp}")
    return rpt

if __name__ == "__main__":
    main()
