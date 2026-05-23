import json
import logging
import re

import jsonschema

from harness_validator.llm import LLMProvider
from harness_validator.types import RISK_CLASSIFICATION_SCHEMA

logger = logging.getLogger(__name__)

MAX_CLASSIFY_ATTEMPTS = 3

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_SCORE = {"none": 0, "low": 1, "high": 2}


def _clean_raw(raw: str) -> str:
    raw = _THINK_RE.sub("", raw).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw[: raw.rfind("```")].strip() if "```" in raw else raw
    return raw


def map_to_risk_profile(classification: dict) -> str:
    """Map the three-vector classification to a risk profile string."""
    total = (
        _SCORE[classification["data_surface"]]
        + _SCORE[classification["integration_depth"]]
        + _SCORE[classification["vulnerability_surface"]]
    )
    if total == 0:
        return "Low"
    elif total <= 2:
        return "Medium"
    elif total <= 4:
        return "High"
    else:
        return "Severe"


async def classify_risk(
    diff_text: str,
    linter_findings: list[dict],
    llm: LLMProvider,
    system_prompt: str,
) -> tuple[str, dict]:
    """Return (risk_profile, raw_classification_dict). Retries up to MAX_CLASSIFY_ATTEMPTS on schema failure."""
    findings_summary = (
        json.dumps(linter_findings, indent=2) if linter_findings else "No findings."
    )
    user_message = f"""Code diff to classify:

{diff_text}

Linter findings:
{findings_summary}

Return your risk classification as raw JSON only."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for attempt in range(MAX_CLASSIFY_ATTEMPTS):
        response = await llm.chat(messages=messages)
        raw = _clean_raw(response.content)
        logger.debug("classify attempt %d response:\n%s", attempt + 1, raw)

        try:
            parsed = json.loads(raw)
            jsonschema.validate(parsed, RISK_CLASSIFICATION_SCHEMA)
            risk_profile = map_to_risk_profile(parsed)
            return risk_profile, parsed
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            logger.warning("classify attempt %d invalid: %s", attempt + 1, e)
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Your previous response was invalid: {e}\nReturn raw JSON only.",
            })

    raise RuntimeError(f"Risk classification failed after {MAX_CLASSIFY_ATTEMPTS} attempts")
