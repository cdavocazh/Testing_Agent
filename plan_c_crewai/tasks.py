"""
Plan C — CrewAI Task Definitions.

Tasks represent discrete units of work assigned to agents.
The orchestrator uses these as building blocks for the iterative cycle.
"""

from crewai import Task, Agent


def create_run_tests_task(
    agent: Agent,
    suite: str = "all",
    iteration: int = 1,
    context_tasks: list[Task] | None = None,
) -> Task:
    """Task: Run the QA test suite and report results.

    Assigned to the Testing Specialist.
    """
    return Task(
        description=(
            f"## Iteration {iteration}: Run QA Tests\n\n"
            f"Execute the Financial Agent QA test suite (suite='{suite}') using the "
            f"`run_qa_tests` tool. Parse the results and produce a structured summary:\n\n"
            f"1. Overall pass rate and test counts\n"
            f"2. List of ALL failures grouped by severity (critical, high, normal, low)\n"
            f"3. For each failure: suite name, command, check description, and notes\n"
            f"4. Identify any patterns (e.g., all FRED tests fail = API key issue)\n\n"
            f"Be precise and thorough. The Financial Engineer needs actionable details."
        ),
        expected_output=(
            "A structured JSON report with: pass_rate (number), total/passed/failed counts, "
            "and a 'failures' array where each entry has suite, command, check, notes, severity. "
            "Also include a 'patterns' field noting any systemic issues."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_fix_failures_task(
    agent: Agent,
    iteration: int = 1,
    context_tasks: list[Task] | None = None,
) -> Task:
    """Task: Diagnose and fix test failures.

    Assigned to the Financial Engineer. Depends on test results from
    the Testing Specialist.
    """
    return Task(
        description=(
            f"## Iteration {iteration}: Fix Test Failures\n\n"
            f"Based on the test results from the Testing Specialist:\n\n"
            f"1. Prioritize CRITICAL and HIGH severity failures first\n"
            f"2. For each failure, use `list_financial_agent_files` to find the relevant tool file\n"
            f"3. Use `read_financial_agent_source` to read the source code\n"
            f"4. Diagnose the root cause of each failure\n"
            f"5. Use `apply_code_patch` to apply minimal, targeted fixes\n"
            f"6. After all patches, use `git_commit_changes` to checkpoint\n\n"
            f"## Important Rules\n"
            f"- Only fix what the tests report as broken\n"
            f"- Keep patches minimal (1-5 lines preferred)\n"
            f"- Do NOT refactor, optimize, or add features\n"
            f"- If a failure is due to external data (API down, stale CSV), skip it and explain why\n"
            f"- Read the source BEFORE attempting any patch"
        ),
        expected_output=(
            "A JSON report with: 'patches_applied' (count), 'patches' (array of "
            "{file, description, applied} objects), 'skipped' (array of failures that "
            "could not be fixed and why), and 'committed' (boolean)."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_evaluate_progress_task(
    agent: Agent,
    iteration: int,
    target_pass_rate: float,
    max_iterations: int,
    context_tasks: list[Task] | None = None,
) -> Task:
    """Task: Evaluate progress and decide whether to continue.

    Assigned to the QA Orchestrator. Decides if another cycle is needed.
    """
    return Task(
        description=(
            f"## Iteration {iteration}: Evaluate Progress\n\n"
            f"Review the test results and patches from this iteration:\n\n"
            f"1. Current pass rate vs target ({target_pass_rate}%)\n"
            f"2. Number of critical failures remaining\n"
            f"3. Whether patches were successfully applied\n"
            f"4. Whether we're making progress (pass rate improving)\n"
            f"5. Whether we've hit max iterations ({max_iterations})\n\n"
            f"Decide: should we run another test-fix cycle?\n\n"
            f"Return a JSON decision:\n"
            f"- 'continue': true/false\n"
            f"- 'reason': why you decided to continue or stop\n"
            f"- 'current_pass_rate': the latest pass rate\n"
            f"- 'iteration': {iteration}"
        ),
        expected_output=(
            "JSON with 'continue' (boolean), 'reason' (string explaining the decision), "
            "'current_pass_rate' (number), and 'iteration' (number)."
        ),
        agent=agent,
        context=context_tasks or [],
    )
