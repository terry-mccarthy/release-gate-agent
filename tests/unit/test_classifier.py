import json
import pytest
from unittest.mock import AsyncMock

from harness_validator.classifier import _clean_raw, map_to_risk_profile, classify_risk, MAX_CLASSIFY_ATTEMPTS
from harness_validator.llm import LLMResponse


# --- _clean_raw ---

def test_clean_raw_passthrough():
    raw = '{"data_surface": "none"}'
    assert _clean_raw(raw) == raw


def test_clean_raw_strips_think_tags():
    raw = "<think>I should reason step by step</think>{\"data_surface\": \"none\"}"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


def test_clean_raw_strips_markdown_fence():
    raw = "```json\n{\"data_surface\": \"none\"}\n```"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


def test_clean_raw_strips_markdown_fence_no_lang():
    raw = "```\n{\"data_surface\": \"none\"}\n```"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


def test_clean_raw_strips_think_and_fence():
    raw = "<think>reason</think>```\n{\"data_surface\": \"none\"}\n```"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


def test_clean_raw_unclosed_fence():
    raw = "```\n{\"data_surface\": \"none\"}"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


def test_clean_raw_multiline_think():
    raw = "<think>\nmulti\nline\n</think>{\"data_surface\": \"none\"}"
    assert _clean_raw(raw) == '{"data_surface": "none"}'


# --- map_to_risk_profile ---

def test_map_low_all_none():
    c = {"data_surface": "none", "integration_depth": "none", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "Low"


def test_map_medium_lowest():
    c = {"data_surface": "low", "integration_depth": "none", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "Medium"


def test_map_medium_via_low_plus_low():
    c = {"data_surface": "low", "integration_depth": "low", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "Medium"


def test_map_medium_via_separate_vector():
    c = {"data_surface": "low", "integration_depth": "none", "vulnerability_surface": "low"}
    assert map_to_risk_profile(c) == "Medium"


def test_map_medium_total_two_high_only():
    c = {"data_surface": "high", "integration_depth": "none", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "Medium"


def test_map_high_exact():
    c = {"data_surface": "high", "integration_depth": "low", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "High"


def test_map_high_via_three_lows():
    c = {"data_surface": "low", "integration_depth": "low", "vulnerability_surface": "low"}
    assert map_to_risk_profile(c) == "High"


def test_map_severe_two_high():
    c = {"data_surface": "high", "integration_depth": "high", "vulnerability_surface": "none"}
    assert map_to_risk_profile(c) == "Severe"


def test_map_severe_all_high():
    c = {"data_surface": "high", "integration_depth": "high", "vulnerability_surface": "high"}
    assert map_to_risk_profile(c) == "Severe"


# --- classify_risk ---

def _mock_llm(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content=content)
    return llm


async def test_classify_happy_path():
    classification = {
        "data_surface": "none",
        "integration_depth": "none",
        "vulnerability_surface": "none",
        "rationale": "clean",
    }
    llm = _mock_llm(json.dumps(classification))
    profile, parsed = await classify_risk("diff", [], llm, "system prompt")
    assert profile == "Low"
    assert parsed == classification


async def test_classify_includes_linter_findings():
    classification = {
        "data_surface": "none", "integration_depth": "none",
        "vulnerability_surface": "none", "rationale": "ok",
    }
    llm = _mock_llm(json.dumps(classification))
    findings = [{"rule": "injection", "severity": "HIGH", "message": "SQL injection risk"}]
    await classify_risk("diff", findings, llm, "system prompt")
    msg = llm.chat.call_args[1]["messages"][1]["content"]
    assert "SQL injection" in msg
    assert "No findings" not in msg


async def test_classify_no_findings():
    classification = {
        "data_surface": "none", "integration_depth": "none",
        "vulnerability_surface": "none", "rationale": "ok",
    }
    llm = _mock_llm(json.dumps(classification))
    await classify_risk("diff", [], llm, "system prompt")
    msg = llm.chat.call_args[1]["messages"][1]["content"]
    assert "No findings" in msg


async def test_classify_retry_on_json_decode_error():
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(content="not json"),
        LLMResponse(content=json.dumps({
            "data_surface": "none", "integration_depth": "none",
            "vulnerability_surface": "none", "rationale": "ok",
        })),
    ]
    profile, parsed = await classify_risk("diff", [], llm, "system prompt")
    assert profile == "Low"
    assert llm.chat.call_count == 2


async def test_classify_retry_on_schema_error():
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(content=json.dumps({
            "data_surface": "invalid", "integration_depth": "none",
            "vulnerability_surface": "none", "rationale": "bad",
        })),
        LLMResponse(content=json.dumps({
            "data_surface": "none", "integration_depth": "none",
            "vulnerability_surface": "none", "rationale": "ok",
        })),
    ]
    profile, parsed = await classify_risk("diff", [], llm, "system prompt")
    assert profile == "Low"
    assert llm.chat.call_count == 2


async def test_classify_retry_on_missing_required_field():
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(content=json.dumps({"data_surface": "none"})),
        LLMResponse(content=json.dumps({
            "data_surface": "none", "integration_depth": "none",
            "vulnerability_surface": "none", "rationale": "ok",
        })),
    ]
    profile, parsed = await classify_risk("diff", [], llm, "system prompt")
    assert profile == "Low"
    assert llm.chat.call_count == 2


async def test_classify_exhausted_raises():
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content="not json")
    with pytest.raises(RuntimeError, match=f"Risk classification failed after {MAX_CLASSIFY_ATTEMPTS} attempts"):
        await classify_risk("diff", [], llm, "system prompt")
    assert llm.chat.call_count == MAX_CLASSIFY_ATTEMPTS


async def test_classify_multiple_retries_then_succeed():
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(content="bad1"),
        LLMResponse(content="bad2"),
        LLMResponse(content=json.dumps({
            "data_surface": "none", "integration_depth": "none",
            "vulnerability_surface": "none", "rationale": "ok",
        })),
    ]
    profile, parsed = await classify_risk("diff", [], llm, "system prompt")
    assert profile == "Low"
    assert llm.chat.call_count == 3
