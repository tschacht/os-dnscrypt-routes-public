#!/usr/bin/env bash
# vm provision [--logging]: turn a created VM into the reference setup (DNSCrypt on 127.0.0.1:5353 behind
# Unbound), create an API key in $VM_STATE_DIR/api.env, and take the "baseline" snapshot (C-07).
# This file also holds the helpers that reset, deploy, update, export and restore share; they source it.
#
# Every setting goes through the guest's own API or tools, never by editing config.xml:
#   packages   pkg install + scripts/firmware/register.php (lib/guest/packages.sh)
#   API key    the calls behind api/auth/user/addApiKey (lib/guest/apikey.php)
#   DNSCrypt   api/dnscryptproxy/general/set + api/dnscryptproxy/service/reconfigure
#              (body from baseline/dnscrypt-proxy.py, mapped from reference/effective-settings.json)
#   Unbound    api/unbound/settings/{searchForward,addForward,setForward,set} + api/unbound/service/reconfigure
# The baseline is a qcow2 internal snapshot inside disk/os.qcow2, taken with the guest powered off.

# shellcheck source=cmd-create.sh
. "$VM_DIR/lib/cmd-create.sh"   # qemu_img
# shellcheck source=cmd-stop.sh
. "$VM_DIR/lib/cmd-stop.sh"     # cmd_stop: clean power-off
# shellcheck source=cmd-start.sh
. "$VM_DIR/lib/cmd-start.sh"    # cmd_start: docker start + wait for SSH

GUEST_DIR="$VM_DIR/lib/guest"
API_ENV="$VM_STATE_DIR/api.env"
# both live in disk/, so destroy removes them with the disk they describe
TAINT_FILE="$DISK_DIR/tainted"
BASELINE_HASH_FILE="$DISK_DIR/baseline.sha256"
SNAPSHOT_NAME=baseline

# ---- helpers shared by the WP-06 commands ----

# shellcheck disable=SC2029  # the arguments are meant to run in the guest
gssh() { ssh_opts; ssh "${SSH_OPTS[@]}" root@127.0.0.1 "$@"; }

# guest_sh <script> [args] / guest_php <script> [args]: run lib/guest/<script> in the guest from stdin.
# The remote login shell joins the arguments, so callers pass plain tokens only.
guest_sh()  { local s="$1"; shift; gssh /bin/sh -s -- "$@" < "$GUEST_DIR/$s"; }
guest_php() { local s="$1"; shift; gssh /usr/local/bin/php -- "$@" < "$GUEST_DIR/$s"; }

require_vm_up() {
  { container_running && ssh_ready; } \
    || die "VM ${VM_NAME} is not running or not reachable over SSH; run 'vm create' (or 'vm start')"
}

require_not_tainted() {
  [ ! -e "$TAINT_FILE" ] \
    || die "the VM is tainted by a configuration import with foreign credentials ('vm restore'); only 'vm destroy' may follow"
}

# SHA-256 of the guest's /conf/config.xml ("config hash")
config_hash() { gssh /sbin/sha256 -q /conf/config.xml; }

# Reboot detection (WP06-F1): kern.boottime follows the wall clock, which moves when ntpd steps it or an
# update restarts services, so it does not identify a boot. Instead a marker file goes into /tmp, which
# every boot empties (guest /usr/local/etc/rc.subr.d/tmp clears it, then may mount a tmpfs over it;
# /var/run is not cleared on the nano image), so a reboot is complete once SSH answers and the marker is gone.
BOOT_MARKER=/tmp/vm-test-boot.marker

# set_boot_marker: call before anything that may reboot the guest
set_boot_marker() { gssh /usr/bin/touch "$BOOT_MARKER" || die "cannot write $BOOT_MARKER in the guest"; }

# prints "same" while the marker exists (no reboot yet), "rebooted" once it is gone; fails without SSH
boot_state() { gssh "/bin/sh -c 'if [ -e $BOOT_MARKER ]; then echo same; else echo rebooted; fi'" 2>/dev/null; }

# wait_reboot [timeout]: until the guest has rebooted since set_boot_marker and SSH works again
wait_reboot() {
  local timeout="${1:-1500}" start said=0
  start=$(date +%s)
  while :; do
    if ssh_ready && [ "$(boot_state || true)" = rebooted ]; then return 0; fi
    if [ "$said" -eq 0 ]; then log "waiting for the guest to reboot and answer SSH (up to ${timeout} s)"; said=1; fi
    container_running || die "container ${VM_NAME} stopped while waiting for the reboot (docker logs ${VM_NAME})"
    [ $(($(date +%s) - start)) -ge "$timeout" ] && die "timed out after ${timeout}s waiting for the guest to reboot"
    sleep 10
  done
}

# Files vm writes inside disk/; like the top-level entries, a symlink there is refused before any write (WP06-F3)
check_disk_files() {
  local f
  for f in "$TAINT_FILE" "$BASELINE_HASH_FILE" "$DISK_DIR/update.log" "$DISK_DIR/api.env.part"; do
    if [ -L "$f" ]; then die "'$f' is a symbolic link, which vm never creates; refusing"; fi
  done
}

# python3 -I evaluates a fixed expression over the JSON on stdin (bound to d); strings print raw
json_eval() {
  python3 -I -c 'import json, sys
d = json.load(sys.stdin)
r = eval(sys.argv[1])
print(r if isinstance(r, str) else json.dumps(r))' "$1"
}

# api.env: plain KEY=VALUE lines, read without evaluating them
load_api_env() {
  API_KEY=""; API_SECRET=""
  { [ -f "$API_ENV" ] && [ ! -L "$API_ENV" ]; } || return 1
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      API_KEY=*) API_KEY="${line#API_KEY=}" ;;
      API_SECRET=*) API_SECRET="${line#API_SECRET=}" ;;
    esac
  done < "$API_ENV"
  [ -n "$API_KEY" ] && [ -n "$API_SECRET" ]
}

# api <GET|POST> <path> [json body]: https://127.0.0.1:$HTTPS_PORT/api/<path> with the api.env key.
# The credentials go to curl on stdin (-K -), not argv. -k: the guest's self-signed certificate is only
# reachable through the loopback forward of this throw-away VM.
api() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-fsS -k --max-time 300 -X "$method")
  if [ "$method" = POST ]; then
    [ -n "$body" ] || body='{}'
    args+=(-H 'Content-Type: application/json' --data "$body")
  fi
  printf 'user = "%s:%s"\n' "$API_KEY" "$API_SECRET" | curl -K - "${args[@]}" "https://127.0.0.1:${HTTPS_PORT}/api/$path"
}

api_ok() { load_api_env && api GET core/backup/providers >/dev/null 2>&1; }

# api_post_expect <path> <body> <expr> <value>: POST and require json_eval <expr> == <value>
api_post_expect() {
  local out
  out="$(api POST "$1" "$2")" || die "API call $1 failed"
  [ "$(printf '%s' "$out" | json_eval "$3")" = "$4" ] || die "API call $1 returned: $out"
}

# wait_noerror <label> [drill args...]: drill <args> @127.0.0.1 example.com in the guest until NOERROR
wait_noerror() {
  local label="$1" start out said=0; shift
  start=$(date +%s)
  while :; do
    out="$(gssh /usr/bin/drill "$@" @127.0.0.1 example.com 2>&1 || true)"
    case "$out" in *"rcode: NOERROR"*) log "drill $label: NOERROR"; return 0 ;; esac
    [ $(($(date +%s) - start)) -ge 240 ] && die "drill $label did not return NOERROR within 240s: $(printf '%s' "$out" | head -n 3)"
    if [ "$said" -eq 0 ]; then log "waiting for drill $label to return NOERROR (up to 240 s)"; said=1; fi
    sleep 5
  done
}

has_baseline() {
  [ -f "$DISK_DIR/os.qcow2" ] || return 1
  # -U: read the snapshot table even while QEMU holds the image
  qemu_img snapshot -U -l /d/os.qcow2 2>/dev/null | awk -v n="$SNAPSHOT_NAME" '$2 == n { f = 1 } END { exit !f }'
}

# ---- provision ----

ensure_api_key() {
  if api_ok; then log "the API key in api.env works"; return 0; fi
  log "creating an API key for root"
  local tmp="$DISK_DIR/api.env.part"
  if ! ( umask 077; guest_php apikey.php > "$tmp" ); then
    rm -f "$tmp"; die "API key creation failed"
  fi
  mv -f "$tmp" "$API_ENV"
  api_ok || die "the new API key does not work (api/core/backup/providers)"
}

apply_dnscrypt() {
  local body
  body="$(python3 -I "$VM_DIR/baseline/dnscrypt-proxy.py" "$VM_WORKTREE/reference/effective-settings.json" "$@")" \
    || die "cannot map reference/effective-settings.json"
  log "applying the DNSCrypt base settings"
  api_post_expect dnscryptproxy/general/set "$body" 'd.get("result")' saved
  api_post_expect dnscryptproxy/service/reconfigure '{}' 'd.get("status")' ok
}

apply_unbound() {
  local logging="$1" out uuids n fwd
  fwd='{"dot":{"enabled":"1","type":"forward","domain":"","server":"127.0.0.1","port":"5353","verify":"","forward_tcp_upstream":"0","forward_first":"0"}}'
  out="$(api GET unbound/settings/searchForward)" || die "API call unbound/settings/searchForward failed"
  uuids="$(printf '%s' "$out" | json_eval '" ".join(r["uuid"] for r in d.get("rows", []) if r.get("domain", "") == "" and r.get("server") == "127.0.0.1" and str(r.get("port")) == "5353")')"
  n=0; for _ in $uuids; do n=$((n + 1)); done
  log "Unbound: forwarding all queries to 127.0.0.1:5353"
  case "$n" in
    0) api_post_expect unbound/settings/addForward "$fwd" 'd.get("result")' saved ;;
    1) api_post_expect "unbound/settings/setForward/$uuids" "$fwd" 'd.get("result")' saved ;;
    *) die "several Unbound forwards to 127.0.0.1:5353 exist ($uuids); expected at most one" ;;
  esac
  # "Use System Nameservers" off; query/reply logging follows --logging
  api_post_expect unbound/settings/set \
    "{\"unbound\":{\"forwarding\":{\"enabled\":\"0\"},\"advanced\":{\"logqueries\":\"$logging\",\"logreplies\":\"$logging\"}}}" \
    'd.get("result")' saved
  api_post_expect unbound/service/reconfigure '{}' 'd.get("status")' ok
}

# take_baseline: power off, replace the snapshot, start again. The caller records the config hash the
# snapshot boots with (WP06-F2); until then baseline.sha256 is absent and reset skips its hash check.
take_baseline() {
  log "taking the '$SNAPSHOT_NAME' snapshot: clean power-off, qemu-img snapshot, start"
  # shellcheck disable=SC2119  # takes no arguments
  cmd_stop
  container_running && die "the VM did not stop; no snapshot taken"
  rm -f "$BASELINE_HASH_FILE"
  if has_baseline; then qemu_img snapshot -d "$SNAPSHOT_NAME" /d/os.qcow2 || die "cannot delete the old snapshot"; fi
  qemu_img snapshot -c "$SNAPSHOT_NAME" /d/os.qcow2 || die "qemu-img snapshot failed"
  log "starting the VM; waiting for SSH (up to 1500 s)"
  # shellcheck disable=SC2119
  cmd_start
}

cmd_provision() {
  local logging=0
  case "$#:${1:-}" in
    0:) ;;
    1:--logging) logging=1 ;;
    *) usage_err "usage: vm provision [--logging]" ;;
  esac
  require_lock
  require_not_tainted
  check_no_symlinks "$VM_STATE_DIR"
  check_disk_files
  require_vm_up

  log "installing os-dnscrypt-proxy, rsync and git"
  guest_sh packages.sh >&2 || die "package installation failed"
  ensure_api_key
  if [ "$logging" -eq 1 ]; then apply_dnscrypt --logging; else apply_dnscrypt; fi
  # DNSCrypt first: on a fresh install it fetches its resolver lists while Unbound still resolves on its own
  wait_noerror "-p 5353 (DNSCrypt)" -p 5353
  apply_unbound "$logging"
  wait_noerror "(Unbound)"

  local before hash
  before="$(config_hash)" || die "cannot read the config hash"
  take_baseline
  wait_noerror "-p 5353 (DNSCrypt, after boot)" -p 5353
  wait_noerror "(Unbound, after boot)"
  # the hash a reset reproduces is the one the snapshot boots with (WP06-F2)
  hash="$(config_hash)" || die "cannot read the config hash"
  [ "$hash" = "$before" ] || log "note: config.xml changed during the boot after the snapshot ($before -> $hash)"
  printf '%s\n' "$hash" > "$BASELINE_HASH_FILE"
  log "provisioned$([ "$logging" -eq 1 ] && echo ' with query logging'); baseline snapshot taken"
  echo "config hash: $hash"
}
