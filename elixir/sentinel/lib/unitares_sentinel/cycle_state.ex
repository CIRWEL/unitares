defmodule UnitaresSentinel.CycleState do
  @moduledoc """
  Cross-cycle state file (the de-dup fence) for Sentinel-on-BEAM.

  Surface 1 of the Wave 1 RFC. See `docs/proposals/beam-wave-1-sentinel.md`
  v0.1.2 amendment block — that is the binding spec; v0.1.1 §Surface 1
  prose is superseded on every point of conflict.

  ## Path resolution (v0.1.2 §B1)

  Canonical path resolves from `:unitares_sentinel, :state_file_path`
  (Application env), falling back to `UNITARES_SENTINEL_STATE_FILE`
  (system env). Production launchd plist is the source of the env var.
  Shadow path is the canonical path with `.beam` suffix appended,
  written to the same directory.

  ## Boot semantics (v0.1.2 §B2 — max-on-boot)

  `load/1` reads both files when both exist and returns the state with
  the larger `forced_release_alarm.last_event_ts` (ISO-8601 lex compare,
  valid because Python writes UTC-offset isoformat). Empty cursors are
  treated as older than any timestamp.

  ## Cutover (v0.1.2 §B3 — max wins)

  Composes with the boot rule: at cutover, BEAM re-reads both files
  one last time, persists the max to the shadow path, and from then on
  the canonical reader stops touching the Python file. Cutover signal
  is a `runtime` flag in the shadow file itself for forensic clarity.

  ## Save semantics (v0.1.2 §C3, §N1)

  - String-key normalization via `Jason.encode! |> Jason.decode!` —
    atom-keyed input round-trips back as string-keyed regardless of
    the caller's shape.
  - Log-and-continue: `AtomicWrite.write/2` failures are caught,
    logged at `:warning`, and `:ok` is returned. Mirrors Python's
    `save_state` swallow at `agents/sentinel/agent.py:506-508` so
    BEAM does not become more brittle than Python on ENOSPC / RO-fs.
  """

  alias UnitaresSentinel.AtomicWrite

  require Logger

  @forced_release_key "forced_release_alarm"
  @cursor_key "last_event_ts"

  @type t :: %{String.t() => term()}

  @doc """
  Load the cross-cycle state with max-on-boot semantics.

  Options:
    * `:canonical` — explicit canonical (Python) path, overrides config
    * `:shadow` — explicit shadow (BEAM) path, overrides default
                  (canonical + ".beam")
  """
  @spec load(keyword()) :: t()
  def load(opts \\ []) do
    {canonical, shadow} = resolve_paths(opts)

    canonical_state = read_decode(canonical)
    shadow_state = read_decode(shadow)

    pick_max(canonical_state, shadow_state)
  end

  @doc """
  Persist `state` to the shadow file, swallowing write errors.

  Always returns `:ok`. Atom-keyed maps are normalized to string keys
  via Jason round-trip before writing.

  Options:
    * `:path` — explicit write target, overrides default shadow path
  """
  @spec save(map(), keyword()) :: :ok
  def save(state, opts \\ []) when is_map(state) do
    path = Keyword.get(opts, :path) || default_shadow_path()
    normalized = state |> Jason.encode!() |> Jason.decode!()

    try do
      :ok = AtomicWrite.write(path, Jason.encode!(normalized))
    rescue
      e ->
        Logger.warning(
          "UnitaresSentinel.CycleState.save: write failed at #{inspect(path)} — #{inspect(e)}"
        )

        :ok
    end
  end

  @doc """
  Single read accessor for the cursor (mirrors Python's one-site discipline
  at agents/sentinel/agent.py:663).
  """
  @spec get_last_event_ts(t()) :: String.t() | nil
  def get_last_event_ts(state) when is_map(state) do
    state
    |> Map.get(@forced_release_key, %{})
    |> Map.get(@cursor_key)
  end

  @doc """
  Single write accessor for the cursor. Preserves sibling keys under
  `forced_release_alarm`.
  """
  @spec update_last_event_ts(t(), String.t()) :: t()
  def update_last_event_ts(state, cursor) when is_map(state) and is_binary(cursor) do
    inner =
      state
      |> Map.get(@forced_release_key, %{})
      |> Map.put(@cursor_key, cursor)

    Map.put(state, @forced_release_key, inner)
  end

  # ---- internals ---------------------------------------------------------

  defp resolve_paths(opts) do
    canonical = Keyword.get(opts, :canonical) || resolve_canonical_from_config()
    shadow = Keyword.get(opts, :shadow) || canonical <> ".beam"
    {canonical, shadow}
  end

  defp resolve_canonical_from_config do
    Application.get_env(:unitares_sentinel, :state_file_path) ||
      System.get_env("UNITARES_SENTINEL_STATE_FILE") ||
      raise """
      UnitaresSentinel.CycleState: STATE_FILE path not configured.
      Set :unitares_sentinel, :state_file_path in config or
      UNITARES_SENTINEL_STATE_FILE in the environment. The launchd
      plist is the source of truth in production.
      """
  end

  defp default_shadow_path, do: resolve_canonical_from_config() <> ".beam"

  # Mirrors Python's load_state guard at agents/sentinel/agent.py:494-501:
  # missing file → %{}, decode failure → %{}, non-map decode → %{}.
  defp read_decode(path) do
    with {:ok, contents} <- File.read(path),
         {:ok, decoded} when is_map(decoded) <- Jason.decode(contents) do
      decoded
    else
      _ -> %{}
    end
  end

  # Max-on-boot: empty cursors lose to any non-empty cursor; ISO-8601 with
  # zero-padded fields and consistent timezone offset is lex-comparable.
  defp pick_max(canonical_state, shadow_state) do
    canonical_cursor = get_last_event_ts(canonical_state) || ""
    shadow_cursor = get_last_event_ts(shadow_state) || ""

    cond do
      canonical_state == %{} and shadow_state == %{} -> %{}
      canonical_cursor >= shadow_cursor -> canonical_state
      true -> shadow_state
    end
  end
end
