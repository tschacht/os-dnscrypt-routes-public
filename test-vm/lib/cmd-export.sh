#!/usr/bin/env bash
# vm export [--to <dir>]: read the guest's /conf/config.xml over SSH and write it with a manifest.json
# (versions, SHA-256) to test-vm/snapshots/<UTC date>/, or to <dir>. The backup API's newest backup
# (api/core/backup/download/this) is only a cross-check: 'vm restore' writes no backup, so right after a
# restore it is older than the live file. Only config.xml and manifest.json are written; a directory
# holding anything else is refused. A failed or interrupted export removes its .part files and the
# directories it created.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"

# write_manifest <out> <config.xml> <versions file>: manifest.json from the guest's KEY=VALUE versions
write_manifest() {
  python3 -I - "$@" "$VM_NAME" "$PLUGINS_COMMIT" "$(git -C "$VM_WORKTREE" rev-parse HEAD 2>/dev/null || echo unknown)" <<'PY'
import datetime, hashlib, json, os, sys
out, cfg, versions, vm_name, plugins_commit, repo_commit = sys.argv[1:7]
kv = {}
with open(versions, encoding="utf-8") as fh:
    for line in fh:
        key, sep, value = line.rstrip("\n").partition("=")
        if sep:
            kv[key] = value
with open(cfg, "rb") as fh:
    data = fh.read()
manifest = {
    "format_version": 1,
    "created_by": "test-vm/vm export",
    "exported_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "vm_name": vm_name,
    "source": {"repo_commit": repo_commit, "plugins_commit": plugins_commit},
    "versions": {
        "opnsense": kv.get("opnsense", ""),
        "kernel": kv.get("kernel", ""),
        "packages": {k[4:]: v for k, v in sorted(kv.items()) if k.startswith("pkg:") and v},
    },
    "config_hash": kv.get("config_sha256", ""),
    "files": {"config.xml": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

EXPORT_PARTS=()
EXPORT_MADE=()
# on failure or interrupt: drop the .part files, then the directories this run created (if still empty)
export_cleanup() {
  local d
  if [ "${#EXPORT_PARTS[@]}" -gt 0 ]; then rm -f -- "${EXPORT_PARTS[@]}"; fi
  if [ "${#EXPORT_MADE[@]}" -gt 0 ]; then
    for d in "${EXPORT_MADE[@]}"; do rmdir -- "$d" 2>/dev/null || break; done
  fi
}

cmd_export() {
  local dir=""
  case "$#:${1:-}" in
    0:) ;;
    2:--to) dir="$2"; [ -n "$dir" ] || usage_err "usage: vm export [--to <dir>]" ;;
    *) usage_err "usage: vm export [--to <dir>]" ;;
  esac
  require_lock
  require_not_tainted
  require_vm_up
  api_ok || die "no working API key in $API_ENV: run 'vm provision' on a VM that was never provisioned; after a configuration change that dropped the key, 'vm reset' returns to the baseline"
  [ -n "$dir" ] || dir="$VM_DIR/snapshots/$(date -u +%F)"

  # the directories mkdir -p is about to create, deepest first, so cleanup can remove them again
  local p="$dir"
  while [ ! -e "$p" ] && [ ! -L "$p" ]; do
    EXPORT_MADE+=("$p")
    [ "$p" = "$(dirname -- "$p")" ] && break
    p="$(dirname -- "$p")"
  done
  trap export_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir -p -- "$dir" || die "cannot create $dir"
  local n
  for p in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
    { [ -e "$p" ] || [ -L "$p" ]; } || continue
    n="${p##*/}"
    case "$n" in
      config.xml|manifest.json|.config.xml.part|.manifest.json.part|.versions.part) ;;
      *) die "$dir holds '$n', which export does not write; choose an empty directory" ;;
    esac
    # never write through a link planted under one of our names
    if [ -L "$p" ]; then die "'$p' is a symbolic link; refusing"; fi
  done

  local cfg="$dir/.config.xml.part" man="$dir/.manifest.json.part" ver="$dir/.versions.part" got want api_hash
  EXPORT_PARTS=("$cfg" "$man" "$ver")
  log "reading /conf/config.xml over SSH"
  gssh /bin/cat /conf/config.xml > "$cfg" || die "cannot read /conf/config.xml from the guest"
  guest_sh versions.sh > "$ver" || die "cannot read versions from the guest"
  got="$(shasum -a 256 "$cfg" | awk '{print $1}')"
  want="$(sed -n 's/^config_sha256=//p' "$ver")"
  [ "$got" = "$want" ] || die "/conf/config.xml changed while it was read ($got, then $want); run 'vm export' again"
  api_hash="$(api GET core/backup/download/this | shasum -a 256 | awk '{print $1}')" || die "backup download failed (api/core/backup/download/this)"
  if [ "$api_hash" = "$got" ]; then
    log "the backup API's newest backup matches /conf/config.xml"
  else
    log "note: the backup API's newest backup ($api_hash) is not /conf/config.xml (normal right after 'vm restore', which writes no backup); exporting /conf/config.xml"
  fi
  write_manifest "$man" "$cfg" "$ver" || die "cannot write manifest.json"
  rm -f "$ver"
  mv -f "$cfg" "$dir/config.xml"
  mv -f "$man" "$dir/manifest.json"
  trap - EXIT INT TERM
  log "exported to $dir"
  echo "config hash: $got"
  echo "snapshot   : $dir"
}
