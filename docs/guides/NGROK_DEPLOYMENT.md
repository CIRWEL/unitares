# Remote access (legacy filename)

Status: thin compatibility entrypoint. Ngrok is no longer the documented path for exposing the MCP server.

Use **Cloudflare Tunnel** (`cloudflared`) and the allowlists described in [README.md](../../README.md) (`UNITARES_MCP_ALLOWED_HOSTS`, `UNITARES_MCP_ALLOWED_ORIGINS`, optional bind-all). Operational steps and troubleshooting live in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (Cloudflare Tunnel section).

This file name is kept so older links and tooling that still reference `docs/guides/NGROK_DEPLOYMENT.md` resolve without 404s.
