import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from harness_gateway.client import GatewayClient
from harness_validator.policy import load_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "policies" / "release_policy.yaml"

GOVERNANCE_URL = os.environ.get("GOVERNANCE_URL", "http://localhost:8090")


@pytest.fixture
def release_policy():
    return load_policy(POLICY_PATH)


@pytest.fixture
def mock_gateway():
    gw = AsyncMock(spec=GatewayClient)

    async def _default_tool(tool_name, params):
        if tool_name == "run_linter":
            return {"warnings": [], "error_count": 0}
        if tool_name == "coverage_report":
            return {"coverage": 0.91, "lines_covered": 182, "lines_total": 200, "source": "stub"}
        return {}

    gw.call_tool.side_effect = _default_tool
    return gw
