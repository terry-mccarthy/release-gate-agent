import hashlib
import yaml
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReleasePolicy:
    version: str
    allowed_risk_profiles: list[str]
    maximum_diff_lines: int
    require_test_coverage: float   # e.g. 0.90
    prohibited_directories: list[str]
    static_analysis_threshold: str
    raw_hash: str                  # SHA-256 of raw YAML bytes


def load_policy(path: Path) -> ReleasePolicy:
    raw = path.read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    data = yaml.safe_load(raw)

    # Parse ">= 90%" → 0.90
    coverage_str = str(data["RequireTestCoverage"])
    coverage_val = float(
        coverage_str.replace(">=", "").replace(">", "").replace("%", "").strip()
    ) / 100.0

    return ReleasePolicy(
        version=data.get("version", "unknown"),
        allowed_risk_profiles=list(data["AllowedRiskProfiles"]),
        maximum_diff_lines=int(data["MaximumDiffLines"]),
        require_test_coverage=coverage_val,
        prohibited_directories=list(data["ProhibitedDirectories"]),
        static_analysis_threshold=str(data["StaticAnalysisThreshold"]),
        raw_hash=content_hash,
    )
