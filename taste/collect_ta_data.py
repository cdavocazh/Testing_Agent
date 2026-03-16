#!/usr/bin/env python3
"""
Collect TA tool outputs + raw price data for 3 test assets.

Assets:
  - BTC:  Full 5min OHLCV, resampled to 1D. Most complete data.
  - gold: Close-only macro CSV, synthesised OHLC (open=high=low=close). Tests degraded-data handling.
  - AAPL: yfinance daily OHLCV. Tests stock/ETF path.

Outputs:
  ta_output_v1.json  with structure:
    {
      "assets": {
        "btc":  { "murphy_full", "support_resistance", "rsi", "breakout",
                  "quick_snapshot", "stop_loss", "raw_price_data" },
        "gold": { ... },
        "AAPL": { ... },
      },
      "cross_asset": {
        "risk_premium":   ...,
        "cross_momentum": ...,
      },
      "meta": { "collected_at", "assets", "elapsed_s" }
    }

Usage:
    FINANCIAL_AGENT_ROOT=/path/to/Financial_Agent python collect_ta_data.py [--output ta_output_v1.json]
"""

import sys, os, json, time, argparse, traceback
from datetime import datetime

FA_ROOT = os.environ.get("FINANCIAL_AGENT_ROOT",
                         "/Users/kriszhang/Github/Financial_Agent")
sys.path.insert(0, FA_ROOT)

TEST_ASSETS = ["btc", "gold", "AAPL"]


# ── helpers ───────────────────────────────────────────────────────────
def safe_call(label, fn, *a, **kw):
    """Call fn and return parsed JSON dict, or error dict."""
    print(f"    {label} ...", end=" ", flush=True)
    try:
        raw = fn(*a, **kw)
        data = json.loads(raw) if isinstance(raw, str) else raw
        print(f"OK ({len(json.dumps(data, default=str)):,} bytes)")
        return {"status": "ok", "data": data}
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()}


def get_raw_price_data(asset: str, bars: int = 250) -> dict:
    """
    Load the last `bars` OHLCV bars for `asset` as a dict of lists.
    This is stored so Approach #8 can recompute indicators offline.
    """
    print(f"    raw_price_data ({bars} bars) ...", end=" ", flush=True)
    try:
        from tools.murphy_ta import _load_asset_data
        df = _load_asset_data(asset, "1D")
        df = df.tail(bars).reset_index(drop=True)
        result = {
            "asset": asset,
            "bars": len(df),
            "columns": list(df.columns),
            "close": df["close"].tolist(),
        }
        # Only include OHLCV if they differ from close (i.e. not synthesised)
        if "open" in df.columns:
            result["open"] = df["open"].tolist()
        if "high" in df.columns:
            result["high"] = df["high"].tolist()
        if "low" in df.columns:
            result["low"] = df["low"].tolist()
        if "volume" in df.columns:
            result["volume"] = df["volume"].tolist()
        if "timestamp" in df.columns:
            result["timestamp"] = [str(t) for t in df["timestamp"].tolist()]
        elif "date" in df.columns:
            result["timestamp"] = [str(t) for t in df["date"].tolist()]

        # Flag whether OHLC is real or synthesised
        if "open" in result and "high" in result:
            opens = result["open"][-10:]
            closes = result["close"][-10:]
            highs = result["high"][-10:]
            all_same = all(o == c == h for o, c, h in zip(opens, closes, highs))
            result["ohlc_synthesised"] = all_same
        else:
            result["ohlc_synthesised"] = True

        print(f"OK ({result['bars']} bars, synth={result['ohlc_synthesised']})")
        return {"status": "ok", "data": result}
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return {"status": "error", "error": str(e)}


# ── main collection ───────────────────────────────────────────────────
def collect_all(assets: list[str]) -> dict:
    from tools.murphy_ta import (
        murphy_technical_analysis, calculate_rsi,
        find_support_resistance, analyze_breakout,
        quick_ta_snapshot, fundamental_ta_synthesis,
    )
    from tools.protrader_sl import protrader_stop_loss_framework
    from tools.protrader_frameworks import (
        protrader_risk_premium_analysis,
        protrader_cross_asset_momentum,
    )

    t0 = time.time()
    result = {"assets": {}, "cross_asset": {}, "meta": {}}

    # ── per-asset collection ──────────────────────────────────────
    for asset in assets:
        print(f"\n  === {asset} ===")
        ad = {}

        # 1) Murphy full TA
        ad["murphy_full"] = safe_call(
            "murphy_technical_analysis", murphy_technical_analysis, asset, "1D")

        # 2) Standalone S/R
        ad["support_resistance"] = safe_call(
            "find_support_resistance", find_support_resistance, asset, "1D", 100)

        # 3) RSI multi-period
        ad["rsi"] = safe_call(
            "calculate_rsi", calculate_rsi, asset, 14, "1D", "7,9,21")

        # 4) Breakout
        ad["breakout"] = safe_call(
            "analyze_breakout", analyze_breakout, asset, "1D")

        # 5) Quick snapshot
        ad["quick_snapshot"] = safe_call(
            "quick_ta_snapshot", quick_ta_snapshot, asset, "1D")

        # 6) Fundamental-TA synthesis (equity only)
        if asset.isupper() and len(asset) <= 5:
            ad["fundamental_synthesis"] = safe_call(
                "fundamental_ta_synthesis", fundamental_ta_synthesis, asset, "1D")

        # 7) Stop-loss framework
        #    Extract inputs from murphy output or quick_snapshot
        murphy_data = (ad.get("murphy_full", {}).get("data") or {})
        snap_data = (ad.get("quick_snapshot", {}).get("data") or {})
        sr_data = (ad.get("support_resistance", {}).get("data") or {})

        current_price = (murphy_data.get("current_price")
                         or snap_data.get("current_price")
                         or sr_data.get("current_price")
                         or 0)

        # Determine asset class for stop-loss
        asset_class_map = {"btc": "crypto", "gold": "gold", "silver": "gold",
                           "crude_oil": "commodity"}
        sl_asset_class = asset_class_map.get(asset.lower(), "equity")

        # Extract swing from fibonacci or S/R
        fib = murphy_data.get("fibonacci", {})
        swing_low = fib.get("swing_low", 0) if isinstance(fib, dict) else 0
        swing_high = fib.get("swing_high", 0) if isinstance(fib, dict) else 0
        if swing_low == 0 and sr_data:
            supports = sr_data.get("supports", [])
            if supports:
                swing_low = supports[0] if supports else 0
        if swing_high == 0 and sr_data:
            resistances = sr_data.get("resistances", [])
            if resistances:
                swing_high = resistances[0] if resistances else 0

        # Compute ATR from raw data (14-period)
        atr_val = 0
        try:
            from tools.murphy_ta import _load_asset_data
            import numpy as np
            df = _load_asset_data(asset, "1D")
            if len(df) > 14:
                highs = df["high"].values[-15:]
                lows = df["low"].values[-15:]
                closes = df["close"].values[-15:]
                tr_vals = []
                for i in range(1, len(highs)):
                    tr_vals.append(max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i-1]),
                        abs(lows[i] - closes[i-1])
                    ))
                atr_val = float(np.mean(tr_vals))
        except Exception:
            pass

        if current_price > 0:
            ad["stop_loss"] = safe_call(
                "protrader_stop_loss_framework", protrader_stop_loss_framework,
                sl_asset_class, current_price, "long",
                current_price, swing_low, swing_high, atr_val)

        # 8) Raw price data
        ad["raw_price_data"] = get_raw_price_data(asset)

        result["assets"][asset] = ad

    # ── cross-asset (once) ────────────────────────────────────────
    print(f"\n  === Cross-Asset ===")
    result["cross_asset"]["risk_premium"] = safe_call(
        "protrader_risk_premium_analysis", protrader_risk_premium_analysis)
    result["cross_asset"]["cross_momentum"] = safe_call(
        "protrader_cross_asset_momentum", protrader_cross_asset_momentum)

    elapsed = time.time() - t0
    result["meta"] = {
        "collected_at": datetime.now().isoformat(),
        "assets": assets,
        "elapsed_s": round(elapsed, 1),
    }
    return result


# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect TA data for taste eval")
    parser.add_argument("--output", default="taste/ta_output_v1.json",
                        help="Output path (default: taste/ta_output_v1.json)")
    parser.add_argument("--assets", default=",".join(TEST_ASSETS),
                        help="Comma-separated assets")
    args = parser.parse_args()

    assets = [a.strip() for a in args.assets.split(",")]
    print("=" * 70)
    print(f"  TA DATA COLLECTION — {datetime.now()}")
    print(f"  Assets: {assets}")
    print("=" * 70)

    data = collect_all(assets)

    # Summary
    print(f"\n{'=' * 70}")
    print("  COLLECTION SUMMARY")
    for asset, ad in data["assets"].items():
        ok = sum(1 for v in ad.values() if isinstance(v, dict) and v.get("status") == "ok")
        err = sum(1 for v in ad.values() if isinstance(v, dict) and v.get("status") == "error")
        print(f"    {asset:8s}: {ok} OK, {err} errors")
    for k, v in data["cross_asset"].items():
        status = v.get("status", "?")
        print(f"    {k:8s}: {status}")
    print(f"  Elapsed: {data['meta']['elapsed_s']}s")
    print("=" * 70)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\n  Saved to {args.output} ({os.path.getsize(args.output):,} bytes)")
