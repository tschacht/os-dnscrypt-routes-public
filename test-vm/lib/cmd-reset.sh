#!/usr/bin/env bash
# vm reset: revert disk/os.qcow2 to the "baseline" snapshot taken by provision and start the VM (C-07).
# The guest is powered off first (clean when SSH answers); its current state is discarded.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"

cmd_reset() {
  [ $# -eq 0 ] || usage_err "usage: vm reset"
  require_lock
  require_not_tainted
  check_no_symlinks "$VM_STATE_DIR"
  check_disk_files
  container_exists || die "no container ${VM_NAME}; run 'vm create' and 'vm provision'"
  has_baseline || die "no '$SNAPSHOT_NAME' snapshot in $DISK_DIR/os.qcow2; run 'vm provision' first"

  # shellcheck disable=SC2119  # takes no arguments
  cmd_stop
  container_running && die "the VM did not stop; disk not reverted"
  log "reverting the disk to the '$SNAPSHOT_NAME' snapshot"
  qemu_img snapshot -a "$SNAPSHOT_NAME" /d/os.qcow2 || die "qemu-img snapshot -a failed"
  log "starting the VM; waiting for SSH (up to 1500 s)"
  # shellcheck disable=SC2119
  cmd_start

  local hash want=""
  hash="$(config_hash)" || die "cannot read the config hash"
  [ -f "$BASELINE_HASH_FILE" ] && want="$(head -n 1 "$BASELINE_HASH_FILE")"
  if [ -z "$want" ]; then
    # provision stopped after taking the snapshot, before it verified the boot and recorded the hash
    log "warning: no recorded baseline hash ($BASELINE_HASH_FILE); config hash check skipped, the snapshot is unverified (re-run 'vm provision')"
  elif [ "$hash" != "$want" ]; then
    die "config hash after reset is $hash, but the baseline recorded $want"
  fi
  wait_noerror "(Unbound)"
  log "reset to the post-provision baseline"
  echo "config hash: $hash"
}
