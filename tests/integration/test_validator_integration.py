"""
Integration tests — require the full Docker stack running.
Run: make stack-up && pytest tests/integration/ -v -m integration
"""
import os
import pytest
import httpx
import pymysql

GOVERNANCE_URL = os.environ.get("GOVERNANCE_URL", "http://localhost:8090")
OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181")
MCPJUNGLE_URL = os.environ.get("MCPJUNGLE_URL", "http://localhost:8080")
DOLT_HOST = os.environ.get("DOLT_HOST", "localhost")
DOLT_PORT = int(os.environ.get("DOLT_PORT", "3306"))
VALIDATOR_SECRET = os.environ.get("VALIDATOR_SECRET", "validator-secret")

CLEAN_DIFF = """\
diff --git a/README.md b/README.md
index abc123..def456 100644
--- a/README.md
+++ b/README.md
@@ -1,2 +1,3 @@
 # My Project
+Added a new section.
 More info here.
"""


@pytest.fixture
async def validator_token():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOVERNANCE_URL}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "deterministic-validator",
                "client_secret": VALIDATOR_SECRET,
            },
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture
def dolt_conn():
    conn = pymysql.connect(
        host=DOLT_HOST,
        port=DOLT_PORT,
        user="root",
        password="root",
        database="harness",
        autocommit=True,
    )
    yield conn
    conn.close()


# --- Auth tests ---

@pytest.mark.integration
async def test_validator_client_auth():
    """Governance issues a JWT for the deterministic-validator client."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOVERNANCE_URL}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "deterministic-validator",
                "client_secret": VALIDATOR_SECRET,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.integration
async def test_unknown_client_rejected():
    """Unknown client gets 401."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOVERNANCE_URL}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "not-a-real-client",
                "client_secret": "wrong",
            },
        )
    assert resp.status_code == 401


# --- OPA policy tests ---

@pytest.mark.integration
async def test_opa_allow_validator_linter():
    """OPA permits deterministic_validator to call run_linter."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{OPA_URL}/v1/data/harness/allow",
            json={"input": {"agent_role": "deterministic_validator", "tool_name": "run_linter"}},
        )
    assert resp.status_code == 200
    assert resp.json()["result"] is True


@pytest.mark.integration
async def test_opa_deny_validator_shell_exec():
    """OPA denies deterministic_validator from calling shell_exec."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{OPA_URL}/v1/data/harness/allow",
            json={"input": {"agent_role": "deterministic_validator", "tool_name": "shell_exec"}},
        )
    assert resp.status_code == 200
    assert resp.json()["result"] is False


@pytest.mark.integration
async def test_validator_token_denied_cross_role_tool(validator_token):
    """Validator token calling shell_exec through governance gets 403."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOVERNANCE_URL}/api/v0/tools/invoke",
            json={"name": "sre_stub__shell_exec", "command": "ls"},
            headers={"Authorization": f"Bearer {validator_token}"},
        )
    assert resp.status_code == 403


# --- Tool reachability ---

@pytest.mark.integration
async def test_validate_diff_tool_registered():
    """validate_diff tool is registered in MCPJungle."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MCPJUNGLE_URL}/api/v0/tools")
    assert resp.status_code == 200
    tool_names = [t.get("name", "") for t in resp.json()]
    assert any("validate_diff" in name for name in tool_names)


# --- End-to-end ---

@pytest.mark.integration
async def test_validate_diff_clean_returns_allow(validator_token):
    """End-to-end: clean diff → ALLOW verdict from the validator_server tool."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{GOVERNANCE_URL}/api/v0/tools/invoke",
            json={"name": "validator_server__validate_diff", "diff_text": CLEAN_DIFF},
            headers={"Authorization": f"Bearer {validator_token}"},
        )
    assert resp.status_code == 200
    # Unwrap MCPJungle response envelope
    data = resp.json()
    items = data.get("content") or data.get("result") or []
    import json
    output = json.loads(items[0]["text"]) if items and items[0].get("type") == "text" else data
    assert output["verdict"] in ("ALLOW", "ESCALATE")  # depends on LLM; clean diff should not BLOCK


# --- Audit ---

@pytest.mark.integration
async def test_audit_row_written_after_tool_call(validator_token, dolt_conn):
    """After calling a tool, Dolt audit_log contains a new row for this agent."""
    with dolt_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_log WHERE agent_id = 'deterministic-validator'")
        before = cur.fetchone()[0]

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{GOVERNANCE_URL}/api/v0/tools/invoke",
            json={"name": "linter_stub__run_linter", "diff_text": CLEAN_DIFF},
            headers={"Authorization": f"Bearer {validator_token}"},
        )

    with dolt_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_log WHERE agent_id = 'deterministic-validator'")
        after = cur.fetchone()[0]

    assert after > before
