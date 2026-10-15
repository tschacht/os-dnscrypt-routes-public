#!/usr/bin/env bash
# vm destroy [--all [--yes]]

remove_container() {
  compose down -v --remove-orphans >&2 2>/dev/null || true
  docker rm -fv "$VM_NAME" >/dev/null 2>&1 || true
}

cmd_destroy() {
  local all=0 yes=0 a
  for a in "$@"; do
    case "$a" in
      --all) all=1 ;;
      --yes) yes=1 ;;
      *) usage_err "usage: vm destroy [--all [--yes]]" ;;
    esac
  done
  [ "$yes" -eq 1 ] && [ "$all" -eq 0 ] && usage_err "--yes only applies to --all"
  require_lock

  require_guards
  local dir foreign e
  dir="$(safe_state_dir)" \
    || die "refusing to touch '$VM_STATE_DIR_RAW': not the default state directory and no $STATE_MARKER marker, or it is / \$HOME / the checkout or contains one (nothing removed)"
  # check everything first, delete afterwards
  check_no_symlinks "$dir"
  check_lock_dir "$dir"
  if [ "$all" -eq 1 ]; then
    foreign="$(foreign_entries "$dir")" || die "cannot list '$dir' (nothing removed)"
    if [ -n "$foreign" ]; then
      die "'$dir' holds entries that vm did not create, so it is not removed (nothing removed): $(printf '%s' "$foreign" | tr '\n' ' ')"
    fi
    if [ -e "$dir/golden.qcow2" ] && [ "$yes" -eq 0 ]; then
      die "golden.qcow2 exists and must be rebuilt by hand if removed; rerun with --yes to confirm (nothing removed)"
    fi
  fi

  remove_container
  rm -rf -- "$dir/disk"

  if [ "$all" -eq 1 ]; then
    # only the entries vm creates, by name and in list order (marker, then lock last), never following a
    # link (checked above); then rmdir, so anything that appeared meanwhile stays
    for e in $STATE_ENTRIES; do
      case "$e" in
        disk) ;;
        lock) remove_lock_dir "$dir" ;;
        *) rm -rf -- "${dir:?}/$e" ;;
      esac
    done
    rmdir -- "$dir" 2>/dev/null || die "'$dir' is not empty after removing the generated entries; left in place"
    log "destroyed everything, including $dir and the lock"
  else
    log "destroyed container and disk/ (kept images/, golden.qcow2, keys, api.env, lock/)"
  fi
}
