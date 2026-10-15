#!/usr/bin/env bash
# vm status: read-only; exit 0 when the VM runs and answers SSH, otherwise 1.
# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"   # SNAPSHOT_NAME

# Whether disk/os.qcow2 holds the snapshot taken by provision. Read-only: disk/ is mounted :ro, -U reads
# the table while QEMU holds the image, and the qemu image is never pulled (unknown if absent).
baseline_state() {
  [ -f "$DISK_DIR/os.qcow2" ] || { echo "no (no disk)"; return; }
  command -v docker >/dev/null 2>&1 || { echo "unknown (docker not found)"; return; }
  docker image inspect "$QEMU_IMAGE_REF" >/dev/null 2>&1 || { echo "unknown (qemu image not pulled)"; return; }
  local out
  out="$(docker run --rm --pull never --entrypoint qemu-img -v "$DISK_DIR:/d:ro" "$QEMU_IMAGE_REF" \
         snapshot -U -l /d/os.qcow2 2>/dev/null)" || { echo "unknown (qemu-img failed)"; return; }
  if printf '%s\n' "$out" | awk -v n="$SNAPSHOT_NAME" '$2 == n { f = 1 } END { exit !f }'; then
    echo "yes (snapshot '$SNAPSHOT_NAME'; 'vm reset' returns to it)"
  else
    echo "no (run 'vm provision')"
  fi
}

cmd_status() {
  [ $# -eq 0 ] || usage_err "usage: vm status"
  echo "state dir : $VM_STATE_DIR"
  echo "lock      : $(lock_holder_desc)"
  local state="absent"
  container_exists && state="$(docker inspect -f '{{.State.Status}}' "$VM_NAME")"
  echo "container : $VM_NAME ($state)"
  if vm_tainted; then
    echo "tainted   : yes ($TAINT_MESSAGE)"
  else
    echo "tainted   : no"
  fi
  echo "baseline  : $(baseline_state)"
  echo "ports     : ssh 127.0.0.1:$SSH_PORT  https 127.0.0.1:$HTTPS_PORT  vnc 127.0.0.1:$VNC_PORT"
  if [ "$state" = running ] && ssh_ready; then
    echo "ssh       : ready"
    return 0
  fi
  echo "ssh       : not ready"
  return 1
}
