#!/usr/bin/env bash
# vm lock <ID> | vm unlock [--force]   (see test-vm/README.md)

cmd_lock() {
  [ $# -eq 1 ] || usage_err "usage: vm lock <ID>"
  local id="$1"
  case "$id" in *[!A-Za-z0-9._-]*|'') usage_err "invalid lock id '$id'" ;; esac
  ensure_state_dir
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    {
      echo "packet=$id"
      echo "agent=${VM_AGENT:-${USER:-unknown}@$(hostname -s)}"
      echo "worktree=$VM_WORKTREE"
      echo "time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$LOCK_DIR/holder"
    log "lock taken for $id"
    return 0
  fi
  if lock_is_mine && [ "$(lock_field packet)" = "$id" ]; then
    log "lock already held by $id from this worktree"
    return 0
  fi
  echo "vm: VM lock is held: $(lock_holder_desc)" >&2
  exit 3
}
