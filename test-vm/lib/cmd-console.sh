#!/usr/bin/env bash
# vm console: print the VNC address of the guest's screen (loopback only).
cmd_console() {
  [ $# -eq 0 ] || usage_err "usage: vm console"
  vm_tainted && log "warning: $TAINT_MESSAGE"
  echo "vnc://127.0.0.1:${VNC_PORT}   (macOS: open vnc://127.0.0.1:${VNC_PORT})"
}
