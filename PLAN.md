# Plan: Deterministic Validator — Standalone App

## Context

`background.md` defines a Release Agent Gate — a deterministic binary gate embedded in CI/CD that evaluates code changes against a Declarative Policy. The gate classifies changes by three vectors (Data Surface, Integration Depth, Vulnerability Surface) using an LLM, then enforces deterministic policy constraints (prohibited directories, diff size, static analysis, coverage). High/Severe risk goes to human review; Low/Medium goes through automated validation.

This is a **fully self-contained repo** at `/Users/terry/personal/rbcr/`. All infrastructure (governance, gateway client, OPA, Dolt, MCP stubs) is copied from friday and lives here. No cross-repo dependencies.

---

## File Structure

```
/Users/terry/personal/rbcr/
├── pyproject.toml                         # uv workspace root, pytest config
├── .env.example
├── Makefile                               # stack-up, test-unit, test-integration, test-eval
├── docker-compose.yml                     # full stack (opa, dolt, mcpjungle, governance, stubs)
├── policies/
│   ├── harness.rego                       # OPA policy (validator role only)
│   └── release_policy.yaml               # Declarative Policy (the gate's rulebook)
├── prompts/
│   └── risk_classifier.md                # LLM system prompt for 3-vector classification
│
├── packages/
│   ├── harness-gateway/                  # copied + trimmed from friday
│   │   ├── pyproject.toml
│   │   └── harness_gateway/
│   │       └── client.py                 # GatewayClient + ToolAccessDenied + TOOL_NAME_MAP
│   │
│   └── harness-validator/
│       ├── pyproject.toml
│       └── harness_validator/
│           ├── __init__.py
│           ├── types.py                  # AgentState, VALIDATOR_OUTPUT_SCHEMA, RISK_CLASSIFICATION_SCHEMA
│           ├── policy.py                 # ReleasePolicy dataclass + load_policy()
│           ├── classifier.py             # LLM risk classifier (retries, schema validation)
│           ├── checker.py                # Pure deterministic checkers
│           └── agent.py                  # DeterministicValidatorAgent
│
├── services/
│   ├── governance/                       # copied from friday, trimmed to validator client only
│   │   ├── server.py                     # FastAPI: /oauth/token + /api/v0/tools/invoke
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── validator_server/
│       ├── server.py                     # FastMCP: validate_diff tool (port 9007)
│       ├── requirements.txt
│       └── Dockerfile
│
├── stub_servers/
│   ├── Dockerfile.stub
│   ├── linter_server.py                  # run_linter stub (port 9002) — copied from friday
│   └── coverage_server.py                # coverage_report stub (port 9006) — new
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_policy_loader.py          # 6 tests
    │   ├── test_checker.py                # 14 tests
    │   └── test_agent.py                  # 10 tests (mock gateway + mock LLM)
    ├── integration/
    │   └── test_validator_integration.py  # 8 tests (requires Docker)
    └── eval/
        ├── fixtures/
        │   ├── scenario_allow_clean.yaml
        │   ├── scenario_block_prohibited_dir.yaml
        │   ├── scenario_block_diff_too_large.yaml
        │   ├── scenario_block_critical_lint.yaml
        │   ├── scenario_block_low_coverage.yaml
        │   ├── scenario_escalate_high_risk.yaml
        │   ├── scenario_allow_boundary_diff.yaml
        │   ├── scenario_allow_boundary_coverage.yaml
        │   └── scenario_block_multi_vector.yaml
        └── test_eval_suite.py             # 9 eval scenarios (mock LLM)
```

---

## What to Copy from Friday

| Source (friday) | Destination (rbcr) | Notes |
|---|---|---|
| `packages/harness-gateway/` | `packages/harness-gateway/` | Trim `TOOL_NAME_MAP` to just `run_linter`, `coverage_report` |
| `services/governance/server.py` | `services/governance/server.py` | Keep only `deterministic-validator` client; strip architect/sre/code-reviewer |
| `services/governance/requirements.txt` | same | unchanged |
| `services/governance/Dockerfile` | same | unchanged |
| `stub_servers/linter_server.py` | `stub_servers/linter_server.py` | unchanged |
| `stub_servers/Dockerfile.stub` | `stub_servers/Dockerfile.stub` | unchanged |
| `packages/harness-agents/harness_agents/llm.py` | inline into `harness_validator/llm.py` | Copy `LLMProvider`, `LLMResponse`, `OllamaProvider`, `GeminiProvider` |
| `packages/harness-agents/harness_agents/types.py` | inline into `harness_validator/types.py` | Copy `AgentState` TypedDict only |

**Friday is NOT a runtime dependency.** The pyproject.toml for `harness-validator` only depends on the local `harness-gateway` package within this repo.

---

## Agent Flow

```
diff in state["diff"]
    ↓
1. check_prohibited_directories(diff, policy)   → BLOCK immediately (no tools, no LLM)
    ↓
2. gateway.call_tool("run_linter", {diff_text}) → linter findings
    ↓
3. LLM risk classification                      → {data_surface, integration_depth, vulnerability_surface}
   (diff + linter findings as context; up to 3 retries; validated against RISK_CLASSIFICATION_SCHEMA)
    ↓
4. map_to_risk_profile(classification)          → "Low" | "Medium" | "High" | "Severe"
    ↓
   High/Severe → ESCALATE  (requires_human_approval=True, stop here)
   Low/Medium  → continue
    ↓
5. gateway.call_tool("coverage_report", {diff_text}) → coverage result
6. check_diff_size(diff_lines, policy.maximum_diff_lines)         → BLOCK
7. check_static_analysis(linter_result)                           → BLOCK
8. check_test_coverage(coverage_result, policy.require_test_coverage) → BLOCK
    ↓ all pass
    → ALLOW
```

---

## Key Module Designs

### `harness_validator/policy.py`
```python
@dataclass
class ReleasePolicy:
    version: str
    allowed_risk_profiles: list[str]   # ["Low", "Medium"]
    maximum_diff_lines: int             # 350
    require_test_coverage: float        # 0.85
    prohibited_directories: list[str]   # ["/src/auth", "/src/billing", "/kubernetes/iam"]
    static_analysis_threshold: str
    raw_hash: str                       # SHA-256 of YAML bytes, for audit pinning

def load_policy(path: Path) -> ReleasePolicy: ...  # reads POLICY_FILE env var
```

### `harness_validator/types.py`
- `AgentState` TypedDict (copied from friday, unchanged)
- `RISK_CLASSIFICATION_SCHEMA` — validated LLM output: `data_surface/integration_depth/vulnerability_surface: "none"|"low"|"high"` + `rationale: string`
- `VALIDATOR_OUTPUT_SCHEMA` — final output: `verdict`, `policy_version`, `risk_profile`, `checks[]`, `audit{policy_commit_hash, timestamp_iso, diff_lines, thread_id}`

### `harness_validator/checker.py`
Pure functions, no I/O:
- `count_diff_lines(diff_text)` — +/- lines only, excludes `+++`/`---` headers
- `check_prohibited_directories(diff_text, prohibited)` — checks `path.startswith(d.lstrip("/") + "/")` (not bare prefix — avoids `/src/authorize` matching `/src/auth`)
- `check_diff_size(diff_lines, maximum)` → `(bool, str)`
- `check_static_analysis(linter_result)` — blocks on `CRITICAL` or `HIGH` severity
- `check_test_coverage(coverage_result, threshold)` → `(bool, str)`

### `harness_validator/classifier.py`
```python
async def classify_risk(diff_text, linter_findings, llm, system_prompt) -> tuple[str, dict]:
    # retries up to 3×, uses _clean_raw() (copied from friday reviewer.py), validates schema
    ...

def map_to_risk_profile(c: dict) -> str:
    score = {"none": 0, "low": 1, "high": 2}
    total = score[c["data_surface"]] + score[c["integration_depth"]] + score[c["vulnerability_surface"]]
    return ["Low","Medium","High","Severe"][[0,2,4,6].index(next(t for t in [0,2,4,6] if total <= t))]
    # 0→Low, 1-2→Medium, 3-4→High, 5-6→Severe
```

### `harness_validator/agent.py`
```python
class DeterministicValidatorAgent:
    name = "deterministic_validator"
    allowed_tools = ["run_linter", "coverage_report"]   # git_diff not needed (diff in state)
    memory_namespace = "deterministic_validator"

    def __init__(self, gateway: GatewayClient, llm_provider: LLMProvider,
                 policy: ReleasePolicy | None = None): ...

    async def run(self, state: AgentState) -> AgentState: ...
```

---

## OPA Policy (`policies/harness.rego`)
```rego
package harness
default allow = false
allow if {
    input.agent_role == "deterministic_validator"
    input.tool_name in {"run_linter", "coverage_report"}
}
```

## Declarative Policy (`policies/release_policy.yaml`)
```yaml
version: "Release Agent Policy v2.4"
AllowedRiskProfiles: [Low, Medium]
MaximumDiffLines: 350
RequireTestCoverage: ">= 90%"
ProhibitedDirectories:
  - "/src/auth"
  - "/src/billing"
  - "/kubernetes/iam"
StaticAnalysisThreshold: "Zero Critical, Zero High Vulnerabilities"
```

## Coverage Stub (`stub_servers/coverage_server.py`)
Port 9006. Returns coverage from env `STUB_COVERAGE_PCT` (default 91%). Magic comment `# COVERAGE:<pct>` in diff text overrides per-call — keeps unit test fixtures hermetic without external state.

## Governance Service (trimmed from friday)
Single client entry:
```python
CLIENTS = {
    "deterministic-validator": {
        "secret": os.environ.get("VALIDATOR_SECRET", "validator-secret"),
        "role": "deterministic_validator",
    }
}
```

## `harness-gateway` TOOL_NAME_MAP (trimmed)
```python
TOOL_NAME_MAP = {
    "run_linter":       "linter_stub__run_linter",
    "coverage_report":  "coverage_stub__coverage_report",
}
```

---

## Test Suite

### Unit (no Docker, `AsyncMock` gateway + mock LLM)

**`test_policy_loader.py`** (6): happy path, coverage string parsed, hash changes, missing key raises, list parsing, version preserved

**`test_checker.py`** (14): prohibited dir exact match fails; `/src/authorize/` passes; exactly 350 lines passes; 351 fails; CRITICAL lint fails; HIGH lint fails; WARNING passes; coverage at 85.0% passes; 84.9% fails; `count_diff_lines` excludes headers

**`test_agent.py`** (10):
- ALLOW on clean diff
- BLOCK on prohibited dir — verify `coverage_report` NOT called (short-circuit)
- BLOCK on diff too large
- BLOCK on critical lint
- BLOCK on low coverage
- ESCALATE on High risk + `requires_human_approval=True`
- `ToolAccessDenied` → error state
- Output validates against `VALIDATOR_OUTPUT_SCHEMA`
- `audit.policy_commit_hash` present
- Prohibited dir short-circuits: no LLM call + no `coverage_report` call

### Integration (`@pytest.mark.integration`, Docker required, 8 tests)
1. JWT issued for `deterministic-validator`
2. Token can call `run_linter` and `coverage_report`
3. Token calling `shell_exec` → 403
4. OPA direct eval: `{deterministic_validator, run_linter}` → true
5. OPA direct eval: `{deterministic_validator, shell_exec}` → false
6. `validate_diff` tool registered in MCPJungle
7. End-to-end clean diff → ALLOW verdict
8. Dolt `audit_log` row written after call

### Eval (`@pytest.mark.eval`, mock LLM, 9 scenarios)

Each YAML fixture: `diff`, `mock_risk_classification`, `lint_result`, `coverage_result`, `expected_verdict`

| Scenario | Expected |
|---|---|
| `allow_clean` | ALLOW |
| `block_prohibited_dir` | BLOCK |
| `block_diff_too_large` | BLOCK |
| `block_critical_lint` | BLOCK |
| `block_low_coverage` | BLOCK |
| `escalate_high_risk` | ESCALATE |
| `allow_boundary_diff` (350 lines) | ALLOW |
| `allow_boundary_coverage` (85.0%) | ALLOW |
| `block_multi_vector` (prohibited + critical) | BLOCK |

Eval runner reports: recall = dangerous scenarios correctly caught / total dangerous scenarios (target: 100%).

---

## Implementation Sequence

**Phase 1 — Core package, all unit + eval tests pass (no Docker)**
1. Copy and trim `harness-gateway` from friday
2. `policies/release_policy.yaml` + `policies/harness.rego`
3. `prompts/risk_classifier.md`
4. `harness_validator/types.py`, `policy.py`, `checker.py`, `classifier.py`, `agent.py`
5. `pyproject.toml` files (root + packages)
6. `tests/conftest.py` + unit tests + eval fixtures + eval suite
7. Verify: `uv run pytest tests/unit/ tests/eval/ -v` — all green, no Docker

**Phase 2 — Docker stack + integration tests**
1. Copy + trim `services/governance/` from friday
2. Copy `stub_servers/linter_server.py` + `Dockerfile.stub` from friday
3. Write `stub_servers/coverage_server.py`
4. Write `services/validator_server/server.py` + `Dockerfile`
5. `docker-compose.yml` (opa, dolt, mcpjungle, governance, linter-stub, coverage-stub, validator-server + register-* init containers)
6. `.env.example`, `Makefile`
7. Integration tests
8. Verify: `make stack-up && uv run pytest tests/integration/ -v -m integration`

---

## Verification

```bash
# Phase 1 — no Docker
cd /Users/terry/personal/rbcr
uv run pytest tests/unit/ tests/eval/ -v

# Phase 2 — full stack
make stack-up
uv run pytest tests/ -v

# Manual smoke test
curl -X POST http://localhost:8090/api/v0/tools/invoke \
  -H "Authorization: Bearer $VALIDATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "validator_server__validate_diff", "diff_text": "diff --git a/README.md b/README.md\n..."}'
# Expect: {"verdict": "ALLOW", "risk_profile": "Low", ...}
```
