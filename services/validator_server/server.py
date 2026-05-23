import logging
import os
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from harness_gateway.client import GatewayClient
from harness_validator.agent import DeterministicValidatorAgent
from harness_validator.types import AgentState

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "validator_server",
    host="0.0.0.0",
    port=9007,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _build_llm_provider():
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.1"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))

    if provider == "gemini":
        from harness_validator.llm import GeminiProvider
        return GeminiProvider(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            api_key=os.environ.get("GEMINI_API_KEY"),
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    else:
        from harness_validator.llm import OllamaProvider
        return OllamaProvider(
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "8192")),
            temperature=temperature,
            num_predict=max_tokens,
        )


@mcp.tool()
async def validate_diff(diff_text: str, thread_id: str = "mcp-call") -> dict:
    """Run the deterministic release gate against a code diff.

    Returns a structured verdict: ALLOW, BLOCK, or ESCALATE, along with
    policy check results and an immutable audit record.
    """
    gateway = GatewayClient(
        gateway_url=os.environ["GOVERNANCE_URL"],
        client_id="deterministic-validator",
        client_secret=os.environ.get("VALIDATOR_SECRET", "validator-secret"),
    )
    llm = _build_llm_provider()
    agent = DeterministicValidatorAgent(gateway=gateway, llm_provider=llm)

    state = AgentState(
        task="Validate this diff against release policy",
        diff=diff_text,
        thread_id=thread_id,
        agent_output=None,
        requires_human_approval=False,
        error=None,
    )
    result = await agent.run(state)

    if result.get("error"):
        raise ValueError(result["error"]["reason"])

    return result["agent_output"]


if __name__ == "__main__":
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=9007)
