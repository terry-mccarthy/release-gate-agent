import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from harness_gateway.client import GatewayClient, ToolAccessDenied


@pytest.fixture
def client():
    return GatewayClient(
        gateway_url="http://gateway:8090",
        client_id="validator",
        client_secret="secret",
        timeout=30.0,
    )


@pytest.fixture
def client_no_auth():
    return GatewayClient(
        gateway_url="http://gateway:8090",
        client_id="validator",
        client_secret="",
    )


class TestGetToken:
    async def test_returns_none_when_no_secret(self, client_no_auth):
        with patch("httpx.AsyncClient") as MockHTTPX:
            token = await client_no_auth._get_token()
            assert token is None
            MockHTTPX.assert_not_called()

    async def test_returns_cached_token(self, client):
        client._token = "cached-token"
        client._token_exp = 9999999999.0
        with patch("httpx.AsyncClient") as MockHTTPX:
            token = await client._get_token()
            assert token == "cached-token"
            MockHTTPX.assert_not_called()

    async def test_fetches_new_token(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
            mock_ctx.post.return_value = mock_response

            token = await client._get_token()

            assert token == "fresh-token"
            assert client._token == "fresh-token"
            mock_ctx.post.assert_called_once_with(
                "http://gateway:8090/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "validator",
                    "client_secret": "secret",
                },
                timeout=10.0,
            )

    async def test_fetches_token_on_expiry(self, client):
        client._token = "expired-token"
        client._token_exp = 0.0  # expired

        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "new-token", "expires_in": 900}
            mock_ctx.post.return_value = mock_response

            token = await client._get_token()
            assert token == "new-token"

    async def test_404_returns_none(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_ctx.post.return_value = mock_response

            token = await client._get_token()
            assert token is None

    async def test_http_error_raises(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_ctx.post.side_effect = __import__("httpx").HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=MagicMock()
            )

            with pytest.raises(__import__("httpx").HTTPStatusError):
                await client._get_token()

    async def test_generic_exception_returns_none(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_ctx.post.side_effect = ConnectionError("network down")

            token = await client._get_token()
            assert token is None


class TestCallTool:
    async def test_unknown_tool_raises(self, client):
        with pytest.raises(ToolAccessDenied, match="not in allowed tool list"):
            await client.call_tool("shell_exec", {})

    async def test_successful_call_returns_parsed_json(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": '{"coverage": 0.91}'}]
            }
            mock_ctx.post.return_value = mock_response

            result = await client.call_tool("coverage_report", {})

            assert result == {"coverage": 0.91}

    async def test_successful_call_returns_raw_text(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "not-json-string"}]
            }
            mock_ctx.post.return_value = mock_response

            result = await client.call_tool("run_linter", {"diff_text": "diff"})
            assert result == "not-json-string"

    async def test_successful_call_no_content_fallback(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "raw-data"}
            mock_ctx.post.return_value = mock_response

            result = await client.call_tool("run_linter", {})
            assert result == {"result": "raw-data"}

    async def test_403_raises(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_ctx.post.return_value = mock_response

            with pytest.raises(ToolAccessDenied, match="403 Forbidden: run_linter"):
                await client.call_tool("run_linter", {})

    async def test_401_raises(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_ctx.post.return_value = mock_response

            with pytest.raises(ToolAccessDenied, match="401 Unauthorized: run_linter"):
                await client.call_tool("run_linter", {})

    async def test_includes_bearer_token(self, client):
        client._token = "my-token"
        client._token_exp = 9999999999.0

        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": []}
            mock_ctx.post.return_value = mock_response

            await client.call_tool("run_linter", {})

            call_kwargs = mock_ctx.post.call_args[1]
            assert call_kwargs["headers"] == {"Authorization": "Bearer my-token"}

    async def test_omits_auth_header_when_no_token(self, client_no_auth):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": []}
            mock_ctx.post.return_value = mock_response

            await client_no_auth.call_tool("run_linter", {})
            call_kwargs = mock_ctx.post.call_args[1]
            assert "Authorization" not in call_kwargs["headers"]

    async def test_records_last_call(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": []}
            mock_ctx.post.return_value = mock_response

            await client.call_tool("run_linter", {"diff_text": "foo"})
            assert len(client.last_calls) == 1
            assert client.last_calls[0]["tool"] == "run_linter"
            assert client.last_calls[0]["status"] == 200

    async def test_raises_on_http_error(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = __import__("httpx").HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=mock_response
            )
            mock_ctx.post.return_value = mock_response

            with pytest.raises(__import__("httpx").HTTPStatusError):
                await client.call_tool("run_linter", {})

    async def test_uses_tool_name_map(self, client):
        with patch("httpx.AsyncClient") as MockHTTPX:
            mock_ctx = MockHTTPX.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": []}
            mock_ctx.post.return_value = mock_response

            await client.call_tool("coverage_report", {"diff_text": "diff"})

            call_kwargs = mock_ctx.post.call_args[1]
            body = call_kwargs["json"]
            assert body["name"] == "coverage_stub__coverage_report"
            assert body["diff_text"] == "diff"
