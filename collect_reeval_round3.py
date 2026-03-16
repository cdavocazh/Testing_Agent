#!/usr/bin/env python3
"""Collect fresh post-bugfix data from 17 remaining commands for re-evaluation round 3."""
import sys, os, json, traceback
sys.path.insert(0, os.environ.get("FINANCIAL_AGENT_ROOT", "/Users/kriszhang/Github/Financial_Agent"))

results = {}

def collect(name, fn, *args, **kwargs):
    print(f"Collecting /{name} ...")
    try:
        raw = fn(*args, **kwargs)
        data = json.loads(raw) if isinstance(raw, str) else raw
        results[name] = {"status": "ok", "data": data}
        print(f"  OK — {len(json.dumps(data))} bytes")
    except Exception as e:
        results[name] = {"status": "error", "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()}
        print(f"  ERROR — {type(e).__name__}: {e}")

# Batch 3 remaining
from tools.yardeni_frameworks import analyze_bond_vigilantes
collect("vigilantes", analyze_bond_vigilantes)

from tools.equity_analysis import get_peer_comparison
collect("peers_NVDA", get_peer_comparison, "NVDA")

from tools.equity_analysis import analyze_capital_allocation
collect("allocation_NVDA", analyze_capital_allocation, "NVDA")

from tools.equity_analysis import analyze_balance_sheet_health
collect("balance_NVDA", analyze_balance_sheet_health, "NVDA")

from tools.protrader_frameworks import protrader_risk_premium_analysis
collect("riskpremium", protrader_risk_premium_analysis)

from tools.protrader_frameworks import protrader_cross_asset_momentum
collect("crossasset", protrader_cross_asset_momentum)

from tools.murphy_ta import murphy_intermarket_analysis
collect("intermarket", murphy_intermarket_analysis)

from tools.macro_synthesis import synthesize_macro_view
collect("synthesize", synthesize_macro_view)

# Batch 4
from tools.btc_analysis import analyze_btc_market
collect("btc", analyze_btc_market)

from tools.protrader_frameworks import protrader_precious_metals_regime
collect("pmregime", protrader_precious_metals_regime)

from tools.protrader_frameworks import protrader_usd_regime_analysis
collect("usdregime", protrader_usd_regime_analysis)

from tools.murphy_ta import murphy_technical_analysis
collect("ta_NVDA", murphy_technical_analysis, "NVDA")

from tools.murphy_ta import fundamental_ta_synthesis
collect("synthesis_NVDA", fundamental_ta_synthesis, "NVDA")

from tools.protrader_sl import protrader_stop_loss_framework
collect("sl_gold", protrader_stop_loss_framework, "gold", 3348, "long")

from tools.graham_analysis import graham_screen
collect("grahamscreen", graham_screen)

from tools.graham_analysis import graham_net_net_screen
collect("netnet", graham_net_net_screen)

from tools.equity_analysis import compare_equity_metrics
collect("compare_NVDA_AAPL_MSFT", compare_equity_metrics, "NVDA,AAPL,MSFT")

# Summary
ok = sum(1 for v in results.values() if v["status"] == "ok")
err = sum(1 for v in results.values() if v["status"] == "error")
print(f"\nCollection done: {ok} OK, {err} errors out of {len(results)}")

out_path = "command_output_reeval_r3.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"Saved to {out_path} ({os.path.getsize(out_path)} bytes)")
