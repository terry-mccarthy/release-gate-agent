import logging
import os
import re
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import uvicorn

logging.getLogger().setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "coverage_stub",
    host="0.0.0.0",
    port=9006,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_DEFAULT_COVERAGE = float(os.environ.get("STUB_COVERAGE_PCT", "91.0"))

_COVERAGE_RE = re.compile(r"#\s*COVERAGE:(\d+(?:\.\d+)?)")


@mcp.tool()
def coverage_report(diff_text: str) -> dict:
    """Return fake test coverage.

    Embed '# COVERAGE:<pct>' anywhere in the diff to override the default
    per-call — useful for keeping unit test fixtures hermetic.
    """
    match = _COVERAGE_RE.search(diff_text)
    pct = float(match.group(1)) if match else _DEFAULT_COVERAGE
    coverage = pct / 100.0
    total_lines = 200
    lines_covered = int(total_lines * coverage)
    return {
        "coverage": coverage,
        "lines_covered": lines_covered,
        "lines_total": total_lines,
        "source": "stub",
    }


if __name__ == "__main__":
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=9006)
