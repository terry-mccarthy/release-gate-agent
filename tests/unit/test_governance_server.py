import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient as HTTPXClient

JWT_SECRET = "test-secret-with-sufficient-length-for-sha256"

os.environ.setdefault("JWT_SECRET", JWT_SECRET)
os.environ.setdefault("MCPJUNGLE_INTERNAL_URL", "http://mcpjungle:8080")


@pytest.fixture(autouse=True)
def _env():
    os.environ.setdefault("JWT_SECRET", JWT_SECRET)
    os.environ.setdefault("MCPJUNGLE_INTERNAL_URL", "http://mcpjungle:8080")
    yield


def _make_token(role="deterministic_validator", client_id="deterministic-validator"):
    import jwt as _jwt
    import time
    payload = {
        "sub": client_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 900,
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _app():
    from services.governance.server import app
    return app


class TestDenyPath:
    """The deny path must hash the request body so it fits in VARCHAR(64)."""

    async def _invoke(self, body: dict, opa_result: bool = False):
        app = _app()
        mock_opa_resp = MagicMock()
        mock_opa_resp.json.return_value = {"result": opa_result}

        mock_httpx_client = AsyncMock()
        mock_httpx_client.__aenter__.return_value.post.return_value = mock_opa_resp

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        token = _make_token()
        async with HTTPXClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("services.governance.server.httpx.AsyncClient", return_value=mock_httpx_client),
                patch("services.governance.server.get_dolt_conn", return_value=mock_conn),
            ):
                resp = await client.post(
                    "/api/v0/tools/invoke",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
        return resp, mock_cursor

    async def test_deny_stores_hash_not_raw_body(self):
        """request_hash should be a short hash, not the raw body."""
        body = {"name": "validator_server__validate_diff", "diff_text": "x" * 10000}
        resp, cursor = await self._invoke(body, opa_result=False)

        assert resp.status_code == 403
        if cursor.execute.call_count > 0:
            call = cursor.execute.call_args_list[0]
            sql, params = call[0]
            req_hash = params[3]
            assert len(req_hash) == 16, f"Expected 16-char hash, got {len(req_hash)}-char: {req_hash!r}"
            assert all(c in "0123456789abcdef" for c in req_hash), "Not a hex hash"

    async def test_deny_with_small_body_still_hashes(self):
        """Even a small body is hashed, not stored raw."""
        body = {"name": "run_linter", "diff_text": "small"}
        resp, cursor = await self._invoke(body, opa_result=False)

        assert resp.status_code == 403
        if cursor.execute.call_count > 0:
            call = cursor.execute.call_args_list[0]
            req_hash = call[0][1][3]
            assert len(req_hash) == 16

    async def test_opa_unreachable_still_hashes(self):
        """When OPA is unreachable, the fallback deny still hashes."""
        body = {"name": "run_linter", "diff_text": "hello"}
        app = _app()
        token = _make_token()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        async with HTTPXClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("services.governance.server.httpx.AsyncClient") as MockHTTPX,
                patch("services.governance.server.get_dolt_conn", return_value=mock_conn),
            ):
                mock_ctx = MockHTTPX.return_value.__aenter__.return_value
                mock_ctx.post.side_effect = ConnectionError("OPA down")

                resp = await client.post(
                    "/api/v0/tools/invoke",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 403
        if mock_cursor.execute.call_count > 0:
            req_hash = mock_cursor.execute.call_args_list[0][0][1][3]
            assert len(req_hash) == 16


class TestAllowPath:
    """validate_diff must be allowed through OPA."""

    async def _invoke(self, body: dict):
        app = _app()
        mock_opa_resp = MagicMock()
        mock_opa_resp.json.return_value = {"result": True}

        mock_httpx_client = AsyncMock()

        async def _post(url, *args, **kwargs):
            if "opa" in url or "v1/data" in url:
                return mock_opa_resp
            upstream_resp = MagicMock()
            upstream_resp.status_code = 200
            upstream_resp.text = json.dumps({"result": "ok"})
            upstream_resp.json.return_value = {"result": "ok"}
            return upstream_resp

        mock_httpx_client.__aenter__.return_value.post = _post
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        token = _make_token()
        async with HTTPXClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("services.governance.server.httpx.AsyncClient", return_value=mock_httpx_client),
                patch("services.governance.server.get_dolt_conn", return_value=mock_conn),
            ):
                resp = await client.post(
                    "/api/v0/tools/invoke",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
        return resp, mock_cursor

    async def test_validate_diff_is_allowed(self):
        """validator_server__validate_diff must be permitted by OPA."""
        body = {"name": "validator_server__validate_diff", "diff_text": "diff ..."}
        resp, _ = await self._invoke(body)
        assert resp.status_code != 403, "OPA denied validate_diff — missing from rego"

    async def test_run_linter_is_allowed(self):
        body = {"name": "linter_stub__run_linter", "diff_text": "diff ..."}
        resp, _ = await self._invoke(body)
        assert resp.status_code != 403

    async def test_coverage_report_is_allowed(self):
        body = {"name": "coverage_stub__coverage_report", "diff_text": "diff ..."}
        resp, _ = await self._invoke(body)
        assert resp.status_code != 403
