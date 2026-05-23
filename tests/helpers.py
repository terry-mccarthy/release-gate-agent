"""Shared test constants — imported by unit tests and eval suite."""
import json
from unittest.mock import AsyncMock

from harness_validator.llm import LLMResponse

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

AUTH_DIFF = """\
diff --git a/src/auth/login.py b/src/auth/login.py
index abc123..def456 100644
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -1,3 +1,4 @@
 def login(username, password):
+    logger.debug("login called")
     return True
"""

CLEAN_CLASSIFICATION = {
    "data_surface": "none",
    "integration_depth": "none",
    "vulnerability_surface": "none",
    "rationale": "No significant risk signals found.",
}

HIGH_RISK_CLASSIFICATION = {
    "data_surface": "high",
    "integration_depth": "high",
    "vulnerability_surface": "none",
    "rationale": "Touches PII and authentication boundaries.",
}

MEDIUM_RISK_CLASSIFICATION = {
    "data_surface": "low",
    "integration_depth": "none",
    "vulnerability_surface": "none",
    "rationale": "Touches data models but no sensitive fields.",
}


def make_mock_llm(classification: dict):
    """Return a mock LLM that always responds with the given classification dict."""
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content=json.dumps(classification))
    return llm
