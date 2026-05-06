defmodule UnitaresSentinel.ForcedReleasePollerFindingsTest do
  @moduledoc """
  Surface 2 bindings for forced-release findings emission.

  The GenServer runtime path must POST alarms before persisting the candidate
  cursor. If the process crashes between poll and emit, the cursor remains
  behind and the next boot can replay the alarms, matching Python ordering.
  """

  use ExUnit.Case, async: false

  @moduletag :db

  alias SentinelTestHelpers, as: H
  alias UnitaresSentinel.ForcedReleasePoller

  setup do
    label = H.random_label()
    surface_prefix = "dialectic:/test_sentinel_findings_#{label}"

    tmpdir =
      System.tmp_dir!()
      |> Path.join("unitares_sentinel_findings_test_#{System.unique_integer([:positive])}")

    File.mkdir_p!(tmpdir)
    state_file = Path.join(tmpdir, ".sentinel_state")
    Application.put_env(:unitares_sentinel, :state_file_path, state_file)

    on_exit(fn ->
      H.cleanup_surface_prefix(surface_prefix)
      Application.delete_env(:unitares_sentinel, :state_file_path)
      File.rm_rf!(tmpdir)
    end)

    {:ok, surface_prefix: surface_prefix, state_file: state_file}
  end

  test "GenServer emits findings before persisting candidate cursor", ctx do
    parent = self()
    shadow_path = ctx.state_file <> ".beam"
    prior = ~U[2030-01-01 00:00:00.000000Z]
    event_ts = DateTime.add(prior, 1, :second)
    surface_id = ctx.surface_prefix <> "/emit_order"

    File.write!(
      ctx.state_file,
      ~s({"forced_release_alarm":{"last_event_ts":"#{DateTime.to_iso8601(prior)}"}})
    )

    {event_id, _returned_ts} = H.insert_forced_event(surface_id, event_ts)

    http_post = fn _url, body, _headers, _timeout_ms ->
      if body["event_id"] == event_id do
        send(parent, {:posted_target_alarm, body, File.exists?(shadow_path)})
      end

      {:ok, 200, ~s({"success":true,"deduped":false})}
    end

    {:ok, pid} =
      ForcedReleasePoller.start_link(
        name: :"test_findings_emit_#{System.unique_integer([:positive])}",
        db: UnitaresSentinel.DB,
        interval_ms: 60_000,
        initial_delay_ms: 60_000,
        jitter_ms: 0,
        emit_findings: true,
        findings_opts: [
          agent_id: "sentinel-test",
          agent_name: "Sentinel",
          http_post: http_post
        ]
      )

    send(pid, :tick)

    assert_receive {:posted_target_alarm, body, persisted_before_post?}, 2_000

    refute persisted_before_post?,
           "cursor must not be written until after the Surface 2 emit loop completes"

    assert body["type"] == "sentinel_forced_release_alarm"
    assert body["alarm_kind"] == "ad_hoc"
    assert body["fingerprint"] == "forced_release:ad_hoc:#{event_id}"

    Process.sleep(50)
    assert File.exists?(shadow_path), "cursor should persist after emit loop"

    decoded = shadow_path |> File.read!() |> Jason.decode!()

    assert get_in(decoded, ["forced_release_alarm", "last_event_ts"]) ==
             DateTime.to_iso8601(event_ts)

    GenServer.stop(pid)
  end
end
