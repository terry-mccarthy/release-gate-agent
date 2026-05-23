import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from harness_gateway.client import GatewayClient, ToolAccessDenied
from harness_validator import checker, classifier
from harness_validator.llm import LLMProvider
from harness_validator.policy import ReleasePolicy, load_policy
from harness_validator.types import AgentState, VALIDATOR_OUTPUT_SCHEMA

logger = logging.getLogger(__name__)

_DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "policies" / "release_policy.yaml"
_DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "risk_classifier.md"


class DeterministicValidatorAgent:
    name = "deterministic_validator"
    allowed_tools = ["run_linter", "coverage_report"]
    memory_namespace = "deterministic_validator"

    def __init__(
        self,
        gateway: GatewayClient,
        llm_provider: LLMProvider,
        policy: ReleasePolicy | None = None,
    ):
        self.gateway = gateway
        self.llm = llm_provider
        if policy is None:
            policy_path = Path(os.environ.get("POLICY_FILE", str(_DEFAULT_POLICY_PATH)))
            policy = load_policy(policy_path)
        self.policy = policy
        prompt_path = Path(os.environ.get("PROMPTS_DIR", str(_DEFAULT_PROMPT_PATH.parent))) / "risk_classifier.md"
        self._system_prompt = prompt_path.read_text()

    async def run(self, state: AgentState) -> AgentState:
        diff_text = state["diff"]
        thread_id = state["thread_id"]
        diff_lines = checker.count_diff_lines(diff_text)

        checks_run: list[dict] = []

        # Step 1: Prohibited directories check (no tools, no LLM — immediate short-circuit)
        passed, detail = checker.check_prohibited_directories(
            diff_text, self.policy.prohibited_directories
        )
        checks_run.append({"check": "ProhibitedDirectories", "passed": passed, "detail": detail})
        if not passed:
            return self._build_state(state, "BLOCK", "Unknown", checks_run, diff_lines)

        # Step 2: Linter tool call
        try:
            lint_result = await self.gateway.call_tool("run_linter", {"diff_text": diff_text})
        except ToolAccessDenied as e:
            logger.error("tool_access_denied: %s", e)
            return {**state, "error": {"code": "tool_access_denied", "reason": str(e)}}

        # Step 3: LLM risk classification
        linter_findings = lint_result.get("warnings", [])
        try:
            risk_profile, _classification = await classifier.classify_risk(
                diff_text, linter_findings, self.llm, self._system_prompt
            )
        except RuntimeError as e:
            logger.error("risk classification failed: %s", e)
            return {**state, "error": {"code": "classification_failed", "reason": str(e)}}

        # Step 4: High/Severe → escalate immediately
        if risk_profile in ("High", "Severe"):
            checks_run.append({
                "check": "AllowedRiskProfiles",
                "passed": False,
                "detail": f"Risk profile '{risk_profile}' requires mandatory human review",
            })
            return self._build_state(state, "ESCALATE", risk_profile, checks_run, diff_lines, requires_human=True)

        # Step 5: Coverage tool call (only for Low/Medium)
        try:
            coverage_result = await self.gateway.call_tool("coverage_report", {"diff_text": diff_text})
        except ToolAccessDenied as e:
            logger.error("tool_access_denied: %s", e)
            return {**state, "error": {"code": "tool_access_denied", "reason": str(e)}}

        # Steps 6-8: Deterministic policy checks
        verdict = "ALLOW"

        passed, detail = checker.check_diff_size(diff_lines, self.policy.maximum_diff_lines)
        checks_run.append({"check": "MaximumDiffLines", "passed": passed, "detail": detail})
        if not passed:
            verdict = "BLOCK"

        if verdict == "ALLOW":
            passed, detail = checker.check_static_analysis(lint_result)
            checks_run.append({"check": "StaticAnalysisThreshold", "passed": passed, "detail": detail})
            if not passed:
                verdict = "BLOCK"

        if verdict == "ALLOW":
            passed, detail = checker.check_test_coverage(
                coverage_result, self.policy.require_test_coverage
            )
            checks_run.append({"check": "RequireTestCoverage", "passed": passed, "detail": detail})
            if not passed:
                verdict = "BLOCK"

        if verdict == "ALLOW":
            checks_run.append({
                "check": "AllowedRiskProfiles",
                "passed": True,
                "detail": f"Risk profile '{risk_profile}' is allowed",
            })

        return self._build_state(state, verdict, risk_profile, checks_run, diff_lines)

    def _build_state(
        self,
        state: AgentState,
        verdict: str,
        risk_profile: str,
        checks: list[dict],
        diff_lines: int,
        requires_human: bool = False,
    ) -> AgentState:
        output = {
            "verdict": verdict,
            "policy_version": self.policy.version,
            "risk_profile": risk_profile,
            "checks": checks,
            "audit": {
                "policy_commit_hash": self.policy.raw_hash,
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "diff_lines": diff_lines,
                "thread_id": state["thread_id"],
            },
        }
        jsonschema.validate(output, VALIDATOR_OUTPUT_SCHEMA)
        return {**state, "agent_output": output, "requires_human_approval": requires_human}
