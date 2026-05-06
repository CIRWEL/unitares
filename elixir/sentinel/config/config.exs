import Config

config :unitares_sentinel,
  database_url:
    System.get_env("UNITARES_SENTINEL_DATABASE_URL") ||
      System.get_env("UNITARES_LEASE_PLANE_DATABASE_URL") ||
      "postgresql://postgres:postgres@localhost:5432/governance",
  pool_size: 2,
  poller_interval_ms: 30_000,
  poller_initial_delay_ms: 1_000,
  findings_url: System.get_env("UNITARES_FINDINGS_URL") || "http://localhost:8767/api/findings",
  findings_timeout_ms: 3_000,
  findings_agent_id: System.get_env("UNITARES_SENTINEL_AGENT_ID") || "sentinel",
  findings_agent_name: "Sentinel",
  emit_findings: true

if File.exists?("config/#{config_env()}.exs") do
  import_config "#{config_env()}.exs"
end
