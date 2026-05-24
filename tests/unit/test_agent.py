import json
import pytest
from unittest.mock import AsyncMock, call
from uuid import uuid4

import jsonschema

from harness_gateway.client import ToolAccessDenied
from harness_validator.agent import DeterministicValidatorAgent
from harness_validator.llm import LLMResponse
from harness_validator.types import AgentState, VALIDATOR_OUTPUT_SCHEMA

from tests.helpers import (
    CLEAN_DIFF,
    AUTH_DIFF,
    CLEAN_CLASSIFICATION,
    HIGH_RISK_CLASSIFICATION,
    MEDIUM_RISK_CLASSIFICATION,
    make_mock_llm,
)


def make_state(diff: str) -> AgentState:
    return AgentState(
        task="Validate this diff",
        diff=diff,
        thread_id=str(uuid4()),
        agent_output=None,
        requires_human_approval=False,
        error=None,
    )


def make_agent(mock_gateway, mock_llm, release_policy):
    return DeterministicValidatorAgent(
        gateway=mock_gateway,
        llm_provider=mock_llm,
        policy=release_policy,
    )


# --- ALLOW ---

async def test_allow_verdict_clean_diff(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(CLEAN_DIFF))
    assert result["agent_output"]["verdict"] == "ALLOW"
    assert result["error"] is None


# --- BLOCK: prohibited directory ---

async def test_block_prohibited_directory(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(AUTH_DIFF))
    assert result["agent_output"]["verdict"] == "BLOCK"
    failed = [c for c in result["agent_output"]["checks"] if not c["passed"]]
    assert any("ProhibitedDirectories" == c["check"] for c in failed)


async def test_prohibited_dir_short_circuits_no_linter_no_coverage(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    await agent.run(make_state(AUTH_DIFF))
    # Neither linter nor coverage should be called
    mock_gateway.call_tool.assert_not_called()
    # LLM should not be called either
    llm.chat.assert_not_called()


# --- BLOCK: diff too large ---

async def test_block_diff_too_large(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    big_diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
    big_diff += "\n".join(f"+line {i}" for i in range(400))
    result = await agent.run(make_state(big_diff))
    assert result["agent_output"]["verdict"] == "BLOCK"
    checks = result["agent_output"]["checks"]
    assert any(c["check"] == "MaximumDiffLines" and not c["passed"] for c in checks)


# --- BLOCK: critical lint ---

async def test_block_critical_lint(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)

    async def linter_returns_critical(tool_name, params):
        if tool_name == "run_linter":
            return {
                "warnings": [{"rule": "injection", "message": "SQL injection risk", "severity": "CRITICAL"}],
                "error_count": 1,
            }
        return {"coverage": 0.91, "lines_covered": 182, "lines_total": 200, "source": "stub"}

    mock_gateway.call_tool.side_effect = linter_returns_critical
    result = await agent.run(make_state(CLEAN_DIFF))
    assert result["agent_output"]["verdict"] == "BLOCK"
    checks = result["agent_output"]["checks"]
    assert any(c["check"] == "StaticAnalysisThreshold" and not c["passed"] for c in checks)


# --- BLOCK: low coverage ---

async def test_block_low_coverage(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)

    async def low_coverage(tool_name, params):
        if tool_name == "run_linter":
            return {"warnings": [], "error_count": 0}
        return {"coverage": 0.80, "lines_covered": 160, "lines_total": 200, "source": "stub"}

    mock_gateway.call_tool.side_effect = low_coverage
    result = await agent.run(make_state(CLEAN_DIFF))
    assert result["agent_output"]["verdict"] == "BLOCK"
    checks = result["agent_output"]["checks"]
    assert any(c["check"] == "RequireTestCoverage" and not c["passed"] for c in checks)


# --- ESCALATE: high risk ---

PY_DIFF = """\
diff --git a/app.py b/app.py
index abc..def 100644
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
 def hello():
+    return "world"
"""


async def test_escalate_high_risk(mock_gateway, release_policy):
    llm = make_mock_llm(HIGH_RISK_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(PY_DIFF))
    assert result["agent_output"]["verdict"] == "ESCALATE"
    assert result["requires_human_approval"] is True
    assert result["agent_output"]["risk_profile"] in ("High", "Severe")


async def test_escalate_does_not_call_coverage(mock_gateway, release_policy):
    llm = make_mock_llm(HIGH_RISK_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    await agent.run(make_state(PY_DIFF))
    called_tools = [c.args[0] for c in mock_gateway.call_tool.call_args_list]
    assert "coverage_report" not in called_tools


# --- Error handling ---

async def test_tool_access_denied_returns_error_state(release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    gw = AsyncMock()
    gw.call_tool.side_effect = ToolAccessDenied("403 Forbidden: run_linter")
    agent = DeterministicValidatorAgent(gateway=gw, llm_provider=llm, policy=release_policy)
    result = await agent.run(make_state(CLEAN_DIFF))
    assert result["error"] is not None
    assert result["error"]["code"] == "tool_access_denied"


# --- Schema + audit ---

async def test_output_validates_against_schema(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(CLEAN_DIFF))
    jsonschema.validate(result["agent_output"], VALIDATOR_OUTPUT_SCHEMA)


async def test_docs_only_diff_skips_llm_and_returns_low(mock_gateway, release_policy):
    """A diff touching only docs files should skip the LLM and default to Low risk."""
    llm = make_mock_llm(HIGH_RISK_CLASSIFICATION)  # would escalate if called
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(CLEAN_DIFF))
    assert result["agent_output"]["verdict"] == "ALLOW"
    assert result["agent_output"]["risk_profile"] == "Low"
    llm.chat.assert_not_called()


async def test_audit_contains_policy_hash(mock_gateway, release_policy):
    llm = make_mock_llm(CLEAN_CLASSIFICATION)
    agent = make_agent(mock_gateway, llm, release_policy)
    result = await agent.run(make_state(CLEAN_DIFF))
    audit = result["agent_output"]["audit"]
    assert len(audit["policy_commit_hash"]) == 64  # SHA-256 hex
    assert audit["diff_lines"] >= 0
