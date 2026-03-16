#!/usr/bin/env python3
"""Collect fresh post-bugfix data from 10 commands for re-evaluation round 2."""
import sys, os, json, traceback
sys.path.insert(0, os.environ.get("FINANCIAL_AGENT_ROOT", "/Users/kriszhang/Github/Financial_Agent"))

results = {}

# 1. /drivers
print("Collecting /drivers ...")
try:
    from tools.macro_market_analysis import analyze_equity_drivers
    raw = analyze_equity_drivers(index="both")
    results["drivers"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["drivers"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 2. /bonds
print("Collecting /bonds ...")
try:
    from tools.macro_market_analysis import analyze_bond_market
    raw = analyze_bond_market()
    results["bonds"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["bonds"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 3. /latecycle
print("Collecting /latecycle ...")
try:
    from tools.market_regime_enhanced import detect_late_cycle_signals
    raw = detect_late_cycle_signals()
    results["latecycle"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["latecycle"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 4. /consumer
print("Collecting /consumer ...")
try:
    from tools.consumer_housing_analysis import analyze_consumer_health
    raw = analyze_consumer_health()
    results["consumer"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["consumer"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 5. /housing
print("Collecting /housing ...")
try:
    from tools.consumer_housing_analysis import analyze_housing_market
    raw = analyze_housing_market()
    results["housing"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["housing"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 6. /labor
print("Collecting /labor ...")
try:
    from tools.consumer_housing_analysis import analyze_labor_deep_dive
    raw = analyze_labor_deep_dive()
    results["labor"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["labor"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 7. /vixanalysis
print("Collecting /vixanalysis ...")
try:
    from tools.market_regime_enhanced import get_enhanced_vix_analysis
    raw = get_enhanced_vix_analysis()
    results["vixanalysis"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["vixanalysis"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 8. /bbb
print("Collecting /bbb ...")
try:
    from tools.yardeni_frameworks import get_boom_bust_barometer
    raw = get_boom_bust_barometer()
    results["bbb"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["bbb"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 9. /fsmi
print("Collecting /fsmi ...")
try:
    from tools.yardeni_frameworks import get_fsmi
    raw = get_fsmi()
    results["fsmi"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["fsmi"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# 10. /drawdown
print("Collecting /drawdown ...")
try:
    from tools.yardeni_frameworks import classify_market_decline
    raw = classify_market_decline()
    results["drawdown"] = {"status": "ok", "data": json.loads(raw) if isinstance(raw, str) else raw}
except Exception as e:
    results["drawdown"] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}

# Summary
ok = sum(1 for v in results.values() if v["status"] == "ok")
err = sum(1 for v in results.values() if v["status"] == "error")
print(f"\nCollection done: {ok} OK, {err} errors")
for cmd, v in results.items():
    status = v["status"]
    extra = ""
    if status == "error":
        extra = f" — {v['error'][:80]}"
    elif status == "ok":
        extra = f" — {len(json.dumps(v['data']))} bytes"
    print(f"  {cmd}: {status}{extra}")

out_path = "command_output_reeval_r2.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nSaved to {out_path}")
