"""
Approach 4: Comparative Benchmarking (Agent vs. Professional Analysis)

Compares the Financial Agent's analysis against curated professional
analyst reports (Goldman Sachs macro outlooks, JPM weekly recaps, etc.)
using an LLM as a pairwise judge.

The LLM scores both the agent and the reference on 7 quality dimensions,
then produces a gap analysis showing where the agent falls short.

Workflow:
    1. Place professional reports in reference_reports/ as .md or .txt
    2. Run the agent's /full_report for the same date (or load saved JSON)
    3. The LLM judge evaluates both side-by-side on a rubric
    4. Results are saved to records/ for trending over time

Usage:
    python comparative_benchmark.py --ref reference_reports/gs_macro_2026Q1.md
    python comparative_benchmark.py --ref reference_reports/gs_macro_2026Q1.md --input saved_report.json
    python comparative_benchmark.py --list   # List available reference reports
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
_REFERENCE_DIR = _THIS_DIR / "reference_reports"
_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

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

from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL


# ═════════════════════════════════════════════════════════════════════
# RUBRIC DEFINITION (CFA Research Challenge + FinDeepResearch inspired)
# ═════════════════════════════════════════════════════════════════════

RUBRIC_DIMENSIONS = [
    {
        "id": "data_accuracy",
        "name": "Data Accuracy & Traceability",
        "weight": 0.15,
        "description": (
            "Are specific data points cited (exact numbers, dates, sources)? "
            "Are figures correct and verifiable? Does the analysis reference "
            "primary data sources (FRED, BLS, ISM, etc.)?"
        ),
    },
    {
        "id": "analytical_depth",
        "name": "Analytical Depth (Why, Not Just What)",
        "weight": 0.20,
        "description": (
            "Does the analysis explain *why* something is happening, not just "
            "describe *what* is happening? Are there cause-and-effect chains? "
            "Second-order thinking? Historical analogies with explanation?"
        ),
    },
    {
        "id": "coherence",
        "name": "Internal Coherence",
        "weight": 0.15,
        "description": (
            "Are different sections logically consistent? If one section says "
            "'reflationary' does another contradict with 'systemic stress'? "
            "Are contradictions acknowledged and reconciled?"
        ),
    },
    {
        "id": "actionability",
        "name": "Actionability & Investment Implications",
        "weight": 0.20,
        "description": (
            "Does the analysis suggest what an investor should *do*? Sector "
            "tilts, duration calls, risk management, hedging strategies? "
            "Or does it just describe conditions without implications?"
        ),
    },
    {
        "id": "completeness",
        "name": "Completeness & Risk Assessment",
        "weight": 0.10,
        "description": (
            "Are alternative scenarios discussed? Key risks identified? "
            "Upside/downside cases presented? Are blind spots acknowledged?"
        ),
    },
    {
        "id": "professional_quality",
        "name": "Professional Quality & Communication",
        "weight": 0.10,
        "description": (
            "Is the language professional? Appropriate use of financial "
            "terminology? Proper caveats? Proportionate detail (not too "
            "verbose, not too terse)? Well-structured?"
        ),
    },
    {
        "id": "signal_specificity",
        "name": "Signal Specificity & Originality",
        "weight": 0.10,
        "description": (
            "Are insights original and specific (cross-dimensional, connecting "
            "dots between indicators)? Or are they generic re-statements of "
            "data? Does it say something a Bloomberg terminal can't?"
        ),
    },
]


# ═════════════════════════════════════════════════════════════════════
# LLM JUDGE
# ═════════════════════════════════════════════════════════════════════

def _build_judge_prompt(agent_analysis: str, reference_analysis: str,
                        reference_source: str) -> str:
    """Build the LLM judge prompt for pairwise comparison."""
    rubric_text = ""
    for dim in RUBRIC_DIMENSIONS:
        rubric_text += (
            f"\n### {dim['name']} (Weight: {dim['weight']*100:.0f}%)\n"
            f"{dim['description']}\n"
        )

    return f"""You are an expert financial analysis evaluator. Your task is to
compare two pieces of financial/macro analysis and score them on a rubric.

## Analysis A: Financial Agent (automated)
The following is output from an automated financial analysis agent. It pulls
live market data and generates analysis programmatically.

<analysis_a>
{agent_analysis[:12000]}
</analysis_a>

## Analysis B: Reference ({reference_source})
The following is from a professional analyst or research report.

<analysis_b>
{reference_analysis[:12000]}
</analysis_b>

## Evaluation Rubric
Score EACH analysis on EACH dimension from 1-10:
- 1-2: Missing or fundamentally wrong
- 3-4: Present but superficial/template-like
- 5-6: Adequate but lacks depth or specificity
- 7-8: Good — demonstrates real analytical thinking
- 9-10: Excellent — insightful, actionable, professional-grade

{rubric_text}

## Output Format
Return ONLY valid JSON with this exact structure:
{{
    "scores": {{
        "analysis_a": {{
            "data_accuracy": <1-10>,
            "analytical_depth": <1-10>,
            "coherence": <1-10>,
            "actionability": <1-10>,
            "completeness": <1-10>,
            "professional_quality": <1-10>,
            "signal_specificity": <1-10>
        }},
        "analysis_b": {{
            "data_accuracy": <1-10>,
            "analytical_depth": <1-10>,
            "coherence": <1-10>,
            "actionability": <1-10>,
            "completeness": <1-10>,
            "professional_quality": <1-10>,
            "signal_specificity": <1-10>
        }}
    }},
    "dimension_critiques": {{
        "data_accuracy": {{
            "analysis_a": "<specific critique for agent>",
            "analysis_b": "<specific critique for reference>",
            "gap_explanation": "<why the gap exists>"
        }},
        "analytical_depth": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }},
        "coherence": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }},
        "actionability": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }},
        "completeness": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }},
        "professional_quality": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }},
        "signal_specificity": {{
            "analysis_a": "<critique>",
            "analysis_b": "<critique>",
            "gap_explanation": "<explanation>"
        }}
    }},
    "overall_verdict": "<2-3 sentence summary of the comparison>",
    "top_improvement_areas": [
        "<most impactful improvement #1>",
        "<most impactful improvement #2>",
        "<most impactful improvement #3>"
    ]
}}

Be specific in your critiques. Reference actual content from both analyses.
Do not be generous — calibrate against what a CFA charterholder would expect."""


def _build_solo_judge_prompt(agent_analysis: str) -> str:
    """Build the LLM judge prompt for solo evaluation (no reference)."""
    rubric_text = ""
    for dim in RUBRIC_DIMENSIONS:
        rubric_text += (
            f"\n### {dim['name']} (Weight: {dim['weight']*100:.0f}%)\n"
            f"{dim['description']}\n"
        )

    return f"""You are an expert financial analysis evaluator. Score the
following automated financial analysis output on a professional rubric.

## Analysis (from automated Financial Agent)
<analysis>
{agent_analysis[:15000]}
</analysis>

## Evaluation Rubric
Score the analysis on EACH dimension from 1-10:
- 1-2: Missing or fundamentally wrong
- 3-4: Present but superficial/template-like
- 5-6: Adequate but lacks depth or specificity
- 7-8: Good — demonstrates real analytical thinking
- 9-10: Excellent — insightful, actionable, professional-grade

{rubric_text}

## Output Format
Return ONLY valid JSON with this exact structure:
{{
    "scores": {{
        "data_accuracy": <1-10>,
        "analytical_depth": <1-10>,
        "coherence": <1-10>,
        "actionability": <1-10>,
        "completeness": <1-10>,
        "professional_quality": <1-10>,
        "signal_specificity": <1-10>
    }},
    "dimension_critiques": {{
        "data_accuracy": "<specific critique with examples from the text>",
        "analytical_depth": "<critique>",
        "coherence": "<critique>",
        "actionability": "<critique>",
        "completeness": "<critique>",
        "professional_quality": "<critique>",
        "signal_specificity": "<critique>"
    }},
    "overall_verdict": "<2-3 sentence verdict on the quality of this analysis>",
    "top_improvement_areas": [
        "<most impactful improvement #1>",
        "<most impactful improvement #2>",
        "<most impactful improvement #3>"
    ]
}}

Be calibrated against a CFA charterholder's expectations. Template-generated
text that just restates numbers should score 3-5. Real analytical thinking
(cause-effect, implications, recommendations) should score 7+."""


def call_llm_judge(prompt: str) -> dict:
    """Call the LLM to judge the analysis."""
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    print("  Calling LLM judge...")
    t0 = time.time()

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "You are a financial analysis quality evaluator. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4000,
    )

    raw = response.choices[0].message.content.strip()
    elapsed = time.time() - t0
    print(f"  LLM responded in {elapsed:.1f}s ({len(raw)} chars)")

    # Strip thinking model tags (<think>...</think>)
    import re as _re
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()

    # Extract JSON from response (handle markdown code blocks)
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # Try to find JSON object in the response
    if not raw.startswith("{"):
        # Look for first { and last }
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  WARNING: LLM returned invalid JSON: {e}")
        print(f"  Raw response (first 500 chars): {raw[:500]}")
        return {"error": str(e), "raw_response": raw[:2000]}


# ═════════════════════════════════════════════════════════════════════
# ANALYSIS FORMATTING
# ═════════════════════════════════════════════════════════════════════

def format_agent_output_for_judge(report_data: dict) -> str:
    """Convert structured agent output into readable text for the LLM judge.

    This formatter extracts interpretive narratives and cause-effect context
    from each tool's output, not just raw numbers.  Richer formatting yields
    fairer quality scoring by the LLM judge.
    """
    sections = []

    # ── Macro Regime ──────────────────────────────────────────────
    regime = report_data.get("analyze_macro_regime", {})
    if regime:
        sections.append("## Macro Regime Analysis")
        outlook = regime.get("composite_outlook", "")
        if outlook:
            sections.append(f"**Outlook**: {outlook}")
        regimes = regime.get("regimes", {})
        for k, v in regimes.items():
            if isinstance(v, dict):
                cls = v.get("classification", "")
                interp = v.get("interpretation", "")
                val = v.get("value")
                line = f"- **{k}**: {cls}"
                if val is not None:
                    line += f" (value: {val})"
                if interp:
                    line += f" — {interp}"
                sections.append(line)
            else:
                sections.append(f"- **{k}**: {v}")
        signals = regime.get("signals", [])
        if signals:
            sections.append(f"\nSignals: {', '.join(str(s) for s in signals[:15])}")

    # ── Financial Stress ──────────────────────────────────────────
    stress = report_data.get("analyze_financial_stress", {})
    if stress:
        sections.append("\n## Financial Stress Analysis")
        sections.append(f"**Composite Score**: {stress.get('composite_score', 'N/A')}/10 "
                        f"(**{stress.get('stress_level', 'N/A')}**)")
        summary = stress.get("summary", "")
        if summary:
            sections.append(f"\n{summary}")
        # Component details with interpretations
        comps = stress.get("components", {})
        if comps:
            sections.append("\nComponent Breakdown:")
            for name, comp in comps.items():
                if isinstance(comp, dict):
                    val = comp.get("value")
                    score = comp.get("score", 0)
                    interp = comp.get("interpretation", "")
                    line = f"- {name}: {val} (score {score}/10)"
                    if interp:
                        line += f" — {interp}"
                    sections.append(line)
        # Supplemental
        supp = stress.get("supplemental", {})
        if isinstance(supp, dict):
            for k, v in supp.items():
                if isinstance(v, dict):
                    interp = v.get("interpretation", v.get("assessment", ""))
                    if interp:
                        sections.append(f"- {k}: {interp}")
        signals = stress.get("signals", [])
        if signals:
            sections.append(f"\nSignals: {', '.join(str(s) for s in signals[:10])}")

    # ── Late-Cycle ────────────────────────────────────────────────
    late = report_data.get("detect_late_cycle_signals", {})
    if late:
        sections.append("\n## Late-Cycle Detection")
        sections.append(f"**{late.get('count', 0)}/13** signals firing "
                        f"(Confidence: **{late.get('confidence_level', 'N/A')}**)")
        fired = late.get("signals_fired", late.get("active_signals", []))
        if isinstance(fired, list):
            for s in fired[:8]:
                if isinstance(s, dict):
                    name = s.get("name", s.get("signal", ""))
                    status = s.get("status", "")
                    detail = s.get("detail", s.get("interpretation", ""))
                    if status == "firing" and detail:
                        sections.append(f"- {name}: {detail}")
                    elif status == "firing":
                        sections.append(f"- {name}")
                elif isinstance(s, str):
                    sections.append(f"- {s}")

    # ── Equity Drivers ────────────────────────────────────────────
    equity = report_data.get("analyze_equity_drivers", {})
    if equity:
        sections.append("\n## Equity Market Drivers")
        summary = equity.get("summary", "")
        if summary:
            sections.append(f"\n{summary}")
        # Real yield impact
        ryi = equity.get("real_yield_impact", {})
        if isinstance(ryi, dict):
            ry_interp = ryi.get("interpretation", "")
            sections.append(f"\n**Real Yield Impact**: 10Y real yield at "
                          f"{ryi.get('real_yield_10y', 'N/A')}%, "
                          f"trend {ryi.get('trend', 'N/A')}.")
            if ry_interp:
                sections.append(f"  {ry_interp}")
        # ERP
        erp = equity.get("equity_risk_premium", {})
        if isinstance(erp, dict):
            erp_interp = erp.get("interpretation", "")
            sections.append(f"**ERP**: {erp.get('erp', erp.get('value', 'N/A'))}%")
            if erp_interp:
                sections.append(f"  {erp_interp}")
        # Credit-equity link
        cel = equity.get("credit_equity_link", {})
        if isinstance(cel, dict):
            cel_interp = cel.get("interpretation", "")
            if cel_interp:
                sections.append(f"**Credit-Equity Link**: {cel_interp}")
        # VIX framework
        vix_fw = equity.get("vix_framework", equity.get("volatility_regime", {}))
        if isinstance(vix_fw, dict):
            vix_interp = vix_fw.get("interpretation", vix_fw.get("assessment", ""))
            if vix_interp:
                sections.append(f"**VIX Framework**: {vix_interp}")
        signals = equity.get("signals", [])
        if signals:
            sections.append(f"\nSignals: {', '.join(str(s) for s in signals[:10])}")

    # ── Bond Market ───────────────────────────────────────────────
    bond = report_data.get("analyze_bond_market", {})
    if bond:
        sections.append("\n## Bond Market Analysis")
        summary = bond.get("summary", "")
        if summary:
            sections.append(f"\n{summary}")
        # Yield curve
        yc = bond.get("yield_curve", {})
        if isinstance(yc, dict):
            shape = yc.get("shape", yc.get("curve_shape", "N/A"))
            yc_interp = yc.get("interpretation", "")
            sections.append(f"\n**Yield Curve**: {shape}")
            if yc_interp:
                sections.append(f"  {yc_interp}")
        # Credit spreads
        cs = bond.get("credit_spreads", {})
        if isinstance(cs, dict):
            for k, v in cs.items():
                if isinstance(v, dict):
                    val = v.get("latest_value_bps", v.get("latest", v.get("value")))
                    interp = v.get("interpretation", v.get("assessment", ""))
                    stress_lvl = v.get("stress_level", "")
                    line = f"- **{k}**: {val}"
                    if isinstance(val, (int, float)):
                        line += " bps"
                    if stress_lvl:
                        line += f" ({stress_lvl})"
                    if interp:
                        line += f" — {interp}"
                    sections.append(line)
        # Fed policy
        fp = bond.get("fed_policy", {})
        if isinstance(fp, dict):
            fp_interp = fp.get("interpretation", fp.get("assessment", ""))
            if fp_interp:
                sections.append(f"\n**Fed Policy**: {fp_interp}")
        # Term premium
        tp = bond.get("term_premium", {})
        if isinstance(tp, dict):
            tp_interp = tp.get("interpretation", "")
            if tp_interp:
                sections.append(f"**Term Premium**: {tp_interp}")
        signals = bond.get("signals", [])
        if signals:
            sections.append(f"\nSignals: {', '.join(str(s) for s in signals[:12])}")

    # ── Consumer Health ───────────────────────────────────────────
    consumer = report_data.get("analyze_consumer_health", {})
    if consumer:
        sections.append("\n## Consumer Health")
        sections.append(f"**Score**: {consumer.get('composite_score', 'N/A')}/10 "
                        f"(**{consumer.get('consumer_health_level', 'N/A')}**)")
        comps = consumer.get("components", {})
        if comps:
            for name, comp in comps.items():
                if isinstance(comp, dict):
                    val = comp.get("value")
                    assessment = comp.get("assessment", comp.get("interpretation", ""))
                    line = f"- {name}: {val}"
                    if assessment:
                        line += f" — {assessment}"
                    sections.append(line)

    # ── Housing ───────────────────────────────────────────────────
    housing = report_data.get("analyze_housing_market", {})
    if housing:
        sections.append("\n## Housing Market")
        assessment = housing.get("assessment", "")
        if assessment:
            sections.append(f"\n{assessment}")
        # Cycle phase
        hcp = housing.get("housing_cycle_phase", {})
        if isinstance(hcp, dict):
            phase = hcp.get("phase", "")
            hcp_interp = hcp.get("interpretation", "")
            if phase:
                sections.append(f"\n**Housing Cycle Phase**: {phase}")
            if hcp_interp:
                sections.append(f"  {hcp_interp}")
        # Leading indicator
        li = housing.get("leading_indicator_signal", {})
        if isinstance(li, dict):
            li_signal = li.get("signal", "")
            li_interp = li.get("interpretation", "")
            if li_signal:
                sections.append(f"**Leading Indicator**: {li_signal}")
            if li_interp:
                sections.append(f"  {li_interp}")
        signals = housing.get("signals", [])
        if signals:
            sections.append(f"\nSignals: {', '.join(str(s) for s in signals[:8])}")

    # ── Synthesis (if present) ────────────────────────────────────
    synthesis = report_data.get("synthesize_macro_view", {})
    if synthesis:
        sections.append("\n## Macro Synthesis & Recommendations")
        exec_summary = synthesis.get("executive_summary", "")
        if exec_summary:
            sections.append(f"\n{exec_summary}")
        # Contradictions
        contradictions = synthesis.get("contradictions", [])
        if contradictions:
            sections.append(f"\n**Cross-Tool Contradictions** ({len(contradictions)}):")
            for c in contradictions[:5]:
                if isinstance(c, dict):
                    obs = c.get("observation", "")
                    contra = c.get("contradiction", "")
                    sections.append(f"- {obs}: {contra}")
        # Cause-effect chains
        chains = synthesis.get("cause_effect_chains", [])
        if chains:
            sections.append("\n**Cause-Effect Reasoning**:")
            for ch in chains[:4]:
                if isinstance(ch, dict):
                    sections.append(
                        f"- Observation: {ch.get('observation', '')}\n"
                        f"  Because: {ch.get('because', '')}\n"
                        f"  So what: {ch.get('so_what', '')}\n"
                        f"  Portfolio action: {ch.get('portfolio_action', '')}"
                    )
        # Recommendations
        recs = synthesis.get("recommendations", {})
        if isinstance(recs, dict):
            sections.append("\n**Recommendations**:")
            for k, v in recs.items():
                if isinstance(v, str) and v:
                    sections.append(f"- **{k}**: {v}")
                elif isinstance(v, list):
                    sections.append(f"- **{k}**: {', '.join(str(x) for x in v[:5])}")
        # Historical analogues
        analogues = synthesis.get("historical_analogues", [])
        if analogues:
            sections.append("\n**Historical Analogues**:")
            for a in analogues[:3]:
                if isinstance(a, dict):
                    sections.append(
                        f"- {a.get('period', '')}: "
                        f"similarity {a.get('similarity_score', 'N/A')}"
                    )

    return "\n".join(sections)


# ═════════════════════════════════════════════════════════════════════
# WEIGHTED SCORE CALCULATION
# ═════════════════════════════════════════════════════════════════════

def compute_weighted_score(scores: dict) -> float:
    """Compute weighted average from dimension scores."""
    total = 0.0
    for dim in RUBRIC_DIMENSIONS:
        score = scores.get(dim["id"], 5)
        total += score * dim["weight"]
    return round(total, 2)


def compute_gap_analysis(scores_a: dict, scores_b: dict) -> list[dict]:
    """Compute per-dimension gap between agent and reference."""
    gaps = []
    for dim in RUBRIC_DIMENSIONS:
        score_a = scores_a.get(dim["id"], 0)
        score_b = scores_b.get(dim["id"], 0)
        gaps.append({
            "dimension": dim["name"],
            "dimension_id": dim["id"],
            "weight": dim["weight"],
            "agent_score": score_a,
            "reference_score": score_b,
            "gap": score_b - score_a,
            "weighted_gap": round((score_b - score_a) * dim["weight"], 3),
        })
    gaps.sort(key=lambda g: g["gap"], reverse=True)
    return gaps


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_full_report(include_synthesis: bool = False) -> dict:
    """Execute all 8 /full_report tools.

    Args:
        include_synthesis: If True, also run synthesize_macro_view() and
            include its output.  The synthesis adds cause-effect chains,
            contradiction detection, historical analogues, and actionable
            recommendations — significantly boosting analytical depth and
            actionability scores.
    """
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

    if include_synthesis:
        from tools.macro_synthesis import synthesize_macro_view
        report["synthesize_macro_view"] = json.loads(synthesize_macro_view())
        print(f"    synthesize_macro_view: OK")

    return report


def load_reference_report(path: str) -> tuple[str, str]:
    """Load a reference report from file. Returns (content, source_name)."""
    p = Path(path)
    if not p.exists():
        # Try relative to reference_reports dir
        p = _REFERENCE_DIR / path
    if not p.exists():
        raise FileNotFoundError(f"Reference report not found: {path}")

    content = p.read_text(encoding="utf-8")
    source_name = p.stem.replace("_", " ").title()
    return content, source_name


def list_reference_reports() -> list[dict]:
    """List available reference reports."""
    reports = []
    for ext in ("*.md", "*.txt", "*.json"):
        for f in _REFERENCE_DIR.glob(ext):
            stat = f.stat()
            reports.append({
                "filename": f.name,
                "path": str(f),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
            })
    return reports


# ═════════════════════════════════════════════════════════════════════
# RECORD KEEPING
# ═════════════════════════════════════════════════════════════════════

def save_record(judge_result: dict, mode: str, reference_source: str = "",
                agent_scores: dict = None, ref_scores: dict = None,
                gaps: list = None):
    """Save benchmark results to records directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    record = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,  # "pairwise" or "solo"
        "reference_source": reference_source,
        "llm_model": LLM_MODEL,
        "judge_result": judge_result,
    }

    if agent_scores:
        record["agent_weighted_score"] = compute_weighted_score(agent_scores)
    if ref_scores:
        record["reference_weighted_score"] = compute_weighted_score(ref_scores)
    if gaps:
        record["gap_analysis"] = gaps

    json_path = _RECORDS_DIR / f"benchmark_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Record saved: {json_path}")

    # Markdown report
    md_path = _RECORDS_DIR / f"benchmark_{ts}.md"
    md = generate_markdown_report(record, mode)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")

    return json_path


def generate_markdown_report(record: dict, mode: str) -> str:
    """Generate a markdown report from benchmark results."""
    lines = [
        "# Comparative Benchmark Report",
        "",
        f"**Date**: {record['timestamp'][:19]}",
        f"**Mode**: {mode}",
        f"**LLM Judge**: {record.get('llm_model', 'N/A')}",
    ]

    if mode == "pairwise":
        lines.append(f"**Reference**: {record.get('reference_source', 'N/A')}")

    jr = record.get("judge_result", {})

    if "error" in jr:
        lines.append(f"\n## Error\n{jr['error']}")
        return "\n".join(lines)

    # Scores table
    if mode == "pairwise":
        scores_a = jr.get("scores", {}).get("analysis_a", {})
        scores_b = jr.get("scores", {}).get("analysis_b", {})
        lines.append("\n## Scores (1-10)\n")
        lines.append("| Dimension | Weight | Agent | Reference | Gap |")
        lines.append("|-----------|--------|-------|-----------|-----|")
        for dim in RUBRIC_DIMENSIONS:
            sa = scores_a.get(dim["id"], "?")
            sb = scores_b.get(dim["id"], "?")
            gap = ""
            if isinstance(sa, (int, float)) and isinstance(sb, (int, float)):
                gap = f"{sb - sa:+.0f}"
            lines.append(f"| {dim['name']} | {dim['weight']*100:.0f}% | {sa} | {sb} | {gap} |")

        wa = record.get("agent_weighted_score", "?")
        wr = record.get("reference_weighted_score", "?")
        lines.append(f"\n**Weighted Score**: Agent = {wa} | Reference = {wr}")
    else:
        scores = jr.get("scores", {})
        lines.append("\n## Scores (1-10)\n")
        lines.append("| Dimension | Weight | Score |")
        lines.append("|-----------|--------|-------|")
        for dim in RUBRIC_DIMENSIONS:
            s = scores.get(dim["id"], "?")
            lines.append(f"| {dim['name']} | {dim['weight']*100:.0f}% | {s} |")
        ws = record.get("agent_weighted_score", "?")
        lines.append(f"\n**Weighted Score**: {ws}")

    # Critiques
    critiques = jr.get("dimension_critiques", {})
    if critiques:
        lines.append("\n## Dimension Critiques\n")
        for dim in RUBRIC_DIMENSIONS:
            crit = critiques.get(dim["id"], {})
            lines.append(f"### {dim['name']}\n")
            if isinstance(crit, dict):
                if "analysis_a" in crit:
                    lines.append(f"**Agent**: {crit.get('analysis_a', '')}")
                    lines.append(f"**Reference**: {crit.get('analysis_b', '')}")
                    lines.append(f"**Gap**: {crit.get('gap_explanation', '')}")
                else:
                    lines.append(str(crit))
            elif isinstance(crit, str):
                lines.append(crit)
            lines.append("")

    # Verdict
    verdict = jr.get("overall_verdict", "")
    if verdict:
        lines.append(f"\n## Overall Verdict\n\n{verdict}")

    # Improvements
    improvements = jr.get("top_improvement_areas", [])
    if improvements:
        lines.append("\n## Top Improvement Areas\n")
        for i, imp in enumerate(improvements, 1):
            lines.append(f"{i}. {imp}")

    # Gap analysis
    gaps = record.get("gap_analysis", [])
    if gaps:
        lines.append("\n## Gap Analysis (sorted by largest gap)\n")
        lines.append("| Dimension | Agent | Ref | Gap | Weighted Impact |")
        lines.append("|-----------|-------|-----|-----|----------------|")
        for g in gaps:
            lines.append(
                f"| {g['dimension']} | {g['agent_score']} | "
                f"{g['reference_score']} | {g['gap']:+.0f} | "
                f"{g['weighted_gap']:+.3f} |"
            )

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN EVALUATION FUNCTIONS
# ═════════════════════════════════════════════════════════════════════

def run_pairwise_benchmark(report_data: dict, reference_path: str) -> dict:
    """Run a pairwise comparison between agent output and reference report."""
    print(f"\n  Loading reference: {reference_path}")
    ref_content, ref_source = load_reference_report(reference_path)
    print(f"  Reference: {ref_source} ({len(ref_content)} chars)")

    agent_text = format_agent_output_for_judge(report_data)
    print(f"  Agent analysis: {len(agent_text)} chars")

    prompt = _build_judge_prompt(agent_text, ref_content, ref_source)
    result = call_llm_judge(prompt)

    if "error" not in result:
        scores_a = result.get("scores", {}).get("analysis_a", {})
        scores_b = result.get("scores", {}).get("analysis_b", {})
        gaps = compute_gap_analysis(scores_a, scores_b)
        save_record(result, "pairwise", ref_source, scores_a, scores_b, gaps)
    else:
        save_record(result, "pairwise", ref_source)

    return result


def run_solo_benchmark(report_data: dict) -> dict:
    """Run a solo evaluation of agent output (no reference needed)."""
    agent_text = format_agent_output_for_judge(report_data)
    print(f"  Agent analysis: {len(agent_text)} chars")

    prompt = _build_solo_judge_prompt(agent_text)
    result = call_llm_judge(prompt)

    if "error" not in result:
        scores = result.get("scores", {})
        save_record(result, "solo", agent_scores=scores)
    else:
        save_record(result, "solo")

    return result


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Approach 4: Comparative Benchmarking")
    parser.add_argument("--input", type=str,
                        help="Path to saved full_report JSON (skip live collection)")
    parser.add_argument("--ref", type=str,
                        help="Path to professional reference report (.md/.txt)")
    parser.add_argument("--solo", action="store_true",
                        help="Run solo evaluation (no reference needed)")
    parser.add_argument("--list", action="store_true",
                        help="List available reference reports")
    parser.add_argument("--synthesis", action="store_true",
                        help="Include macro synthesis (cause-effect + recommendations). "
                        "Recommended: significantly boosts analytical depth/actionability scores.")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 4: COMPARATIVE BENCHMARKING")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # List mode
    if args.list:
        reports = list_reference_reports()
        if reports:
            print(f"\n  Found {len(reports)} reference report(s):\n")
            for r in reports:
                print(f"    {r['filename']} ({r['size_kb']}KB, {r['modified']})")
            print(f"\n  Directory: {_REFERENCE_DIR}")
        else:
            print(f"\n  No reference reports found in: {_REFERENCE_DIR}")
            print("  Place .md or .txt files there to use pairwise comparison.")
        sys.exit(0)

    # Load or collect agent data
    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
        print(f"\n  Loaded from: {args.input}")
    else:
        report_data = collect_full_report(include_synthesis=args.synthesis)

    # Run evaluation
    print(f"\n{'─' * 70}")
    if args.ref:
        print("  Mode: PAIRWISE COMPARISON")
        print(f"{'─' * 70}\n")
        result = run_pairwise_benchmark(report_data, args.ref)
    else:
        print("  Mode: SOLO EVALUATION (no reference)")
        print("  Tip: Use --ref <path> for pairwise comparison")
        print(f"{'─' * 70}\n")
        result = run_solo_benchmark(report_data)

    # Display results
    if "error" in result:
        print(f"\n  ERROR: {result['error']}")
    else:
        print(f"\n{'=' * 70}")
        print("  BENCHMARK RESULTS")
        print(f"{'=' * 70}")

        if args.ref:
            scores_a = result.get("scores", {}).get("analysis_a", {})
            scores_b = result.get("scores", {}).get("analysis_b", {})
            wa = compute_weighted_score(scores_a)
            wb = compute_weighted_score(scores_b)
            print(f"  Agent Weighted Score:     {wa}/10")
            print(f"  Reference Weighted Score: {wb}/10")
            print(f"  Gap: {wb - wa:+.2f}")
        else:
            scores = result.get("scores", {})
            ws = compute_weighted_score(scores)
            print(f"  Agent Weighted Score: {ws}/10")

        verdict = result.get("overall_verdict", "")
        if verdict:
            print(f"\n  Verdict: {verdict[:200]}")

        improvements = result.get("top_improvement_areas", [])
        if improvements:
            print(f"\n  Top Improvements:")
            for i, imp in enumerate(improvements, 1):
                print(f"    {i}. {imp}")
