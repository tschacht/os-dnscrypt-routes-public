# Manual override

## What it is

A pair of files that make the stock `os-dnscrypt-proxy` plugin generate a fixed European resolver pool
with anonymized routes, using the documented template target-overwrite mechanism.[1] The UI is unchanged.

- Pool: `scaleway-ams`, `cs-de`, `nwps.fi`, `dorriere-fr`, `dnscry.pt-nuremberg-ipv4`; strategy `wp2`;
  synthetic ECS prefix `146.70.82.0/24`; per-resolver anonymized routes that avoid the resolver's own operator.
- Exported from plugin `1.17`, dnscrypt-proxy `2.1.15` (`dnscrypt-proxy2 2.1.15_8`) on OPNsense `26.7.6_3`.
  A newer plugin is not proof that the copied template still fits; see "After an OPNsense or plugin upgrade".

Resolver list, `wp2`, ECS and routes belong to the override; the UI's resolver and relay choices no longer
apply. Everything else follows the saved UI settings, and only while the plugin is **Enabled**.

## Files and destinations

| In this repository | Installed on the router (mode) |
|---|---|
| `artifacts/OPNsense/Dnscryptproxy/dnscrypt-proxy-eu.toml` | `/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy/dnscrypt-proxy-eu.toml` (`0644 root:wheel`) |
| `artifacts/OPNsense/Dnscryptproxy/+TARGETS.D/90-eu.TARGET` | `/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy/+TARGETS.D/90-eu.TARGET` (`0600 root:wheel`) |

The mapping redirects the runtime TOML (`/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml`) to the custom
template. SHA-256 values are in `reference/manifest.json`. `reference/` files are comparison baselines, not
installation payloads or OPNsense import files. The custom template contains upstream-derived code; no
blanket license is asserted for it.

## Install

Keep the router out of the live client DNS path until "Verify" passes. If versions, paths or model fields
differ from the exported baseline, stop and adapt instead of copying blindly. The snippets are POSIX
`/bin/sh`: type `/bin/sh` first and run them from there (OPNsense's root shell may be csh, which rejects multi-line quotes and `$(...)`).

1. Install `os-dnscrypt-proxy` (System > Firmware > Plugins) and configure it in Services > DNSCrypt-Proxy.
   Compare the generated TOML with `reference/effective-settings.json`, not UI labels. Keep the service
   disabled while preparing, and check no other `.TARGET` file maps `dnscrypt-proxy.toml`.
2. Upload (verify the SSH host key; the target must not exist) with
   `scp -r artifacts/OPNsense/Dnscryptproxy root@ROUTER:/root/dnscrypt-override-upload`.
   On the router, compare `sha256` of the two files against `reference/manifest.json`.
3. Back up before installing (fresh-install form: it refuses to run if an override already exists). Also take
   a protected OPNsense configuration backup; it may hold credentials and never belongs in Git.

   ```sh
   /bin/sh -c '
   set -eu
   umask 077
   T=/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy
   B=/root/dnscrypt-override-before-install-01
   test -d "$T" || { echo "template directory missing" >&2; exit 1; }
   test ! -e "$T/dnscrypt-proxy-eu.toml" -a ! -e "$T/+TARGETS.D/90-eu.TARGET" || { echo "override already installed; use the upgrade replace snippet" >&2; exit 1; }
   test ! -e "$B" || { echo "backup directory exists" >&2; exit 1; }
   mkdir -m 700 "$B"
   cp -p "$T/dnscrypt-proxy.toml" "$B/stock-template.toml"
   cp -p "$T/+TARGETS" "$B/stock-targets.txt"
   if test -f /usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml; then
     cp -p /usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml "$B/runtime.toml"
   fi
   '
   ```

4. Install only the two custom files. Renames are atomic per file, not across both; on failure, stop and
   assess the partial state. Never replace the stock template, `+TARGETS`, plugin models or generation code.

   ```sh
   /bin/sh -c '
   set -eu
   T=/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy
   U=/root/dnscrypt-override-upload
   cd "$T"
   test ! -e dnscrypt-proxy-eu.toml -a ! -e +TARGETS.D/90-eu.TARGET || { echo "override already installed" >&2; exit 1; }
   test ! -e .dnscrypt-proxy-eu.toml.restore-pending -a ! -e +TARGETS.D/.90-eu.TARGET.restore-pending || { echo "restore-pending file exists" >&2; exit 1; }
   install -d -m 755 +TARGETS.D
   install -o root -g wheel -m 644 "$U/dnscrypt-proxy-eu.toml" .dnscrypt-proxy-eu.toml.restore-pending
   install -o root -g wheel -m 600 "$U/+TARGETS.D/90-eu.TARGET" +TARGETS.D/.90-eu.TARGET.restore-pending
   mv .dnscrypt-proxy-eu.toml.restore-pending dnscrypt-proxy-eu.toml
   mv +TARGETS.D/.90-eu.TARGET.restore-pending +TARGETS.D/90-eu.TARGET
   '
   ```

5. Save the plugin settings with **Enabled** selected. Saving or applying in the UI may regenerate files
   and restart the service, so keep clients off this router (save without Apply if supported). Regenerate with
   `configctl template reload OPNsense/Dnscryptproxy`.
   This rewrites all five stock-mapped outputs. If the runtime TOML is empty or wrong, check the Enabled
   flag, competing mappings and version compatibility; never copy another router's TOML over it.

## Verify

Assert the override-owned values in the generated runtime (Python 3 with `tomllib` on the router):

```sh
python3 -B -c '
import tomllib
c = tomllib.load(open("/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml", "rb"))
assert c["server_names"] == ["scaleway-ams", "cs-de", "nwps.fi", "dorriere-fr", "dnscry.pt-nuremberg-ipv4"]
assert c["lb_strategy"] == "wp2"
assert c["edns_client_subnet"] == ["146.70.82.0/24"]
a = c["anonymized_dns"]
assert len(a["routes"]) == 5
assert a["skip_incompatible"] is True and a["direct_cert_fallback"] is True
assert {r["server_name"]: r["via"] for r in a["routes"]} == {
 "scaleway-ams": ["anon-cs-de", "anon-cs-fr"],
 "cs-de": ["anon-scaleway-ams", "anon-scaleway"],
 "nwps.fi": ["anon-cs-de", "anon-scaleway-ams"],
 "dorriere-fr": ["anon-cs-de", "anon-scaleway-ams"],
 "dnscry.pt-nuremberg-ipv4": ["anon-cs-de", "anon-scaleway-ams"]}
print("ok")
'
```

These checks cover pool and routes only, not reachability. Explicit `server_names` bypass the `require_*`
filters, so vet stamps and operators yourself.[2]

Then validate. `-check` is not parse-only: it can open logs and update signed registry caches. As written it
is safe on a router that does not yet serve clients (the Install precondition):
`cd /usr/local/etc/dnscrypt-proxy && /usr/local/sbin/dnscrypt-proxy -check -config dnscrypt-proxy.toml`

On a live router check an isolated copy with its own logs and listener instead (remove `$D` afterwards):

```sh
D=$(mktemp -d /root/dnscrypt-check.XXXXXX) && cp -Rp /usr/local/etc/dnscrypt-proxy/. "$D" && cd "$D" &&
sed -i "" -e "s|^listen_addresses.*|listen_addresses = [\"127.0.0.1:5399\"]|" -e "s|/var/log/dnscrypt-proxy/|$D/|" dnscrypt-proxy.toml &&
/usr/local/sbin/dnscrypt-proxy -check -config dnscrypt-proxy.toml
```

Restart once with `/usr/local/etc/rc.d/dnscrypt-proxy restart` (skip if the UI already started the service
with the final configuration). Startup took about 62 seconds on the source router; wait 90 seconds, do not restart repeatedly. In
`/var/log/dnscrypt-proxy/dnscrypt-proxy.log` read the new startup records: routes declared, each resolver
`OK (DNSCrypt)`, `live servers: 5`; a later anonymous-reachability error overrides an earlier OK.
Check the listeners belong to dnscrypt-proxy (FreeBSD may truncate the name to `dnscrypt-p`; match PIDs):

```sh
sockstat -4 -l -p 5353; pgrep -laf '(^|/)dnscrypt-proxy([[:space:]]|$)'
```

Unbound must forward its root to `127.0.0.1:5353` (set up in the UI, keeping local zones and per-domain
exceptions). From a LAN client, query the router's LAN resolver (`LAN_DNS_IP`):
`dig @LAN_DNS_IP example.com A +time=3 +tries=1 +dnssec +noall +comments +answer +stats`.

Switch clients over only after the pool and LAN answers look right. On failure, keep the error output, stop, and see Rollback.

## After an OPNsense or plugin upgrade

Upgrades may break custom templates.[1] The custom template is a full copy of the stock one, so re-diff
it after every plugin upgrade.

1. Back up the router configuration (the step 5 snippet backs up the installed pair and the runtime TOML).
2. Check the custom files survived and no competing `.TARGET` maps the runtime.
3. Copy the new stock `dnscrypt-proxy.toml` from the router to a review location and diff it against the
   baseline and the custom template (a nonzero `diff` exit only means differences exist):

   ```sh
   diff -u reference/stock-template.toml /path/to/new-stock-template.toml
   diff -u reference/stock-template.toml artifacts/OPNsense/Dnscryptproxy/dnscrypt-proxy-eu.toml
   ```

   Look for new or renamed keys, guards, source URLs, logging and the static-server section. Never replace
   the new stock file with the old baseline.
4. Re-apply the pool, strategy, ECS and route changes on top of the new stock template, keeping other
   settings bound to the UI. Re-vet the resolvers and relay operators.
5. In your copy of the kit, copy the new stock file to `reference/stock-template.toml`, update
   `reference/manifest.json` (the `sha256` values **and** `versions`) and the version line under "What it is". Upload the pair with `scp -r` to a directory that does not exist yet
   (as in Install: `/root/dnscrypt-override-upload-2`, then `-3` next time, never an existing one). In a planned window, from `/bin/sh`, run the replace snippet as
   `env U=<upload dir> /bin/sh -c '...'` (refuses without `U`); it backs up the installed pair (upload layout) and the runtime TOML, stages the new files, renames them, prints hashes:

   ```sh
   /bin/sh -c '
   set -eu
   T=/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy
   U=${U:?set U to the upload directory}
   B=/root/dnscrypt-override-replaced-$(date +%Y%m%d%H%M%S)
   cd "$T"
   test -f "$U/dnscrypt-proxy-eu.toml" -a -f "$U/+TARGETS.D/90-eu.TARGET" || { echo "upload files missing" >&2; exit 1; }
   test ! -e .dnscrypt-proxy-eu.toml.restore-pending
   test ! -e +TARGETS.D/.90-eu.TARGET.restore-pending
   mkdir -m 700 "$B" "$B/+TARGETS.D"
   cp -p dnscrypt-proxy-eu.toml "$B/"
   cp -p +TARGETS.D/90-eu.TARGET "$B/+TARGETS.D/"
   if test -f /usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml; then cp -p /usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml "$B/runtime.toml"; fi
   install -o root -g wheel -m 644 "$U/dnscrypt-proxy-eu.toml" .dnscrypt-proxy-eu.toml.restore-pending
   install -o root -g wheel -m 600 "$U/+TARGETS.D/90-eu.TARGET" +TARGETS.D/.90-eu.TARGET.restore-pending
   mv .dnscrypt-proxy-eu.toml.restore-pending dnscrypt-proxy-eu.toml
   mv +TARGETS.D/.90-eu.TARGET.restore-pending +TARGETS.D/90-eu.TARGET
   sha256 dnscrypt-proxy-eu.toml +TARGETS.D/90-eu.TARGET
   '
   ```

   The hashes must equal the updated manifest. Then run `configctl template reload OPNsense/Dnscryptproxy`,
   the isolated `-check` under "Verify" (it now sees the new output), restart once, and commit artifacts,
   stock baseline, effective settings and manifest together. A failed `-check` after a replace is reverted by
   rerunning the snippet as `env U=<backup dir> /bin/sh -c '...'` (the backup keeps the upload layout), then
   `configctl template reload OPNsense/Dnscryptproxy`.

When changing the pool, edit resolver names and routes together, excluding any relay run by the resolver's
own operator. Extra relays are alternate single-relay paths, not extra hops. Keep
`skip_incompatible = true`, review certificate-fetch privacy before changing `direct_cert_fallback`, and
never enable direct DNS-query fallback to make a failed anonymized path pass. Keep one synthetic ECS
prefix; in 2.1.15 an existing ECS option is preserved, so it proves nothing about what was sent.[3]

## Rollback

Removes the installed kit (any version), run from `/bin/sh` (see Install); to undo a failed upgrade replace, use the revert under
"After an OPNsense or plugin upgrade". Stock generation differs in privacy and ECS policy (wildcard routing cannot
express per-resolver relay exclusions); review the stock UI settings first. Files are moved aside, never deleted; the reload runs only if the move succeeded:

```sh
/bin/sh -c '
set -eu
T=/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy
B=/root/dnscrypt-override-removed-$(date +%Y%m%d%H%M%S)
test -f "$T/+TARGETS.D/90-eu.TARGET" -a -f "$T/dnscrypt-proxy-eu.toml" || { echo "kit files not installed" >&2; exit 1; }
mkdir -m 700 "$B"
mv "$T/+TARGETS.D/90-eu.TARGET" "$T/dnscrypt-proxy-eu.toml" "$B/"
' && configctl template reload OPNsense/Dnscryptproxy
```

Removing the mapping does not change the running process. The reload rewrites the five package targets
from the installed stock plugin (not `reference/`). Inspect the new runtime TOML, then restart once in a
planned window. If the plugin is disabled the runtime may be empty: do not start the service with it.

## os-dnscrypt-routes

The `os-dnscrypt-routes` plugin (see [plugin.md](plugin.md)) replaces this kit. Both map onto `dnscrypt-proxy.toml`;
the plugin's `95-dnscrypt-routes.TARGET` wins over `90-eu.TARGET`. Installing it never changes a working
router: while routing is disabled, its template includes the manual one if `90-eu.TARGET` is active.

| State | What generates `dnscrypt-proxy.toml` |
|---|---|
| Not installed, uninstalled, or installed with routing disabled | Manual override if present, otherwise stock |
| Installed, routing enabled | Plugin routing; the manual override is shadowed (the UI shows a notice) |

Gap-free migration: install the plugin, enable it and Save & Apply. Confirm it took over: the first line of
`/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml` must be `# dnscrypt-routes: managed`. Only then run the
move-aside snippet under "Rollback". Removing the kit while the plugin is disabled returns to stock.

## Caveats

- The `0.0.0.0:53` fallback/bootstrap value in the source settings is a snapshot, not a recommendation;
  review it against the new router's system DNS and avoid a circular bootstrap dependency.
- "Block IPv6 answers" is not the upstream IPv6 transport switch; do not disable it silently.
- Private rules (forwarding, cloaking, allow-list) are not here; do not overwrite existing ones with empty files.
  Leave DNSBL off unless you review the extra log and rule paths it adds.
- `wp2` adapts to the live pool; no equal shares, outage recovery, CDN benefit or seamless failover is promised.[4]
- The kit does not touch firewall, DHCP, clients or Unbound. Avoid concurrent UI Save/Apply during updates.

## Sources

[1] https://docs.opnsense.org/development/backend/templates.html
[2] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/example-dnscrypt-proxy.toml
[3] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/plugin_ecs.go
[4] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/serversInfo.go
