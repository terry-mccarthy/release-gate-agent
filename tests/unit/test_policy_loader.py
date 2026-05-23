import hashlib
import pytest
import yaml
from pathlib import Path
from harness_validator.policy import load_policy, ReleasePolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policies" / "release_policy.yaml"


def test_load_valid_policy():
    policy = load_policy(POLICY_PATH)
    assert isinstance(policy, ReleasePolicy)
    assert policy.maximum_diff_lines == 350
    assert "Low" in policy.allowed_risk_profiles
    assert "Medium" in policy.allowed_risk_profiles
    assert len(policy.prohibited_directories) >= 1


def test_coverage_threshold_parsed(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text("""
version: "Test Policy"
AllowedRiskProfiles: [Low]
MaximumDiffLines: 100
RequireTestCoverage: ">= 85%"
ProhibitedDirectories: ["/src/auth"]
StaticAnalysisThreshold: "Zero Critical"
""")
    policy = load_policy(f)
    assert abs(policy.require_test_coverage - 0.85) < 1e-9


def test_raw_hash_changes_on_edit(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text("""
version: "v1"
AllowedRiskProfiles: [Low]
MaximumDiffLines: 100
RequireTestCoverage: ">= 85%"
ProhibitedDirectories: ["/src/auth"]
StaticAnalysisThreshold: "Zero Critical"
""")
    hash1 = load_policy(f).raw_hash

    f.write_text("""
version: "v2"
AllowedRiskProfiles: [Low, Medium]
MaximumDiffLines: 200
RequireTestCoverage: ">= 90%"
ProhibitedDirectories: ["/src/auth"]
StaticAnalysisThreshold: "Zero Critical"
""")
    hash2 = load_policy(f).raw_hash

    assert hash1 != hash2


def test_missing_required_key_raises(tmp_path):
    f = tmp_path / "bad_policy.yaml"
    f.write_text("version: bad\n")
    with pytest.raises(KeyError):
        load_policy(f)


def test_prohibited_directories_as_list(tmp_path):
    f = tmp_path / "policy.yaml"
    f.write_text("""
version: "v1"
AllowedRiskProfiles: [Low]
MaximumDiffLines: 100
RequireTestCoverage: ">= 80%"
ProhibitedDirectories:
  - "/src/auth"
  - "/src/billing"
  - "/kubernetes/iam"
StaticAnalysisThreshold: "Zero Critical"
""")
    policy = load_policy(f)
    assert len(policy.prohibited_directories) == 3
    assert "/src/billing" in policy.prohibited_directories


def test_policy_version_preserved():
    policy = load_policy(POLICY_PATH)
    assert "Release Agent Policy" in policy.version
