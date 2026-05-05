import Config

config :unitares_sentinel,
  database_url:
    System.get_env("UNITARES_SENTINEL_DATABASE_URL") ||
      System.get_env("UNITARES_LEASE_PLANE_DATABASE_URL") ||
      "postgresql://postgres:postgres@localhost:5432/governance",
  pool_size: 2,
  poller_interval_ms: 30_000,
  poller_initial_delay_ms: 1_000

if File.exists?("config/#{config_env()}.exs") do
  import_config "#{config_env()}.exs"
end
