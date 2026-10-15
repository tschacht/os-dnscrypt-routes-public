#!/usr/bin/env bash
# vm unlock [--force]   (see test-vm/README.md)

cmd_unlock() {
  local force=0
  case "${1:-}" in
    --force) force=1; shift ;;
    '') ;;
    *) usage_err "usage: vm unlock [--force]" ;;
  esac
  [ $# -eq 0 ] || usage_err "usage: vm unlock [--force]"
  { [ -e "$LOCK_DIR" ] || [ -L "$LOCK_DIR" ]; } || { log "no lock held"; return 0; }
  if [ "$force" -eq 0 ] && ! lock_is_mine; then
    echo "vm: VM lock held by another worktree: $(lock_holder_desc); use --force only if that holder is gone" >&2
    exit 3
  fi
  # same state-directory checks as destroy; only the holder file and the lock directory itself go
  require_guards
  local dir
  dir="$(safe_state_dir)" \
    || die "refusing to touch '$VM_STATE_DIR_RAW': not the default state directory and no $STATE_MARKER marker, or it is / \$HOME / the checkout or contains one (nothing removed)"
  # check everything first, delete afterwards
  check_no_symlinks "$dir"
  check_lock_dir "$dir"
  remove_lock_dir "$dir"
  log "lock released"
}
