defmodule UnitaresSentinel.FindingsTest do
  use ExUnit.Case, async: true

  alias UnitaresSentinel.Findings

  defp alarm do
    %{
      kind: "ad_hoc",
      severity: "high",
      summary: "forced release: dialectic:/x (lease lease-1)",
      fingerprint: "forced_release:ad_hoc:event-1",
      extra: %{
        event_id: "event-1",
        ts: "2026-05-06T00:00:00Z",
        lease_id: "lease-1",
        surface_id: "dialectic:/x",
        surface_kind: "dialectic",
        fingerprint: "spoofed"
      }
    }
  end

  test "alarm_body mirrors Python forced-release post_finding shape" do
    body = Findings.alarm_body(alarm(), agent_id: "sentinel-test", agent_name: "Sentinel")

    assert body["type"] == "sentinel_forced_release_alarm"
    assert body["severity"] == "high"
    assert body["message"] == "forced release: dialectic:/x (lease lease-1)"
    assert body["agent_id"] == "sentinel-test"
    assert body["agent_name"] == "Sentinel"
    assert body["fingerprint"] == "forced_release:ad_hoc:event-1"
    assert body["alarm_kind"] == "ad_hoc"
    assert body["event_id"] == "event-1"
    assert body["surface_kind"] == "dialectic"
  end

  test "post_alarm returns true only for accepted non-deduped response" do
    http_post = fn url, body, headers, timeout_ms ->
      assert url == "http://example.test/api/findings"
      assert body["type"] == "sentinel_forced_release_alarm"
      assert {"Content-Type", "application/json"} in headers
      assert timeout_ms == 123

      {:ok, 200, ~s({"success":true,"deduped":false})}
    end

    assert Findings.post_alarm(
             alarm(),
             url: "http://example.test/api/findings",
             timeout_ms: 123,
             http_post: http_post
           )
  end

  test "post_alarm swallows transport failures" do
    http_post = fn _url, _body, _headers, _timeout_ms -> raise "connection refused" end

    refute Findings.post_alarm(alarm(), http_post: http_post)
  end

  test "post_alarm returns false for deduped responses" do
    http_post = fn _url, _body, _headers, _timeout_ms ->
      {:ok, 200, ~s({"success":true,"deduped":true})}
    end

    refute Findings.post_alarm(alarm(), http_post: http_post)
  end
end
