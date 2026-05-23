def count_diff_lines(diff_text: str) -> int:
    """Count added + removed lines (+ or - prefix), excluding +++ and --- headers."""
    return sum(
        1 for line in diff_text.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )


def check_prohibited_directories(
    diff_text: str,
    prohibited: list[str],
) -> tuple[bool, str]:
    """Block if any touched file path starts with a prohibited directory."""
    touched = []
    for line in diff_text.splitlines():
        path = None
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("--- a/"):
            path = line[6:]
        if path is None:
            continue
        norm = path.lstrip("/")
        for d in prohibited:
            d_norm = d.lstrip("/")
            # Match exact path or path under that directory
            if norm == d_norm or norm.startswith(d_norm + "/"):
                touched.append(path)
                break
    if touched:
        unique = sorted(set(touched))
        return False, f"Touches prohibited directories: {', '.join(unique)}"
    return True, "No prohibited directories touched"


def check_diff_size(diff_lines: int, maximum: int) -> tuple[bool, str]:
    if diff_lines > maximum:
        return False, f"Diff is {diff_lines} lines, exceeds limit of {maximum}"
    return True, f"Diff is {diff_lines} lines (limit: {maximum})"


def check_static_analysis(linter_result: dict) -> tuple[bool, str]:
    """Block on any CRITICAL or HIGH severity linter finding."""
    warnings = linter_result.get("warnings", [])
    blockers = [w for w in warnings if w.get("severity") in ("CRITICAL", "HIGH")]
    if blockers:
        msgs = "; ".join(
            w.get("message", w.get("rule", "unknown")) for w in blockers
        )
        return False, f"Static analysis blockers: {msgs}"
    return True, "Zero Critical, Zero High vulnerabilities"


def check_test_coverage(
    coverage_result: dict,
    threshold: float,
) -> tuple[bool, str]:
    """Block if coverage is below threshold. coverage_result: {"coverage": 0.91, ...}"""
    coverage = float(coverage_result.get("coverage", 0.0))
    pct = round(coverage * 100, 1)
    threshold_pct = round(threshold * 100, 1)
    if coverage < threshold:
        return False, f"Coverage is {pct}%, below threshold of {threshold_pct}%"
    return True, f"Coverage is {pct}% (threshold: {threshold_pct}%)"
