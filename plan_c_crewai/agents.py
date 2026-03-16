"""
Plan C — CrewAI Agent Definitions.

Three agents with distinct roles:
    1. QA Orchestrator (manager) — drives the cycle, decides when to stop
    2. Testing Specialist — runs tests, interprets results
    3. Financial Engineer — reads code, diagnoses bugs, applies patches
"""

import os
import sys
from pathlib import Path

from crewai import Agent, LLM

from tools import (
    RunTestsTool,
    ReadSourceTool,
    ApplyPatchTool,
    ListFilesTool,
    GitCommitTool,
)
from config import (
    FINANCIAL_AGENT_ROOT,
    CREWAI_LLM_MODEL,
    CREWAI_LLM_API_KEY,
    CREWAI_LLM_BASE_URL,
)


def _get_llm() -> LLM:
    """Build the CrewAI LLM instance from config or Financial Agent defaults."""
    api_key = CREWAI_LLM_API_KEY
    base_url = CREWAI_LLM_BASE_URL
    model = CREWAI_LLM_MODEL

    if not api_key:
        sys.path.insert(0, str(FINANCIAL_AGENT_ROOT))
        from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
        api_key = api_key or LLM_API_KEY
        base_url = base_url or LLM_BASE_URL
        model = model or LLM_MODEL

    return LLM(
        model=f"openai/{model}",
        api_key=api_key,
        base_url=base_url,
        temperature=0.15,
    )


def create_qa_orchestrator() -> Agent:
    """The QA Orchestrator (manager agent).

    Coordinates the testing-fixing cycle. Decides when to run tests,
    what failures to prioritize, and when to stop iterating.
    """
    return Agent(
        role="QA Orchestrator",
        goal=(
            "Drive the Financial Agent's test pass rate above the target threshold "
            "by coordinating iterative test-fix cycles. Prioritize critical and high "
            "severity failures. Stop when converged or when no further progress is possible."
        ),
        backstory=(
            "You are a senior QA engineering lead with 15 years of experience in "
            "financial software quality. You've built testing pipelines for Bloomberg, "
            "Goldman Sachs, and Two Sigma. You think systematically: test first, analyze "
            "failures, fix the most impactful bugs, verify the fix, repeat. You never "
            "let a critical bug slip to production."
        ),
        llm=_get_llm(),
        verbose=True,
        allow_delegation=True,
        memory=True,
    )


def create_testing_specialist() -> Agent:
    """The Testing Specialist agent.

    Runs the QA test suites and interprets results. Reports structured
    findings back to the orchestrator.
    """
    return Agent(
        role="Testing Specialist",
        goal=(
            "Execute QA test suites against the Financial Agent and produce clear, "
            "structured reports of all failures with their severity, affected tools, "
            "and actionable context for the engineer to fix them."
        ),
        backstory=(
            "You are a meticulous QA engineer specializing in financial data systems. "
            "You've tested macro data pipelines, equity analysis tools, and real-time "
            "trading signals. You know that a wrong RSI value or a misclassified credit "
            "spread can cost millions. You document everything precisely."
        ),
        tools=[RunTestsTool()],
        llm=_get_llm(),
        verbose=True,
        memory=True,
    )


def create_financial_engineer() -> Agent:
    """The Financial Engineer agent.

    Reads Financial Agent source code, diagnoses root causes of test
    failures, and applies minimal targeted patches to fix them.
    """
    return Agent(
        role="Financial Software Engineer",
        goal=(
            "Diagnose the root cause of each test failure by reading the relevant "
            "Financial Agent source code, then apply minimal, targeted code patches "
            "that fix the bug without introducing side effects. After applying patches, "
            "commit the changes."
        ),
        backstory=(
            "You are a senior financial software engineer who has built quantitative "
            "analysis tools for hedge funds. You understand VIX thresholds, credit "
            "spread classification, RSI calculations, Graham Number formulas, and "
            "macro regime detection. You write surgical bug fixes — never more code "
            "than necessary. You always read the source before patching."
        ),
        tools=[
            ReadSourceTool(),
            ApplyPatchTool(),
            ListFilesTool(),
            GitCommitTool(),
        ],
        llm=_get_llm(),
        verbose=True,
        memory=True,
    )
