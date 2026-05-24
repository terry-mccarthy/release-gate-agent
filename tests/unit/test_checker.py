import pytest
from harness_validator.checker import (
    check_prohibited_directories,
    check_diff_size,
    check_static_analysis,
    check_test_coverage,
    count_diff_lines,
    is_docs_only_diff,
)

PROHIBITED = ["/src/auth", "/src/billing", "/kubernetes/iam"]

# --- count_diff_lines ---

def test_count_diff_lines_basic():
    diff = "+added line\n-removed line\n context line\n"
    assert count_diff_lines(diff) == 2


def test_count_diff_lines_excludes_headers():
    diff = "--- a/file.py\n+++ b/file.py\n+added\n-removed\n"
    assert count_diff_lines(diff) == 2


def test_count_diff_lines_empty():
    assert count_diff_lines("") == 0


# --- check_prohibited_directories ---

def test_prohibited_dir_exact_match_blocks():
    diff = "--- a/src/auth/login.py\n+++ b/src/auth/login.py\n+foo\n"
    passed, detail = check_prohibited_directories(diff, PROHIBITED)
    assert not passed
    assert "src/auth" in detail


def test_prohibited_dir_subpath_blocks():
    diff = "--- a/src/auth/oauth/flow.py\n+++ b/src/auth/oauth/flow.py\n+foo\n"
    passed, _ = check_prohibited_directories(diff, PROHIBITED)
    assert not passed


def test_prohibited_dir_similar_prefix_passes():
    # /src/authorize is NOT the same as /src/auth
    diff = "--- a/src/authorize/middleware.py\n+++ b/src/authorize/middleware.py\n+foo\n"
    passed, _ = check_prohibited_directories(diff, PROHIBITED)
    assert passed


def test_prohibited_dir_clean_diff_passes():
    diff = "--- a/app/utils.py\n+++ b/app/utils.py\n+foo\n"
    passed, _ = check_prohibited_directories(diff, PROHIBITED)
    assert passed


def test_prohibited_dir_multiple_files_one_blocked():
    diff = (
        "--- a/app/utils.py\n+++ b/app/utils.py\n+foo\n"
        "--- a/src/billing/invoice.py\n+++ b/src/billing/invoice.py\n+bar\n"
    )
    passed, detail = check_prohibited_directories(diff, PROHIBITED)
    assert not passed
    assert "billing" in detail


# --- check_diff_size ---

def test_diff_size_at_limit_passes():
    passed, detail = check_diff_size(350, 350)
    assert passed
    assert "350" in detail


def test_diff_size_one_over_blocks():
    passed, detail = check_diff_size(351, 350)
    assert not passed
    assert "351" in detail


def test_diff_size_well_under_passes():
    passed, _ = check_diff_size(10, 350)
    assert passed


# --- check_static_analysis ---

def test_static_analysis_critical_blocks():
    result = {"warnings": [{"rule": "injection", "message": "SQL injection", "severity": "CRITICAL"}]}
    passed, detail = check_static_analysis(result)
    assert not passed
    assert "SQL injection" in detail


def test_static_analysis_high_blocks():
    result = {"warnings": [{"rule": "xss", "message": "XSS risk", "severity": "HIGH"}]}
    passed, _ = check_static_analysis(result)
    assert not passed


def test_static_analysis_warning_only_passes():
    result = {"warnings": [{"rule": "style", "message": "line too long", "severity": "WARNING"}]}
    passed, _ = check_static_analysis(result)
    assert passed


def test_static_analysis_empty_passes():
    passed, detail = check_static_analysis({"warnings": [], "error_count": 0})
    assert passed
    assert "Zero" in detail


# --- check_test_coverage ---

def test_coverage_at_threshold_passes():
    result = {"coverage": 0.85, "lines_covered": 170, "lines_total": 200}
    passed, detail = check_test_coverage(result, 0.85)
    assert passed
    assert "85.0%" in detail


def test_coverage_below_threshold_blocks():
    result = {"coverage": 0.849, "lines_covered": 169, "lines_total": 200}
    passed, detail = check_test_coverage(result, 0.85)
    assert not passed
    assert "84.9%" in detail


def test_coverage_well_above_passes():
    result = {"coverage": 0.95, "lines_covered": 190, "lines_total": 200}
    passed, _ = check_test_coverage(result, 0.85)
    assert passed


# --- is_docs_only_diff ---

def test_docs_only_md():
    diff = "--- a/README.md\n+++ b/README.md\n+foo\n"
    assert is_docs_only_diff(diff)


def test_docs_only_rst():
    diff = "--- a/docs/guide.rst\n+++ b/docs/guide.rst\n+foo\n"
    assert is_docs_only_diff(diff)


def test_docs_only_multiple_doc_files():
    diff = "--- a/README.md\n+++ b/README.md\n+foo\n--- a/CHANGELOG.md\n+++ b/CHANGELOG.md\n+bar\n"
    assert is_docs_only_diff(diff)


def test_docs_only_false_for_py():
    diff = "--- a/app.py\n+++ b/app.py\n+foo\n"
    assert not is_docs_only_diff(diff)


def test_docs_only_mixed_doc_and_code():
    diff = "--- a/README.md\n+++ b/README.md\n+foo\n--- a/app.py\n+++ b/app.py\n+bar\n"
    assert not is_docs_only_diff(diff)


def test_docs_only_empty_diff():
    assert not is_docs_only_diff("")


def test_docs_only_no_touched_files():
    diff = " context line\n another context line\n"
    assert not is_docs_only_diff(diff)
