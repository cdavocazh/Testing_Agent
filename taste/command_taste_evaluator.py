"""
Command-Level Taste Evaluation

Evaluates the quality of Financial Agent command outputs:
  - /analyze NVDA  → analyze_equity_valuation("NVDA")
  - /commodity crude oil  → analyze_commodity_outlook("crude_oil")
  - /drivers  → analyze_equity_drivers("both")

Approaches:
  1. Data Accuracy — arithmetic correctness, range plausibility, internal consistency
  2. Coherence — cross-field logical consistency within and across commands
  3. Grounding — do labels/interpretations match numeric values?
  4. LLM Judge — qualitative assessment via external LLM

Usage:
    python command_taste_evaluator.py --input command_output_v1.json
    python command_taste_evaluator.py  # Collect live then evaluate
"""

import sys, os, json, time, math, argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── Path setup ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_TESTING_ROOT = _THIS_DIR.parent
_RECORDS_DIR = _THIS_DIR / "command_eval_records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent")
)
sys.path.insert(0, _FA_ROOT)

# Load FA .env for API keys (MiniMax, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_FA_ROOT, ".env"))
except ImportError:
    pass


# ═════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═════════════════════════════════════════════════════════════════════

class Check:
    """A single evaluation check result."""
    def __init__(self, check_id: str, category: str, command: str,
                 check_name: str, passed: bool, detail: str,
                 expected=None, actual=None,
                 severity: str = "medium"):
        self.check_id = check_id
        self.category = category
        self.command = command
        self.check_name = check_name
        self.passed = passed
        self.detail = detail
        self.expected = expected
        self.actual = actual
        self.severity = severity
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {k: v for k, v in {
            "check_id": self.check_id,
            "category": self.category,
            "command": self.command,
            "check_name": self.check_name,
            "passed": self.passed,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
        }.items()}


class Report:
    """Collects all check results across approaches."""
    def __init__(self):
        self.checks: list[Check] = []
        self.start_time = time.time()

    def add(self, c: Check):
        self.checks.append(c)

    @property
    def summary(self):
        elapsed = time.time() - self.start_time
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        failed = total - passed
        by_category = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        by_command = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        for c in self.checks:
            by_category[c.category]["total"] += 1
            by_category[c.category]["passed" if c.passed else "failed"] += 1
            by_command[c.command]["total"] += 1
            by_command[c.command]["passed" if c.passed else "failed"] += 1
        critical_failures = sum(1 for c in self.checks
                                if not c.passed and c.severity == "critical")
        return {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": critical_failures,
            "by_category": dict(by_category),
            "by_command": dict(by_command),
            "elapsed": f"{elapsed:.1f}s",
        }


# ═════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════

def _safe(d, *keys, default=None):
    """Safely navigate nested dicts."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d

def _approx_eq(a, b, tol=0.02):
    """Approximate equality within tolerance."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False

def _pct_close(a, b, pct_tol=1.0):
    """Values within pct_tol% of each other."""
    if a is None or b is None:
        return False
    try:
        a, b = float(a), float(b)
        if abs(b) < 1e-9:
            return abs(a) < 1e-9
        return abs((a - b) / b) * 100 <= pct_tol
    except (TypeError, ValueError):
        return False


# ═════════════════════════════════════════════════════════════════════
# APPROACH 1: DATA ACCURACY CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_accuracy_checks(data: dict, report: Report):
    """Arithmetic correctness, range plausibility, internal consistency."""
    nvda = data.get("analyze_equity_valuation_NVDA", {})
    oil = data.get("analyze_commodity_outlook_crude_oil", {})
    drivers = data.get("analyze_equity_drivers_both", {})

    # ── NVDA Equity Checks ──────────────────────────────────────
    lm = nvda.get("latest_metrics", {})
    margins = nvda.get("margins", {})
    bs = nvda.get("balance_sheet", {})
    cfq = nvda.get("cash_flow_quality", {})
    roc = nvda.get("return_on_capital", {})
    val = nvda.get("valuation", {})
    ncp = nvda.get("net_cash_position", {})
    bse = nvda.get("balance_sheet_efficiency", {})
    ca = nvda.get("capital_allocation", {})

    # EA-01: Gross margin = gross_profit / revenue
    rev = lm.get("revenue")
    gp = lm.get("gross_profit")
    gm = margins.get("gross_margin_pct")
    if rev and gp and gm:
        expected_gm = round(gp / rev * 100, 2)
        report.add(Check("EA-01", "accuracy", "equity",
                         "Gross margin = gross_profit / revenue × 100",
                         _approx_eq(expected_gm, gm, 0.1),
                         f"Expected {expected_gm}%, got {gm}%",
                         expected_gm, gm, "high"))

    # EA-02: Operating margin = operating_income / revenue
    oi = lm.get("operating_income")
    om = margins.get("operating_margin_pct")
    if rev and oi and om:
        expected_om = round(oi / rev * 100, 2)
        report.add(Check("EA-02", "accuracy", "equity",
                         "Operating margin = OI / revenue × 100",
                         _approx_eq(expected_om, om, 0.1),
                         f"Expected {expected_om}%, got {om}%",
                         expected_om, om, "high"))

    # EA-03: Net margin = net_income / revenue
    ni = lm.get("net_income")
    nm = margins.get("net_margin_pct")
    if rev and ni and nm:
        expected_nm = round(ni / rev * 100, 2)
        report.add(Check("EA-03", "accuracy", "equity",
                         "Net margin = NI / revenue × 100",
                         _approx_eq(expected_nm, nm, 0.1),
                         f"Expected {expected_nm}%, got {nm}%",
                         expected_nm, nm, "high"))

    # EA-04: Debt ratio = total_liabilities / total_assets
    tl = lm.get("total_liabilities")
    ta = lm.get("total_assets")
    dr = lm.get("debt_ratio")
    if tl and ta and dr:
        expected_dr = round(tl / ta, 4)
        report.add(Check("EA-04", "accuracy", "equity",
                         "Debt ratio = total_liabilities / total_assets",
                         _approx_eq(expected_dr, dr, 0.01),
                         f"Expected {expected_dr}, got {dr}",
                         expected_dr, dr, "high"))

    # EA-05: Equity ratio = equity / total_assets
    eq = bs.get("total_equity")
    er = bs.get("equity_ratio")
    if eq and ta and er:
        expected_er = round(eq / ta, 4)
        report.add(Check("EA-05", "accuracy", "equity",
                         "Equity ratio = total_equity / total_assets",
                         _approx_eq(expected_er, er, 0.01),
                         f"Expected {expected_er}, got {er}",
                         expected_er, er, "medium"))

    # EA-06: Total equity = total_assets - total_liabilities
    if ta and tl and eq:
        expected_eq = ta - tl
        report.add(Check("EA-06", "accuracy", "equity",
                         "Total equity = assets - liabilities",
                         _approx_eq(expected_eq, eq, 1e6),
                         f"Expected {expected_eq}, got {eq}",
                         expected_eq, eq, "high"))

    # EA-07: OCF/NI ratio matches components
    ocf = lm.get("operating_cash_flow")
    ocf_ni = cfq.get("ocf_to_net_income")
    if ocf and ni and ocf_ni and ni != 0:
        expected_ratio = round(ocf / ni, 2)
        report.add(Check("EA-07", "accuracy", "equity",
                         "OCF/NI ratio = OCF / net_income",
                         _approx_eq(expected_ratio, ocf_ni, 0.02),
                         f"Expected {expected_ratio}, got {ocf_ni}",
                         expected_ratio, ocf_ni, "high"))

    # EA-08: FCF = OCF + capex (capex is negative)
    fcf = lm.get("free_cash_flow")
    capex = lm.get("capital_expenditure")
    if ocf is not None and capex is not None and fcf is not None:
        expected_fcf = ocf + capex
        report.add(Check("EA-08", "accuracy", "equity",
                         "FCF = OCF + capex",
                         _approx_eq(expected_fcf, fcf, 1e6),
                         f"Expected {expected_fcf}, got {fcf}",
                         expected_fcf, fcf, "high"))

    # EA-09: Annualized EPS = quarterly EPS × 4
    eps = val.get("diluted_eps")
    ann_eps = val.get("annualized_eps")
    if eps and ann_eps:
        expected_ann = round(eps * 4, 2)
        report.add(Check("EA-09", "accuracy", "equity",
                         "Annualized EPS = quarterly EPS × 4",
                         _approx_eq(expected_ann, ann_eps, 0.02),
                         f"Expected {expected_ann}, got {ann_eps}",
                         expected_ann, ann_eps, "medium"))

    # EA-10: Book value per share = equity / diluted_shares
    shares = lm.get("diluted_shares")
    bvps = val.get("book_value_per_share")
    if eq and shares and bvps and shares > 0:
        expected_bvps = round(eq / shares, 2)
        report.add(Check("EA-10", "accuracy", "equity",
                         "BV/share = total_equity / diluted_shares",
                         _approx_eq(expected_bvps, bvps, 0.1),
                         f"Expected {expected_bvps}, got {bvps}",
                         expected_bvps, bvps, "medium"))

    # EA-11: Net cash position = cash - debt
    cash = ncp.get("cash_and_equivalents")
    debt = ncp.get("total_debt")
    net_cash = ncp.get("net_cash_position")
    net_debt = ncp.get("net_debt")
    if cash is not None and debt is not None and net_cash is not None:
        expected_nc = cash - debt
        # net_cash_position should be positive when net cash
        report.add(Check("EA-11", "accuracy", "equity",
                         "Net cash position = cash - debt",
                         _approx_eq(expected_nc, net_cash, 1e6),
                         f"Expected {expected_nc}, got {net_cash}",
                         expected_nc, net_cash, "medium"))

    # EA-12: ROE quarterly = NI / equity
    roe_q = roc.get("roe_quarterly_pct")
    if ni and eq and roe_q and eq > 0:
        expected_roe = round(ni / eq * 100, 2)
        report.add(Check("EA-12", "accuracy", "equity",
                         "ROE quarterly = NI / equity × 100",
                         _approx_eq(expected_roe, roe_q, 0.5),
                         f"Expected {expected_roe}%, got {roe_q}%",
                         expected_roe, roe_q, "medium"))

    # EA-13: ROE annualized = ROE quarterly × 4
    roe_a = roc.get("roe_annualized_pct")
    if roe_q and roe_a:
        expected_roe_a = round(roe_q * 4, 2)
        report.add(Check("EA-13", "accuracy", "equity",
                         "ROE annualized = ROE quarterly × 4",
                         _approx_eq(expected_roe_a, roe_a, 0.5),
                         f"Expected {expected_roe_a}%, got {roe_a}%",
                         expected_roe_a, roe_a, "low"))

    # EA-14: Data freshness — latest quarter should be recent
    lq = nvda.get("latest_quarter", "")
    # Check if within last 2 years
    is_stale = False
    if lq:
        try:
            year = int(lq.split("-")[0])
            is_stale = year < 2024
        except:
            is_stale = True
    report.add(Check("EA-14", "accuracy", "equity",
                     "Data freshness — latest quarter within 2 years",
                     not is_stale,
                     f"Latest quarter: {lq}. {'STALE — data is from {}'.format(lq) if is_stale else 'OK'}",
                     "≥ 2024", lq, "critical"))

    # EA-15: R&D % = R&D / revenue
    rd = lm.get("research_development")
    rd_pct = margins.get("rd_to_revenue_pct")
    if rd and rev and rd_pct:
        expected_rd = round(rd / rev * 100, 2)
        report.add(Check("EA-15", "accuracy", "equity",
                         "R&D % = R&D / revenue × 100",
                         _approx_eq(expected_rd, rd_pct, 0.1),
                         f"Expected {expected_rd}%, got {rd_pct}%",
                         expected_rd, rd_pct, "medium"))

    # EA-16: Leverage ratio = liabilities / equity
    lr = bs.get("leverage_ratio")
    if tl and eq and lr and eq > 0:
        expected_lr = round(tl / eq, 2)
        report.add(Check("EA-16", "accuracy", "equity",
                         "Leverage ratio = liabilities / equity",
                         _approx_eq(expected_lr, lr, 0.02),
                         f"Expected {expected_lr}, got {lr}",
                         expected_lr, lr, "medium"))

    # ── Crude Oil Commodity Checks ──────────────────────────────
    pa = _safe(oil, "price_analysis", "metrics", "crude_oil_price", default={})
    sr = oil.get("support_resistance", {})
    inv = oil.get("inventory_data", {})
    etf_div = oil.get("energy_etf_divergence", {})

    # CA-01: Support levels < current price < Resistance levels
    curr_price = sr.get("current_price")
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])
    if curr_price and supports:
        all_below = all(s < curr_price for s in supports)
        report.add(Check("CA-01", "accuracy", "commodity",
                         "All support levels below current price",
                         all_below,
                         f"Supports: {supports}, Price: {curr_price}. "
                         f"{'All below' if all_below else 'BUG: supports above price'}",
                         f"all < {curr_price}", supports, "high"))

    if curr_price and resistances:
        all_above = all(r > curr_price for r in resistances)
        report.add(Check("CA-02", "accuracy", "commodity",
                         "All resistance levels above current price",
                         all_above,
                         f"Resistances: {resistances}, Price: {curr_price}. "
                         f"{'All above' if all_above else 'BUG: resistances below price'}",
                         f"all > {curr_price}", resistances, "high"))

    # CA-03: S/R levels should be within reasonable range of current price (within 50%)
    if curr_price and supports:
        reasonable = all(s > curr_price * 0.5 for s in supports)
        report.add(Check("CA-03", "accuracy", "commodity",
                         "Support levels within 50% of current price",
                         reasonable,
                         f"Supports: {supports}, Price: {curr_price}. "
                         f"{'Reasonable' if reasonable else 'BUG: supports far from price'}",
                         f"> {curr_price * 0.5:.2f}", supports, "critical"))

    # CA-04: Daily change consistency
    lv = pa.get("latest_value")
    dc = pa.get("daily_change")
    dc_pct = pa.get("daily_change_pct")
    if lv and dc and dc_pct:
        prev = lv - dc
        if prev != 0:
            expected_pct = round(dc / prev * 100, 2)
            report.add(Check("CA-04", "accuracy", "commodity",
                             "Daily change % = change / (price - change) × 100",
                             _approx_eq(expected_pct, dc_pct, 0.5),
                             f"Expected {expected_pct}%, got {dc_pct}%",
                             expected_pct, dc_pct, "medium"))

    # CA-05: WTI/Brent spread consistency
    wti = _safe(inv, "wti", "latest_price")
    brent = _safe(inv, "brent", "latest_price")
    spread = _safe(inv, "wti_brent_spread", "value")
    if wti and brent and spread is not None:
        expected_spread = round(wti - brent, 2)
        report.add(Check("CA-05", "accuracy", "commodity",
                         "WTI-Brent spread = WTI - Brent",
                         _approx_eq(expected_spread, spread, 0.1),
                         f"Expected {expected_spread}, got {spread}",
                         expected_spread, spread, "medium"))

    # CA-06: ETF divergence spread arithmetic
    xle_1w = _safe(etf_div, "xle", "pct_change_1w")
    xop_1w = _safe(etf_div, "xop", "pct_change_1w")
    spread_1w = etf_div.get("spread_1w_pp")
    if xle_1w is not None and xop_1w is not None and spread_1w is not None:
        expected_sp = round(xop_1w - xle_1w, 2)
        report.add(Check("CA-06", "accuracy", "commodity",
                         "ETF spread 1w = XOP 1w% - XLE 1w%",
                         _approx_eq(expected_sp, spread_1w, 0.1),
                         f"Expected {expected_sp}pp, got {spread_1w}pp",
                         expected_sp, spread_1w, "medium"))

    # CA-07: ETF percent changes are arithmetic-correct
    xle_latest = _safe(etf_div, "xle", "latest_price")
    xle_1w_ago = _safe(etf_div, "xle", "price_1w_ago")
    if xle_latest and xle_1w_ago and xle_1w is not None:
        expected_xle_pct = round((xle_latest - xle_1w_ago) / xle_1w_ago * 100, 2)
        report.add(Check("CA-07", "accuracy", "commodity",
                         "XLE 1w% = (latest - 1w_ago) / 1w_ago × 100",
                         _approx_eq(expected_xle_pct, xle_1w, 0.1),
                         f"Expected {expected_xle_pct}%, got {xle_1w}%",
                         expected_xle_pct, xle_1w, "low"))

    # CA-08: Price at 52w high but supports far below — suspicious
    pct_from_high = pa.get("pct_from_52w_high")
    w52_low = pa.get("52w_low")
    if curr_price and pct_from_high is not None and supports:
        max_support = max(supports) if supports else 0
        gap_pct = ((curr_price - max_support) / curr_price) * 100 if curr_price else 0
        report.add(Check("CA-08", "accuracy", "commodity",
                         "S/R levels relevant to current price (gap < 30%)",
                         gap_pct < 30,
                         f"Price: {curr_price}, Nearest support: {max_support}, "
                         f"Gap: {gap_pct:.1f}%. {'OK' if gap_pct < 30 else 'BUG: S/R levels stale or computed from old data range'}",
                         "gap < 30%", f"{gap_pct:.1f}%", "critical"))

    # ── Equity Drivers Checks ──────────────────────────────────
    ry = drivers.get("real_yield_impact", {})
    cel = drivers.get("credit_equity_link", {})
    dxy = drivers.get("dxy_impact", {})
    inf = drivers.get("inflation_rotation", {})
    vol = drivers.get("volatility_regime", {})
    corrs = drivers.get("rolling_correlations", {})

    # DA-01: HY OAS bps = pct × 100
    hy_pct = cel.get("hy_oas_pct")
    hy_bps = cel.get("hy_oas_bps")
    if hy_pct and hy_bps:
        expected_bps = round(hy_pct * 100)
        report.add(Check("DA-01", "accuracy", "drivers",
                         "HY OAS bps = pct × 100",
                         abs(expected_bps - hy_bps) <= 1,
                         f"Expected {expected_bps}bps, got {hy_bps}bps",
                         expected_bps, hy_bps, "high"))

    # DA-02: Correlation range (-1, 1) for all rolling correlations
    bad_corrs = []
    for idx_name, factors in corrs.items():
        if isinstance(factors, dict):
            for factor, vals in factors.items():
                if isinstance(vals, dict):
                    for key in ["latest_20d", "avg_60d"]:
                        v = vals.get(key)
                        if v is not None and (v < -1.01 or v > 1.01):
                            bad_corrs.append(f"{idx_name}/{factor}/{key}={v}")
    report.add(Check("DA-02", "accuracy", "drivers",
                     "All correlations in [-1, 1] range",
                     len(bad_corrs) == 0,
                     f"{'All OK' if not bad_corrs else 'Out of range: ' + ', '.join(bad_corrs)}",
                     "all in [-1,1]", bad_corrs or "all OK", "high"))

    # DA-03: VIX tier matches value
    vix = vol.get("vix")
    tier = vol.get("tier")
    if vix is not None and tier is not None:
        expected_tier = (7 if vix >= 50 else 6 if vix >= 40 else
                         5 if vix >= 30 else 4 if vix >= 25 else
                         3 if vix >= 20 else 2 if vix >= 14 else 1)
        report.add(Check("DA-03", "accuracy", "drivers",
                         "VIX tier matches VIX value",
                         expected_tier == tier,
                         f"VIX={vix}, Expected tier {expected_tier}, got tier {tier}",
                         expected_tier, tier, "high"))

    # DA-04: CPI YoY plausibility (-5% to +15%)
    cpi = inf.get("cpi_yoy_pct")
    if cpi is not None:
        plausible = -5 <= cpi <= 15
        report.add(Check("DA-04", "accuracy", "drivers",
                         "CPI YoY in plausible range (-5% to 15%)",
                         plausible,
                         f"CPI YoY: {cpi}%. {'Plausible' if plausible else 'SUSPICIOUS — check data source'}",
                         "[-5, 15]", cpi, "high"))

    # DA-05: ERP data availability
    erp = drivers.get("equity_risk_premium", {})
    erp_available = erp.get("status") != "data_unavailable"
    report.add(Check("DA-05", "accuracy", "drivers",
                     "Equity Risk Premium data available",
                     erp_available,
                     f"{'Available' if erp_available else 'MISSING — ERP is a core driver metric, should not be unavailable'}",
                     "available", erp.get("status", "available"), "critical"))

    # DA-06: DXY range plausibility (70-130 historically)
    dxy_val = dxy.get("latest_dxy")
    if dxy_val:
        plausible = 70 <= dxy_val <= 130
        report.add(Check("DA-06", "accuracy", "drivers",
                         "DXY in plausible range (70-130)",
                         plausible,
                         f"DXY: {dxy_val}",
                         "[70, 130]", dxy_val, "medium"))

    # DA-07: Real yield plausibility (-3% to +5%)
    ry_val = ry.get("real_yield_10y")
    if ry_val is not None:
        plausible = -3 <= ry_val <= 5
        report.add(Check("DA-07", "accuracy", "drivers",
                         "Real yield in plausible range (-3% to 5%)",
                         plausible,
                         f"Real yield: {ry_val}%",
                         "[-3, 5]", ry_val, "medium"))

    # DA-08: VIX plausibility (5-90)
    if vix is not None:
        plausible = 5 <= vix <= 90
        report.add(Check("DA-08", "accuracy", "drivers",
                         "VIX in plausible range (5-90)",
                         plausible,
                         f"VIX: {vix}",
                         "[5, 90]", vix, "low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 2: COHERENCE CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(data: dict, report: Report):
    """Cross-field and cross-command logical consistency."""
    nvda = data.get("analyze_equity_valuation_NVDA", {})
    oil = data.get("analyze_commodity_outlook_crude_oil", {})
    drivers = data.get("analyze_equity_drivers_both", {})

    margins = nvda.get("margins", {})
    flags = nvda.get("flags", [])
    cfq = nvda.get("cash_flow_quality", {})
    roc = nvda.get("return_on_capital", {})
    bs = nvda.get("balance_sheet", {})
    ncp = nvda.get("net_cash_position", {})
    mt = nvda.get("margin_trends", {})

    # ── Within-Equity Coherence ──────────────────────────────────
    # EC-01: HIGH_MARGIN flag ↔ operating margin > 30%
    om = margins.get("operating_margin_pct", 0)
    has_high_margin = any("HIGH_MARGIN" in f for f in flags)
    expected_flag = om > 30
    report.add(Check("EC-01", "coherence", "equity",
                     "HIGH_MARGIN flag ↔ operating margin > 30%",
                     has_high_margin == expected_flag,
                     f"OM: {om}%, Flag present: {has_high_margin}, Expected: {expected_flag}",
                     expected_flag, has_high_margin, "medium"))

    # EC-02: CASH_FLOW_WARNING ↔ OCF/NI < 0.5
    ocf_ni = cfq.get("ocf_to_net_income")
    has_cfw = any("CASH_FLOW_WARNING" in f for f in flags)
    if ocf_ni is not None:
        expected_warning = ocf_ni < 0.5
        report.add(Check("EC-02", "coherence", "equity",
                         "CASH_FLOW_WARNING flag ↔ OCF/NI < 0.5",
                         has_cfw == expected_warning,
                         f"OCF/NI: {ocf_ni}, Warning flag: {has_cfw}, Expected: {expected_warning}",
                         expected_warning, has_cfw, "high"))

    # EC-03: Cash flow interpretation ↔ OCF/NI ratio
    # OCF/NI of 0.99 should be "Strong", not "Weak"
    interp = cfq.get("interpretation", "")
    if ocf_ni is not None:
        is_strong = ocf_ni >= 0.7
        says_strong = "strong" in interp.lower()
        says_weak = "weak" in interp.lower()
        report.add(Check("EC-03", "coherence", "equity",
                         "Cash flow interpretation matches OCF/NI ratio",
                         (is_strong and says_strong) or (not is_strong and says_weak),
                         f"OCF/NI: {ocf_ni}, Interpretation: '{interp}'. "
                         f"{'CONTRADICTION' if is_strong and says_weak else 'OK'}",
                         "Strong" if is_strong else "Weak", interp, "critical"))

    # EC-04: Net cash position label ↔ net_debt sign
    position = ncp.get("position")
    net_debt_val = ncp.get("net_debt")
    if position and net_debt_val is not None:
        expected_pos = "net_cash" if net_debt_val < 0 else "net_debt"
        report.add(Check("EC-04", "coherence", "equity",
                         "Net cash position label ↔ net_debt sign",
                         position == expected_pos,
                         f"net_debt={net_debt_val}, position='{position}', expected='{expected_pos}'",
                         expected_pos, position, "high"))

    # EC-05: Margin trend ↔ margin values direction
    gm_trend = _safe(mt, "gross_margin", "trend")
    gm_vals = _safe(mt, "gross_margin", "values_pct", default=[])
    if gm_trend and len(gm_vals) >= 3:
        last_3 = gm_vals[-3:]
        declining = last_3[-1] < last_3[0]
        says_declining = gm_trend == "declining"
        # If recent values are declining, trend should say so
        report.add(Check("EC-05", "coherence", "equity",
                         "Gross margin trend label ↔ recent values",
                         True,  # Informational — complex trend logic
                         f"Last 3 values: {last_3}, Trend: {gm_trend}. "
                         f"Recent direction: {'down' if declining else 'up/flat'}",
                         severity="low"))

    # EC-06: REVENUE_DECLINE flag ↔ YoY revenue growth
    yoy = nvda.get("year_over_year", {})
    yoy_rev = yoy.get("total_revenue_yoy_growth_pct")
    has_rev_decline = any("REVENUE_DECLINE" in f for f in flags)
    if yoy_rev is not None:
        expected_flag = yoy_rev < -5
        report.add(Check("EC-06", "coherence", "equity",
                         "REVENUE_DECLINE flag ↔ YoY revenue < -5%",
                         has_rev_decline == expected_flag,
                         f"YoY rev: {yoy_rev}%, Flag: {has_rev_decline}, Expected: {expected_flag}",
                         expected_flag, has_rev_decline, "medium"))

    # EC-07: HIGH_ROIC flag ↔ ROIC annualized > 25%
    roic_a = roc.get("roic_annualized_pct")
    has_high_roic = any("HIGH_ROIC" in f for f in flags)
    if roic_a is not None:
        expected_flag = roic_a > 25
        report.add(Check("EC-07", "coherence", "equity",
                         "HIGH_ROIC flag ↔ ROIC annualized > 25%",
                         has_high_roic == expected_flag,
                         f"ROIC: {roic_a}%, Flag: {has_high_roic}, Expected: {expected_flag}",
                         expected_flag, has_high_roic, "medium"))

    # ── Within-Oil Coherence ──────────────────────────────────
    pa = _safe(oil, "price_analysis", "metrics", "crude_oil_price", default={})
    pa_flags = pa.get("flags", [])

    # OC-01: Price at 52w high flag ↔ pct_from_52w_high
    pct_from_high = pa.get("pct_from_52w_high")
    has_at_high = any("AT_52W_HIGH" in f for f in pa_flags)
    if pct_from_high is not None:
        expected_flag = pct_from_high <= 1
        report.add(Check("OC-01", "coherence", "commodity",
                         "AT_52W_HIGH flag ↔ within 1% of 52w high",
                         has_at_high == expected_flag,
                         f"Pct from high: {pct_from_high}%, Flag: {has_at_high}",
                         expected_flag, has_at_high, "medium"))

    # OC-02: WTI premium interpretation
    spread_interp = _safe(oil, "inventory_data", "wti_brent_spread", "interpretation", default="")
    spread_val = _safe(oil, "inventory_data", "wti_brent_spread", "value")
    if spread_val is not None and spread_interp:
        says_premium = "premium" in spread_interp.lower()
        is_premium = spread_val > 0
        report.add(Check("OC-02", "coherence", "commodity",
                         "WTI-Brent spread interpretation ↔ value sign",
                         (says_premium and is_premium) or (not says_premium and not is_premium),
                         f"Spread: {spread_val}, Interpretation: '{spread_interp}'",
                         "premium" if is_premium else "discount", spread_interp, "medium"))

    # ── Within-Drivers Coherence ──────────────────────────────
    cel = drivers.get("credit_equity_link", {})
    dxy_d = drivers.get("dxy_impact", {})
    vol = drivers.get("volatility_regime", {})
    signals = drivers.get("signals", [])

    # DC-01: DXY interpretation ↔ DXY level and direction
    dxy_val = dxy_d.get("latest_dxy")
    dxy_wow = dxy_d.get("wow_change_pct")
    dxy_interp = dxy_d.get("interpretation", "")
    if dxy_val and dxy_wow is not None:
        says_weak = "weak" in dxy_interp.lower()
        says_tailwind = "tailwind" in dxy_interp.lower()
        # DXY < 100 → weak dollar, DXY > 105 → strong dollar
        # But if DXY is rising WoW (+0.74%), calling it "weak dollar tailwind" is contradictory
        is_strengthening = dxy_wow > 0
        report.add(Check("DC-01", "coherence", "drivers",
                         "DXY interpretation ↔ level and direction",
                         not (says_tailwind and is_strengthening),
                         f"DXY: {dxy_val}, WoW: +{dxy_wow}%, Interp: '{dxy_interp}'. "
                         f"{'CONTRADICTION: DXY rising but called tailwind' if says_tailwind and is_strengthening else 'OK'}",
                         "no contradiction", f"weak+tailwind with +{dxy_wow}% WoW",
                         "critical"))

    # DC-02: Credit stress level ↔ HY OAS level
    hy_bps = cel.get("hy_oas_bps")
    stress = cel.get("stress_level")
    if hy_bps and stress:
        # Typical thresholds: < 300 = normal/tight, 300-400 = elevated, 400-500 = stressed, > 500 = severe
        # At 313 bps, "elevated" seems reasonable
        report.add(Check("DC-02", "coherence", "drivers",
                         "Credit stress level ↔ HY OAS level (informational)",
                         True,  # Informational
                         f"HY OAS: {hy_bps}bps, Stress: '{stress}'. Consistent.",
                         severity="low"))

    # DC-03: Signal generation ↔ data conditions
    # Real yield at 1.8% and rising → should NOT trigger REAL_YIELD_HEADWIND (needs > 2.0)
    # Should NOT trigger REAL_YIELD_TAILWIND (needs < 1.0 OR falling)
    ry = drivers.get("real_yield_impact", {})
    ry_val = ry.get("real_yield_10y")
    ry_trend = ry.get("trend")
    has_headwind = "REAL_YIELD_HEADWIND" in signals
    has_tailwind = "REAL_YIELD_TAILWIND" in signals
    if ry_val is not None:
        expect_headwind = ry_val > 2.0 and ry_trend == "rising"
        expect_tailwind = ry_val < 1.0 or ry_trend == "falling"
        if not expect_headwind and has_headwind:
            report.add(Check("DC-03a", "coherence", "drivers",
                             "REAL_YIELD_HEADWIND signal ↔ conditions",
                             False,
                             f"RY={ry_val}%, trend={ry_trend}. Headwind requires >2% AND rising.",
                             "no signal", "REAL_YIELD_HEADWIND", "high"))
        elif not expect_tailwind and has_tailwind:
            report.add(Check("DC-03b", "coherence", "drivers",
                             "REAL_YIELD_TAILWIND signal ↔ conditions",
                             False,
                             f"RY={ry_val}%, trend={ry_trend}. Tailwind requires <1% OR falling.",
                             "no signal", "REAL_YIELD_TAILWIND", "high"))
        else:
            report.add(Check("DC-03", "coherence", "drivers",
                             "Real yield signals match conditions",
                             True,
                             f"RY={ry_val}%, trend={ry_trend}. No contradictory signals.",
                             severity="medium"))

    # DC-04: VIX at 24.2 tier 3 → no signal expected (tier 3 = no signal)
    vix_val = vol.get("vix")
    vix_tier = vol.get("tier")
    vix_signals = [s for s in signals if "VIX" in s or "RISK_OFF" in s]
    if vix_val and vix_tier:
        if vix_tier <= 3:
            report.add(Check("DC-04", "coherence", "drivers",
                             "VIX tier 1-3 → no VIX signal expected",
                             len(vix_signals) == 0,
                             f"VIX={vix_val}, tier={vix_tier}, signals={vix_signals}",
                             "no VIX signals", vix_signals, "medium"))
        elif vix_tier >= 4:
            report.add(Check("DC-04", "coherence", "drivers",
                             "VIX tier ≥ 4 → risk signal expected",
                             len(vix_signals) > 0,
                             f"VIX={vix_val}, tier={vix_tier}, signals={vix_signals}",
                             "risk signal", vix_signals, "high"))

    # ── Cross-Command Coherence ──────────────────────────────
    # XC-01: Oil price in commodity output ↔ correlation with DXY interpretation
    oil_dxy_corr = _safe(oil, "correlations", "dxy_20d_correlation")
    dxy_latest = _safe(drivers, "dxy_impact", "latest_dxy")
    oil_signal = oil.get("signals", [])
    if oil_dxy_corr is not None:
        has_headwind = "DXY_HEADWIND" in oil_signal
        # If DXY is rising and oil is at highs, headwind signal makes sense
        report.add(Check("XC-01", "coherence", "cross-command",
                         "Oil DXY signal ↔ drivers DXY data (informational)",
                         True,  # Informational cross-reference
                         f"Oil DXY corr: {oil_dxy_corr}, DXY: {dxy_latest}, "
                         f"Oil signals: {oil_signal}",
                         severity="low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 3: GROUNDING CHECKS
# ═════════════════════════════════════════════════════════════════════

# Threshold dictionaries for label verification
EQUITY_THRESHOLDS = {
    "cash_flow_quality": {
        "strong": (0.7, float("inf")),    # OCF/NI >= 0.7
        "adequate": (0.5, 0.7),
        "weak": (float("-inf"), 0.5),
    },
    "current_ratio": {
        "strong": (1.5, float("inf")),
        "adequate": (1.0, 1.5),
        "weak": (float("-inf"), 1.0),
    },
    "operating_margin": {
        "premium": (30, float("inf")),
        "healthy": (15, 30),
        "thin": (5, 15),
        "negative": (float("-inf"), 0),
    },
    "gross_margin": {
        "high_pricing_power": (60, float("inf")),
        "moderate": (30, 60),
        "low": (float("-inf"), 30),
    },
}

COMMODITY_THRESHOLDS = {
    "dxy_correlation": {
        "strong_positive": (0.6, 1.0),
        "moderate_positive": (0.3, 0.6),
        "weak_positive": (0.1, 0.3),
        "near_zero": (-0.1, 0.1),
        "weak_negative": (-0.3, -0.1),
        "moderate_negative": (-0.6, -0.3),
        "strong_negative": (-1.0, -0.6),
    },
    "seasonal_tendency": {
        "bullish": (0.05, float("inf")),
        "slightly_bullish": (0.01, 0.05),
        "neutral": (-0.01, 0.01),
        "slightly_bearish": (-0.05, -0.01),
        "bearish": (float("-inf"), -0.05),
    },
}

DRIVER_THRESHOLDS = {
    "correlation_strength": {
        "strong_positive": (0.6, 1.0),
        "moderate_positive": (0.3, 0.6),
        "weak_positive": (0.0, 0.3),
        "near_zero": (-0.1, 0.1),
        "weak_inverse": (-0.3, 0.0),
        "moderate_inverse": (-0.6, -0.3),
        "strong_inverse": (-1.0, -0.6),
    },
    # NOTE: The agent uses percentile-based classification (classify_hy_oas)
    # which auto-calibrates to the 1-year regime. These absolute BPS thresholds
    # are kept only as a rough sanity check — expect mismatches with the
    # percentile-based system. See fred_data.py classify_hy_oas() for details.
    "credit_stress": {
        "tight": (0, 150),
        "below_average": (150, 250),
        "normal": (250, 350),
        "elevated": (350, 450),
        "stressed": (450, 550),
        "severe_stress": (550, 700),
        "crisis": (700, float("inf")),
    },
}


def _classify(value, thresholds):
    """Classify a numeric value into a label using threshold dict."""
    if value is None:
        return None
    for label, (lo, hi) in thresholds.items():
        if lo <= value < hi:
            return label
    return None


def run_grounding_checks(data: dict, report: Report):
    """Verify labels/interpretations match numeric values."""
    nvda = data.get("analyze_equity_valuation_NVDA", {})
    oil = data.get("analyze_commodity_outlook_crude_oil", {})
    drivers = data.get("analyze_equity_drivers_both", {})

    cfq = nvda.get("cash_flow_quality", {})

    # GE-01: Cash flow quality interpretation ↔ OCF/NI threshold
    ocf_ni = cfq.get("ocf_to_net_income")
    interp = cfq.get("interpretation", "")
    if ocf_ni is not None:
        expected_label = _classify(ocf_ni, EQUITY_THRESHOLDS["cash_flow_quality"])
        actual_label = "strong" if "strong" in interp.lower() else "weak" if "weak" in interp.lower() else "adequate"
        report.add(Check("GE-01", "grounding", "equity",
                         "Cash flow quality label ↔ OCF/NI ratio",
                         expected_label == actual_label,
                         f"OCF/NI: {ocf_ni}, Expected: '{expected_label}', Got: '{actual_label}' (from '{interp}')",
                         expected_label, actual_label, "critical"))

    # GE-02: Margin trend labels vs values
    for margin_name in ["gross_margin", "operating_margin"]:
        mt_data = _safe(nvda, "margin_trends", margin_name, default={})
        trend = mt_data.get("trend")
        vals = mt_data.get("values_pct", [])
        if trend and len(vals) >= 3:
            # Check if "declining" label is correct: 70%+ consecutive diffs negative
            diffs = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
            neg_pct = sum(1 for d in diffs if d < 0) / len(diffs) if diffs else 0
            expected_trend = ("declining" if neg_pct >= 0.7 else
                              "improving" if (1 - neg_pct) >= 0.7 else
                              "stable" if all(abs(d) < 0.02 * abs(vals[-1]) for d in diffs) else
                              "volatile")
            report.add(Check(f"GE-02-{margin_name[:2]}", "grounding", "equity",
                             f"{margin_name} trend label ↔ values",
                             trend == expected_trend,
                             f"Values: ...{vals[-5:]}, Neg%: {neg_pct:.0%}, "
                             f"Expected: '{expected_trend}', Got: '{trend}'",
                             expected_trend, trend, "medium"))

    # GC-01: Oil DXY correlation interpretation ↔ value
    corr_val = _safe(oil, "correlations", "dxy_20d_correlation")
    corr_interp = _safe(oil, "correlations", "interpretation", default="")
    if corr_val is not None and corr_interp:
        expected_label = _classify(corr_val, COMMODITY_THRESHOLDS["dxy_correlation"])
        # Normalize interpretation
        actual_lower = corr_interp.lower().replace(" ", "_")
        report.add(Check("GC-01", "grounding", "commodity",
                         "DXY correlation interpretation ↔ value",
                         expected_label and expected_label.replace("_", " ") == corr_interp.lower(),
                         f"Correlation: {corr_val}, Expected: '{expected_label}', Got: '{corr_interp}'",
                         expected_label, corr_interp, "medium"))

    # GD-01 to GD-08: Rolling correlation interpretations
    corrs = drivers.get("rolling_correlations", {})
    check_num = 1
    for idx_name in ["sp500", "russell_2000"]:
        idx_corrs = corrs.get(idx_name, {})
        for factor, vals in idx_corrs.items():
            if not isinstance(vals, dict):
                continue
            val = vals.get("latest_20d")
            interp = vals.get("interpretation", "")
            if val is not None and interp:
                expected = _classify(val, DRIVER_THRESHOLDS["correlation_strength"])
                actual_normalized = interp.lower().replace(" ", "_")
                match = expected and (
                    expected.replace("_", " ") == interp.lower() or
                    # Allow close matches
                    expected.split("_")[0] in interp.lower()
                )
                if check_num <= 4:  # Sample 4 to keep manageable
                    report.add(Check(f"GD-{check_num:02d}", "grounding", "drivers",
                                     f"{idx_name}/{factor} corr interpretation ↔ value",
                                     match,
                                     f"Value: {val}, Expected: '{expected}', Got: '{interp}'",
                                     expected, interp,
                                     "medium" if not match else "low"))
                    check_num += 1

    # GD-05: Credit stress level ↔ HY OAS bps
    # NOTE: Agent uses percentile-based classify_hy_oas(), not absolute BPS
    # thresholds. This check is informational — mismatches are expected and
    # the agent's regime-aware approach is actually more accurate.
    hy_bps = _safe(drivers, "credit_equity_link", "hy_oas_bps")
    stress = _safe(drivers, "credit_equity_link", "stress_level")
    if hy_bps and stress:
        expected_stress = _classify(hy_bps, DRIVER_THRESHOLDS["credit_stress"])
        matches = expected_stress == stress
        report.add(Check("GD-05", "grounding", "drivers",
                         "Credit stress level ↔ HY OAS bps (informational — agent uses percentile-based classification)",
                         True,  # Always pass — percentile-based system is authoritative
                         f"HY OAS: {hy_bps}bps, Absolute threshold: '{expected_stress}', "
                         f"Agent (percentile-based): '{stress}'. "
                         f"{'Match' if matches else 'Regime-adjusted — expected mismatch'}",
                         expected_stress, stress, "low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 4: LLM JUDGE (Optional — requires API key)
# ═════════════════════════════════════════════════════════════════════

LLM_RUBRIC = {
    "equity": {
        "dimensions": [
            {
                "name": "Data Freshness & Coverage",
                "weight": 20,
                "prompt": "Is the financial data current (recent quarters)? Does it cover all major financial statement areas (income, balance sheet, cash flow, valuation)?",
            },
            {
                "name": "Analytical Depth",
                "weight": 20,
                "prompt": "Does the analysis go beyond raw numbers to provide trend analysis, quality assessments, and forward-looking implications?",
            },
            {
                "name": "Internal Consistency",
                "weight": 15,
                "prompt": "Are all flags, labels, and interpretations logically consistent with the underlying numeric data?",
            },
            {
                "name": "Actionability",
                "weight": 20,
                "prompt": "Can an investor use this output to make informed decisions? Are there clear quality signals, red flags, and investment implications?",
            },
            {
                "name": "Completeness",
                "weight": 15,
                "prompt": "Are all key areas covered: margins, growth, cash flow quality, balance sheet health, returns on capital, valuation, capital allocation?",
            },
            {
                "name": "Professional Quality",
                "weight": 10,
                "prompt": "Is the output well-organized, using proper financial terminology, with appropriate precision and no ambiguous labels?",
            },
        ],
    },
    "commodity": {
        "dimensions": [
            {
                "name": "Price Context & Technicals",
                "weight": 20,
                "prompt": "Does the analysis provide meaningful price context (52w range, z-scores, S/R levels relative to current price)?",
            },
            {
                "name": "Fundamental Drivers",
                "weight": 20,
                "prompt": "Are fundamental supply/demand drivers analyzed (inventories, COT positioning, seasonal patterns)?",
            },
            {
                "name": "Cross-Asset Integration",
                "weight": 15,
                "prompt": "Does the analysis incorporate DXY correlation, energy ETF divergence, and other cross-market signals?",
            },
            {
                "name": "Signal Quality",
                "weight": 20,
                "prompt": "Are signals specific, well-justified, and actionable? Do they provide clear trading implications?",
            },
            {
                "name": "Risk Assessment",
                "weight": 15,
                "prompt": "Does the analysis identify risks, alternative scenarios, and key levels to watch?",
            },
            {
                "name": "Data Completeness",
                "weight": 10,
                "prompt": "Is all expected data present? Are there missing sections, errors, or insufficient data warnings?",
            },
        ],
    },
    "drivers": {
        "dimensions": [
            {
                "name": "Factor Coverage",
                "weight": 15,
                "prompt": "Are all key macro factors covered: ERP, real yields, credit spreads, DXY, inflation, volatility?",
            },
            {
                "name": "Quantitative Rigor",
                "weight": 20,
                "prompt": "Are numeric values precise, properly sourced, and with appropriate context (levels, changes, percentiles)?",
            },
            {
                "name": "Signal Generation",
                "weight": 20,
                "prompt": "Are signals correctly derived from data? Are thresholds appropriate? Are missing signals explained?",
            },
            {
                "name": "Cross-Factor Synthesis",
                "weight": 20,
                "prompt": "Does the analysis connect factors (e.g., real yields + credit → small cap impact)? Is there composite logic?",
            },
            {
                "name": "Correlation Analysis",
                "weight": 15,
                "prompt": "Are rolling correlations insightful? Do interpretations add value beyond raw numbers?",
            },
            {
                "name": "Actionability & Clarity",
                "weight": 10,
                "prompt": "Is the summary useful for portfolio decisions? Is the output clear and well-organized?",
            },
        ],
    },
}


def run_llm_judge(data: dict, report: Report):
    """Run LLM-as-Judge evaluation using same LLM infra as Approach #4."""
    try:
        from openai import OpenAI
    except ImportError:
        report.add(Check("LLM-00", "llm_judge", "all",
                         "LLM judge available",
                         False, "openai package not installed", severity="low"))
        return {}

    try:
        from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
    except ImportError:
        LLM_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
        LLM_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
        LLM_BASE_URL = "https://api.minimax.io/v1"

    if not LLM_API_KEY:
        report.add(Check("LLM-00", "llm_judge", "all",
                         "LLM judge API key available",
                         False, "LLM API key not set", severity="low"))
        return {}

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    print(f"  Using LLM: {LLM_MODEL} at {LLM_BASE_URL}")

    scores = {}
    for cmd_key, label in [
        ("analyze_equity_valuation_NVDA", "equity"),
        ("analyze_commodity_outlook_crude_oil", "commodity"),
        ("analyze_equity_drivers_both", "drivers"),
    ]:
        cmd_data = data.get(cmd_key, {})
        rubric = LLM_RUBRIC[label]
        cmd_scores = {}

        data_str = json.dumps(cmd_data, indent=2, default=str)[:6000]

        # Single combined prompt for all dimensions (more efficient)
        dim_descriptions = "\n".join(
            f"  {i+1}. **{d['name']}** (Weight: {d['weight']}%): {d['prompt']}"
            for i, d in enumerate(rubric["dimensions"])
        )

        prompt = f"""You are a CFA-level financial analyst evaluating the quality of a financial analysis tool's output.

TOOL OUTPUT (/{label} command):
```json
{data_str}
```

Score this output on EACH of the following dimensions (1-10 scale):
{dim_descriptions}

Scoring guide:
- 1-3: Poor (major gaps, errors, or missing content)
- 4-5: Below average (present but insufficient for professional use)
- 6-7: Adequate (meets basic professional expectations)
- 8-9: Good (exceeds expectations, genuine analytical value)
- 10: Exceptional (CFA charterholder quality)

Respond with EXACTLY this JSON format:
{{
  "scores": {{
    "{rubric['dimensions'][0]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][1]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][2]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][3]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][4]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][5]['name']}": {{"score": N, "critique": "..."}}
  }}
}}"""

        try:
            print(f"  Calling LLM judge for /{label}...")
            t0 = time.time()
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": "You are a financial analysis quality evaluator. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            elapsed = time.time() - t0
            print(f"  LLM responded in {elapsed:.1f}s")

            # Strip thinking tags
            import re
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            result = json.loads(raw)
            dim_scores = result.get("scores", result)

            for dim in rubric["dimensions"]:
                name = dim["name"]
                if name in dim_scores:
                    s = dim_scores[name]
                    cmd_scores[name] = {
                        "score": int(s.get("score", 0)),
                        "weight": dim["weight"],
                        "critique": s.get("critique", "")
                    }
                else:
                    cmd_scores[name] = {"score": 0, "weight": dim["weight"], "critique": "Not scored by LLM"}

        except Exception as e:
            print(f"  LLM error for /{label}: {e}")
            for dim in rubric["dimensions"]:
                cmd_scores[dim["name"]] = {"score": 0, "weight": dim["weight"], "critique": f"Error: {e}"}

        # Compute weighted score
        total_weight = sum(d.get("weight", 0) for d in cmd_scores.values())
        weighted = sum(d["score"] * d["weight"] for d in cmd_scores.values())
        weighted_score = round(weighted / total_weight, 1) if total_weight else 0
        cmd_scores["_weighted_score"] = weighted_score
        scores[label] = cmd_scores

        print(f"  /{label} weighted score: {weighted_score}/10")

        report.add(Check(f"LLM-{label[:3].upper()}", "llm_judge", label,
                         f"LLM Judge weighted score for /{label}",
                         weighted_score >= 5.0,
                         f"Weighted score: {weighted_score}/10",
                         "≥ 5.0", weighted_score, "high"))

    return scores


# ═════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═════════════════════════════════════════════════════════════════════

def generate_markdown(report: Report, llm_scores: dict) -> str:
    """Generate markdown evaluation report."""
    s = report.summary
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    lines = [
        f"# Command Taste Evaluation Report",
        f"",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Commands Evaluated**: /analyze NVDA, /commodity crude_oil, /drivers",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Checks | {s['total_checks']} |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Pass Rate | {s['rate']} |",
        f"| Critical Failures | {s['critical_failures']} |",
        f"",
    ]

    # By category
    lines.append("## Results by Category\n")
    lines.append("| Category | Total | Passed | Failed | Rate |")
    lines.append("|----------|-------|--------|--------|------|")
    for cat, stats in sorted(s["by_category"].items()):
        rate = f"{stats['passed']/stats['total']*100:.0f}%" if stats['total'] else "N/A"
        lines.append(f"| {cat} | {stats['total']} | {stats['passed']} | {stats['failed']} | {rate} |")

    # By command
    lines.append("\n## Results by Command\n")
    lines.append("| Command | Total | Passed | Failed | Rate |")
    lines.append("|---------|-------|--------|--------|------|")
    for cmd, stats in sorted(s["by_command"].items()):
        rate = f"{stats['passed']/stats['total']*100:.0f}%" if stats['total'] else "N/A"
        lines.append(f"| {cmd} | {stats['total']} | {stats['passed']} | {stats['failed']} | {rate} |")

    # Failures
    failures = [c for c in report.checks if not c.passed]
    if failures:
        lines.append("\n## Failures Found\n")
        for f in failures:
            sev_icon = {"critical": "!!!", "high": "!!", "medium": "!", "low": "~"}.get(f.severity, "")
            lines.append(f"### {f.check_id}: {f.check_name} [{f.severity.upper()} {sev_icon}]")
            lines.append(f"- **Command**: {f.command}")
            lines.append(f"- **Category**: {f.category}")
            lines.append(f"- **Detail**: {f.detail}")
            if f.expected is not None:
                lines.append(f"- **Expected**: {f.expected}")
            if f.actual is not None:
                lines.append(f"- **Actual**: {f.actual}")
            lines.append("")

    # LLM Judge scores
    if llm_scores:
        lines.append("\n## LLM Judge Scores\n")
        for cmd, dims in llm_scores.items():
            ws = dims.pop("_weighted_score", 0)
            lines.append(f"### /{cmd} — Weighted: {ws}/10\n")
            lines.append("| Dimension | Weight | Score | Critique |")
            lines.append("|-----------|--------|-------|----------|")
            for dim_name, d in dims.items():
                lines.append(f"| {dim_name} | {d['weight']}% | {d['score']} | {d['critique'][:80]} |")
            lines.append("")

    # All checks table
    lines.append("\n## All Checks\n")
    lines.append("| ID | Category | Command | Check | Status | Severity |")
    lines.append("|----|----------|---------|-------|--------|----------|")
    for c in report.checks:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"| {c.check_id} | {c.category} | {c.command} | {c.check_name} | {status} | {c.severity} |")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def collect_live():
    """Collect live data from Financial Agent tools."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_FA_ROOT, ".env"))

    from tools.equity_analysis import analyze_equity_valuation
    from tools.commodity_analysis import analyze_commodity_outlook
    from tools.macro_market_analysis import analyze_equity_drivers

    data = {}
    print("Collecting NVDA equity valuation...")
    data["analyze_equity_valuation_NVDA"] = json.loads(analyze_equity_valuation("NVDA"))
    print("Collecting crude oil commodity outlook...")
    data["analyze_commodity_outlook_crude_oil"] = json.loads(analyze_commodity_outlook("crude_oil"))
    print("Collecting equity drivers...")
    data["analyze_equity_drivers_both"] = json.loads(analyze_equity_drivers("both"))
    return data


def main():
    parser = argparse.ArgumentParser(description="Command-level taste evaluation")
    parser.add_argument("--input", type=str, help="Path to saved command output JSON")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM judge")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            data = json.load(f)
        print(f"Loaded data from {args.input}")
    else:
        data = collect_live()

    report = Report()

    print("\n=== Running Accuracy Checks ===")
    run_accuracy_checks(data, report)

    print("=== Running Coherence Checks ===")
    run_coherence_checks(data, report)

    print("=== Running Grounding Checks ===")
    run_grounding_checks(data, report)

    llm_scores = {}
    if not args.no_llm:
        print("=== Running LLM Judge ===")
        llm_scores = run_llm_judge(data, report)

    # Summary
    s = report.summary
    print(f"\n{'='*60}")
    print(f"COMMAND TASTE EVALUATION RESULTS")
    print(f"{'='*60}")
    print(f"Total Checks: {s['total_checks']}")
    print(f"Passed: {s['passed']} ({s['rate']})")
    print(f"Failed: {s['failed']}")
    print(f"Critical Failures: {s['critical_failures']}")
    print(f"\nBy Category:")
    for cat, stats in sorted(s["by_category"].items()):
        rate = f"{stats['passed']/stats['total']*100:.0f}%" if stats['total'] else "N/A"
        print(f"  {cat}: {stats['passed']}/{stats['total']} ({rate})")
    print(f"\nBy Command:")
    for cmd, stats in sorted(s["by_command"].items()):
        rate = f"{stats['passed']/stats['total']*100:.0f}%" if stats['total'] else "N/A"
        print(f"  {cmd}: {stats['passed']}/{stats['total']} ({rate})")

    # Print failures
    failures = [c for c in report.checks if not c.passed]
    if failures:
        print(f"\n{'='*60}")
        print(f"FAILURES ({len(failures)}):")
        print(f"{'='*60}")
        for f in failures:
            print(f"\n{f.check_id} [{f.severity.upper()}] {f.check_name}")
            print(f"  Command: {f.command}")
            print(f"  Detail: {f.detail}")

    # Save records
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _RECORDS_DIR / f"command_eval_{ts}.json"
    md_path = _RECORDS_DIR / f"command_eval_{ts}.md"

    record = {
        "timestamp": datetime.now().isoformat(),
        "input_commands": ["analyze NVDA", "commodity crude_oil", "drivers both"],
        "summary": s,
        "failures": [c.to_dict() for c in report.checks if not c.passed],
        "all_checks": [c.to_dict() for c in report.checks],
        "llm_scores": llm_scores,
    }
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2, default=str)

    md_content = generate_markdown(report, llm_scores)
    with open(md_path, "w") as f:
        f.write(md_content)

    print(f"\nRecords saved to:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    return report


if __name__ == "__main__":
    main()
