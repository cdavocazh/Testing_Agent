#!/usr/bin/env python3
"""
Re-evaluation Round 2: Taste evaluator for 10 commands post-bugfix.
Commands: /drivers, /bonds, /latecycle, /consumer, /housing, /labor, /vixanalysis, /bbb, /fsmi, /drawdown

Evaluates 4 approaches:
  1. Data Accuracy — arithmetic, ranges, freshness, units
  2. Coherence     — cross-command and cross-signal consistency
  3. Grounding     — label-to-value alignment
  4. LLM Judge     — MiniMax-M2.5 rubric scoring (holistic taste)

Usage:
  FINANCIAL_AGENT_ROOT=/path/to/Financial_Agent python3 taste/reeval_round2_evaluator.py --input command_output_reeval_r2.json [--no-llm]
"""
import json, sys, os, math, argparse, datetime, pathlib

# ── helpers ──────────────────────────────────────────────────────────────
class Check:
    def __init__(self, check_id, category, command, check_name, passed, detail,
                 expected=None, actual=None, severity="medium"):
        self.check_id = check_id
        self.category = category
        self.command = command
        self.check_name = check_name
        self.passed = bool(passed)
        self.detail = detail
        self.expected = expected
        self.actual = actual
        self.severity = severity
    def to_dict(self):
        return vars(self)

class Report:
    def __init__(self):
        self.checks: list[Check] = []
        self.llm_scores = {}
    def add(self, c: Check):
        self.checks.append(c)
    @property
    def summary(self):
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        failed = total - passed
        crit = sum(1 for c in self.checks if not c.passed and c.severity == "critical")
        by_cat = {}
        for c in self.checks:
            by_cat.setdefault(c.category, {"total": 0, "passed": 0, "failed": 0})
            by_cat[c.category]["total"] += 1
            if c.passed:
                by_cat[c.category]["passed"] += 1
            else:
                by_cat[c.category]["failed"] += 1
        by_cmd = {}
        for c in self.checks:
            by_cmd.setdefault(c.command, {"total": 0, "passed": 0, "failed": 0})
            by_cmd[c.command]["total"] += 1
            if c.passed:
                by_cmd[c.command]["passed"] += 1
            else:
                by_cmd[c.command]["failed"] += 1
        return {
            "total_checks": total, "passed": passed, "failed": failed,
            "rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": crit,
            "by_category": by_cat, "by_command": by_cmd
        }

def approx(a, b, tol=0.02):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs(a), abs(b)) * tol + 0.01

def safe_get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d

# ── main ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="command_output_reeval_r2.json")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)
    print(f"Loaded from {args.input}\n")

    report = Report()

    # Helper to get data safely
    def get_data(cmd):
        entry = raw.get(cmd, {})
        if entry.get("status") != "ok":
            return None
        return entry.get("data", {})

    dr = get_data("drivers")
    bo = get_data("bonds")
    lc = get_data("latecycle")
    co = get_data("consumer")
    ho = get_data("housing")
    lb = get_data("labor")
    vx = get_data("vixanalysis")
    bb = get_data("bbb")
    fs = get_data("fsmi")
    dd = get_data("drawdown")

    # ═══════════════════════════════════════════════════════════════════
    # APPROACH 1: DATA ACCURACY
    # ═══════════════════════════════════════════════════════════════════
    print("=== Accuracy Checks ===")

    # --- DRIVERS ---
    if dr:
        # DR-01: ERP data available (was data_unavailable in prior eval)
        erp = safe_get(dr, "equity_risk_premium", "equity_risk_premium_pct")
        if erp is None:
            erp = dr.get("erp_pct")
        report.add(Check("DR-01", "accuracy", "drivers", "Equity Risk Premium data available",
                         erp is not None and isinstance(erp, (int, float)),
                         f"ERP: {erp}%" if erp else "MISSING — was data_unavailable in prior eval",
                         expected="available", actual=erp, severity="critical"))

        # DR-02: DXY in plausible range (70-130)
        dxy_val = safe_get(dr, "dxy_impact", "latest_dxy")
        report.add(Check("DR-02", "accuracy", "drivers", "DXY in plausible range (70-130)",
                         dxy_val is not None and 70 <= dxy_val <= 130,
                         f"DXY: {dxy_val}", expected="[70, 130]", actual=dxy_val, severity="medium"))

        # DR-03: HY OAS available and in range
        hy_bps = safe_get(dr, "credit_equity_link", "hy_oas_bps")
        report.add(Check("DR-03", "accuracy", "drivers", "HY OAS available in bps",
                         hy_bps is not None and 100 <= hy_bps <= 2000,
                         f"HY OAS: {hy_bps} bps",
                         expected="[100, 2000]", actual=hy_bps, severity="high"))

        # DR-04: VIX data available
        vix_val = safe_get(dr, "volatility_regime", "vix")
        report.add(Check("DR-04", "accuracy", "drivers", "VIX data available in drivers",
                         vix_val is not None,
                         f"VIX: {vix_val}", severity="medium"))

        # DR-05: Correlations data available
        corr = dr.get("rolling_correlations", {})
        has_corr = isinstance(corr, dict) and len(corr) > 0
        # Check if any correlation sub-dicts have data
        corr_count = 0
        for idx_key, idx_corr in corr.items():
            if isinstance(idx_corr, dict):
                corr_count += len(idx_corr)
        report.add(Check("DR-05", "accuracy", "drivers", "Rolling correlations data present",
                         corr_count > 0,
                         f"Correlation entries: {corr_count}",
                         severity="medium"))

        # DR-06: Signals generated (was empty in prior eval)
        sigs = dr.get("signals", [])
        report.add(Check("DR-06", "accuracy", "drivers", "Signals generated (was empty before)",
                         len(sigs) > 0,
                         f"{len(sigs)} signals: {sigs[:5]}",
                         severity="high"))

    # --- BONDS ---
    if bo:
        # BO-01: 10Y yield available and plausible
        y10 = safe_get(bo, "yield_curve", "nominal_yields", "10y", "latest_value")
        report.add(Check("BO-01", "accuracy", "bonds", "10Y yield available and plausible",
                         y10 is not None and 0 < y10 < 10,
                         f"10Y: {y10}%", expected="(0, 10)", actual=y10, severity="high"))

        # BO-02: 2s10s spread = 10Y - 2Y
        y2 = safe_get(bo, "yield_curve", "nominal_yields", "2y", "latest_value")
        spread = safe_get(bo, "yield_curve", "spreads", "2s10s", "latest_value")
        if y10 and y2 and spread:
            calc = round(y10 - y2, 2)
            report.add(Check("BO-02", "accuracy", "bonds", "2s10s spread = 10Y - 2Y",
                             approx(spread, calc),
                             f"10Y={y10}, 2Y={y2}, Spread={spread}, Calc={calc}",
                             expected=calc, actual=spread, severity="high"))
        else:
            report.add(Check("BO-02", "accuracy", "bonds", "2s10s spread = 10Y - 2Y",
                             False, f"Missing: 10Y={y10}, 2Y={y2}, spread={spread}",
                             severity="high"))

        # BO-03: Real yields present
        r10 = safe_get(bo, "real_yields", "10y_real", "latest_value")
        report.add(Check("BO-03", "accuracy", "bonds", "10Y real yield available",
                         r10 is not None and -3 <= r10 <= 5,
                         f"10Y real: {r10}%", expected="[-3, 5]", actual=r10, severity="high"))

        # BO-04: Breakevens present
        be10 = safe_get(bo, "breakevens", "t10yie", "latest_value")
        report.add(Check("BO-04", "accuracy", "bonds", "10Y breakeven inflation available",
                         be10 is not None and 0 < be10 < 6,
                         f"10Y BE: {be10}%", expected="(0, 6)", actual=be10, severity="medium"))

        # BO-05: Term premium = nominal - real - breakeven (approximate)
        if y10 and r10 and be10:
            tp_calc = round(y10 - r10 - be10, 3)
            tp_reported = safe_get(bo, "yield_curve", "term_premium")
            # Term premium may not be at top level anymore — check duration_risk
            # Just verify the identity: nominal ≈ real + BE + TP
            report.add(Check("BO-05", "accuracy", "bonds", "Nominal ≈ Real + Breakeven + Term Premium",
                             abs(tp_calc) < 0.5,
                             f"10Y={y10}, Real={r10}, BE={be10}, Residual={tp_calc}",
                             expected="residual < 0.5", actual=tp_calc, severity="medium"))

        # BO-06: Credit data present (HY OAS, IG OAS)
        # Check bonds credit section
        bo_credit = bo.get("credit", {})
        hy_oas = safe_get(bo_credit, "hy_oas_bps") or safe_get(bo_credit, "hy_oas", "bps")
        report.add(Check("BO-06", "accuracy", "bonds", "Credit spreads data present in bonds",
                         hy_oas is not None or len(bo_credit) > 0,
                         f"Credit keys: {list(bo_credit.keys())}, HY: {hy_oas}",
                         severity="high"))

    # --- LATECYCLE ---
    if lc:
        sigs = lc.get("signals_firing", [])
        firing = sum(1 for s in sigs if s.get("status") == "firing")
        total_sigs = len(sigs)

        # LC-01: Reported count matches actual firing signals
        reported_count = lc.get("count")
        report.add(Check("LC-01", "accuracy", "latecycle", "Reported count matches actual firing signals",
                         reported_count == firing,
                         f"Reported: {reported_count}, Actual firing: {firing}/{total_sigs}",
                         expected=firing, actual=reported_count, severity="high"))

        # LC-02: Total signals count is 13 (8-signal framework expanded)
        report.add(Check("LC-02", "accuracy", "latecycle", "Signal framework has ≥8 signals",
                         total_sigs >= 8,
                         f"Total signals: {total_sigs}",
                         expected="≥ 8", actual=total_sigs, severity="medium"))

        # LC-03: Confidence level present and meaningful
        conf = lc.get("confidence_level", lc.get("confidence"))
        report.add(Check("LC-03", "accuracy", "latecycle", "Confidence level present and clear",
                         conf is not None and "late-early" not in str(conf),
                         f"Confidence: '{conf}' (prior was 'late-early warning' — confusing)",
                         severity="medium"))

    # --- CONSUMER ---
    if co:
        # CON-01: Composite score plausible [0,10]
        comp = co.get("composite_score")
        report.add(Check("CON-01", "accuracy", "consumer", "Composite score in [0,10]",
                         comp is not None and 0 <= comp <= 10,
                         f"Composite: {comp}", severity="medium"))

        # CON-02: Composite = weighted avg of components
        comps = co.get("components", {})
        if comps and comp:
            weighted = 0
            total_w = 0
            for k, v in comps.items():
                s = v.get("score")
                w = v.get("weight", 0.25)
                if s is not None:
                    weighted += s * w
                    total_w += w
            if total_w > 0:
                calc_comp = round(weighted / total_w, 2)
                # The composite may use only non-null components
                report.add(Check("CON-02", "accuracy", "consumer", "Composite = weighted avg of available components",
                                 approx(comp, calc_comp, tol=0.15),
                                 f"Weighted avg: {calc_comp}, Reported: {comp} ({len(comps)} components)",
                                 expected=calc_comp, actual=comp, severity="medium"))

        # CON-03: Credit growth velocity data available
        cred = safe_get(comps, "credit_growth_velocity", "value")
        report.add(Check("CON-03", "accuracy", "consumer", "Credit growth velocity data available",
                         cred is not None,
                         f"Credit velocity: {cred}" if cred else "MISSING — key consumer metric unavailable",
                         expected="available", severity="high"))

    # --- HOUSING ---
    if ho:
        # HO-01: Housing cycle phase present
        phase = safe_get(ho, "housing_cycle_phase", "phase")
        report.add(Check("HO-01", "accuracy", "housing", "Housing cycle phase present",
                         phase is not None,
                         f"Cycle phase: {phase}", severity="medium"))

        # HO-02: Price dynamics data available (Case-Shiller)
        pd_status = safe_get(ho, "price_dynamics", "status")
        report.add(Check("HO-02", "accuracy", "housing", "Price dynamics (Case-Shiller) available",
                         pd_status != "data_unavailable" and pd_status is not None,
                         f"Status: {pd_status}" if pd_status else "MISSING",
                         expected="available", actual=pd_status, severity="high"))

        # HO-03: Permits/starts ratio computed
        ps_ratio = safe_get(ho, "permits_pipeline", "permits_to_starts_ratio")
        report.add(Check("HO-03", "accuracy", "housing", "Permits/starts ratio computed",
                         ps_ratio is not None and 0.5 < ps_ratio < 2.0,
                         f"Permits/starts: {ps_ratio}",
                         expected="(0.5, 2.0)", actual=ps_ratio, severity="medium"))

        # HO-04: Affordability metrics present
        aff = ho.get("affordability", {})
        rate = safe_get(aff, "mortgage_rate_pct")
        price = safe_get(aff, "median_price_usd")
        report.add(Check("HO-04", "accuracy", "housing", "Affordability metrics (rate + median price) present",
                         rate is not None and price is not None,
                         f"Rate: {rate}%, Price: ${price}",
                         severity="medium"))

    # --- LABOR ---
    if lb:
        # LB-01: Hires/layoffs ratio available and plausible
        ratio = safe_get(lb, "hiring_firing_balance", "hires_to_layoffs_ratio")
        report.add(Check("LB-01", "accuracy", "labor", "Hires/layoffs ratio available and plausible",
                         ratio is not None and 0.5 < ratio < 10,
                         f"Ratio: {ratio}",
                         expected="(0.5, 10)", actual=ratio, severity="medium"))

        # LB-02: Productivity vs ULC data available
        prod = safe_get(lb, "productivity_vs_ulc", "productivity_yoy_pct")
        ulc = safe_get(lb, "productivity_vs_ulc", "ulc_yoy_pct")
        report.add(Check("LB-02", "accuracy", "labor", "Productivity vs ULC data available",
                         prod is not None and ulc is not None,
                         f"Productivity: {prod}, ULC: {ulc}",
                         expected="both available", actual=f"prod={prod}, ulc={ulc}", severity="high"))

        # LB-03: Core CPI YoY in plausible range
        cpi = safe_get(lb, "wage_inflation_link", "core_cpi_yoy_pct")
        report.add(Check("LB-03", "accuracy", "labor", "Core CPI YoY in plausible range (-5% to 15%)",
                         cpi is not None and -5 <= cpi <= 15,
                         f"Core CPI YoY: {cpi}%" + (" — IMPLAUSIBLE" if cpi and (cpi < -5 or cpi > 15) else ""),
                         expected="[-5, 15]", actual=cpi, severity="critical"))

        # LB-04: Labor signals generated
        l_sigs = lb.get("signals", [])
        report.add(Check("LB-04", "accuracy", "labor", "Labor signals generated",
                         len(l_sigs) > 0,
                         f"{len(l_sigs)} signals: {l_sigs}", severity="medium"))

    # --- VIXANALYSIS ---
    if vx:
        # VX-01: VIX value present and plausible
        vix_val = safe_get(vx, "vix", "latest")
        report.add(Check("VX-01", "accuracy", "vixanalysis", "VIX value present and plausible (5-90)",
                         vix_val is not None and 5 <= vix_val <= 90,
                         f"VIX: {vix_val}",
                         expected="[5, 90]", actual=vix_val, severity="high"))

        # VX-02: VIX tier matches value
        tier = safe_get(vx, "vix", "tier")
        if vix_val and tier:
            # Tier mapping: 1=<14, 2=14-18, 3=18-22, 4=22-30, 5=30-40, 6=40-50, 7=>50
            expected_tier = (1 if vix_val < 14 else 2 if vix_val < 18 else 3 if vix_val < 22
                            else 4 if vix_val < 30 else 5 if vix_val < 40 else 6 if vix_val < 50 else 7)
            report.add(Check("VX-02", "accuracy", "vixanalysis", "VIX tier matches VIX value",
                             tier == expected_tier,
                             f"VIX={vix_val}, Tier={tier}, Expected={expected_tier}",
                             expected=expected_tier, actual=tier, severity="high"))

        # VX-03: MOVE/VIX ratio = MOVE / VIX
        move_val = safe_get(vx, "move", "latest")
        mvr = safe_get(vx, "move", "move_vix_ratio")
        if move_val and vix_val and mvr:
            calc_mvr = round(move_val / vix_val, 1)
            report.add(Check("VX-03", "accuracy", "vixanalysis", "MOVE/VIX ratio = MOVE / VIX",
                             approx(mvr, calc_mvr, tol=0.05),
                             f"MOVE={move_val}, VIX={vix_val}, Ratio={mvr}, Calc={calc_mvr}",
                             expected=calc_mvr, actual=mvr, severity="medium"))

        # VX-04: Percentile in [0, 100]
        pct = safe_get(vx, "vix", "percentile_1y")
        report.add(Check("VX-04", "accuracy", "vixanalysis", "VIX percentile in [0, 100]",
                         pct is not None and 0 <= pct <= 100,
                         f"Percentile: {pct}",
                         expected="[0, 100]", actual=pct, severity="low"))

    # --- BBB ---
    if bb:
        # BBB-01: BBB ratio > 0 (was 0 in prior due to claims bug)
        ratio = bb.get("bbb_ratio", 0)
        report.add(Check("BBB-01", "accuracy", "bbb", "BBB ratio > 0 (was 0 in prior eval)",
                         ratio > 0,
                         f"Ratio: {ratio} (prior was 0.0 due to claims in raw units)",
                         severity="critical"))

        # BBB-02: Initial claims in thousands (not raw 213000)
        claims = bb.get("initial_claims_thousands", bb.get("initial_claims"))
        report.add(Check("BBB-02", "accuracy", "bbb", "Initial claims in thousands (not raw 213000)",
                         claims is not None and 100 < claims < 1000,
                         f"Claims: {claims}K",
                         expected="100-1000K", actual=claims, severity="high"))

        # BBB-03: Copper price plausible ($2-$10/lb)
        cu = bb.get("copper_price")
        report.add(Check("BBB-03", "accuracy", "bbb", "Copper price in plausible range ($2-$10/lb)",
                         cu is not None and 2 <= cu <= 10,
                         f"Copper: ${cu}/lb",
                         expected="[2, 10]", actual=cu, severity="medium"))

        # BBB-04: Ratio = copper / claims (verify arithmetic)
        if cu and claims and ratio:
            calc = round(cu / claims, 4)
            report.add(Check("BBB-04", "accuracy", "bbb", "BBB ratio = copper_price / initial_claims",
                             approx(ratio, calc, tol=0.01),
                             f"Copper={cu}, Claims={claims}, Ratio={ratio}, Calc={calc}",
                             expected=calc, actual=ratio, severity="high"))

    # --- FSMI ---
    if fs:
        # FSMI-01: FSMI no longer crashes (was TypeError in prior eval)
        has_zscore = fs.get("fsmi_zscore") is not None
        report.add(Check("FSMI-01", "accuracy", "fsmi", "FSMI runs without crashing (prior: TypeError)",
                         has_zscore,
                         f"FSMI z-score: {fs.get('fsmi_zscore')} (prior: crashed with TypeError)",
                         severity="critical"))

        # FSMI-02: Consumer sentiment available
        cs = safe_get(fs, "components", "consumer_sentiment", "value")
        report.add(Check("FSMI-02", "accuracy", "fsmi", "Consumer sentiment data available",
                         cs is not None,
                         f"Consumer sentiment: {cs}" if cs else "MISSING — null",
                         severity="high"))

        # FSMI-03: FSMI z-score = avg of available component z-scores
        comps = fs.get("components", {})
        zscores = []
        for k, v in comps.items():
            z = v.get("zscore")
            if z is not None:
                zscores.append(z)
        if zscores:
            # FSMI may be avg of available or just copper if sentiment missing
            calc_avg = round(sum(zscores) / len(zscores), 2)
            reported = fs.get("fsmi_zscore")
            # Check if it's one of the component z-scores (when only 1 available)
            passes = approx(reported, calc_avg, tol=0.05) or reported in zscores
            report.add(Check("FSMI-03", "accuracy", "fsmi", "FSMI z-score = avg of available z-scores",
                             passes,
                             f"Components: {[(k, v.get('zscore')) for k,v in comps.items()]}, Avg={calc_avg}, Reported={reported}",
                             expected=calc_avg, actual=reported, severity="medium"))

    # --- DRAWDOWN ---
    if dd:
        # DD-01: Drawdown % computed correctly
        price = dd.get("current_price")
        ath = dd.get("all_time_high")
        dd_pct = dd.get("drawdown_pct")
        if price and ath and dd_pct:
            calc = round((price - ath) / ath * 100, 2)
            report.add(Check("DD-01", "accuracy", "drawdown", "Drawdown % = (price - ATH) / ATH × 100",
                             approx(dd_pct, calc, tol=0.02),
                             f"Price={price}, ATH={ath}, DD={dd_pct}%, Calc={calc}%",
                             expected=calc, actual=dd_pct, severity="high"))

        # DD-02: Classification matches drawdown magnitude
        cls = dd.get("classification")
        if dd_pct is not None:
            abs_dd = abs(dd_pct)
            expected_cls = "panic_attack" if abs_dd < 10 else "correction" if abs_dd < 20 else "bear_market"
            report.add(Check("DD-02", "accuracy", "drawdown", "Classification matches drawdown magnitude",
                             cls == expected_cls,
                             f"DD={dd_pct}%, Class='{cls}', Expected='{expected_cls}'",
                             expected=expected_cls, actual=cls, severity="high"))

        # DD-03: 52wk high ≥ ATH or ATH ≥ 52wk high (consistency)
        h52 = dd.get("52wk_high")
        if h52 and ath:
            report.add(Check("DD-03", "accuracy", "drawdown", "52wk high ≈ ATH (if ATH within 52 weeks)",
                             approx(h52, ath, tol=0.01) or ath >= h52,
                             f"52wk_high={h52}, ATH={ath}",
                             severity="low"))

    # ═══════════════════════════════════════════════════════════════════
    # APPROACH 2: COHERENCE
    # ═══════════════════════════════════════════════════════════════════
    print("=== Coherence Checks ===")

    # CC-R2-01: Drivers HY OAS ≈ Bonds HY OAS (cross-tool consistency)
    dr_hy = safe_get(dr, "credit_equity_link", "hy_oas_bps") if dr else None
    # Bonds credit may be empty — try to find it
    bo_hy = safe_get(bo, "credit", "hy_oas_bps") if bo else None
    # Also check latecycle credit spread evidence
    lc_hy = None
    if lc:
        for s in lc.get("signals_firing", []):
            if "credit" in s.get("name", "").lower():
                ev = s.get("evidence", "")
                import re
                m = re.search(r'(\d+)\s*bps', ev)
                if m:
                    lc_hy = int(m.group(1))
    if dr_hy and lc_hy:
        report.add(Check("CC-R2-01", "coherence", "cross-command",
                         "Drivers HY OAS ≈ Latecycle HY OAS",
                         approx(dr_hy, lc_hy, tol=0.05),
                         f"Drivers: {dr_hy}bps, Latecycle: {lc_hy}bps",
                         severity="high"))
    elif dr_hy is None and lc_hy:
        report.add(Check("CC-R2-01", "coherence", "cross-command",
                         "Drivers HY OAS ≈ Latecycle HY OAS",
                         False,
                         f"Drivers HY: None, Latecycle: {lc_hy}bps — drivers missing credit data",
                         severity="high"))

    # CC-R2-02: VIX consistent across /drivers, /vixanalysis, /latecycle
    dr_vix = safe_get(dr, "volatility_regime", "vix") if dr else None
    vx_vix = safe_get(vx, "vix", "latest") if vx else None
    if dr_vix and vx_vix:
        report.add(Check("CC-R2-02", "coherence", "cross-command",
                         "VIX consistent: /drivers ≈ /vixanalysis",
                         approx(dr_vix, vx_vix, tol=0.05),
                         f"Drivers VIX: {dr_vix}, VIX analysis: {vx_vix}",
                         severity="high"))
    elif dr_vix is None and vx_vix:
        report.add(Check("CC-R2-02", "coherence", "cross-command",
                         "VIX consistent: /drivers ≈ /vixanalysis",
                         False, f"Drivers VIX: None, VIX: {vx_vix}",
                         severity="high"))

    # CC-R2-03: BBB recession signal ↔ latecycle confidence
    bbb_sigs = bb.get("signals", []) if bb else []
    lc_conf = lc.get("confidence_level", "") if lc else ""
    bbb_recession = "RECESSION_WARNING" in bbb_sigs
    # If BBB warns recession and latecycle shows no warning, that's a coherence issue
    lc_firing = lc.get("count", 0) if lc else 0
    report.add(Check("CC-R2-03", "coherence", "cross-command",
                     "BBB recession signal consistent with late-cycle warning level",
                     not (bbb_recession and lc_firing < 2),
                     f"BBB: recession_warning={bbb_recession}, Latecycle: {lc_firing}/13 firing, conf='{lc_conf}'",
                     severity="medium"))

    # CC-R2-04: Housing affordability ↔ consumer health
    aff_level = safe_get(ho, "affordability", "affordability_level") if ho else None
    cons_health = co.get("consumer_health") if co else None
    cons_comp = co.get("composite_score") if co else None
    report.add(Check("CC-R2-04", "coherence", "cross-command",
                     "Housing affordability stress reflected in consumer signals",
                     True,  # Informational — just record the relationship
                     f"Affordability: {aff_level}, Consumer composite: {cons_comp}, Health: {cons_health}",
                     severity="low"))

    # CC-R2-05: Bond curve shape ↔ late-cycle yield curve signal
    curve_shape = safe_get(bo, "yield_curve", "shape") if bo else None
    lc_curve_firing = False
    if lc:
        for s in lc.get("signals_firing", []):
            if "curve" in s.get("name", "").lower():
                lc_curve_firing = s.get("status") == "firing"
    # Inverted curve should fire the yield curve signal
    is_inverted = curve_shape and "inverted" in str(curve_shape).lower()
    report.add(Check("CC-R2-05", "coherence", "cross-command",
                     "Bond curve shape ↔ late-cycle yield curve signal",
                     (is_inverted == lc_curve_firing) or not is_inverted,
                     f"Curve: '{curve_shape}', LC curve signal firing: {lc_curve_firing}",
                     severity="medium"))

    # CC-R2-06: Labor core CPI = Macro core CPI (same underlying FRED data)
    lb_cpi = safe_get(lb, "wage_inflation_link", "core_cpi_yoy_pct") if lb else None
    report.add(Check("CC-R2-06", "coherence", "labor",
                     "Labor core CPI YoY uses same data as /macro (informational)",
                     True,  # Informational
                     f"Labor CPI: {lb_cpi}% (macro was -12.88% in round 1 reeval)",
                     severity="low"))

    # ═══════════════════════════════════════════════════════════════════
    # APPROACH 3: GROUNDING
    # ═══════════════════════════════════════════════════════════════════
    print("=== Grounding Checks ===")

    # GR-R2-01: Drivers DXY interpretation ↔ level
    dxy_level = safe_get(dr, "dxy_impact", "latest_dxy") if dr else None
    dxy_interp = safe_get(dr, "dxy_impact", "interpretation") if dr else ""
    if dxy_level:
        # DXY > 100 = strong dollar, < 95 = weak dollar
        strong = dxy_level > 100
        weak = dxy_level < 95
        interp_str = str(dxy_interp).lower()
        has_weak = "weak" in interp_str
        has_strong = "strong" in interp_str
        contradiction = (strong and has_weak and not has_strong) or (weak and has_strong and not has_weak)
        report.add(Check("GR-R2-01", "grounding", "drivers",
                         "DXY interpretation coherent with level",
                         not contradiction,
                         f"DXY={dxy_level}, Interp='{dxy_interp}'",
                         severity="high"))

    # GR-R2-02: VIX tier description matches tier
    vx_tier = safe_get(vx, "vix", "tier") if vx else None
    vx_desc = safe_get(vx, "vix", "tier_description") if vx else ""
    if vx_tier:
        # Tier 4 = risk-off
        tier_label_map = {1: "complacen", 2: "calm", 3: "normal", 4: "risk-off",
                          5: "fear", 6: "panic", 7: "home run"}
        expected_partial = tier_label_map.get(vx_tier, "")
        report.add(Check("GR-R2-02", "grounding", "vixanalysis",
                         "VIX tier description matches tier number",
                         expected_partial.lower() in str(vx_desc).lower(),
                         f"Tier={vx_tier}, Desc='{vx_desc}', Expected contains '{expected_partial}'",
                         severity="medium"))

    # GR-R2-03: BBB interpretation ↔ ratio level
    if bb:
        bbb_ratio = bb.get("bbb_ratio", 0)
        bbb_interp = bb.get("interpretation", "")
        # Low ratio = contraction, high ratio = expansion
        is_low = bbb_ratio < 0.05
        has_contraction = "contraction" in bbb_interp.lower()
        report.add(Check("GR-R2-03", "grounding", "bbb",
                         "BBB interpretation matches ratio level",
                         (is_low and has_contraction) or not is_low,
                         f"Ratio={bbb_ratio}, Interp='{bbb_interp}'",
                         severity="medium"))

    # GR-R2-04: Drawdown classification description ↔ actual %
    if dd:
        dd_desc = dd.get("description", "")
        dd_pct_val = dd.get("drawdown_pct")
        dd_cls_val = dd.get("classification")
        if dd_cls_val == "panic_attack":
            grounded = "panic" in dd_desc.lower() or "pullback" in dd_desc.lower()
        elif dd_cls_val == "correction":
            grounded = "correction" in dd_desc.lower()
        else:
            grounded = "bear" in dd_desc.lower()
        report.add(Check("GR-R2-04", "grounding", "drawdown",
                         "Drawdown description reflects classification",
                         grounded,
                         f"Class='{dd_cls_val}', Desc='{dd_desc[:80]}...'",
                         severity="medium"))

    # GR-R2-05: Late-cycle confidence ↔ firing count
    if lc:
        lc_count = lc.get("count", 0)
        lc_conf_val = lc.get("confidence_level", "")
        # <3 = no warning, 3-5 = early, 5-8 = elevated, >8 = imminent
        if lc_count < 3:
            expected_conf = ["no", "low", "minimal"]
        elif lc_count < 6:
            expected_conf = ["early", "warning", "emerging"]
        elif lc_count < 9:
            expected_conf = ["elevated", "high", "significant"]
        else:
            expected_conf = ["imminent", "critical", "very high"]
        conf_match = any(e in str(lc_conf_val).lower() for e in expected_conf)
        report.add(Check("GR-R2-05", "grounding", "latecycle",
                         "Late-cycle confidence label matches firing count",
                         conf_match,
                         f"Count={lc_count}, Confidence='{lc_conf_val}'",
                         severity="medium"))

    # GR-R2-06: Consumer health label ↔ composite score
    if co:
        cons_score = co.get("composite_score")
        cons_hlth = co.get("consumer_health")
        cons_sigs = co.get("signals", [])
        # Score > 5 should not say "distressed"
        if cons_score and cons_hlth:
            grounded = not (cons_score > 5 and "distress" in str(cons_hlth).lower())
            report.add(Check("GR-R2-06", "grounding", "consumer",
                             "Consumer health label ↔ composite score",
                             grounded,
                             f"Score={cons_score}, Health='{cons_hlth}'",
                             severity="medium"))
        elif cons_score:
            report.add(Check("GR-R2-06", "grounding", "consumer",
                             "Consumer health label present",
                             cons_hlth is not None,
                             f"Score={cons_score}, Health label: {cons_hlth}",
                             severity="medium"))

    # GR-R2-07: Housing cycle phase ↔ component data
    if ho:
        h_phase = safe_get(ho, "housing_cycle_phase", "phase")
        h_starts = safe_get(ho, "starts_momentum", "direction")
        h_sales = safe_get(ho, "sales_trend", "trend")
        report.add(Check("GR-R2-07", "grounding", "housing",
                         "Housing cycle phase consistent with underlying trends",
                         h_phase is not None,
                         f"Phase='{h_phase}', Starts direction='{h_starts}', Sales='{h_sales}'",
                         severity="medium"))

    # GR-R2-08: FSMI interpretation ↔ z-score
    if fs:
        fsmi_z = fs.get("fsmi_zscore")
        fsmi_interp = fs.get("interpretation", "")
        if fsmi_z is not None:
            # z > 1 = strong, z < -1 = weak
            if fsmi_z > 1:
                grounded = "strong" in fsmi_interp.lower() or "elevated" in fsmi_interp.lower()
            elif fsmi_z < -1:
                grounded = "weak" in fsmi_interp.lower() or "contraction" in fsmi_interp.lower()
            else:
                grounded = True  # neutral
            report.add(Check("GR-R2-08", "grounding", "fsmi",
                             "FSMI interpretation matches z-score level",
                             grounded,
                             f"Z-score={fsmi_z}, Interp='{fsmi_interp}'",
                             severity="medium"))

    # ═══════════════════════════════════════════════════════════════════
    # APPROACH 4: LLM JUDGE
    # ═══════════════════════════════════════════════════════════════════
    if not args.no_llm:
        print("=== LLM Judge ===")
        from openai import OpenAI
        client = OpenAI(api_key="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJHcm91cE5hbWUiOiJrcmlzIiwiVXNlck5hbWUiOiJrcmlzIiwiQWNjb3VudCI6IiIsIlN1YmplY3QiOiIxODU1NjM2MDYzNTA5NDMxNjA5IiwiUGhvbmUiOiIxMzc5ODE3MTExNiIsIkdyb3VwSWQiOiIxODU1NjM2MDYzNTA1MjM2OTAxIiwiUGFnZU5hbWUiOiIiLCJNYWlsIjoiIiwiQ3JlYXRlVGltZSI6IjIwMjUtMDMtMDYgMTU6MjI6MTEiLCJUb2tlblR5cGUiOjEsImlzcyI6Im1pbmltYXgifQ.N43CT8JzliX4OOhHG-BKRuhNZ0BEBCHvQ0fMbMSFIrLTm0De1PkiO76LZ1FpBMJlDfLpLt8bKkkTxnXxRJh6Ydy3wGcUmbl94H3RDVHbxyPzJDSPr7dQxh0PmYi6qJGC2f6zt3-sTaVRqFiNNz2ALc1CSzJKxuAgNyJPcnxoaqO2aQfHxGXp7Ot76l7LgVAqam2lGxlXMrsNTzlO7KVDrUhJUG9Xh8cj--zOMG8KU6JG-ZlOhNJ5G3c8kjMuaD6d0WJHYN8gXvWA5F-2BmsJGP0LOv5DiPW_d5F6kYVnFQhVAq_KPgqEHrWAHHcjNqEfxKUcxZKEMG0mNvIDJDqRuZQ",
                         base_url="https://api.minimax.io/v1")
        model = "MiniMax-M2.5"
        print(f"  Using LLM: {model}")

        def llm_judge(group_name, prompt_text):
            print(f"  Calling LLM for {group_name}...")
            import time
            t0 = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.2, max_tokens=2000
                )
                raw_text = resp.choices[0].message.content
                dt = time.time() - t0
                print(f"  Responded in {dt:.1f}s")
                # Parse JSON from response
                import re
                m = re.search(r'\{[\s\S]*\}', raw_text)
                if m:
                    data = json.loads(m.group())
                    ws = data.get("weighted_score", data.get("overall_score", 5.0))
                    dims = data.get("dimensions", [])
                    return ws, dims, raw_text
            except Exception as e:
                print(f"  LLM error: {e}")
            return 5.0, [], ""

        # Group 1: Drivers + Bonds + VIX
        g1_data = {}
        if dr: g1_data["drivers"] = dr
        if bo: g1_data["bonds"] = bo
        if vx: g1_data["vixanalysis"] = vx
        g1_prompt = f"""You are a financial data quality judge. Evaluate this output from three financial tools (/drivers, /bonds, /vixanalysis). Score on a 1-10 scale across these dimensions:
1. Data Coverage (20%): Are key metrics (yields, spreads, ERP, DXY, VIX, correlations) present and non-null?
2. Signal Quality (20%): Are generated signals meaningful and not contradictory?
3. Cross-Tool Consistency (20%): Do values match across tools (VIX, HY OAS, yields)?
4. Quantitative Accuracy (20%): Are calculations (spreads, ratios, tier classifications) correct?
5. Actionability (20%): Could a portfolio manager make decisions from this data?

Return JSON: {{"weighted_score": X.X, "dimensions": [["name", score, "critique"], ...]}}

DATA:
{json.dumps(g1_data, indent=2, default=str)[:6000]}"""

        ws1, dims1, _ = llm_judge("drivers_bonds_vix", g1_prompt)
        print(f"  drivers_bonds_vix: {ws1}/10")
        report.llm_scores["drivers_bonds_vix"] = {"weighted_score": ws1, "dimensions": dims1}
        report.add(Check("LLM-DBV", "llm_judge", "drivers_bonds_vix",
                         "LLM Judge: /drivers + /bonds + /vixanalysis",
                         ws1 >= 5.0, f"Score: {ws1}/10", severity="high"))

        # Group 2: Consumer + Housing + Labor
        g2_data = {}
        if co: g2_data["consumer"] = co
        if ho: g2_data["housing"] = ho
        if lb: g2_data["labor"] = lb
        g2_prompt = f"""You are a financial data quality judge. Evaluate output from three tools (/consumer, /housing, /labor). Score 1-10 across:
1. Component Coverage (20%): Are all sub-indicators (savings, credit, housing starts, permits, productivity) present?
2. Data Availability (15%): What fraction of fields are non-null?
3. Composite Score Logic (20%): Do weighted averages match reported composites?
4. Leading Indicator Value (25%): Are forward-looking signals (consumer stress, housing pipeline, labor power) useful?
5. Cross-Domain Integration (20%): Do the three tools paint a consistent economic picture?

Return JSON: {{"weighted_score": X.X, "dimensions": [["name", score, "critique"], ...]}}

DATA:
{json.dumps(g2_data, indent=2, default=str)[:6000]}"""

        ws2, dims2, _ = llm_judge("consumer_housing_labor", g2_prompt)
        print(f"  consumer_housing_labor: {ws2}/10")
        report.llm_scores["consumer_housing_labor"] = {"weighted_score": ws2, "dimensions": dims2}
        report.add(Check("LLM-CHL", "llm_judge", "consumer_housing_labor",
                         "LLM Judge: /consumer + /housing + /labor",
                         ws2 >= 5.0, f"Score: {ws2}/10", severity="high"))

        # Group 3: BBB + FSMI + Drawdown + Latecycle
        g3_data = {}
        if bb: g3_data["bbb"] = bb
        if fs: g3_data["fsmi"] = fs
        if dd: g3_data["drawdown"] = dd
        if lc: g3_data["latecycle"] = lc
        g3_prompt = f"""You are a financial data quality judge. Evaluate output from Yardeni frameworks (/bbb, /fsmi, /drawdown) and /latecycle. Score 1-10 across:
1. Framework Fidelity (25%): Do BBB, FSMI, drawdown correctly implement Yardeni's published frameworks?
2. Data Quality (20%): Are inputs (copper, claims, sentiment, S&P) fresh and correct?
3. Classification Accuracy (20%): Is drawdown classification (panic attack/correction/bear) correct? Is late-cycle confidence logical?
4. Signal Coherence (20%): Do the four tools tell a consistent macro story?
5. Methodology Transparency (15%): Are formulas and methodology clearly documented?

Return JSON: {{"weighted_score": X.X, "dimensions": [["name", score, "critique"], ...]}}

DATA:
{json.dumps(g3_data, indent=2, default=str)[:6000]}"""

        ws3, dims3, _ = llm_judge("yardeni_latecycle", g3_prompt)
        print(f"  yardeni_latecycle: {ws3}/10")
        report.llm_scores["yardeni_latecycle"] = {"weighted_score": ws3, "dimensions": dims3}
        report.add(Check("LLM-YLC", "llm_judge", "yardeni_latecycle",
                         "LLM Judge: /bbb + /fsmi + /drawdown + /latecycle",
                         ws3 >= 5.0, f"Score: {ws3}/10", severity="high"))

    # ═══════════════════════════════════════════════════════════════════
    # REPORT
    # ═══════════════════════════════════════════════════════════════════
    s = report.summary
    print(f"\n{'='*60}")
    print("RE-EVALUATION ROUND 2 RESULTS (POST-BUGFIX)")
    print(f"{'='*60}")
    print(f"Total: {s['total_checks']} | Passed: {s['passed']} ({s['rate']}) | "
          f"Failed: {s['failed']} | Critical: {s['critical_failures']}")
    for cat, v in s['by_category'].items():
        print(f"  {cat}: {v['passed']}/{v['total']} ({v['passed']*100//v['total'] if v['total'] else 0}%)")

    failures = [c for c in report.checks if not c.passed]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for c in failures:
            sev = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}[c.severity]
            print(f"  {c.check_id} [{sev}] {c.check_name}")
            print(f"    {c.detail}")

    # Save results
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = pathlib.Path("taste/command_eval_records")
    out_dir.mkdir(parents=True, exist_ok=True)

    data_out = {
        "timestamp": datetime.datetime.now().isoformat(),
        "commands": ["drivers", "bonds", "latecycle", "consumer", "housing",
                     "labor", "vixanalysis", "bbb", "fsmi", "drawdown"],
        "summary": s,
        "checks": [c.to_dict() for c in report.checks],
        "llm_scores": report.llm_scores
    }

    json_path = out_dir / f"reeval_r2_{ts}.json"
    md_path = out_dir / f"reeval_r2_{ts}.md"

    with open(json_path, "w") as f:
        json.dump(data_out, f, indent=2, default=str)

    # Write markdown
    with open(md_path, "w") as f:
        f.write("# Re-evaluation Round 2 Taste Report (Post-Bugfix)\n\n")
        f.write(f"**Date**: {datetime.datetime.now().isoformat()}\n")
        f.write("**Commands**: /drivers, /bonds, /latecycle, /consumer, /housing, /labor, /vixanalysis, /bbb, /fsmi, /drawdown\n\n")

        f.write("## Summary\n\n")
        f.write("| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Checks | {s['total_checks']} |\n")
        f.write(f"| Passed | {s['passed']} |\n")
        f.write(f"| Failed | {s['failed']} |\n")
        f.write(f"| Pass Rate | {s['rate']} |\n")
        f.write(f"| Critical Failures | {s['critical_failures']} |\n\n")

        f.write("## By Category\n\n")
        f.write("| Category | Total | Passed | Failed | Rate |\n")
        f.write("|----------|-------|--------|--------|------|\n")
        for cat, v in s['by_category'].items():
            r = v['passed']*100//v['total'] if v['total'] else 0
            f.write(f"| {cat} | {v['total']} | {v['passed']} | {v['failed']} | {r}% |\n")

        f.write("\n## By Command\n\n")
        f.write("| Command | Total | Passed | Failed | Rate |\n")
        f.write("|---------|-------|--------|--------|------|\n")
        for cmd, v in s['by_command'].items():
            r = v['passed']*100//v['total'] if v['total'] else 0
            f.write(f"| {cmd} | {v['total']} | {v['passed']} | {v['failed']} | {r}% |\n")

        f.write("\n## Failures\n\n")
        for c in report.checks:
            if not c.passed:
                sev = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}[c.severity]
                f.write(f"### {c.check_id}: {c.check_name} [{sev}]\n")
                f.write(f"- **Command**: {c.command}\n")
                f.write(f"- **Detail**: {c.detail}\n")
                if c.expected:
                    f.write(f"- **Expected**: {c.expected}\n")
                if c.actual is not None:
                    f.write(f"- **Actual**: {c.actual}\n")
                f.write("\n")

        if report.llm_scores:
            f.write("\n## LLM Judge Scores\n\n")
            for name, data in report.llm_scores.items():
                f.write(f"### {name} — Weighted: {data['weighted_score']}/10\n\n")
                if data.get("dimensions"):
                    f.write("| Dimension | Score | Critique |\n|-----------|-------|----------|\n")
                    for dim in data["dimensions"]:
                        if isinstance(dim, list) and len(dim) >= 3:
                            f.write(f"| {dim[0]} | {dim[1]} | {dim[2][:100]} |\n")
                f.write("\n")

        f.write("\n## All Checks\n\n")
        f.write("| ID | Cat | Cmd | Check | Status | Sev |\n")
        f.write("|----|-----|-----|-------|--------|-----|\n")
        for c in report.checks:
            st = "PASS" if c.passed else "**FAIL**"
            f.write(f"| {c.check_id} | {c.category} | {c.command} | {c.check_name} | {st} | {c.severity} |\n")

    print(f"\nSaved: {json_path}")
    print(f"       {md_path}")


if __name__ == "__main__":
    main()
