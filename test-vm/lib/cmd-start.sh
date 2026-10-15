#!/usr/bin/env bash
# vm start: start the existing container and wait for SSH.
cmd_start() {
  [ $# -eq 0 ] || usage_err "usage: vm start"
  die_if_tainted
  require_lock
  container_exists || die "no container ${VM_NAME}; run 'vm create'"
  container_running || docker start "$VM_NAME" >/dev/null
  wait_ssh 1500
  log "VM ${VM_NAME} is up"
}
