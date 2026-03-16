"""
Plan S — Superset MCP API Client.

Wraps the Superset.sh MCP server API for workspace management, agent
session launching, and status polling.

Superset's MCP endpoint exposes these capabilities:
    - Workspace: initialize, list, retrieve, rename, delete
    - Agent sessions: launch (Claude, Codex, Gemini, etc.) with task context
    - Tasks: create, update, list, retrieve, soft-delete

This client uses the REST-over-MCP protocol via HTTP POST.
"""

import json
import os
import time
from dataclasses import dataclass

import requests

from config import (
    SUPERSET_MCP_URL,
    SUPERSET_API_KEY,
    SUPERSET_PROJECT_ID,
    POLL_INTERVAL_SECONDS,
    AGENT_TIMEOUT_SECONDS,
)


@dataclass
class WorkspaceInfo:
    workspace_id: str
    name: str
    branch: str
    path: str
    status: str


@dataclass
class AgentSessionInfo:
    session_id: str
    workspace_id: str
    agent_type: str
    status: str  # "running", "completed", "failed", "waiting_for_input"


class SupersetClient:
    """Client for the Superset.sh MCP API.

    Authentication:
        - API key (sk_live_...): set SUPERSET_API_KEY env var
        - OAuth: handle externally, pass token to constructor

    The MCP protocol sends JSON-RPC style requests to the MCP endpoint.
    """

    def __init__(self, api_key: str = "", mcp_url: str = ""):
        self.api_key = api_key or SUPERSET_API_KEY
        self.mcp_url = mcp_url or SUPERSET_MCP_URL
        self.project_id = SUPERSET_PROJECT_ID

        if not self.api_key:
            raise ValueError(
                "Superset API key required. Set SUPERSET_API_KEY env var "
                "(format: sk_live_...) or pass api_key to constructor."
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _mcp_call(self, method: str, params: dict) -> dict:
        """Make an MCP tool call to the Superset API.

        The MCP protocol wraps tool calls as JSON-RPC:
            POST /api/agent/mcp
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "<tool_name>", "arguments": {...}}
            }
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": method,
                "arguments": params,
            },
        }

        resp = requests.post(
            self.mcp_url,
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error']}")

        return result.get("result", {})

    # ── Workspace management ─────────────────────────────────────────

    def create_workspace(self, name: str) -> WorkspaceInfo:
        """Initialize a new Git worktree workspace in Superset.

        This creates an isolated copy of the repository on a new branch.
        """
        result = self._mcp_call("initialize_workspace", {
            "name": name,
            "projectId": self.project_id,
        })

        return WorkspaceInfo(
            workspace_id=result.get("id", ""),
            name=result.get("name", name),
            branch=result.get("branch", ""),
            path=result.get("path", ""),
            status=result.get("status", "created"),
        )

    def get_workspace(self, workspace_id: str) -> WorkspaceInfo:
        """Get details of an existing workspace."""
        result = self._mcp_call("get_workspace_details", {
            "workspaceId": workspace_id,
        })
        return WorkspaceInfo(
            workspace_id=result.get("id", workspace_id),
            name=result.get("name", ""),
            branch=result.get("branch", ""),
            path=result.get("path", ""),
            status=result.get("status", ""),
        )

    def list_workspaces(self) -> list[WorkspaceInfo]:
        """List all workspaces in the project."""
        result = self._mcp_call("list_workspaces", {
            "projectId": self.project_id,
        })
        workspaces = result.get("workspaces", [])
        return [
            WorkspaceInfo(
                workspace_id=w.get("id", ""),
                name=w.get("name", ""),
                branch=w.get("branch", ""),
                path=w.get("path", ""),
                status=w.get("status", ""),
            )
            for w in workspaces
        ]

    def delete_workspace(self, workspace_id: str):
        """Delete a workspace and its worktree."""
        self._mcp_call("delete_workspace", {"workspaceId": workspace_id})

    # ── Agent session management ─────────────────────────────────────

    def launch_agent_session(
        self,
        workspace_id: str,
        agent_type: str,
        task_prompt: str,
    ) -> AgentSessionInfo:
        """Launch an AI agent session in a workspace.

        Args:
            workspace_id: Workspace to run in.
            agent_type: "claude" | "codex" | "gemini" | "aider" | "copilot"
            task_prompt: The prompt/instructions for the agent.

        Returns:
            AgentSessionInfo with session_id for polling.
        """
        result = self._mcp_call("launch_agent_session", {
            "workspaceId": workspace_id,
            "agentType": agent_type,
            "taskContext": task_prompt,
        })

        return AgentSessionInfo(
            session_id=result.get("sessionId", ""),
            workspace_id=workspace_id,
            agent_type=agent_type,
            status=result.get("status", "running"),
        )

    def get_session_status(self, session_id: str) -> str:
        """Check if an agent session is still running.

        Returns: "running", "completed", "failed", "waiting_for_input"
        """
        result = self._mcp_call("get_session_status", {
            "sessionId": session_id,
        })
        return result.get("status", "unknown")

    def wait_for_session(self, session_id: str) -> str:
        """Poll until an agent session completes or times out.

        Returns final status: "completed", "failed", or "timeout".
        """
        start = time.time()
        while time.time() - start < AGENT_TIMEOUT_SECONDS:
            status = self.get_session_status(session_id)
            if status in ("completed", "failed"):
                return status
            if status == "waiting_for_input":
                print(f"    WARNING: Agent is waiting for input (session {session_id})")
                return "waiting_for_input"
            time.sleep(POLL_INTERVAL_SECONDS)
        return "timeout"

    # ── Task management ──────────────────────────────────────────────

    def create_task(self, title: str, description: str, priority: str = "medium") -> str:
        """Create a task in Superset's task manager.

        Returns the task ID.
        """
        result = self._mcp_call("create_tasks", {
            "tasks": [{
                "title": title,
                "description": description,
                "priority": priority,
            }],
        })
        tasks = result.get("tasks", [])
        return tasks[0].get("id", "") if tasks else ""
