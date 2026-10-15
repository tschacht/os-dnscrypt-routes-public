#!/usr/bin/env bash
# vm test [check...]: on-device smoke tests of os-dnscrypt-routes (R-16), over SSH and the HTTPS API.
# Without check names all checks run (CHECKS below); naming some runs only those, for debugging.
# Starts from the post-provision baseline (vm reset) and installs this checkout's plugin itself (vm deploy),
# so it can be repeated; ends reset and deployed, routing not enabled (the last check). About 14 min under
# emulation. Each check runs on its own; a failed check prints FAIL with the reason and the run goes on.
# Exit 1 if any check failed.
# Guest helpers: tests/guest/{probe.py,cfgedit.php}; JSON assertions: tests/host.py.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"
# shellcheck source=cmd-reset.sh
. "$VM_DIR/lib/cmd-reset.sh"
# shellcheck source=cmd-deploy.sh
. "$VM_DIR/lib/cmd-deploy.sh"

TESTS_DIR="$VM_DIR/tests"
PRESET_JSON="$VM_WORKTREE/plugin/dns/dnscrypt-routes/src/opnsense/mvc/app/models/OPNsense/DnscryptRoutes/preset.json"
REFERENCE_JSON="$VM_WORKTREE/reference/effective-settings.json"
KIT_DIR="$VM_WORKTREE/artifacts/OPNsense/Dnscryptproxy"
PKG_NAME=os-dnscrypt-routes
PKG_FILE_GLOB='/root/plugins/dns/dnscrypt-routes/work/pkg/os-dnscrypt-routes-*.pkg'   # left by vm deploy; expanded in the guest
TPL_DIR=/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy
TESTRUN=/usr/local/opnsense/scripts/dnscrypt_routes/testrun.py
CATALOG_UNAVAILABLE="Start DNSCrypt-Proxy once so it downloads the signed resolver list."

# ---- output and assertions (every check runs in a subshell: fail ends only that check)
pass() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; exit 1; }

# keep <name> <value> / kept <name>: values shared between checks (each check is a subshell)
keep() { printf '%s\n' "$2" > "$T_DIR/$1"; }
kept() { cat "$T_DIR/$1"; }

# ---- guest and API helpers
probe()   { gssh /usr/local/bin/python3 - "$@" < "$TESTS_DIR/guest/probe.py"; }
cfgedit() { gssh /usr/local/bin/php -- "$@" < "$TESTS_DIR/guest/cfgedit.php"; }
host()    { python3 -I "$TESTS_DIR/host.py" "$@"; }
jv()      { json_eval "$1"; }
regen()   { gssh /usr/local/sbin/configctl template reload OPNsense/Dnscryptproxy >/dev/null; }
toml_hash() { probe snap | jv 'd["toml"]'; }
GET()  { api GET "dnscryptroutes/$1"; }
POST() { api POST "dnscryptroutes/$1" "${2:-}"; }
uuid_of() { GET settings/get | host uuid "$1" "$2"; }
# jset <dotted.key=value>...: a JSON request body, e.g. jset dnscryptroutes.general.enabled=1 (built in
# python: bash 3.2 brace-expands "{...,...}" inside "$(...)")
jset() {
  python3 -I -c 'import json, sys
d = {}
for arg in sys.argv[1:]:
    key, value = arg.split("=", 1)
    node = d
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
print(json.dumps(d))' "$@"
}
G=dnscryptroutes.general
R=dnscryptroutes.resolvers.resolver
status_field() { GET service/status | jv "$1"; }

# saved <label> <endpoint> <body>: C-03 success; WARN = the warning paths, one per line
saved() {
  local out
  out="$(POST "$2" "$3")"
  WARN="$(printf '%s' "$out" | host saved)" || fail "$1: $WARN"
  pass "$1: saved${WARN:+ (warnings: ${WARN//$'\n'/ })}"
}

# refused <label> <endpoint> <body> <path regex>: C-03 failure format, and config.xml, the generated TOML,
# the service PID and the live log (no restart: dnscrypt-proxy truncates it when it starts) are unchanged (F1)
refused() {
  local before out why
  before="$(probe snap)"
  out="$(POST "$2" "$3")"
  why="$(printf '%s' "$out" | host failed "$4")" || fail "$1: $why"
  why="$(probe snap | host same config,toml,pid,log "$before")" || fail "$1: a refused write changed state: $why"
  pass "$1: refused on $(printf '%s' "$out" | jv '" ".join(sorted(d["validations"]))'); nothing changed (F1)"
}

gnow() { gssh date +%s; }

# wait_live <guest epoch> <timeout s> [want]: until the startup block begun at or after <guest epoch> (gnow
# before the restart) reports live servers (want: that many); prints probe.py block
wait_live() {
  local since="$1" timeout="$2" want="${3:-}" start b
  start=$(date +%s)
  while :; do
    b="$(probe block)"
    if [ "$(printf '%s' "$b" | jv "d['since'] is not None and d['since'] >= $since and d['live'] is not None and ('$want' == '' or str(d['live']) == '$want')")" = true ]; then
      printf '%s\n' "$b"; return 0
    fi
    [ $(($(date +%s) - start)) -lt "$timeout" ] || { printf '%s\n' "$b"; return 1; }
    sleep 3
  done
}

# wait_settled <guest epoch> <timeout s> [restart output]: until the startup block begun at or after <guest
# epoch> is past the network wait (about 60 s on this VM; nothing listens on 127.0.0.1:5353 before it) and has
# either reported live servers or stopped (FATAL line or no process); prints probe.py block. A start that died
# before logging (configd answered "Error (n)", WP12-D2) also settles once, for 5 polls in a row, no new block
# appeared and nothing runs (rc onestatus fails and no dnscrypt-proxy process); the block then has died: true
wait_settled() {
  local since="$1" timeout="$2" restart="${3:-}" start b dead=0 rc
  start=$(date +%s)
  while :; do
    b="$(probe block)"
    if [ "$(printf '%s' "$b" | jv "d['since'] is not None and d['since'] >= $since and d['loaded'] and (d['live'] is not None or d['fatal'] is not None or d['pid'] is None)")" = true ]; then
      printf '%s\n' "$b"; return 0
    fi
    rc=0
    if [ "${restart#Error}" != "$restart" ] \
      && [ "$(printf '%s' "$b" | jv "d['pid'] is None and (d['since'] is None or d['since'] < $since)")" = true ]; then
      gssh "/bin/sh -c 'service dnscrypt-proxy onestatus || pgrep -x dnscrypt-proxy'" >/dev/null 2>&1 || rc=$?
    fi
    if [ "$rc" = 1 ]; then dead=$((dead + 1)); else dead=0; fi   # 1: nothing runs (255 would be ssh)
    if [ "$dead" -ge 5 ]; then
      printf '%s' "$b" | jv 'dict(d, died=True)'; return 0
    fi
    [ $(($(date +%s) - start)) -lt "$timeout" ] || { printf '%s\n' "$b"; return 1; }
    sleep 3
  done
}

# watch_start / watch_stop: count dnscrypt-proxy startups while something runs (probe.py watch, in the
# background); watch_stop then leaves {"starts": n, "pids": [...]} in $T_DIR/watch (not called in $(...):
# wait only knows children of the current shell)
WATCH_STOP=/tmp/wp11-watch.stop
watch_start() {
  local t0
  gssh rm -f "$WATCH_STOP" "$WATCH_STOP.ready"
  probe watch "$WATCH_STOP" > "$T_DIR/watch" &
  WATCH_PID=$!
  t0=$(date +%s)
  until gssh test -e "$WATCH_STOP.ready"; do
    [ $(($(date +%s) - t0)) -lt 60 ] || fail "the log watcher did not start"
    sleep 1
  done
}
watch_stop() {
  gssh touch "$WATCH_STOP"
  wait "$WATCH_PID" || fail "the log watcher failed"
}

# apply: service/reconfigure (Save & Apply, second half) must succeed
apply() {
  local out
  out="$(POST service/reconfigure)"
  [ "$(printf '%s' "$out" | jv 'd.get("status")')" = ok ] || fail "service/reconfigure: $out"
}

pkg_remove() {
  gssh "/bin/sh -c 'pkg remove -y $PKG_NAME && /usr/local/opnsense/scripts/firmware/register.php remove $PKG_NAME'" >&2
}
pkg_add() {
  gssh "/bin/sh -c 'pkg add $PKG_FILE_GLOB && /usr/local/opnsense/scripts/firmware/register.php install $PKG_NAME'" >&2
}

# manual kit (artifacts/, docs/manual-override.md): kit_install [template-only] / kit_remove
kit_install() {
  gssh "/bin/sh -c 'cat > $TPL_DIR/dnscrypt-proxy-eu.toml && chmod 644 $TPL_DIR/dnscrypt-proxy-eu.toml'" \
    < "$KIT_DIR/dnscrypt-proxy-eu.toml"
  [ "${1:-}" = template-only ] && return 0
  gssh "/bin/sh -c 'mkdir -p $TPL_DIR/+TARGETS.D && cat > $TPL_DIR/+TARGETS.D/90-eu.TARGET && chmod 600 $TPL_DIR/+TARGETS.D/90-eu.TARGET'" \
    < "$KIT_DIR/+TARGETS.D/90-eu.TARGET"
}
kit_remove() { gssh rm -f "$TPL_DIR/dnscrypt-proxy-eu.toml" "$TPL_DIR/+TARGETS.D/90-eu.TARGET"; }

# drill through Unbound with an empty cache; prints the rcode (or "none": no answer, drill exits 1 on a
# timeout, which a failed-closed Unbound sometimes gives; an ssh failure (255) still fails)
drill_fresh() {
  local out
  gssh /usr/local/sbin/unbound-control -c /var/unbound/unbound.conf flush_zone . >/dev/null
  out="$(gssh /usr/bin/drill @127.0.0.1 example.com 2>&1)" || [ $? = 1 ] || return 1
  printf '%s\n' "$out" | awk '/rcode:/ { for (i = 1; i <= NF; i++) if ($i == "rcode:") { sub(",", "", $(i+1)); print $(i+1); f = 1 } } END { if (!f) print "none" }'
}

# after_test <snap before> <log offset>: F3 isolation and the cleanup checks
after_test() {
  local why side
  why="$(probe snap | host isolated "$1")" || fail "isolation/cleanup: $why"
  side="$(probe log "$2" | jv 'd["side"]')"
  [ "$side" = "[]" ] || fail "the live log got side-instance lines: $side"
  pass "PID, 127.0.0.1:5353 owner, generated TOML and catalog cache unchanged; live log not truncated, rotated or written by the side instance; nothing on 127.0.0.1:5354, no extra dnscrypt-proxy, sandbox gone"
}

# test_wait <timeout s> [status command]: poll the test result until it is no longer running; prints it
test_wait() {
  local timeout="$1" start out
  start=$(date +%s)
  while :; do
    if [ -n "${2:-}" ]; then out="$(gssh "$2")"; else out="$(GET service/testStatus)"; fi
    [ "$(printf '%s' "$out" | jv 'd["state"]')" = running ] || { printf '%s\n' "$out"; return 0; }
    [ $(($(date +%s) - start)) -lt "$timeout" ] || { printf '%s\n' "$out"; return 1; }
    sleep 2
  done
}

C04_KEYS='["check", "duration_s", "error", "finished", "live_servers", "queries", "resolvers", "started", "state"]'

# ======================================================================== checks

c_install() {
  cmd_reset >&2
  ! gssh pkg info -e "$PKG_NAME" || fail "$PKG_NAME is installed in the baseline"
  regen
  local before why
  before="$(probe snap)"
  [ "$(printf '%s' "$before" | jv 'd["pid"] is not None')" = true ] || fail "dnscrypt-proxy is not running before the install"
  # what the stock template alone generates (no plugin installed)
  keep stock "$(printf '%s' "$before" | jv 'd["toml"]')"
  cmd_deploy >&2
  gssh pkg info -e "$PKG_NAME" || fail "$PKG_NAME is not installed after vm deploy"
  why="$(probe snap | host same pid,toml,log "$before")" || fail "installing changed the DNS service: $why"
  pass "installed $PKG_NAME: DNS service PID $(printf '%s' "$before" | jv 'd["pid"]'), generated TOML and live log unchanged (no restart)"
}

c_preset() {
  local why
  why="$(GET settings/get | host preset "$PRESET_JSON")" || fail "settings/get differs from preset.json plus the C-01 defaults: $why"
  pass "settings/get equals preset.json plus the C-01 defaults"
}

c_php() {
  local files out n=0 f
  files="$(gssh pkg info -l "$PKG_NAME" | awk '$1 ~ /\.php$/ { print $1 }')"
  [ -n "$files" ] || fail "no PHP files listed for $PKG_NAME"
  for f in $files; do n=$((n + 1)); done
  out="$(for f in $files; do echo "/usr/local/bin/php -l '$f' || exit 1"; done | gssh /bin/sh -s 2>&1)" || fail "php -l: $out"
  pass "php -l: $n PHP files, no syntax errors"
}

c_disabled() {
  regen
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "with the plugin installed and disabled the generated TOML differs from the stock output"
  [ "$(status_field 'd["override"]')" = disabled ] || fail "service/status override is not 'disabled'"
  pass "installed and disabled: generated TOML identical to the stock output; status override 'disabled'"
}

c_apply() {
  local out r b why st t0 since w
  out="$(GET catalog/get)"
  [ "$(printf '%s' "$out" | jv 'd["available"] is True and len(d["resolvers"]) > 0 and len(d["relays"]) > 0')" = true ] \
    || fail "catalog/get: no catalog"
  [ "$(GET settings/searchRelay | jv 'sorted(r["name"] for r in d["rows"])')" = '["anon-cs-de", "anon-cs-fr", "anon-scaleway", "anon-scaleway-ams"]' ] \
    || fail "settings/searchRelay rows differ from the preset"
  [ "$(GET settings/searchResolver | jv 'len(d["rows"])')" = 5 ] || fail "settings/searchResolver: expected 5 rows"
  r="$(uuid_of relay anon-cs-de)"
  [ "$(GET "settings/getRelay/$r" | jv 'd["relay"]["name"]')" = anon-cs-de ] || fail "settings/getRelay/$r"
  r="$(uuid_of resolver cs-de)"
  [ "$(GET "settings/getResolver/$r" | jv 'd["resolver"]["name"]')" = cs-de ] || fail "settings/getResolver/$r"
  [ "$(GET service/testStatus | jv "sorted(d) == $C04_KEYS and d['state'] == 'idle'")" = true ] || fail "service/testStatus is not an idle C-04 result"
  st="$(GET service/status)"
  [ "$(printf '%s' "$st" | jv '[k for k in ("running", "live_servers", "total_servers", "override", "direct_servers", "manual_override_present", "manual_template_without_mapping", "applied", "pending") if k not in d]')" = "[]" ] \
    || fail "service/status lacks C-02 keys: $st"
  [ "$(printf '%s' "$st" | jv 'd["running"] is True and d["applied"] is None and d["pending"] is True')" = true ] \
    || fail "service/status before the first apply: $st"
  pass "read endpoints (catalog/get, search/get Relay and Resolver, testStatus, service/status) answer per C-03/C-02/C-04"

  # V8: the unchanged preset saves without errors. The baseline sets the stock Server list (vm provision),
  # which gives exactly the stock-list warning; with an empty stock list there is no warning at all.
  saved "V8 enable the unchanged preset" settings/set "$(jset $G.enabled=1)"
  [ "$WARN" = dnscryptroutes.general.enabled ] || fail "V8: expected only the stock-list warning, got: ${WARN//$'\n'/ }"
  api_post_expect dnscryptproxy/general/set '{"general":{"serverlist":""}}' 'd.get("result")' saved
  saved "V8 again with an empty stock Server list" settings/set "$(jset $G.enabled=1)"
  [ -z "$WARN" ] || fail "V8: warnings with empty stock lists: ${WARN//$'\n'/ }"
  api_post_expect dnscryptproxy/general/set \
    "$(jset "general.serverlist=$(jv '",".join(d["server_names"])' < "$REFERENCE_JSON")")" 'd.get("result")' saved
  [ "$(status_field 'd["pending"]')" = true ] || fail "service/status pending is not true after a save"

  since="$(gnow)"
  watch_start
  apply
  t0=$(date +%s)
  b="$(wait_live "$since" 90 5)" || fail "no 'live servers: 5' within 90 s after the apply: $b"
  pass "Save & Apply: live servers 5 after $(($(date +%s) - t0)) s"
  watch_stop
  w="$(cat "$T_DIR/watch")"
  [ "$(printf '%s' "$w" | jv 'd["starts"]')" = 1 ] || fail "F2: $w startup blocks/service pids during the apply, expected exactly one startup"
  pass "F2: exactly one new startup block during the apply (pids $(printf '%s' "$w" | jv '" -> ".join(map(str, d["pids"]))'))"
  why="$(probe toml | host owned "$REFERENCE_JSON")" || fail "owned keys of the generated TOML: $why"
  pass "owned keys equal reference/effective-settings.json (no edns_client_subnet, ECS off); protocol filters forced"
  wait_noerror "(Unbound, after the apply)"
  pass "drill through Unbound: NOERROR"
  st="$(GET service/status)"
  [ "$(printf '%s' "$st" | jv 'd["running"] is True and d["override"] == "applied" and d["live_servers"] == 5 and d["total_servers"] == 5 and d["direct_servers"] == [] and d["pending"] is False and len(d["applied"]["hash"]) == 64')" = true ] \
    || fail "service/status after the apply: $st"
  pass "service/status: running, override applied, 5/5 live, no direct servers, nothing pending"
  saved "a save that changes nothing" settings/set "$(jset $G.enabled=1)"
  [ "$(status_field 'd["pending"]')" = false ] || fail "a save without changes turned pending true"
  pass "a save without changes keeps pending false"
}

c_vectors() {
  local m0 csde nwps dorr dnspt scw l_csde l_csfr l_scwams l_scw u doh before why
  m0="$(GET settings/get | host model)"
  csde="$(uuid_of resolver cs-de)"; nwps="$(uuid_of resolver nwps.fi)"; dorr="$(uuid_of resolver dorriere-fr)"
  dnspt="$(uuid_of resolver dnscry.pt-nuremberg-ipv4)"; scw="$(uuid_of resolver scaleway-ams)"
  l_csde="$(uuid_of relay anon-cs-de)"; l_csfr="$(uuid_of relay anon-cs-fr)"
  l_scwams="$(uuid_of relay anon-scaleway-ams)"; l_scw="$(uuid_of relay anon-scaleway)"
  [ "$(GET settings/get | jv 'd["dnscryptroutes"]["general"]["enabled"]')" = 1 ] || fail "routing is not enabled; the vectors need it"
  local P='dnscryptroutes\.resolvers\.resolver\.'

  refused "V1 cs-de via anon-cs-de (same operator)" settings/set "$(jset "$R.$csde.relays=$l_csde")" "$P$csde\.relays"
  # anon-cs-de is also anon- + cs-de (V5's rule): anon-cs-fr isolates the operator rule
  refused "V1 cs-de via anon-cs-fr (same operator, other server)" settings/set "$(jset "$R.$csde.relays=$l_csfr")" "$P$csde\.relays"
  refused "V2 enabled resolver without relays" settings/set "$(jset "$R.$dorr.relays=")" "$P$dorr\.relays"
  saved "V3 add a disabled resolver without relays" settings/addResolver \
    '{"resolver":{"enabled":"0","name":"wp11-v3","operator":"wp11","relays":""}}'
  saved "V3 cleanup" "settings/delResolver/$(uuid_of resolver wp11-v3)" ''
  refused "V4 empty operator" settings/set "$(jset "$R.$dorr.operator=")" "$P$dorr\.operator"
  saved "V5 setup: relay anon-nwps.fi (operator b)" settings/addRelay '{"relay":{"name":"anon-nwps.fi","operator":"b"}}'
  u="$(uuid_of relay anon-nwps.fi)"
  refused "V5 nwps.fi (operator a) via anon-nwps.fi" settings/set "$(jset "$R.$nwps.operator=a" "$R.$nwps.relays=$u")" "$P$nwps\.relays"
  saved "V5 cleanup" "settings/delRelay/$u" ''
  saved "V6 a single relay" settings/set "$(jset "$R.$dnspt.relays=$l_csde")"
  printf '%s\n' "$WARN" | awk -v p="dnscryptroutes.resolvers.resolver.$dnspt.relays" '$0 == p { f = 1 } END { exit !f }' \
    || fail "V6: no single-relay warning"
  saved "V6 cleanup" settings/set "$(jset "$R.$dnspt.relays=$l_csde,$l_scwams")"
  saved "V7 ECS on, 203.0.113.0/24" settings/set "$(jset $G.ecsEnabled=1 $G.ecsSubnet=203.0.113.0/24)"
  printf '%s\n' "$WARN" | awk '$0 == "dnscryptroutes.general.ecsSubnet" { f = 1 } END { exit !f }' || fail "V7: no ECS warning"
  saved "V7 ECS on, 146.70.82.0/24" settings/set "$(jset $G.ecsEnabled=1 $G.ecsSubnet=146.70.82.0/24)"
  ! printf '%s\n' "$WARN" | awk '$0 == "dnscryptroutes.general.ecsSubnet" { f = 1 } END { exit !f }' || fail "V7: ECS warning for the preset subnet"
  saved "V7 cleanup" settings/set "$(jset $G.ecsEnabled=0)"
  refused "V9 no enabled resolver" settings/set \
    "$(jset "$R.$csde.enabled=0" "$R.$nwps.enabled=0" "$R.$dorr.enabled=0" "$R.$dnspt.enabled=0" "$R.$scw.enabled=0")" \
    'dnscryptroutes\.general\.enabled'
  doh="$(GET catalog/get | jv 'sorted(r["name"] for r in d["resolvers"] if r["proto"] == "doh")[0]')"
  refused "V10 enabled resolver $doh (DoH in the catalog)" settings/addResolver \
    "$(jset resolver.enabled=1 "resolver.name=$doh" resolver.operator=wp11 "resolver.relays=$l_csde,$l_scwams")" "${P}[^.]+\.name"

  # V11 and V16 need the catalog unavailable: move the cached resolver list aside (put back on any exit)
  trap 'gssh "/bin/sh -c \"[ -f /root/wp11-pr.md ] && mv /root/wp11-pr.md /usr/local/etc/dnscrypt-proxy/public-resolvers.md; true\""' EXIT
  gssh mv /usr/local/etc/dnscrypt-proxy/public-resolvers.md /root/wp11-pr.md
  [ "$(GET catalog/get | jv 'd["available"]')" = false ] || fail "catalog/get still available"
  saved "V16 routing enabled, catalog unavailable: enabled = 0" settings/set "$(jset $G.enabled=0)"
  local out
  out="$(POST settings/set "$(jset $G.enabled=1)")"
  [ "$(printf '%s' "$out" | jv 'd["validations"].get("dnscryptroutes.general.enabled")')" = "$CATALOG_UNAVAILABLE" ] \
    || fail "V11: $out"
  refused "V11 enabling while the catalog is unavailable" settings/set "$(jset $G.enabled=1)" 'dnscryptroutes\.general\.enabled'
  gssh mv /root/wp11-pr.md /usr/local/etc/dnscrypt-proxy/public-resolvers.md
  trap - EXIT
  saved "V11/V16 cleanup: enable again" settings/set "$(jset $G.enabled=1)"

  # V12: a stock static server named like an enabled resolver (stock Server model, api/dnscryptproxy/server)
  api_post_expect dnscryptproxy/server/addServer \
    '{"server":{"enabled":"1","name":"cs-de","stamp":"sdns://wp11-not-used"}}' \
    'd.get("result")' saved
  u="$(api GET dnscryptproxy/server/searchServer | jv '[r["uuid"] for r in d["rows"] if r["name"] == "cs-de"][0]')"
  refused "V12 stock static server cs-de" settings/set "$(jset $G.enabled=1)" "$P$csde\.name"
  api_post_expect "dnscryptproxy/server/delServer/$u" '' 'd.get("result")' deleted

  refused "V13 delete the referenced relay anon-cs-de" "settings/delRelay/$l_csde" '' "dnscryptroutes\.relays\.relay\.$l_csde\.name"
  [ "$(POST "settings/delRelay/$l_csde" | jv 'sorted(d)')" = '["result", "validations"]' ] || fail "V13: extra keys in the refusal"
  for u in "$nwps" "$dorr" "$dnspt" "$scw"; do
    saved "V14 setup: disable one resolver" "settings/setResolver/$u" '{"resolver":{"enabled":"0"}}'
  done
  refused "V14 disable the last enabled resolver (setResolver)" "settings/setResolver/$csde" '{"resolver":{"enabled":"0"}}' 'dnscryptroutes\.general\.enabled'
  refused "V14 delete the last enabled resolver (delResolver)" "settings/delResolver/$csde" '' 'dnscryptroutes\.general\.enabled'
  for u in "$nwps" "$dorr" "$dnspt" "$scw"; do
    saved "V14 cleanup: enable again" "settings/setResolver/$u" '{"resolver":{"enabled":"1"}}'
  done
  saved "V15 skipIncompatible off" settings/set "$(jset $G.skipIncompatible=0)"
  printf '%s\n' "$WARN" | awk '$0 == "dnscryptroutes.general.skipIncompatible" { f = 1 } END { exit !f }' || fail "V15: no warning"
  saved "V15 cleanup" settings/set "$(jset $G.skipIncompatible=1)"

  # V17: a broken route while enabled can only come from a hand edit (the API refuses it)
  cfgedit relays cs-de anon-cs-de >/dev/null
  saved "V17 enabled with a broken route (hand edit): enabled = 0" settings/set "$(jset $G.enabled=0)"
  refused "V17 enabling again with the broken route" settings/set "$(jset $G.enabled=1)" "$P$csde\.relays"
  saved "V17 route fixed, enable again" settings/set \
    "$(jset $G.enabled=1 "$R.$csde.relays=$l_scwams,$l_scw")"

  [ "$(GET settings/get | host model)" = "$m0" ] || fail "the settings after the vectors differ from before"
  before="$(probe snap)"
  refused "F1 Save & Apply with an invalid payload (settings/set refuses, so no reconfigure)" settings/set \
    "$(jset "$R.$scw.relays=$l_scwams")" "$P$scw\.relays"
  why="$(probe snap | host same pid,log "$before")" || fail "F1: $why"
  pass "vectors done; settings as before"
}

c_savetest() {
  local before off out res st1 why t0 s seen=0
  saved "Save & Test, first half: settings/set" settings/set "$(jset $G.enabled=1)"
  before="$(probe snap)"; off="$(printf '%s' "$before" | jv 'd["log"]["size"]')"
  out="$(POST service/testStart)"
  [ "$(printf '%s' "$out" | jv 'd == {"started": True, "reason": None}')" = true ] || fail "service/testStart: $out"
  st1="$(GET service/testStatus)"
  out="$(POST service/testStart)"
  [ "$(printf '%s' "$out" | jv 'd == {"started": False, "reason": "already-running"}')" = true ] || fail "F6: second testStart: $out"
  [ "$(GET service/testStatus)" = "$st1" ] || fail "F6: the refused start changed the running test's result"
  pass "F6: a second start while running: started false, reason already-running; the running result untouched"
  t0=$(date +%s)
  while [ "$(GET service/testStatus | jv 'd["state"]')" = running ]; do
    s="$(probe snap)"
    why="$(printf '%s' "$s" | host same pid,toml,l5353,catalog,log "$before")" || fail "F3 during the test: $why"
    [ "$(printf '%s' "$s" | jv 'len(d["side"]) > 0')" = true ] && seen=1
    [ $(($(date +%s) - t0)) -lt 150 ] || fail "the test still runs after 150 s"
  done
  [ "$seen" = 1 ] || fail "the side instance was never seen running"
  pass "F3 during the test (side instance seen running): PID, 127.0.0.1:5353 owner, TOML, catalog cache, live log unchanged"
  res="$(GET service/testStatus)"
  [ "$(printf '%s' "$res" | jv "sorted(d) == $C04_KEYS")" = true ] || fail "not a C-04 result: $res"
  [ "$(printf '%s' "$res" | jv 'd["state"]')" = "done" ] || fail "Save & Test did not finish as done: $res"
  pass "Save & Test: C-04 result, state done in $(printf '%s' "$res" | jv 'd["duration_s"]') s, $(printf '%s' "$res" | jv 'sum(1 for r in d["resolvers"] if r["pass"])')/$(printf '%s' "$res" | jv 'len(d["resolvers"])') resolvers pass, queries $(printf '%s' "$res" | jv '" ".join(q["rcode"] for q in d["queries"])')"
  after_test "$before" "$off"
}

c_killed() {
  local before off out t0 pid res
  before="$(probe snap)"; off="$(printf '%s' "$before" | jv 'd["log"]["size"]')"
  out="$(POST service/testStart)"
  [ "$(printf '%s' "$out" | jv 'd["started"]')" = true ] || fail "service/testStart: $out"
  t0=$(date +%s)
  until pid="$(probe snap | jv '" ".join(map(str, d["side"]))')" && [ -n "$pid" ]; do
    [ $(($(date +%s) - t0)) -lt 90 ] || fail "the side instance never started"
    sleep 1
  done
  gssh kill -9 "$pid"
  res="$(test_wait 60)" || fail "the killed test still runs after 60 s"
  [ "$(printf '%s' "$res" | jv 'd["state"]')" = failed ] || fail "F4: killed side instance gave $res"
  pass "F4: side instance (pid $pid) killed mid-run: result failed, error $(printf '%s' "$res" | jv 'd["error"]')"
  after_test "$before" "$off"
}

c_timeout() {
  local before off out res t0 wall
  before="$(probe snap)"; off="$(printf '%s' "$before" | jv 'd["log"]["size"]')"
  t0=$(date +%s)
  out="$(gssh env DNSCRYPT_ROUTES_TEST_DEADLINE=5 /usr/local/bin/python3 "$TESTRUN" start)"
  [ "$(printf '%s' "$out" | jv 'd["started"]')" = true ] || fail "testrun.py start: $out"
  res="$(test_wait 40 "/usr/local/bin/python3 $TESTRUN status")" || fail "F5: still running 40 s after a 5 s deadline"
  wall=$(($(date +%s) - t0))
  [ "$(printf '%s' "$res" | jv 'd["state"] == "failed" and d["error"] == "timeout"')" = true ] || fail "F5: $res"
  [ "$(printf '%s' "$res" | jv 'd["duration_s"] <= 5 + 10')" = true ] || fail "F5: ran $(printf '%s' "$res" | jv 'd["duration_s"]') s, deadline 5 s + 10 s grace"
  pass "F5: deadline 5 s: failed/timeout after $(printf '%s' "$res" | jv 'd["duration_s"]') s (worker), $wall s seen from the host"
  after_test "$before" "$off"
}

c_failclosed() {
  local before out b rc since why restart
  trap 'cfgedit relays dorriere-fr anon-cs-de,anon-scaleway-ams >/dev/null' EXIT   # the preset route, also on failure
  cfgedit relays dorriere-fr - >/dev/null
  before="$(probe snap)"
  out="$(POST service/reconfigure)"
  [ "$(printf '%s' "$out" | jv 'd.get("status") == "failed" and len(d.get("validations", {})) > 0')" = true ] \
    || fail "service/reconfigure accepted a saved config that breaks the invariant: $out"
  why="$(probe snap | host same toml,pid,log "$before")" || fail "F1: a refused reconfigure changed state: $why"
  pass "F1: Save & Apply of an invalid saved config (hand edit): reconfigure refuses, no restart, TOML unchanged"
  # what a reconfigure does without the API check: stock template reload and restart through configd
  since="$(gnow)"
  regen
  restart="$(gssh /usr/local/sbin/configctl dnscryptproxy restart)"
  b="$(probe toml)"
  [ "$(printf '%s' "$b" | jv 'd["first_line"] == "# dnscrypt-routes: invariant-violated" and d["server_names"] == ["dnscrypt-routes-invalid-config"] and not d["routes"]')" = true ] \
    || fail "generated TOML is not failed closed: $b"
  pass "generated TOML: invariant-violated marker, server_names = ['dnscrypt-routes-invalid-config'], no routes"
  [ "$(status_field 'd["override"]')" = invariant-violated ] || fail "service/status override is not invariant-violated"
  # drill only once dnscrypt-proxy is past its network wait: before that Unbound fails with any config
  b="$(wait_settled "$since" 150 "$restart")" || fail "dnscrypt-proxy did not get past its network wait: $b"
  if [ "$(printf '%s' "$b" | jv 'd.get("died", False)')" = true ]; then
    pass "dnscrypt-proxy refused to serve: its start failed before it logged (configd: $restart), nothing runs"
  else
    [ "$(printf '%s' "$b" | jv 'd["live"] is None and (d["fatal"] is not None or d["pid"] is None)')" = true ] \
      || fail "dnscrypt-proxy serves with the failed-closed config: $b"
    pass "dnscrypt-proxy loaded its sources and refused to serve: $(printf '%s' "$b" | jv 'd["fatal"] or "process gone"')"
  fi
  rc="$(drill_fresh)"
  case "$rc" in NOERROR|NXDOMAIN) fail "drill through Unbound still resolves: $rc" ;; esac
  pass "drill through Unbound fails ($rc) instead of resolving"
  cfgedit relays dorriere-fr anon-cs-de,anon-scaleway-ams >/dev/null
  since="$(gnow)"
  apply
  wait_live "$since" 120 5 >/dev/null || fail "no 'live servers: 5' after restoring the route"
  wait_noerror "(Unbound, route restored)"
  pass "route restored and applied: 5 live, NOERROR"
}

c_uninstall() {
  local files left
  saved "disable" settings/set "$(jset $G.enabled=0)"
  apply
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "disabled and applied: generated TOML differs from the stock output"
  pass "disable and apply: stock output again"
  files="$(gssh pkg info -l "$PKG_NAME" | awk 'NR > 1 { print $1 }')"
  pkg_remove
  ! gssh pkg info -e "$PKG_NAME" || fail "$PKG_NAME still installed"
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "uninstalled: generated TOML differs from the stock output"
  regen
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "uninstalled and regenerated: generated TOML differs from the stock output"
  left="$(for f in $files; do echo "[ ! -e '$f' ] || echo '$f'"; done | gssh /bin/sh -s)"
  [ -z "$left" ] || fail "package files left after uninstall: $left"
  left="$(probe leftovers)"
  [ "$left" = "[]" ] || fail "plugin files left outside /var/db and /var/run: $left"
  pass "uninstall: stock output (also after regenerating), no plugin files left outside /var/db and /var/run"
}

c_coexist() {
  local manual b st
  gssh pkg info -e "$PKG_NAME" && pkg_remove
  kit_install
  regen
  manual="$(toml_hash)"
  b="$(probe toml)"
  [ "$manual" != "$(kept stock)" ] && [ "$(printf '%s' "$b" | jv 'd["edns_client_subnet"] == ["146.70.82.0/24"] and len(d["server_names"]) == 5 and not d["first_line"].startswith("# dnscrypt-routes")')" = true ] \
    || fail "the manual kit does not generate its own output: $b"
  pass "manual kit, no plugin: manual output"
  pkg_add
  [ "$(toml_hash)" = "$manual" ] || fail "installing the plugin changed the generated TOML"
  regen
  [ "$(toml_hash)" = "$manual" ] || fail "plugin installed and disabled: regenerated TOML is not the manual output"
  pass "install the plugin: generated TOML unchanged (manual output, also after regenerating)"
  saved "enable" settings/set "$(jset $G.enabled=1)"
  apply
  # earlier checks rewrote routes (vectors, failclosed), which may change each route's relay order: compare via as sets
  why="$(probe toml | host owned "$REFERENCE_JSON" any-via-order)" || fail "enabled with the manual kit: not plugin routing: $why"
  st="$(GET service/status)"
  [ "$(printf '%s' "$st" | jv 'd["manual_override_present"] is True and d["override"] == "applied" and d["manual_template_without_mapping"] is False')" = true ] \
    || fail "service/status with the shadowed manual override: $st"
  pass "enable and apply: plugin routing; the shadowed notice applies (manual_override_present with routing on)"
  saved "disable" settings/set "$(jset $G.enabled=0)"
  apply
  [ "$(toml_hash)" = "$manual" ] || fail "disabled and applied: not the manual output"
  pass "disable and apply: manual output again"
  pkg_remove
  regen
  [ "$(toml_hash)" = "$manual" ] || fail "uninstalled: not the manual output"
  pass "uninstall: manual output"
  kit_remove
  regen
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "manual kit removed: not the stock output"
  pass "remove the manual kit and regenerate: stock output"
  kit_install template-only
  pkg_add
  regen
  [ "$(toml_hash)" = "$(kept stock)" ] || fail "orphan manual template, plugin disabled: not the stock output"
  st="$(GET service/status)"
  [ "$(printf '%s' "$st" | jv 'd["manual_template_without_mapping"] is True and d["manual_override_present"] is False')" = true ] \
    || fail "service/status with an orphan manual template: $st"
  kit_remove
  regen
  pass "manual template without 90-eu.TARGET, plugin disabled: stock output, manual_template_without_mapping true"
}

# End state of a full run: vm reset and vm deploy, routing not enabled
c_end() {
  cmd_reset >&2
  cmd_deploy >&2
  gssh pkg info -e "$PKG_NAME" || fail "$PKG_NAME is not installed after vm deploy"
  [ "$(status_field 'd["override"]')" = disabled ] || fail "service/status override is not 'disabled'"
  pass "vm reset, vm deploy: $PKG_NAME installed, routing not enabled"
}

# ======================================================================== runner

T_FAILED=0
T_RESULTS=()
run_check() {
  local rc
  echo "== $1"
  set +e
  # errexit inside the check; the ERR message only at the check's own level, not in $(...) below it
  ( set -eE; T_LEVEL=$BASH_SUBSHELL
    trap '[ "$BASH_SUBSHELL" != "$T_LEVEL" ] || echo "  FAIL unexpected exit status $? from: $BASH_COMMAND"' ERR
    "$2" ) < /dev/null
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then T_RESULTS+=("ok   $1"); else T_RESULTS+=("FAIL $1"); T_FAILED=$((T_FAILED + 1)); fi
}

# name|title, in run order. Every check after "install" relies on the state the earlier ones leave.
CHECKS="install|install: vm reset, then installing the package keeps the DNS service PID
preset|seeded preset after a fresh install
php|php -l on every plugin PHP file
disabled|disabled: stock output
apply|apply the preset via the API: exactly one restart, 5 live servers
vectors|validation vectors V1-V17: refused saves change nothing
savetest|Save & Test isolation and concurrent start
killed|Save & Test side instance killed
timeout|Save & Test timeout
failclosed|fail closed
uninstall|without the manual kit: disable, uninstall
coexist|manual override coexistence
end|end state: vm reset, vm deploy"

cmd_test() {
  local only="" a name title t0
  for a in "$@"; do
    case "$a" in
      -*) usage_err "usage: vm test [check...]" ;;
      *) case " $(printf '%s\n' "$CHECKS" | cut -d'|' -f1 | tr '\n' ' ')" in
           *" $a "*) only="$only $a " ;;
           *) usage_err "unknown check '$a'; checks: $(printf '%s\n' "$CHECKS" | cut -d'|' -f1 | tr '\n' ' ')" ;;
         esac ;;
    esac
  done
  require_lock
  require_not_tainted
  check_no_symlinks "$VM_STATE_DIR"
  check_disk_files
  require_vm_up
  has_baseline || die "no '$SNAPSHOT_NAME' snapshot; run 'vm provision' first"
  api_ok || die "the API key in $API_ENV does not work; run 'vm provision' first"
  T_DIR="$(mktemp -d "${TMPDIR:-/tmp}/vm-test.XXXXXX")"
  trap 'rm -rf "$T_DIR"' EXIT
  t0=$(date +%s)
  while IFS='|' read -r name title; do
    [ -z "$only" ] || case "$only" in *" $name "*) ;; *) continue ;; esac
    run_check "$title" "c_$name"
  done <<< "$CHECKS"

  echo "== summary ($(( ($(date +%s) - t0) / 60 )) min)"
  printf '%s\n' "${T_RESULTS[@]}"
  [ "$T_FAILED" -eq 0 ] || { echo "vm test: $T_FAILED check(s) failed"; return 1; }
  echo "vm test: all checks passed"
}
