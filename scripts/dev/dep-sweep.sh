#!/bin/bash
# Weekly system-dep sweep: surfaces outdated packages across Mac + Pi.
# Triggered by com.unitares.dep-sweep launchd (Sundays 9am local) or run manually.

set -u

LOG=${UNITARES_DEP_SWEEP_LOG:-$HOME/Library/Logs/unitares-dep-sweep.log}
PI_HOST=${UNITARES_PI_HOST:-lumen}
TS=$(date '+%Y-%m-%d %H:%M:%S %Z')

{
  echo
  echo "=========================================="
  echo "Dep sweep — $TS"
  echo "=========================================="

  echo
  echo "--- Homebrew (formulae) ---"
  HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --formula 2>/dev/null
  brew_count=$(HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --formula --quiet 2>/dev/null | wc -l | tr -d ' ')

  echo
  echo "--- Homebrew (casks) ---"
  HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --cask 2>/dev/null
  cask_count=$(HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --cask --quiet 2>/dev/null | wc -l | tr -d ' ')

  echo
  echo "--- Pi apt (upgradable) ---"
  apt_output=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$PI_HOST" 'apt list --upgradable 2>/dev/null | tail -n +2' 2>&1)
  apt_status=$?
  if [ $apt_status -ne 0 ]; then
    echo "(SSH to $PI_HOST failed — skipped)"
    apt_count=0
  else
    echo "$apt_output"
    apt_count=$(printf '%s\n' "$apt_output" | grep -c '/' || true)
  fi

  echo
  echo "--- Pi OS ---"
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$PI_HOST" 'lsb_release -d 2>/dev/null; uname -r' 2>&1 || echo "(skipped)"

  echo
  echo "--- Toolchain ---"
  printf 'claude  : %s\n' "$(claude --version 2>/dev/null | head -1)"
  printf 'python3 : %s\n' "$(python3 --version 2>/dev/null)"
  printf 'node    : %s\n' "$(node --version 2>/dev/null)"
  printf 'uv      : %s\n' "$(uv --version 2>/dev/null)"
  printf 'gh      : %s\n' "$(gh --version 2>/dev/null | head -1)"
  printf 'cflared : %s\n' "$(cloudflared --version 2>/dev/null | head -1)"
  printf 'ts      : %s\n' "$(tailscale version 2>/dev/null | head -1)"

  echo
  echo "--- Pinned-with-known-fragility (manual review) ---"
  echo "  cloudflared 2026.3+ has IPv6 WS regression — sidecar required for gov.cirwel.org /ws/eisv"
  echo "  postgresql@17 — major upgrades require data migration"
  echo "  Pi firmware-brcm80211 — WiFi flake under load is a known kernel bug"

  echo
  echo "Summary: brew=$brew_count cask=$cask_count apt=$apt_count"
} >> "$LOG" 2>&1

# Best-effort desktop notification (no-op if osascript unavailable)
if command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"brew=$brew_count cask=$cask_count apt=$apt_count — see ~/Library/Logs/unitares-dep-sweep.log\" with title \"Weekly dep sweep\"" 2>/dev/null || true
fi
