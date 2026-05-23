from typing import TypedDict


class AgentState(TypedDict):
    task: str
    diff: str
    thread_id: str
    agent_output: dict | None
    requires_human_approval: bool
    error: dict | None


RISK_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "required": ["data_surface", "integration_depth", "vulnerability_surface", "rationale"],
    "additionalProperties": False,
    "properties": {
        "data_surface": {
            "type": "string",
            "enum": ["none", "low", "high"],
        },
        "integration_depth": {
            "type": "string",
            "enum": ["none", "low", "high"],
        },
        "vulnerability_surface": {
            "type": "string",
            "enum": ["none", "low", "high"],
        },
        "rationale": {"type": "string"},
    },
}

VALIDATOR_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "policy_version", "risk_profile", "checks", "audit"],
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["ALLOW", "BLOCK", "ESCALATE"],
        },
        "policy_version": {"type": "string"},
        "risk_profile": {
            "type": "string",
            "enum": ["Low", "Medium", "High", "Severe", "Unknown"],
        },
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["check", "passed", "detail"],
                "additionalProperties": False,
                "properties": {
                    "check": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "detail": {"type": "string"},
                },
            },
        },
        "audit": {
            "type": "object",
            "required": ["policy_commit_hash", "timestamp_iso", "diff_lines", "thread_id"],
            "additionalProperties": False,
            "properties": {
                "policy_commit_hash": {"type": "string"},
                "timestamp_iso": {"type": "string"},
                "diff_lines": {"type": "integer"},
                "thread_id": {"type": "string"},
            },
        },
    },
}
