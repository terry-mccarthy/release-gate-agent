import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from harness_validator.llm import LLMResponse, LLMProvider


class TestLLMResponse:
    def test_content_attr(self):
        resp = LLMResponse(content="hello world")
        assert resp.content == "hello world"


class TestLLMProviderProtocol:
    def test_structural_subtyping(self):
        mock = AsyncMock(spec=LLMProvider)
        # Protocol without @runtime_checkable can't use isinstance
        # Verify structural conformance by checking method signature
        assert hasattr(mock, "chat")
        import inspect
        assert inspect.iscoroutinefunction(mock.chat)


class TestOllamaProvider:
    @pytest.fixture(autouse=True)
    def _mock_ollama_module(self):
        """ollama is not installed in the test env — inject a mock."""
        mock_mod = MagicMock()
        mock_mod.AsyncClient = MagicMock()
        with patch.dict("sys.modules", {"ollama": mock_mod}):
            yield

    def test_init_creates_client(self):
        from harness_validator.llm import OllamaProvider

        provider = OllamaProvider(host="http://ollama:11434", model="llama3")
        mod = __import__("sys").modules["ollama"]
        mod.AsyncClient.assert_called_once_with(host="http://ollama:11434")
        assert provider.model == "llama3"
        assert provider._options == {"temperature": 0.1, "num_ctx": 8192, "num_predict": 1024}

    def test_init_custom_options(self):
        from harness_validator.llm import OllamaProvider

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="mistral",
            num_ctx=4096,
            temperature=0.8,
            num_predict=256,
        )
        assert provider._options == {
            "temperature": 0.8,
            "num_ctx": 4096,
            "num_predict": 256,
        }

    async def test_chat_returns_llm_response(self):
        from harness_validator.llm import OllamaProvider

        mod = __import__("sys").modules["ollama"]
        mock_msg = MagicMock()
        mock_msg.message.content = "ollama response"
        mock_client = AsyncMock()
        mock_client.chat.return_value = mock_msg
        mod.AsyncClient.return_value = mock_client

        provider = OllamaProvider(host="http://ollama:11434", model="llama3")
        messages = [{"role": "user", "content": "hello"}]
        result = await provider.chat(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "ollama response"
        mock_client.chat.assert_called_once_with(
            model="llama3",
            messages=messages,
            options={"temperature": 0.1, "num_ctx": 8192, "num_predict": 1024},
        )


class _MockGeminiMixin:
    """Helpers to set up mock google.genai modules for GeminiProvider tests."""

    @staticmethod
    def _get_mocks():
        genai_mod = __import__("sys").modules["google.genai"]
        types_mod = __import__("sys").modules["google.genai.types"]
        return genai_mod, types_mod

    @staticmethod
    def _make_async_generate(text: str):
        """Create a proper async mock chain for client.aio.models.generate_content."""
        genai_mod, _ = _MockGeminiMixin._get_mocks()
        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_generate = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = text
        mock_generate.return_value = mock_response
        mock_client.aio.models.generate_content = mock_generate
        genai_mod.Client.return_value = mock_client
        return mock_generate, mock_response


class TestGeminiProvider(_MockGeminiMixin):
    @pytest.fixture(autouse=True)
    def _mock_genai_modules(self):
        """google.genai is not installed in the test env — inject mocks."""
        google_mod = MagicMock()
        genai_mod = MagicMock()
        types_mod = MagicMock()
        google_mod.genai = genai_mod
        genai_mod.types = types_mod
        mocks = {
            "google": google_mod,
            "google.genai": genai_mod,
            "google.genai.types": types_mod,
        }
        with patch.dict("sys.modules", mocks):
            yield

    async def test_init_defaults(self):
        from harness_validator.llm import GeminiProvider

        genai_mod, _ = self._get_mocks()
        mock_client = MagicMock()
        genai_mod.Client.return_value = mock_client

        provider = GeminiProvider(api_key="test-key")
        genai_mod.Client.assert_called_once_with(api_key="test-key")
        assert provider.client is mock_client
        assert provider.model == "gemini-2.5-flash"
        assert provider.temperature == 0.1
        assert provider.max_output_tokens == 1024

    async def test_init_custom_params(self):
        from harness_validator.llm import GeminiProvider

        genai_mod, _ = self._get_mocks()

        provider = GeminiProvider(
            model="gemini-pro",
            api_key="custom-key",
            temperature=0.9,
            max_output_tokens=2048,
        )
        assert provider.model == "gemini-pro"
        assert provider.temperature == 0.9
        assert provider.max_output_tokens == 2048

    async def test_chat_returns_llm_response(self):
        from harness_validator.llm import GeminiProvider

        self._make_async_generate(text="gemini response")
        provider = GeminiProvider(api_key="test-key")

        messages = [{"role": "user", "content": "hello"}]
        result = await provider.chat(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "gemini response"

    async def test_chat_with_system_prompt(self):
        from harness_validator.llm import GeminiProvider

        self._make_async_generate(text="response")
        genai_mod, types_mod = self._get_mocks()
        mock_config = MagicMock()
        mock_config_cls = MagicMock()
        mock_config_cls.return_value = mock_config
        types_mod.GenerateContentConfig = mock_config_cls

        provider = GeminiProvider(api_key="test-key")
        messages = [
            {"role": "system", "content": "You are a classifier"},
            {"role": "user", "content": "classify this"},
        ]
        result = await provider.chat(messages)

        assert result.content == "response"
        assert mock_config.system_instruction == "You are a classifier"
