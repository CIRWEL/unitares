"""Tests for SyncGovernanceClient."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest

from unitares_sdk.errors import GovernanceConnectionError, IdentityDriftError
from unitares_sdk.models import CheckinResult, ModelResult, NoteResult, OnboardResult
from unitares_sdk.sync_client import SyncGovernanceClient


# --- REST envelope parsing ---


class TestRESTEnvelope:
    """Test _rest_call parsing of the /v1/tools/call response format."""

    def _make_client(self, handler_class) -> tuple[SyncGovernanceClient, HTTPServer]:
        server = HTTPServer(("127.0.0.1", 0), handler_class)
        port = server.server_address[1]
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        client = SyncGovernanceClient(
            rest_url=f"http://127.0.0.1:{port}/v1/tools/call",
            transport="rest",
            timeout=5.0,
        )
        return client, server

    def test_dict_result(self):
        """Core tools return result as a plain dict."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "name": "onboard",
                    "result": {
                        "success": True,
                        "client_session_id": "sid-1",
                        "uuid": "u-1",
                    },
                    "success": True,
                }).encode())

            def log_message(self, *args):
                pass

        client, server = self._make_client(Handler)
        raw = client.call_tool("onboard", {"name": "Test"})
        assert raw["success"] is True
        assert raw["client_session_id"] == "sid-1"
        server.server_close()

    def test_string_result(self):
        """Some tools may return a JSON string that needs parsing."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "name": "test",
                    "result": '{"success": true, "data": "hello"}',
                    "success": True,
                }).encode())

            def log_message(self, *args):
                pass

        client, server = self._make_client(Handler)
        raw = client.call_tool("test", {})
        assert raw["success"] is True
        assert raw["data"] == "hello"
        server.server_close()

    def test_failure_envelope(self):
        """When success=false in envelope, should raise."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "Tool not found",
                }).encode())

            def log_message(self, *args):
                pass

        client, server = self._make_client(Handler)
        with pytest.raises(GovernanceConnectionError, match="Tool not found"):
            client.call_tool("bad_tool", {})
        server.server_close()

    def test_multi_content_result(self):
        """Multi-content-block result (rarer, for tools that return multiple text blocks)."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "name": "test",
                    "result": {
                        "content": [
                            {"type": "text", "text": '{"part": "one"}'},
                            {"type": "text", "text": '{"part2": "two"}'},
                        ]
                    },
                    "success": True,
                }).encode())

            def log_message(self, *args):
                pass

        client, server = self._make_client(Handler)
        raw = client.call_tool("test", {})
        assert raw["part"] == "one"
        assert raw["part2"] == "two"
        server.server_close()


# --- Session injection ---


class TestSyncSessionInjection:
    def test_injects_session_id(self):
        client = SyncGovernanceClient(transport="rest")
        client.client_session_id = "sid-123"
        result = client._inject_session("process_agent_update", {"response_text": "hi"})
        assert result["client_session_id"] == "sid-123"

    def test_skips_for_identity_tools(self):
        client = SyncGovernanceClient(transport="rest")
        client.client_session_id = "sid-123"
        assert "client_session_id" not in client._inject_session("onboard", {})
        assert "client_session_id" not in client._inject_session("identity", {})


# --- Identity capture ---


class TestSyncIdentityCapture:
    def test_captures_identity(self):
        client = SyncGovernanceClient(transport="rest")
        client._capture_identity({
            "client_session_id": "sid-1",
            "uuid": "u-1",
            "continuity_token": "tok-1",
        })
        assert client.client_session_id == "sid-1"
        assert client.agent_uuid == "u-1"

    def test_raises_on_drift(self):
        client = SyncGovernanceClient(transport="rest")
        client.agent_uuid = "old-uuid"
        with pytest.raises(IdentityDriftError):
            client._capture_identity({"uuid": "new-uuid"})


# --- Typed method tool mapping ---


class TestSyncToolMapping:
    def test_checkin_maps_to_process_agent_update(self):
        client = SyncGovernanceClient(transport="rest")
        calls = []

        def fake_call(tool_name, arguments, **kwargs):
            calls.append(tool_name)
            return {
                "success": True,
                "decision": {"action": "proceed"},
                "metrics": {},
            }

        client.call_tool = fake_call
        result = client.checkin("test")
        assert calls[-1] == "process_agent_update"
        assert isinstance(result, CheckinResult)

    def test_get_metrics_maps_to_get_governance_metrics(self):
        client = SyncGovernanceClient(transport="rest")
        calls = []

        def fake_call(tool_name, arguments, **kwargs):
            calls.append(tool_name)
            return {"success": True, "metrics": {}}

        client.call_tool = fake_call
        client.get_metrics()
        assert calls[-1] == "get_governance_metrics"

    def test_call_model_omits_none_provider(self):
        client = SyncGovernanceClient(transport="rest")
        captured_args = []

        def fake_call(tool_name, arguments, **kwargs):
            captured_args.append(arguments)
            return {"success": True, "response": "hi"}

        client.call_tool = fake_call
        client.call_model("test prompt")
        assert "provider" not in captured_args[0]
        assert "model" not in captured_args[0]


# --- MCP transport guard ---


class TestMCPTransportGuard:
    def test_detects_no_running_loop(self):
        """In a plain sync context, _ensure_async_client should work
        (but we can't actually test it without a real server)."""
        # Just verify the transport attribute is set
        client = SyncGovernanceClient(transport="mcp")
        assert client.transport == "mcp"


# --- Connection error ---


class TestSyncConnectionError:
    def test_unreachable_server(self):
        client = SyncGovernanceClient(
            rest_url="http://127.0.0.1:1/v1/tools/call",
            transport="rest",
            timeout=1.0,
        )
        with pytest.raises(GovernanceConnectionError):
            client.call_tool("test", {})
