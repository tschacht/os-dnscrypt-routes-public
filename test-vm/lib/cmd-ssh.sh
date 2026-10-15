#!/usr/bin/env bash
# vm ssh [cmd...]: key-only SSH to the VM as root (loopback forward).
cmd_ssh() {
  require_lock
  vm_tainted && log "warning: $TAINT_MESSAGE"
  [ -f "$SSH_KEY" ] || die "no SSH key at $SSH_KEY; run 'vm create'"
  if [ $# -eq 0 ]; then
    ssh_opts interactive
    exec ssh "${SSH_OPTS[@]}" root@127.0.0.1
  fi
  ssh_opts
  exec ssh "${SSH_OPTS[@]}" root@127.0.0.1 "$@"
}
