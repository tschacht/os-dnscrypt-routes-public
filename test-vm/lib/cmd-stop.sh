#!/usr/bin/env bash
# vm stop: clean guest power-off, then the container exits with QEMU.
# docker stop alone is not clean: the image sends ACPI but kills QEMU after a few seconds, long
# before an emulated guest has shut down. So power off over SSH first and wait; docker stop is the
# fallback when SSH is not available or the guest does not go down in time.
cmd_stop() {
  [ $# -eq 0 ] || usage_err "usage: vm stop"
  require_lock
  container_running || { log "VM ${VM_NAME} is not running"; return 0; }
  local waited=0
  if ssh_ready; then
    log "powering off the guest"
    ssh_opts
    ssh "${SSH_OPTS[@]}" root@127.0.0.1 '/sbin/shutdown -p now' >/dev/null 2>&1 || true
    while container_running && [ "$waited" -lt 300 ]; do
      sleep 5; waited=$((waited + 5))
    done
  fi
  if container_running; then
    log "guest did not power off; stopping the container"
    docker stop -t 60 "$VM_NAME" >/dev/null
  fi
  log "VM ${VM_NAME} stopped"
}
