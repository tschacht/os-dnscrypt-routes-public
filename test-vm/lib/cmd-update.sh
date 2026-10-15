#!/usr/bin/env bash
# vm update: non-interactive firmware and package update (the GUI's configctl firmware update, see
# lib/guest/firmware-update.sh), waiting through its reboot if it needs one, then 'vm deploy' again.
# The progress log is kept in disk/update.log.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"
# shellcheck source=cmd-deploy.sh
. "$VM_DIR/lib/cmd-deploy.sh"

cmd_update() {
  [ $# -eq 0 ] || usage_err "usage: vm update"
  require_lock
  require_not_tainted
  check_no_symlinks "$VM_STATE_DIR"
  check_disk_files
  require_vm_up
  local before rc=0
  before="$(gssh opnsense-version)" || die "cannot read the version"
  set_boot_marker
  log "firmware update from $before (configctl firmware update; slow under emulation, up to 30 min)"
  log "progress log: $DISK_DIR/update.log (follow with: tail -f $DISK_DIR/update.log)"
  guest_sh firmware-update.sh > "$DISK_DIR/update.log" 2>&1 || rc=$?
  tail -n 12 "$DISK_DIR/update.log" >&2
  case "$rc" in
    0) ;;
    # 255: the SSH session ended, which the reboot right after ***REBOOT*** can cause
    10|255) log "waiting for the guest to reboot into the update"; wait_reboot ;;
    *) die "firmware update failed (exit $rc); full log: $DISK_DIR/update.log" ;;
  esac
  log "firmware: $before -> $(gssh opnsense-version)"
  # shellcheck disable=SC2119  # takes no arguments
  cmd_deploy
}
