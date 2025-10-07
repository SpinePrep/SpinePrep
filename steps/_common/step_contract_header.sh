#!/usr/bin/env bash
set -euo pipefail

log() { printf "[%s] %s\n" "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }

require_file() {
  local f="$1"
  [[ -f "$f" ]] || { log "Missing required file: $f"; exit 2; }
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { log "Missing required executable: $1"; exit 2; }
}

atomically_write() {
  # atomically_write <dst> : reads stdin to tmp then mv
  local dst="$1"
  local dir; dir="$(dirname "$dst")"
  mkdir -p "$dir"
  local tmp; tmp="$(mktemp "${dst}.XXXX.tmp")"
  cat > "$tmp"
  mv -f "$tmp" "$dst"
}

write_prov() {
  # write_prov <outfile> <step> <inputs_json> <params_json> <tool_versions_json>
  local outfile="$1"; shift
  local step="$1"; shift
  local inputs="$1"; shift
  local params="$1"; shift
  local tools="$1"; shift
  local now; now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  local prov="${outfile%.nii.gz}.prov.json"
  {
    echo "{"
    echo "  \"step\": \"${step}\","
    echo "  \"output\": \"${outfile}\","
    echo "  \"inputs\": ${inputs},"
    echo "  \"params\": ${params},"
    echo "  \"tool_versions\": ${tools},"
    echo "  \"timestamp\": \"${now}\""
    echo "}"
  } | atomically_write "$prov"
}
