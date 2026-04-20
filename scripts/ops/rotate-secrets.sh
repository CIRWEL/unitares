#!/usr/bin/env bash
# rotate-secrets.sh — rotate UNITARES bearer-token secrets.
#
# Rotation steps:
#   1. Generate new secret values (32 bytes, base64url).
#   2. Write them into the 9 LaunchAgent plists that reference them.
#   3. Surgical-strip each anchor in ~/.unitares/anchors/:
#        drop continuity_token + client_session_id, keep agent_uuid.
#   4. Bounce the governance-mcp launchd service.
#
# Residents wake on their normal cadence and resume via PATH 0 UUID-direct
# identity lookup (shipped 2026-04-17). They do NOT fresh-onboard and do
# NOT get new UUIDs.
#
# Why this exists: on 2026-04-19 the ad-hoc rotation runbook wiped the
# anchors/ dir wholesale. Every resident then fresh-onboarded with a new
# UUID. See memory/project_identity-audit-2026-04-19.md and the
# anchor-resilience series plan.

set -euo pipefail

ANCHOR_DIR="${HOME}/.unitares/anchors"
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"
GOVERNANCE_PLIST="${LAUNCHAGENTS_DIR}/com.unitares.governance-mcp.plist"
DATE_STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${HOME}/.unitares/rotation-backup-${DATE_STAMP}"

log()  { printf '\033[1;34m[rotate]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[rotate]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[rotate]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Pre-flight ---
[[ -d "${ANCHOR_DIR}" ]] || die "anchor dir missing: ${ANCHOR_DIR}"
[[ -f "${GOVERNANCE_PLIST}" ]] || die "governance plist missing: ${GOVERNANCE_PLIST}"

# Every anchor must already have an agent_uuid — if any don't, abort loudly;
# operator needs to re-bootstrap that resident explicitly.
missing=()
for f in "${ANCHOR_DIR}"/*.json; do
  [[ -e "$f" ]] || continue
  if ! python3 -c "
import json, sys
d = json.load(open('$f'))
sys.exit(0 if d.get('agent_uuid') else 1)
" 2>/dev/null; then
    missing+=("$f")
  fi
done
if (( ${#missing[@]} > 0 )); then
  die "anchors missing agent_uuid (cannot do surgical rotation): ${missing[*]}"
fi

log "backup dir: ${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"
cp -a "${ANCHOR_DIR}" "${BACKUP_DIR}/anchors"

# --- Generate new secrets ---
new_continuity_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
new_http_api_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# --- Write into plists (all 9 com.unitares.*.plist files) ---
log "rotating secrets in LaunchAgents plists..."
for plist in "${LAUNCHAGENTS_DIR}"/com.unitares.*.plist; do
  [[ -e "$plist" ]] || continue
  cp "$plist" "${BACKUP_DIR}/$(basename "$plist")"
  /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:UNITARES_CONTINUITY_TOKEN_SECRET ${new_continuity_secret}" "$plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:UNITARES_HTTP_API_TOKEN ${new_http_api_token}" "$plist" 2>/dev/null || true
done

# --- Surgical anchor strip: drop continuity_token + client_session_id,
#     keep agent_uuid. ---
log "surgical anchor strip..."
for f in "${ANCHOR_DIR}"/*.json; do
  [[ -e "$f" ]] || continue
  python3 - "$f" <<'PY'
import json, os, sys, tempfile
path = sys.argv[1]
with open(path) as fh:
    d = json.load(fh)
uuid = d.get("agent_uuid")
if not uuid:
    sys.exit(f"refusing to strip {path}: no agent_uuid")
new = {"agent_uuid": uuid}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as fh:
    json.dump(new, fh)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
done

# --- Bounce governance-mcp so it picks up the new secrets. ---
log "restarting governance-mcp..."
launchctl unload "${GOVERNANCE_PLIST}" 2>/dev/null || true
launchctl load   "${GOVERNANCE_PLIST}"

log "rotation complete. backup at ${BACKUP_DIR}"
log "residents will re-auth via PATH 0 on their next cycle."
