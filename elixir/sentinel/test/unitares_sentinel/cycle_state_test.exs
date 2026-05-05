defmodule UnitaresSentinel.CycleStateTest do
  @moduledoc """
  Surface 1 binding spec — see `docs/proposals/beam-wave-1-sentinel.md`
  v0.1.2 amendment block. Path resolution, max-on-boot semantics,
  string-key normalization, isinstance guard, and log-and-continue
  exception contract are all council-folded BLOCKs/CONCERNs. These
  tests are the regression bar.
  """

  use ExUnit.Case, async: true

  alias UnitaresSentinel.CycleState

  setup do
    tmpdir =
      System.tmp_dir!()
      |> Path.join("unitares_sentinel_cycle_state_test_#{System.unique_integer([:positive])}")

    File.mkdir_p!(tmpdir)
    on_exit(fn -> File.rm_rf!(tmpdir) end)

    # Surface 1 path discipline: shadow file lives next to canonical
    # with `.beam` suffix appended (v0.1.2 §B1).
    canonical = Path.join(tmpdir, ".sentinel_state")
    shadow = canonical <> ".beam"

    {:ok, tmpdir: tmpdir, canonical: canonical, shadow: shadow}
  end

  # ---------------------------------------------------------------------------
  # Round-trip: save then load recovers the cursor (canonical happy path).
  # ---------------------------------------------------------------------------

  test "save then load round-trips the cursor", ctx do
    state = %{"forced_release_alarm" => %{"last_event_ts" => "2026-05-03T13:56:34.479878+00:00"}}

    :ok = CycleState.save(state, path: ctx.shadow)
    assert CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow) == state
  end

  # ---------------------------------------------------------------------------
  # Max-on-boot (v0.1.2 §B2). The four cases the amendment enumerates.
  # ---------------------------------------------------------------------------

  test "max-on-boot: both files exist, beam newer — beam wins", ctx do
    File.write!(
      ctx.canonical,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-03T00:00:00.000000+00:00"}})
    )

    File.write!(
      ctx.shadow,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-04T00:00:00.000000+00:00"}})
    )

    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)
    assert get_in(state, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-04T00:00:00.000000+00:00"
  end

  test "max-on-boot: both files exist, python newer — python wins", ctx do
    File.write!(
      ctx.canonical,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-05T12:00:00.000000+00:00"}})
    )

    File.write!(
      ctx.shadow,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-04T00:00:00.000000+00:00"}})
    )

    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)
    assert get_in(state, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-05T12:00:00.000000+00:00"
  end

  test "max-on-boot: only python file exists — python wins", ctx do
    File.write!(
      ctx.canonical,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-03T13:56:34.479878+00:00"}})
    )

    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)
    assert get_in(state, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-03T13:56:34.479878+00:00"
  end

  test "max-on-boot: only beam file exists — beam wins", ctx do
    File.write!(
      ctx.shadow,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-04T01:02:03.456789+00:00"}})
    )

    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)
    assert get_in(state, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-04T01:02:03.456789+00:00"
  end

  test "max-on-boot: neither file exists — empty map", ctx do
    assert CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow) == %{}
  end

  test "max-on-boot: empty cursor counts as oldest (any non-empty wins)", ctx do
    # Canonical has the key but empty; shadow has a real timestamp.
    File.write!(ctx.canonical, ~s({"forced_release_alarm": {}}))

    File.write!(
      ctx.shadow,
      ~s({"forced_release_alarm": {"last_event_ts": "2026-05-04T00:00:00.000000+00:00"}})
    )

    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)
    assert get_in(state, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-04T00:00:00.000000+00:00"
  end

  # ---------------------------------------------------------------------------
  # Schema binding (v0.1.1 §Surface 1, retained in v0.1.2).
  # ---------------------------------------------------------------------------

  test "schema binding: forced_release_alarm.last_event_ts stays top-level ISO-8601 string", ctx do
    state = %{"forced_release_alarm" => %{"last_event_ts" => "2026-05-05T12:34:56.789012+00:00"}}
    :ok = CycleState.save(state, path: ctx.shadow)

    raw = File.read!(ctx.shadow)
    decoded = Jason.decode!(raw)

    # Top-level key, not nested under "state" or "cursor" — Python's
    # rollback reader at agents/sentinel/agent.py:663 reads exactly this path.
    assert get_in(decoded, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-05T12:34:56.789012+00:00"
  end

  # ---------------------------------------------------------------------------
  # String-key normalization (v0.1.2 §C3) — atom keys round-trip as strings.
  # ---------------------------------------------------------------------------

  test "string-key normalization: atom-keyed input round-trips as string-keyed", ctx do
    atom_keyed = %{forced_release_alarm: %{last_event_ts: "2026-05-05T12:00:00.000000+00:00"}}

    :ok = CycleState.save(atom_keyed, path: ctx.shadow)
    loaded = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)

    # Caller MUST see string keys back regardless of input shape.
    assert loaded == %{
             "forced_release_alarm" => %{"last_event_ts" => "2026-05-05T12:00:00.000000+00:00"}
           }
  end

  # ---------------------------------------------------------------------------
  # isinstance guard (v0.1.2 verifier REFUTED) — non-map JSON falls through.
  # ---------------------------------------------------------------------------

  test "isinstance guard: non-map JSON (array) falls through to %{}", ctx do
    File.write!(ctx.shadow, ~s([1, 2, 3]))

    assert CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow) == %{}
  end

  test "isinstance guard: malformed JSON falls through to %{}", ctx do
    File.write!(ctx.shadow, "not json at all {{{")

    assert CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow) == %{}
  end

  # ---------------------------------------------------------------------------
  # save/1 log-and-continue (v0.1.2 §N1).
  # ---------------------------------------------------------------------------

  test "save log-and-continue: returns :ok even when AtomicWrite fails", ctx do
    # Force AtomicWrite to raise by making the destination a non-empty directory
    # (matches the AtomicWrite test's failure-injection strategy).
    File.mkdir_p!(ctx.shadow)
    File.touch!(Path.join(ctx.shadow, "hold"))

    # Must NOT raise — Python's save_state swallows; BEAM matches.
    assert CycleState.save(%{"forced_release_alarm" => %{"last_event_ts" => "2026-05-05T00:00:00+00:00"}}, path: ctx.shadow) == :ok
  end

  # ---------------------------------------------------------------------------
  # Single-site accessors (v0.1.2 verifier REFUTED — Python has one read site).
  # ---------------------------------------------------------------------------

  test "get_last_event_ts/1 returns the cursor string", _ctx do
    state = %{"forced_release_alarm" => %{"last_event_ts" => "2026-05-05T01:23:45.678901+00:00"}}
    assert CycleState.get_last_event_ts(state) == "2026-05-05T01:23:45.678901+00:00"
  end

  test "get_last_event_ts/1 returns nil on empty/missing", _ctx do
    assert CycleState.get_last_event_ts(%{}) == nil
    assert CycleState.get_last_event_ts(%{"forced_release_alarm" => %{}}) == nil
  end

  test "update_last_event_ts/2 sets the cursor under the canonical key path", _ctx do
    updated = CycleState.update_last_event_ts(%{}, "2026-05-05T01:23:45.678901+00:00")
    assert get_in(updated, ["forced_release_alarm", "last_event_ts"]) ==
             "2026-05-05T01:23:45.678901+00:00"
  end

  test "update_last_event_ts/2 preserves sibling keys under forced_release_alarm", _ctx do
    state = %{"forced_release_alarm" => %{"sibling_key" => "preserve_me"}}
    updated = CycleState.update_last_event_ts(state, "2026-05-05T01:23:45+00:00")
    assert get_in(updated, ["forced_release_alarm", "sibling_key"]) == "preserve_me"
    assert get_in(updated, ["forced_release_alarm", "last_event_ts"]) == "2026-05-05T01:23:45+00:00"
  end

  # ---------------------------------------------------------------------------
  # Tier 2 cross-runtime fixture (v0.1.2 §C4).
  # ---------------------------------------------------------------------------

  test "Tier 2: BEAM CycleState.load round-trips a Python-written fixture", ctx do
    # The committed fixture is byte-equivalent to what `agents/sentinel/agent.py`
    # writes via `save_state`. Drift between Python's writer and this fixture
    # is a Tier 2 contract violation and a CI failure.
    fixture_path = Path.join([__DIR__, "..", "fixtures", "sentinel_state_python_v1.json"])
    fixture = File.read!(fixture_path)

    File.write!(ctx.canonical, fixture)
    state = CycleState.load(canonical: ctx.canonical, shadow: ctx.shadow)

    # Cursor MUST be recoverable from the Python fixture without loss.
    cursor = CycleState.get_last_event_ts(state)
    assert is_binary(cursor), "Python fixture cursor must be a binary string"
    assert String.match?(cursor, ~r/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/),
           "Python fixture cursor must be ISO-8601 (got: #{inspect(cursor)})"
  end

  # ---------------------------------------------------------------------------
  # Path resolution from config (v0.1.2 §B1).
  # ---------------------------------------------------------------------------

  test "default path resolves from :unitares_sentinel, :state_file_path config", ctx do
    Application.put_env(:unitares_sentinel, :state_file_path, ctx.canonical)
    on_exit(fn -> Application.delete_env(:unitares_sentinel, :state_file_path) end)

    state = %{"forced_release_alarm" => %{"last_event_ts" => "2026-05-05T03:14:15+00:00"}}

    # save with no opts uses config; load with no opts uses config.
    :ok = CycleState.save(state)
    assert CycleState.load() == state
  end
end
