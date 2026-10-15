#!/usr/bin/env bash
# vm restore <dir>: configuration import only (C-07). Uploads <dir>/config.xml (otherwise the folder's
# single *.xml), imports it like System > Configuration > Backups (lib/guest/restore.php), reboots and
# waits for login. Installs no packages and restores no files.
#
# A snapshot made by 'vm export' (manifest.json created_by "test-vm/vm export") restores onto any
# provisioned VM: root's SSH key (authorizedkeys) and API key (apikeys) in the uploaded copy are replaced
# with this VM's, taken from its running configuration; root's password hash stays (ROOT_PASSWORD is the
# same everywhere). Any other snapshot whose root user does not carry this VM's SSH key (e.g. the
# historical test-vm/restore/2026-10-11/) replaces the credentials: the VM is then tainted (disk/tainted)
# and only 'vm destroy' may follow; login uses the snapshot's own credentials.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"

EXPORT_CREATED_BY="test-vm/vm export"

# snapshot_check <xml> <dir>: verify the SHA-256 listed in <dir>/manifest.json (if any) and print
# "export" when the manifest says 'vm export' wrote the file, otherwise "own" when root's authorized keys
# in <xml> contain this VM's public key, else "foreign"
snapshot_check() {
  python3 -I - "$1" "$2" "$SSH_KEY.pub" "$EXPORT_CREATED_BY" <<'PY'
import base64, binascii, hashlib, json, os, sys
import xml.etree.ElementTree as ET
xml, folder, pubfile, export_tag = sys.argv[1:5]
name = os.path.basename(xml)
data = open(xml, "rb").read()
man = os.path.join(folder, "manifest.json")
manifest = {}
if os.path.isfile(man):
    try:
        manifest = json.load(open(man, encoding="utf-8"))
    except ValueError:
        sys.exit("manifest.json is not valid JSON")
    if not isinstance(manifest, dict):
        manifest = {}
    files = manifest.get("files")
    entry = files.get(name, {}) if isinstance(files, dict) else {}
    want = entry.get("sha256") if isinstance(entry, dict) else None
    if want and hashlib.sha256(data).hexdigest() != want:
        sys.exit("%s does not match the SHA-256 in manifest.json" % name)
    exported = manifest.get("created_by") == export_tag
    if exported and not want:
        sys.exit("manifest.json says 'vm export' wrote %s but lists no SHA-256 for it" % name)
else:
    exported = False
try:
    root = ET.fromstring(data)
except ET.ParseError as e:
    sys.exit("%s is not well-formed XML: %s" % (name, e))
if root.tag != "opnsense":
    sys.exit("%s is not an OPNsense configuration" % name)
if exported:
    print("export")
    sys.exit(0)
ours = open(pubfile, encoding="utf-8").read().split()[1]
keys = ""
for user in root.findall("./system/user"):
    if user.findtext("name") == "root":
        raw = (user.findtext("authorizedkeys") or "").strip()
        try:
            keys = base64.b64decode(raw, validate=True).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            keys = raw
print("own" if ours in keys.split() else "foreign")
PY
}

# local_credentials <snapshot> <out> < live config.xml: write <out> = <snapshot> with root's
# <authorizedkeys> and <apikeys> elements copied byte for byte from the live configuration on stdin;
# every other byte stays. Refuses unless the live root user carries this VM's SSH key and an API key.
# The program comes from the here-document on stdin, so the live configuration is passed on fd 3.
local_credentials() {
  python3 -I - "$1" "$2" "$SSH_KEY.pub" 3<&0 <<'PY'
import base64, binascii, os, re, sys
import xml.etree.ElementTree as ET
snap_path, out_path, pubfile = sys.argv[1:4]
with os.fdopen(3, "rb") as fh:
    live = fh.read()
snap = open(snap_path, "rb").read()
FIELDS = ("authorizedkeys", "apikeys")
USER = re.compile(rb"<user(?:\s[^>]*)?>.*?</user>", re.S)

def root_block(data, what):
    found = [m for m in USER.finditer(data) if b"<name>root</name>" in m.group(0)]
    if len(found) != 1:
        sys.exit("%s: expected one root user, found %d" % (what, len(found)))
    return found[0]

def element(block, tag, what):
    t = tag.encode()
    found = list(re.finditer(rb"<" + t + rb"\s*/>|<" + t + rb">[^<]*</" + t + rb">", block))
    if len(found) != 1:
        sys.exit("%s: root user has %d <%s> elements, expected one" % (what, len(found), tag))
    return found[0]

def root_values(data, what):
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as e:
        sys.exit("%s is not well-formed XML: %s" % (what, e))
    users = [u for u in tree.findall("./system/user") if u.findtext("name") == "root"]
    if len(users) != 1:
        sys.exit("%s: expected one root user, found %d" % (what, len(users)))
    return {f: (users[0].findtext(f) or "") for f in FIELDS}

want = root_values(live, "the running configuration")
ours = open(pubfile, encoding="utf-8").read().split()[1]
try:
    keys = base64.b64decode(want["authorizedkeys"].strip(), validate=True).decode("utf-8", "replace")
except (binascii.Error, ValueError):
    keys = want["authorizedkeys"]
if ours not in keys.split():
    sys.exit("the running configuration does not hold this VM's SSH key for root")
if not want["apikeys"].strip():
    sys.exit("the running configuration holds no API key for root")

lb = root_block(live, "the running configuration")
sb = root_block(snap, os.path.basename(snap_path))
block = sb.group(0)
for tag in FIELDS:
    new = element(lb.group(0), tag, "the running configuration").group(0)
    m = element(block, tag, os.path.basename(snap_path))
    block = block[:m.start()] + new + block[m.end():]
out = snap[:sb.start()] + block + snap[sb.end():]
if root_values(out, "the adjusted copy") != want:
    sys.exit("the adjusted copy does not carry the running configuration's root credentials")
with open(out_path, "wb") as fh:
    fh.write(out)
print("unchanged" if out == snap else "replaced")
PY
}

# true when sshd in the guest answers (key accepted or refused), false when nothing answers
sshd_answers() {
  local out
  ssh_opts
  out="$(ssh "${SSH_OPTS[@]}" root@127.0.0.1 true 2>&1)" && return 0
  case "$out" in *"Permission denied"*) return 0 ;; esac
  return 1
}

# wait until sshd goes away (reboot started), then until it answers again
wait_sshd_cycle() {
  local start
  start=$(date +%s)
  log "waiting for the guest to go down (up to 600 s), then for sshd (up to 1500 s)"
  while sshd_answers; do
    [ $(($(date +%s) - start)) -ge 600 ] && die "the guest did not go down within 600s after the reboot request"
    sleep 3
  done
  start=$(date +%s)
  until sshd_answers; do
    container_running || die "container ${VM_NAME} stopped while waiting for the reboot (docker logs ${VM_NAME})"
    [ $(($(date +%s) - start)) -ge 1500 ] && die "timed out after 1500s waiting for the login (sshd) after the reboot"
    sleep 10
  done
}

RESTORE_TMP=""
restore_cleanup() { if [ -n "$RESTORE_TMP" ]; then rm -f "$RESTORE_TMP"; fi; }

cmd_restore() {
  [ $# -eq 1 ] || usage_err "usage: vm restore <dir>"
  local dir="$1" xml kind
  [ -d "$dir" ] || usage_err "not a directory: $dir"
  require_lock
  require_not_tainted
  check_no_symlinks "$VM_STATE_DIR"
  check_disk_files
  require_vm_up

  if [ -f "$dir/config.xml" ]; then
    xml="$dir/config.xml"
  else
    local found=() f
    for f in "$dir"/*.xml; do [ -f "$f" ] && found+=("$f"); done
    case "${#found[@]}" in
      0) die "$dir holds neither config.xml nor any *.xml" ;;
      1) xml="${found[0]}" ;;
      *) die "$dir holds several *.xml files and no config.xml; refusing to guess" ;;
    esac
  fi
  kind="$(snapshot_check "$xml" "$dir")" || die "refusing $xml"

  # what is uploaded: the snapshot itself, or for an export a copy carrying this VM's credentials
  local upload="$xml"
  if [ "$kind" = export ]; then
    api_ok || die "the API key in $API_ENV does not work on this VM; run 'vm provision' first (nothing imported)"
    trap restore_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    RESTORE_TMP="$(mktemp "${TMPDIR:-/tmp}/vm-restore.XXXXXX")" || die "cannot create a temporary file"
    local how
    how="$(gssh /bin/cat /conf/config.xml | local_credentials "$xml" "$RESTORE_TMP")" \
      || die "cannot put this VM's credentials into ${xml##*/} (nothing imported)"
    upload="$RESTORE_TMP"
  fi

  echo "restore: configuration import only of ${xml##*/}: no packages are installed and no files are restored"
  if [ "$kind" = export ]; then
    if [ "$how" = unchanged ]; then how="the snapshot already holds them"; else how="replaced in the uploaded copy"; fi
    echo "restore: snapshot made by 'vm export': root's SSH key and API key are this VM's, from its running configuration ($how)"
  elif [ "$kind" = foreign ]; then
    echo "restore: this snapshot carries its own credentials; after the import login uses them, not vm.env or the vm SSH key"
    echo "restore: the VM is then tainted; only 'vm destroy' may follow"
  fi

  local newhash want
  want="$(shasum -a 256 "$upload" | awk '{print $1}')"
  set_boot_marker
  gssh "/bin/sh -c 'umask 077; cat > /tmp/vm-restore.xml'" < "$upload" || die "upload failed"
  restore_cleanup; RESTORE_TMP=""
  newhash="$(guest_php restore.php /tmp/vm-restore.xml)" || die "import failed; the guest kept its configuration"
  gssh rm -f /tmp/vm-restore.xml || true
  [ "$newhash" = "$want" ] || log "note: /conf/config.xml is $newhash after the import, the file is $want"
  # from here on the guest runs the imported configuration
  if [ "$kind" = foreign ]; then : > "$TAINT_FILE"; fi

  log "rebooting the guest"
  gssh "/usr/sbin/daemon -f /bin/sh -c 'sleep 2; /usr/local/sbin/configctl system reboot'" || die "reboot request failed"
  if [ "$kind" = foreign ]; then
    wait_sshd_cycle
    log "the guest is back: sshd answers; login with the snapshot's own credentials"
    echo "restore: done; the VM is tainted, only 'vm destroy' may follow"
    return 0
  fi
  wait_reboot
  local after
  after="$(config_hash)" || die "cannot read the config hash"
  wait_noerror "(Unbound)"
  echo "config hash: $after"
  [ "$after" = "$want" ] || die "config hash after the reboot ($after) differs from the imported file ($want)"
  api_ok || die "the API key in $API_ENV does not work after the restore (api/core/backup/providers); 'vm reset' returns to the baseline"
  log "the API key in $API_ENV works"
}
