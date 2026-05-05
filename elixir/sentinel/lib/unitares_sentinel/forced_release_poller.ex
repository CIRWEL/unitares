defmodule UnitaresSentinel.ForcedReleasePoller do
  @moduledoc """
  Surface 1 cycle worker — periodic poller that drives `CycleState`.

  Reads the cursor from `CycleState`, queries `lease_plane.lease_plane_events`
  for `event_type='forced'` rows past the cursor, builds alarms via
  `ForcedReleasePoller.Logic.build_alarms/2`, advances the cursor to
  max(rows.ts), and persists via `CycleState.save/2`.

  ## Scope (this PR)

  Ad_hoc forced events (`event_type='forced'`) only — the lowest-volume
  class. Deferred to follow-up PRs:

    * `event_type='lease.deprecation_swept'` deprecation-batch class
    * `event_type='conflict_held_by_other'` conflict-batch class

  ## Findings emit

  This module RETURNS alarms but does NOT POST them. Surface 2 (findings
  emit) is a separate writer-locked surface and lands in its own PR.
  Returning alarms keeps the API forward-compatible: when Surface 2 wires
  up, it calls `tick/1` and routes the alarms to the dashboard / Discord
  bridge.

  ## Tick API

  `tick/1` is the unit of work — call it from the GenServer's tick loop
  OR from tests with explicit options. The GenServer itself is a thin
  scheduler; the testable behavior lives in `tick/1`.
  """

  use GenServer

  require Logger

  alias UnitaresSentinel.{CycleState, ForcedReleasePoller.Logic}

  @type opts :: [
          prior_cursor: DateTime.t() | nil,
          db: GenServer.server(),
          persist: boolean(),
          state_path: Path.t() | nil
        ]

  # ---- Public tick API --------------------------------------------------

  @doc """
  Run one poll cycle.

  Options:
    * `:prior_cursor` — cursor to filter against (`nil` = no filter, fetch all)
    * `:db` — Postgrex registered name (default: `UnitaresSentinel.DB`)
    * `:persist` — when true, write the new cursor via `CycleState.save/2`
       (default: false; the GenServer flips this to true at runtime, tests
       opt in selectively)
    * `:state_path` — explicit shadow path to persist into; only used when
       `:persist` is true and overrides the default config-resolved path

  Returns `{alarms, new_cursor}` where `new_cursor` is `DateTime.t() | nil`.
  """
  @spec tick(opts()) :: {[Logic.alarm()], DateTime.t() | nil}
  def tick(opts \\ []) do
    db = Keyword.get(opts, :db, UnitaresSentinel.DB)
    prior_cursor = Keyword.get(opts, :prior_cursor)
    persist? = Keyword.get(opts, :persist, false)

    rows = query_forced_rows(db, prior_cursor)
    {alarms, new_cursor} = Logic.build_alarms(rows, prior_cursor)

    if persist? and new_cursor != nil do
      persist_cursor(new_cursor, opts)
    end

    {alarms, new_cursor}
  end

  defp query_forced_rows(db, prior_cursor) do
    sql = """
    SELECT event_id::text AS event_id,
           ts,
           lease_id::text AS lease_id,
           surface_id,
           surface_kind
    FROM lease_plane.lease_plane_events
    WHERE event_type = 'forced'
      AND ($1::timestamptz IS NULL OR ts > $1)
    ORDER BY ts
    """

    case Postgrex.query(db, sql, [prior_cursor]) do
      {:ok, %{rows: rows, columns: cols}} ->
        Enum.map(rows, &row_to_map(cols, &1))

      {:error, e} ->
        Logger.warning(
          "ForcedReleasePoller.query_forced_rows: #{inspect(e)} — returning empty rows"
        )

        []
    end
  end

  defp row_to_map(columns, row) do
    columns
    |> Enum.zip(row)
    |> Enum.into(%{}, fn {col, val} -> {String.to_atom(col), val} end)
  end

  defp persist_cursor(new_cursor, opts) do
    state = CycleState.update_last_event_ts(%{}, DateTime.to_iso8601(new_cursor))

    save_opts =
      case Keyword.get(opts, :state_path) do
        nil -> []
        path -> [path: path]
      end

    CycleState.save(state, save_opts)
  end

  # ---- GenServer scheduler ----------------------------------------------

  @doc """
  Start the poller GenServer. Reads cursor from CycleState on init,
  schedules first tick after `:poller_initial_delay_ms`, then ticks
  every `:poller_interval_ms`.

  Both intervals are config-driven so tests can inject short values.
  """
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: Keyword.get(opts, :name, __MODULE__))
  end

  @impl true
  def init(opts) do
    db = Keyword.get(opts, :db, UnitaresSentinel.DB)
    interval_ms = Keyword.get(opts, :interval_ms, Application.get_env(:unitares_sentinel, :poller_interval_ms, 30_000))
    initial_delay_ms = Keyword.get(opts, :initial_delay_ms, Application.get_env(:unitares_sentinel, :poller_initial_delay_ms, 1_000))

    cursor = load_cursor_from_state()

    state = %{
      db: db,
      cursor: cursor,
      interval_ms: interval_ms
    }

    Process.send_after(self(), :tick, initial_delay_ms)
    {:ok, state}
  end

  @impl true
  def handle_info(:tick, state) do
    {_alarms, new_cursor} =
      tick(prior_cursor: state.cursor, db: state.db, persist: true)

    Process.send_after(self(), :tick, state.interval_ms)
    {:noreply, %{state | cursor: new_cursor}}
  end

  defp load_cursor_from_state do
    case CycleState.get_last_event_ts(CycleState.load()) do
      nil ->
        nil

      ts when is_binary(ts) ->
        case DateTime.from_iso8601(ts) do
          {:ok, dt, _} -> dt
          _ -> nil
        end
    end
  rescue
    _ -> nil
  end
end
