# rbcr — Release Branch Code Review

A release-gating harness that validates code diffs against a configurable policy before they can ship. It combines deterministic rule checks with LLM-based risk classification and produces a structured, auditable verdict.

## How it works

Every diff runs through the `DeterministicValidatorAgent` in a fixed sequence:

1. **Prohibited directories** — immediate BLOCK if any touched file is under a restricted path (no tools, no LLM)
2. **Linter** — calls `run_linter` via the governance gateway
3. **LLM risk classification** — scores the diff on three vectors (data surface, integration depth, vulnerability surface); maps to a risk profile: `Low → Medium → High → Severe`
4. **Risk gate** — High or Severe → immediate ESCALATE for human review
5. **Coverage** — calls `coverage_report` (skipped for High/Severe)
6. **Diff size, static analysis, test coverage** — deterministic policy checks → ALLOW or BLOCK

Verdicts: **ALLOW**, **BLOCK**, **ESCALATE**

Every invocation writes an immutable audit record to [Dolt](https://github.com/dolthub/dolt) (a git-backed MySQL database).

## Architecture

```
MCP client
    │  validate_diff(diff_text)
    ▼
validator_server (FastMCP :9007)
    │  DeterministicValidatorAgent
    ▼
governance (FastAPI :8000)
    ├── /oauth/token       OAuth2 client credentials
    ├── /api/v0/tools/invoke
    │       ├── OPA policy check (harness.rego)
    │       ├── Dolt audit log
    │       └── forward → MCPJungle
    └──────────────────────────────
MCPJungle  ──→  linter_stub / coverage_stub
```

## Packages

| Package | Description |
|---|---|
| `packages/harness-validator` | Agent, checker, classifier, LLM providers, policy loader |
| `packages/harness-gateway` | OAuth2-aware HTTP client for the governance gateway |

## Quickstart

```bash
# Install dependencies (requires uv)
make install

# Run unit + eval tests
make test
```

## Running the full stack

```bash
make stack-up      # starts governance, validator, MCPJungle, OPA, Dolt
make stack-down    # tears everything down and removes volumes
make logs          # tail all service logs
```

### End-to-end smoke test

After the stack is healthy, get a token and pipe a real git diff to the validator:

```bash
# 1. Get a bearer token
TOKEN=$(curl -s -X POST http://localhost:8090/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=deterministic-validator \
  -d client_secret=validator-secret | jq -r .access_token)

# 2. Validate a diff from your working tree
jq -n \
  --arg name "validator_server__validate_diff" \
  --arg diff "$(git diff README.md)" \
  '{name: $name, diff_text: $diff}' | \
curl -s -X POST http://localhost:8090/api/v0/tools/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @-
```

The response contains the structured verdict:

```json
{
  "verdict": "ALLOW",
  "risk_profile": "Low",
  "checks": [...],
  "audit": { "policy_commit_hash": "...", "diff_lines": 45, ... }
}
```

To test a BLOCK, target a prohibited directory like `src/auth`:

```bash
jq -n \
  --arg name "validator_server__validate_diff" \
  --arg diff "$(git diff src/auth/login.py)" \
  '{name: $name, diff_text: $diff}' | \
curl -s -X POST http://localhost:8090/api/v0/tools/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @-
# Verdict will be "BLOCK"
```

Required environment variables for the governance server:

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET` | — | Secret for signing bearer tokens |
| `MCPJUNGLE_INTERNAL_URL` | — | URL of the MCPJungle instance |
| `OPA_URL` | `http://opa:8181` | OPA endpoint |
| `DOLT_HOST` | `dolt` | Dolt host |
| `VALIDATOR_SECRET` | `validator-secret` | Shared secret for the validator client |

LLM provider for the validator server:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama base URL |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model name |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model (when `LLM_PROVIDER=gemini`) |
| `GEMINI_API_KEY` | — | Gemini API key |
| `GOVERNANCE_URL` | — | URL of the governance server |

## Policy

Edit `policies/release_policy.yaml` to tune thresholds:

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

Tool access rules live in `policies/harness.rego` (OPA). By default only `run_linter` and `coverage_report` are permitted for the validator role.

## Tests

```bash
make test-unit         # unit tests (no I/O)
make test-eval         # YAML-fixture eval suite with mock LLM
make test-integration  # requires running Docker stack
```

Eval fixtures are in `tests/eval/fixtures/`. Each fixture specifies a diff, mock LLM classification, tool responses, and expected verdict/risk profile — making the eval suite deterministic and fast.

## Future enhancements

### Architecture diagram
Add a high-fidelity system diagram at the top of this README showing the request flow through governance, OPA, MCPJungle, Dolt, and the stub servers.

### Policy-as-code directory with versioned schemas
Extend `policies/` with versioned YAML schemas (e.g. `soc2-cc8.1.yaml`) that define thresholds, approved reviewers, and audit timestamps — making the policy engine fully auditable by SOC 2 reviewers.

### Compliance manifest artifact
Output a structured `compliance-manifest.json` after every validation run containing the commit SHA, policy version applied, per-check verdicts, and final gate status. This is the artifact handed to auditors.

### Emergency override (break-glass protocol)
Document and implement a human-in-the-loop escape hatch: a cryptographically signed approval from a designated team can override a BLOCK, with the override flagged in the Dolt audit log for retroactive review.
