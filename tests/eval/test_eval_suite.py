"""
Eval suite: runs all YAML scenario fixtures against the agent with a mock LLM.
Reports recall (dangerous scenarios correctly caught) at the end.
"""
import json
from pathlib import Path

import pytest
import yaml
from unittest.mock import AsyncMock

from harness_gateway.client import GatewayClient
from harness_validator.agent import DeterministicValidatorAgent
from harness_validator.llm import LLMResponse
from harness_validator.policy import load_policy
from harness_validator.types import AgentState

FIXTURES_DIR = Path(__file__).parent / "fixtures"
POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "release_policy.yaml"

DANGEROUS_VERDICTS = {"BLOCK", "ESCALATE"}


def load_fixtures():
    scenarios = []
    for f in sorted(FIXTURES_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        scenarios.append((data["name"], data))
    return scenarios


def make_mock_gateway(scenario: dict):
    gw = AsyncMock(spec=GatewayClient)

    async def tool_side_effect(tool_name, params):
        if tool_name == "run_linter":
            return scenario["lint_result"]
        if tool_name == "coverage_report":
            return scenario["coverage_result"]
        return {}

    gw.call_tool.side_effect = tool_side_effect
    return gw


def make_mock_llm(classification: dict):
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content=json.dumps(classification))
    return llm


def make_state(scenario: dict) -> AgentState:
    return AgentState(
        task="Validate this diff against release policy",
        diff=scenario["diff"],
        thread_id="eval-thread",
        agent_output=None,
        requires_human_approval=False,
        error=None,
    )


@pytest.mark.eval
@pytest.mark.parametrize("name,scenario", load_fixtures())
async def test_eval_scenario(name, scenario):
    policy = load_policy(POLICY_PATH)
    mock_gateway = make_mock_gateway(scenario)
    mock_llm = make_mock_llm(scenario["mock_risk_classification"])

    agent = DeterministicValidatorAgent(
        gateway=mock_gateway,
        llm_provider=mock_llm,
        policy=policy,
    )

    result = await agent.run(make_state(scenario))

    assert result["error"] is None, f"[{name}] Unexpected error: {result['error']}"
    output = result["agent_output"]
    assert output is not None, f"[{name}] No agent_output"

    expected_verdict = scenario["expected_verdict"]
    assert output["verdict"] == expected_verdict, (
        f"[{name}] Expected verdict={expected_verdict}, got={output['verdict']}\n"
        f"Checks: {json.dumps(output['checks'], indent=2)}"
    )

    # If the fixture specifies which check should fail, verify it
    if "expected_check_failed" in scenario:
        expected_check = scenario["expected_check_failed"]
        failed_checks = [c["check"] for c in output["checks"] if not c["passed"]]
        assert expected_check in failed_checks, (
            f"[{name}] Expected '{expected_check}' to fail, got failed checks: {failed_checks}"
        )

    # If the fixture specifies expected risk profile, verify it
    if "expected_risk_profile" in scenario:
        expected_profile = scenario["expected_risk_profile"]
        assert output["risk_profile"] == expected_profile, (
            f"[{name}] Expected risk_profile={expected_profile}, got={output['risk_profile']}"
        )


def test_eval_recall_summary():
    """Compute and assert recall: all dangerous scenarios must be caught."""
    scenarios = load_fixtures()

    dangerous = [s for _, s in scenarios if s["expected_verdict"] in DANGEROUS_VERDICTS]
    total = len(scenarios)
    n_dangerous = len(dangerous)

    # This test just documents the numbers — actual recall is verified per-scenario above
    print(f"\n=== Eval Recall Summary ===")
    print(f"Total scenarios: {total}")
    print(f"Dangerous (BLOCK/ESCALATE): {n_dangerous}")
    print(f"Safe (ALLOW): {total - n_dangerous}")
    print(f"Theoretical recall target: 100% ({n_dangerous}/{n_dangerous})")

    # Sanity check: we have at least one scenario of each type
    assert n_dangerous > 0, "Eval suite must include at least one BLOCK or ESCALATE scenario"
    assert (total - n_dangerous) > 0, "Eval suite must include at least one ALLOW scenario"
