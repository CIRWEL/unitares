defmodule UnitaresSentinel.ForcedReleasePoller.Logic do
  @moduledoc """
  Pure logic for transforming `lease_plane.lease_plane_events` rows into
  Sentinel alarms + advancing the cursor.

  Surface 1 cycle worker scope (this PR): `event_type='forced'` only —
  the per-event ad_hoc class. Mirrors `_ad_hoc_alarm` in
  `agents/sentinel/forced_release_alarm.py` for parity.

  Deferred (follow-up PRs):
    * `event_type='lease.deprecation_swept'` deprecation-batch class
    * `event_type='conflict_held_by_other'` conflict-batch class

  Caller contract (the GenServer): rows arrive as `[%{event_id: binary,
  ts: DateTime.t, lease_id: binary | nil, surface_id: binary,
  surface_kind: binary}]` — atom keys, UUIDs already cast to text by the
  SQL layer. The `prior_cursor` is `DateTime.t | nil`; `nil` means first
  poll, advance to max(rows.ts) or stay nil if rows are empty.
  """

  @type row :: %{
          required(:event_id) => binary(),
          required(:ts) => DateTime.t(),
          required(:lease_id) => binary() | nil,
          required(:surface_id) => binary(),
          required(:surface_kind) => binary()
        }

  @type alarm :: %{
          kind: String.t(),
          severity: String.t(),
          summary: String.t(),
          fingerprint: String.t(),
          extra: %{
            event_id: binary(),
            ts: String.t(),
            lease_id: binary() | nil,
            surface_id: binary(),
            surface_kind: binary()
          }
        }

  @doc """
  Build alarms from `rows` and advance the cursor.

  Cursor never regresses: if every row's ts is older than `prior_cursor`,
  the prior is preserved. This is defensive — the SQL filter should
  already exclude older rows, but a buggy filter must not corrupt the
  de-dup fence.
  """
  @spec build_alarms([row()], DateTime.t() | nil) :: {[alarm()], DateTime.t() | nil}
  def build_alarms(rows, prior_cursor) when is_list(rows) do
    alarms = Enum.map(rows, &row_to_alarm/1)
    new_cursor = advance_cursor(rows, prior_cursor)
    {alarms, new_cursor}
  end

  defp row_to_alarm(%{event_id: event_id, surface_id: surface_id} = row) do
    lease_label = lease_label(row.lease_id)

    %{
      kind: "ad_hoc",
      severity: "high",
      summary: "forced release: #{surface_id} (lease #{lease_label})",
      fingerprint: "forced_release:ad_hoc:#{event_id}",
      extra: %{
        event_id: event_id,
        ts: DateTime.to_iso8601(row.ts),
        lease_id: row.lease_id,
        surface_id: surface_id,
        surface_kind: row.surface_kind
      }
    }
  end

  defp lease_label(nil), do: "<unknown>"
  defp lease_label(lease_id) when is_binary(lease_id), do: lease_id

  defp advance_cursor([], prior), do: prior

  defp advance_cursor(rows, prior) do
    max_ts = rows |> Enum.map(& &1.ts) |> Enum.max(DateTime)

    cond do
      is_nil(prior) -> max_ts
      DateTime.compare(max_ts, prior) == :gt -> max_ts
      true -> prior
    end
  end
end
