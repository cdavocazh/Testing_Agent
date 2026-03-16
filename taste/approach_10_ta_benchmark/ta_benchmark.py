#!/usr/bin/env python3
"""
Approach #10 — TA Quality LLM Judge

7 rubric dimensions, scored per asset by LLM-as-Judge.
Uses MiniMax-M2.5 via OpenAI-compatible API.

Dimensions (weights):
  1. S/R Quality          (20%)
  2. Entry/Exit Clarity   (20%)
  3. Indicator Interp.    (15%)
  4. Signal Synthesis      (15%)
  5. Risk Management       (15%)
  6. Pattern Detection      (5%)
  7. Professional Pres.    (10%)

Usage:
    python ta_benchmark.py --input ../../taste/ta_output_v1.json
    python ta_benchmark.py --input ../../taste/ta_output_v1.json --no-llm
"""

import sys, os, json, argparse, time
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_RECORDS = _THIS / "records"
_RECORDS.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# RUBRIC DIMENSIONS
# ═══════════════════════════════════════════════════════════════════

RUBRIC = [
    {
        "name": "S/R Quality",
        "weight": 0.20,
        "prompt": """Evaluate the SUPPORT/RESISTANCE levels for this asset.

Scoring guide:
10 — Meaningful pivot levels at key turning points, proper spacing, covers multiple timeframes
8  — Good levels with clear pivot significance, adequate spacing
6  — Reasonable levels but may miss key pivots or have poor spacing
4  — Levels exist but seem arbitrary or mechanically computed without market significance
2  — Few/no levels, or levels are clearly wrong (supports above price, etc.)
0  — No S/R analysis provided

Focus on: Are the levels at actual pivot highs/lows? Are they properly spaced? Would a trader trust these?""",
    },
    {
        "name": "Entry/Exit Clarity",
        "weight": 0.20,
        "prompt": """Evaluate the ENTRY/EXIT guidance and actionability.

Scoring guide:
10 — Clear entry points, stop-loss placement, risk/reward ratio, position sizing guidance
8  — Good entry/exit levels with stop placement, some risk context
6  — Entry/exit mentioned but lacks specificity or risk/reward
4  — Vague direction without specific levels or stops
2  — Only direction (bullish/bearish) with no actionable levels
0  — No entry/exit guidance

Focus on: Can a trader directly use this to place an order? Are stop-losses defined?""",
    },
    {
        "name": "Indicator Interpretation",
        "weight": 0.15,
        "prompt": """Evaluate the INDICATOR INTERPRETATION quality.

Scoring guide:
10 — Contextual interpretation beyond simple labels (e.g. RSI divergences, MACD histogram expansion rate, multi-timeframe RSI)
8  — Good interpretation with context (e.g. "RSI oversold after extended downtrend suggests bounce potential")
6  — Correct labels with basic interpretation
4  — Just labels without context (e.g. "RSI: bearish_momentum")
2  — Labels present but some are incorrect or contradictory
0  — No indicator analysis

Focus on: Does the analysis go beyond simple overbought/oversold labels?""",
    },
    {
        "name": "Signal Synthesis",
        "weight": 0.15,
        "prompt": """Evaluate the SIGNAL SYNTHESIS — how well conflicting signals are reconciled.

Scoring guide:
10 — All indicators synthesised into coherent narrative, conflicts explicitly addressed, composite weighting logic clear
8  — Good synthesis with most conflicts addressed
6  — Composite signal present but doesn't address conflicts between indicators
4  — Individual indicator results listed but not synthesised
2  — Contradictory signals with no attempt at reconciliation
0  — No synthesis

Focus on: When RSI says one thing and MACD another, does the composite explain why?""",
    },
    {
        "name": "Risk Management",
        "weight": 0.15,
        "prompt": """Evaluate the RISK MANAGEMENT quality.

Scoring guide:
10 — Multiple stop-loss methods (swing, ATR, percent), position sizing rules, trailing stop guidance, Fidenza framework rules
8  — Good stop-loss with multiple methods and basic position sizing
6  — Single stop-loss method with risk percentage
4  — Stop mentioned but no specific level or method
2  — Risk mentioned in passing
0  — No risk management

Focus on: Are there specific stop levels? Position sizing guidance? Trailing stop rules?""",
    },
    {
        "name": "Pattern Detection",
        "weight": 0.05,
        "prompt": """Evaluate CHART PATTERN DETECTION quality.

Scoring guide:
10 — Patterns correctly identified with price targets, confirmation criteria, and failure conditions
8  — Patterns identified with targets
6  — Patterns mentioned but without targets
4  — Generic pattern labels only
2  — Patterns claimed but clearly wrong
0  — No pattern detection

Focus on: Are identified patterns plausible given the price action described?""",
    },
    {
        "name": "Professional Presentation",
        "weight": 0.10,
        "prompt": """Evaluate the PROFESSIONAL PRESENTATION of the TA output.

Scoring guide:
10 — Well-organised, uses correct terminology, includes suggested followups, suitable for professional trader
8  — Good organisation with proper terminology
6  — Readable but somewhat disorganised or uses imprecise terms
4  — Basic but missing organisation or standard TA terminology
2  — Confusing output that would mislead a trader
0  — Unparseable or empty output

Focus on: Organisation, terminology correctness, follow-up suggestions, overall utility.""",
    },
]


# ═══════════════════════════════════════════════════════════════════
# LLM JUDGE
# ═══════════════════════════════════════════════════════════════════

def llm_judge(asset: str, dimension: dict, asset_data: dict,
              use_llm: bool = True) -> dict:
    """Score one dimension for one asset using LLM-as-judge."""
    if not use_llm:
        return {"dimension": dimension["name"], "score": 5.0,
                "explanation": "Default score (LLM disabled)", "asset": asset}

    # Build context from asset data
    murphy = asset_data.get("murphy_full", {}).get("data", {})
    sr = asset_data.get("support_resistance", {}).get("data", {})
    rsi = asset_data.get("rsi", {}).get("data", {})
    bo = asset_data.get("breakout", {}).get("data", {})
    snap = asset_data.get("quick_snapshot", {}).get("data", {})
    sl = asset_data.get("stop_loss", {}).get("data", {})
    synth = asset_data.get("fundamental_synthesis", {}).get("data", {})

    context = f"""ASSET: {asset}

MURPHY FULL TA (composite + all frameworks):
{json.dumps(murphy, indent=1, default=str)[:3000]}

SUPPORT/RESISTANCE:
{json.dumps(sr, indent=1, default=str)[:800]}

RSI (multi-period):
{json.dumps(rsi, indent=1, default=str)[:400]}

BREAKOUT ANALYSIS:
{json.dumps(bo, indent=1, default=str)[:600]}

QUICK TA SNAPSHOT:
{json.dumps(snap, indent=1, default=str)[:800]}

STOP-LOSS FRAMEWORK:
{json.dumps(sl, indent=1, default=str)[:1200]}
"""
    if synth:
        context += f"\nFUNDAMENTAL-TA SYNTHESIS:\n{json.dumps(synth, indent=1, default=str)[:500]}"

    system_msg = """You are a professional quantitative analyst evaluating the quality of technical analysis (TA) tool outputs. Score on a 0-10 scale based on the rubric provided. Be strict but fair.

After your analysis, you MUST end with exactly this format:
FINAL_SCORE: X/10
EXPLANATION: <one sentence>"""

    user_msg = f"""{dimension['prompt']}

---
TA OUTPUT TO EVALUATE:
{context}
---

Analyze this {dimension['name']} dimension. End with FINAL_SCORE: X/10 and EXPLANATION: <one sentence>."""

    try:
        import re
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("MINIMAX_API_KEY", ""),
            base_url="https://api.minimax.io/v1",
        )
        response = client.chat.completions.create(
            model="MiniMax-M2.5",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        text = response.choices[0].message.content.strip()
        # MiniMax-M2.5 wraps everything in <think>...</think>
        # Remove think tags but keep content
        clean = re.sub(r'</?think>', '', text).strip()

        score_val = None
        explanation = ""

        # Priority 1: FINAL_SCORE: X/10
        fs_match = re.search(r'FINAL_SCORE:\s*(\d+(?:\.\d+)?)\s*/\s*10', clean)
        if fs_match:
            score_val = float(fs_match.group(1))
            # Get EXPLANATION if present
            exp_match = re.search(r'EXPLANATION:\s*(.+?)(?:\n|$)', clean)
            if exp_match:
                explanation = exp_match.group(1).strip()

        # Priority 2: JSON object
        if score_val is None and "{" in clean and "}" in clean:
            try:
                json_str = clean[clean.index("{"):clean.rindex("}")+1]
                result = json.loads(json_str)
                score_val = float(result.get("score", 0))
                explanation = result.get("explanation", "")
            except (json.JSONDecodeError, ValueError):
                pass

        # Priority 3: Last N/10 pattern in text
        if score_val is None:
            matches = list(re.finditer(r'(\d+(?:\.\d+)?)\s*/\s*10', clean))
            if matches:
                score_val = float(matches[-1].group(1))
                start = max(0, matches[-1].start() - 100)
                explanation = clean[start:matches[-1].end()+50].strip().replace('\n', ' ')

        if score_val is not None and 0 <= score_val <= 10:
            return {"dimension": dimension["name"],
                    "score": score_val,
                    "explanation": explanation[:120],
                    "asset": asset}
    except Exception as e:
        print(f"    LLM error for {asset}/{dimension['name']}: {e}")

    return {"dimension": dimension["name"], "score": 5.0,
            "explanation": f"Default score (LLM unavailable)",
            "asset": asset}


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Approach #10: TA LLM Judge")
    parser.add_argument("--input", required=True, help="Path to ta_output_v1.json")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM calls, use default 5.0 scores")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    print("=" * 70)
    print("  APPROACH #10: TA QUALITY LLM JUDGE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  LLM: {'DISABLED' if args.no_llm else 'MiniMax-M1-80k'}")
    print("=" * 70)

    results = {}
    use_llm = not args.no_llm

    for asset, ad in data["assets"].items():
        print(f"\n{'─' * 60}  {asset}")
        asset_scores = []
        for dim in RUBRIC:
            result = llm_judge(asset, dim, ad, use_llm)
            asset_scores.append(result)
            icon = "\u2705" if result["score"] >= 6 else ("\u26a0\ufe0f" if result["score"] >= 4 else "\u274c")
            print(f"  {icon} {dim['name']:25s}: {result['score']:.1f}/10 "
                  f"(wt={dim['weight']:.0%}) — {result['explanation'][:60]}")

        # Weighted average
        weighted = sum(s["score"] * d["weight"]
                      for s, d in zip(asset_scores, RUBRIC))
        results[asset] = {
            "dimensions": asset_scores,
            "weighted_score": round(weighted, 2),
        }
        print(f"  {'─' * 40}")
        print(f"  WEIGHTED SCORE: {weighted:.2f}/10")

    # Cross-asset summary
    print(f"\n{'=' * 70}")
    print("  CROSS-ASSET SUMMARY")
    print(f"  {'Asset':8s}  {'Score':>6s}  {'Tier':>12s}")
    for asset, r in results.items():
        ws = r["weighted_score"]
        tier = ("Excellent" if ws >= 8 else "Good" if ws >= 6
                else "Acceptable" if ws >= 4 else "Poor")
        print(f"  {asset:8s}  {ws:6.2f}  {tier:>12s}")
    print("=" * 70)

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "approach": "10_ta_benchmark",
        "timestamp": datetime.now().isoformat(),
        "llm_enabled": use_llm,
        "rubric": [{"name": d["name"], "weight": d["weight"]} for d in RUBRIC],
        "results": results,
    }
    jp = _RECORDS / f"approach10_{ts}.json"
    with open(jp, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  Saved: {jp}")
    return results

if __name__ == "__main__":
    main()
