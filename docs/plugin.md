# os-dnscrypt-routes plugin

One page, Services → DNSCrypt-Proxy → Anonymized Routing, that writes the resolver list, the
per-resolver relay routes, `lb_strategy`, `skip_incompatible`, `direct_cert_fallback` and an optional
ECS subnet into the dnscrypt-proxy configuration. Every other setting still comes from the stock
Configuration page. Policy, preset and caveats: [README](../README.md).

## Install

There is no published package. Build one with the test VM (see "Build" below): `vm deploy` leaves
`os-dnscrypt-routes-1.0.pkg` in the guest under `/root/plugins/dns/dnscrypt-routes/work/pkg/` and prints
its SHA-256. Copy it to the host before `vm destroy` (`vm ssh` needs the VM lock), then compare the hash:

```sh
test-vm/vm ssh cat /root/plugins/dns/dnscrypt-routes/work/pkg/os-dnscrypt-routes-1.0.pkg > os-dnscrypt-routes-1.0.pkg
shasum -a 256 os-dnscrypt-routes-1.0.pkg
```

It has only been installed on that test VM (OPNsense 26.7 and 26.7.7, amd64).

1. Install `os-dnscrypt-proxy` (System → Firmware → Plugins), configure it and start it once, so it
   downloads the signed resolver and relay lists. Enabling routing is refused without them.
2. Copy the package to the router and install and register it as a firmware install would, from a
   root shell in the package's directory:

   ```sh
   pkg add os-dnscrypt-routes-1.0.pkg && /usr/local/opnsense/scripts/firmware/register.php install os-dnscrypt-routes
   ```

Installing restarts nothing and changes no generated file: a first install seeds the preset with routing
disabled, and while it is disabled `dnscrypt-proxy.toml` is generated as without the plugin (stock, or
the manual override if active). Migrating from the manual override: [manual-override.md](manual-override.md).

## The page

- **Service widget** (top right): the stock dnscrypt-proxy start, restart and stop buttons.
- **Status strip**:
  - *Policy*: `Applied` (the generated file starts with `# dnscrypt-routes: managed`), `Off` (routing
    disabled), `Off: DNSCrypt-Proxy is disabled`, `Stopped` while dnscrypt-proxy is not running (also in
    the fail-closed states, see Troubleshooting).
  - *Live servers (log)*: live servers reported by the last dnscrypt-proxy startup in its log / servers
    named in the generated configuration.
  - *Last applied*: time of the last successful Save & Apply, in UTC.
  - *Pending*: `None`, `Saved, not applied` (saved settings differ from the last applied ones, or nothing
    was applied yet) or `Unsaved changes` (edits on the page not yet saved).
  - Red alerts below it: fail-closed states, "Direct connection detected" (a live server without a relay
    route in the log, only while routing is in effect) and "Relay-only routing not guaranteed" while
    *Skip incompatible routes* is off. Blue notices: the manual override is shadowed (follows the applied
    state, not the saved checkbox), a leftover manual template without its mapping, and non-empty stock
    Server/Relay lists, which routing overrides.
- **General**: *Enable anonymized routing*, *Load balancing* (`lb_strategy`, default `wp2`),
  *Skip incompatible routes*, *Direct certificate fallback*, *ECS subnet hint* and *ECS subnet* (off by
  default; any subnet is accepted, with a privacy warning unless it is the synthetic preset).
- **Relays**: grid with name and operator. *+* opens a dialog with a searchable picker from the signed
  `relays.md`; the operator is pre-filled from the name and editable.
- **Resolvers and routes**: one row per resolver (*On*, name, operator), one column per relay. Tick the
  relays a resolver may use. Cells where the relay has the resolver's operator, or is the resolver's own
  `anon-` relay, are locked. *Add resolver* opens a picker from the signed `public-resolvers.md`.

Matrix ticks stay local until you save. Dialog edits and deletes are written at once, and a refused
write shows its reason and changes nothing.

### What is refused and what only warns

While routing is enabled, a save is refused if a relay has its resolver's operator or is the resolver's
own `anon-` relay, an operator is empty, an enabled resolver has no relay or a deleted relay, no resolver
is enabled, an enabled resolver is not a DNSCrypt server in the catalog (DoH, ODoH and unknown names
are refused), an enabled stock static server has a resolver's name, or a relay name contains `*` or
starts with `sdns:` (dnscrypt-proxy reads them as "any relay" and as a stamp). Disabling or deleting the
last enabled resolver is refused too. Deleting a relay that a resolver uses is always refused. Enabling
is refused while the catalog is missing. Unticking *Enable anonymized routing* is always accepted; while
routing is enabled and the catalog is missing, it is the only change accepted.

Warnings only: a single relay (no failover), a relay name not in the catalog, an ECS subnet other than
the preset, *Skip incompatible routes* off, non-empty stock Server/Relay lists.

## Save & Apply

Saves, re-checks every rule, regenerates the configuration through the stock template set and restarts
dnscrypt-proxy once. A refused save restarts nothing and changes nothing. The button keeps its spinner
until the log reports live servers: on the test VM about 65 s, as every dnscrypt-proxy start first waits
about 60 s for the network. The "Applied" message appears only once dnscrypt-proxy runs again and
reports live servers; otherwise the page says that it is not running, or that no live servers appeared
within 90 s.

To undo a change, edit the settings back (or untick Enable) and Save & Apply again.

## Save & Test

Saves without applying and runs the saved configuration in a temporary dnscrypt-proxy on
127.0.0.1:5354, for at most 90 s, then stops it. The live service, its configuration, log, cache and
listener are not touched. The test sends real queries to the selected resolvers through the selected
relays. The result shows, per resolver, the route used in this test, certificate, RTT and pass/fail,
then three test queries; *Apply* under it applies the tested settings.

- dnscrypt-proxy picks one relay per resolver at random at each start, so one run tests one relay per
  resolver. Run it again to cover others.
- With routing off, the test covers the configuration dnscrypt-proxy uses without the plugin (stock or
  the manual override), not the matrix; the panel says so and offers no *Apply*.
- If the settings change after the test, the panel says the result no longer covers them.
- One test at a time; a second start shows the running test's result.

## Troubleshooting

- **Red alert "Invariant violated: …" or "Override not applied: …"**: the generated file starts with
  `# dnscrypt-routes: invariant-violated` (the saved model breaks the relay-only rule, e.g. after a hand
  edit) or `# dnscrypt-routes: override-not-applied` (the stock template no longer has the lines the plugin
  patches, typically after an `os-dnscrypt-proxy` update). Both fail closed: dnscrypt-proxy exits, so DNS
  stops instead of going direct, and Policy then shows `Stopped`. For `invariant-violated`, fix the routes
  and Save & Apply. In either case you can untick *Enable anonymized routing* and Save & Apply; stock, or
  the manual override if present, applies again. First line: `head -n 1 /usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml`.
- **"Start DNSCrypt-Proxy once so it downloads the signed resolver list."**: the catalog is missing;
  start the stock service, wait for its lists, then enable.
- **Direct connection detected**: a server is used without a relay route. Save & Test fails such a
  resolver too; check the resolver's relays and that *Skip incompatible routes* is on.
- **Stock forwarding rules** (Configuration page, tab *Forwarders*): matching queries still go straight to
  the configured server as plain, unencrypted DNS, outside the relays, also while routing is enabled.
- **A hand-edited `config.xml` that core's field checks reject** (e.g. an empty relay name): every save
  that leaves the field as it is fails with that field error, unticking Enable alone included. Correct
  the field (e.g. rename the relay in its dialog). If the catalog is unavailable too, while routing is
  enabled the only way out is a single `settings/set` API call that sets `general.enabled` to 0 and gives
  the relay a valid name together. Such a configuration renders fail closed meanwhile; nothing goes direct.

## Uninstall

Untick *Enable anonymized routing* and Save & Apply, then:

```sh
pkg remove -y os-dnscrypt-routes && /usr/local/opnsense/scripts/firmware/register.php remove os-dnscrypt-routes
```

The template and its `95-dnscrypt-routes.TARGET` mapping go with the package, so the next regeneration
gives the manual override if present, otherwise stock. No plugin files remain outside
`/var/db/dnscrypt-routes/` (last applied hash) and `/var/run/dnscrypt-routes/` (last test result).
The settings stay in `config.xml` (there is no deinstall hook), and a reinstall picks them up again: the
migration `M1_0_0` seeds the preset only into a model without relays and resolvers. This follows from the
code, not from a recorded VM run. To return to the preset, re-create it from the table in the README.

## Build

The package is built inside the test VM, against the `opnsense/plugins` commit pinned in
`test-vm/vm.env`, from the `plugin/` tree of the checkout you run it from. On a provisioned VM (setup:
[test-vm/README.md](../test-vm/README.md)), `test-vm/vm deploy` rsyncs `plugin/dns/dnscrypt-routes/`,
runs `make package`, installs or upgrades the package in the guest (settings kept) and prints the
package name and SHA-256.

**Note for page authors:** success responses of the settings API (`/api/dnscryptroutes/settings/*`)
always carry `"validations": {}`. Core's stock `saveFormToEndpoint` and grid dialogs treat any
`validations` key as a failure, so this page uses its own save, grid and dialog handlers. A new page on
this API needs the same.
