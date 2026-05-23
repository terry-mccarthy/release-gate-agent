package harness

default allow = false

allow if {
    input.agent_role == "deterministic_validator"
    input.tool_name in {"run_linter", "coverage_report"}
}
