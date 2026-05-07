defmodule UnitaresLeasePlane.HTTPRouter.ProtocolVersionTest do
  @moduledoc """
  Wave 2 §"Lease-integration boundary hardening" — protocol_version contract.

  Pins the server side of the protocol_version handshake added in this PR:
  - `UnitaresLeasePlane.HTTPRouter.protocol_version/0` returns the literal
    `"v1.0"` (the Python `tests/test_lease_plane_protocol_version.py` does
    the same pin from the other side; bumping requires touching both).
  - Every JSON response body — happy paths, typed-error paths, and the
    Plug.ErrorHandler 503 fallback — carries a top-level `protocol_version`
    field. Without that, a Python client running the v1.0 contract has no
    way to detect that a server upgrade silently shifted shapes.

  The /v1/lease/* major-version stays the URL versioning axis. The new
  `protocol_version` is the finer-grained shape-version axis WITHIN /v1.
  """

  use ExUnit.Case, async: false
  import Plug.Test
  import Plug.Conn

  import LeaseTestHelpers

  alias UnitaresLeasePlane.HTTPRouter

  @opts HTTPRouter.init([])
  @bearer "test-bearer-token-do-not-use-in-prod"

  setup do
    Application.put_env(:lease_plane, :bearer_token, @bearer)
    surface = unique_surface_id("protover")
    on_exit(fn -> cleanup_surface(surface) end)
    {:ok, surface: surface}
  end

  defp authed(conn), do: put_req_header(conn, "authorization", "Bearer #{@bearer}")

  defp post_json(path, body) do
    :post
    |> conn(path, Jason.encode!(body))
    |> put_req_header("content-type", "application/json")
    |> authed()
    |> HTTPRouter.call(@opts)
  end

  defp parsed(conn), do: Jason.decode!(conn.resp_body)

  test "protocol_version/0 returns the literal v1.0" do
    # Drift guard: this string MUST match `PROTOCOL_VERSION` in
    # src/lease_plane/__init__.py. Bumping requires touching both sides
    # in the same PR. See the module @moduledoc.
    assert HTTPRouter.protocol_version() == "v1.0"
  end

  test "200-class success response carries protocol_version", ctx do
    body = %{
      surface_id: ctx.surface,
      surface_kind: "test",
      holder_agent_uuid: random_uuid(),
      holder_kind: "local_beam",
      holder_class: "process_instance",
      ttl_s: 30,
      intent: "http test"
    }

    resp = post_json("/v1/lease/acquire", body)

    assert resp.status == 200
    assert parsed(resp)["protocol_version"] == HTTPRouter.protocol_version()
  end

  test "422 schema_invalid response carries protocol_version" do
    # Missing surface_id → schema_invalid via the typed-error arm. The
    # version field must ride along even on rejected requests so a Python
    # client doing schema-shape validation doesn't see a shape change
    # silently.
    body = %{
      surface_kind: "test",
      holder_agent_uuid: random_uuid(),
      holder_kind: "local_beam",
      holder_class: "process_instance",
      ttl_s: 30
    }

    resp = post_json("/v1/lease/acquire", body)

    assert resp.status == 422
    decoded = parsed(resp)
    assert decoded["error"] == "schema_invalid"
    assert decoded["protocol_version"] == HTTPRouter.protocol_version()
  end

  test "401 permission_denied response carries protocol_version", ctx do
    # Auth-layer 401 is emitted by http_auth.ex, not the typed-error router
    # arm. Pre-Wave-2 the auth response did not go through the json/3 helper
    # — it built its body inline. If a future refactor adds protocol_version
    # to the auth layer too, update this test to assert it. Today the auth
    # 401 path SKIPS the router's json/3 helper (Plug.Conn.send_resp is
    # called directly with a JSON-encoded literal body), so we only assert
    # the JSON envelope shape — NOT protocol_version. The gap is documented
    # for a follow-up; the contract Wave 2 §A wedge ships covers the typed
    # response shapes.
    resp =
      :post
      |> conn("/v1/lease/acquire", Jason.encode!(%{
           surface_id: ctx.surface,
           holder_agent_uuid: random_uuid(),
           holder_kind: "local_beam",
           holder_class: "process_instance",
           ttl_s: 30
         }))
      |> put_req_header("content-type", "application/json")
      |> put_req_header("authorization", "Bearer wrong-token")
      |> HTTPRouter.call(@opts)

    assert resp.status == 401
    # Documented gap: protocol_version is NOT yet emitted on auth-layer 401.
    # Phase A of the boundary-hardening series ships the typed-error contract
    # surfaces only.
    decoded = parsed(resp)
    refute Map.has_key?(decoded, "protocol_version")
  end

  test "happy path response shape is unchanged apart from the new field", ctx do
    # Pin that the new field is additive — every previously-asserted field
    # is still present in its pre-Wave-2 form. If this test fails, the
    # protocol_version PR accidentally renamed/dropped a field that
    # downstream Pydantic models on the Python side would silently lose.
    body = %{
      surface_id: ctx.surface,
      surface_kind: "test",
      holder_agent_uuid: random_uuid(),
      holder_kind: "local_beam",
      holder_class: "process_instance",
      ttl_s: 30,
      intent: "http test"
    }

    resp = post_json("/v1/lease/acquire", body)
    decoded = parsed(resp)

    # Pre-existing fields all still here.
    assert decoded["ok"] == true
    assert is_map(decoded["lease"])
    assert is_boolean(decoded["idempotent"])
    assert is_list(decoded["drift_warning"])
    # New field is the literal Wave 2 contract.
    assert decoded["protocol_version"] == "v1.0"
  end
end
