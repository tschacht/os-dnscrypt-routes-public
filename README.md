# os-dnscrypt-routes

Per-resolver anonymized DNSCrypt routes for OPNsense. You choose which resolvers dnscrypt-proxy uses and
which relays each of them may go through; a resolver never uses a relay run by its own operator.
It builds on the stock `os-dnscrypt-proxy` plugin, which keeps owning the service and all other settings.
The requirements and design are in the [revision plan](docs/clear-cut-revision-plan.html).

## Two ways to deploy

| | How | Guide |
|---|---|---|
| Plugin | `os-dnscrypt-routes`: page Services → DNSCrypt-Proxy → Anonymized Routing, with a route editor, Save & Apply and an optional Save & Test | [docs/plugin.md](docs/plugin.md) |
| Manual override | two files copied onto the router; fixed policy, no UI | [docs/manual-override.md](docs/manual-override.md) |

Choose the plugin for the route editor and Save & Test. It has no published package: you build it once with the
test VM (needs Docker or OrbStack, about 10 minutes for create, provision and deploy), see [docs/plugin.md](docs/plugin.md).
The test VM needs an arm64 host such as Apple silicon: its container image is pinned for arm64 only, other hosts
are untested. Choose the manual override for the fixed preset without building anything.

Both generate `/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml` through OPNsense's template targets.[1]
While the plugin's routing is enabled it wins; while it is disabled (or uninstalled) the manual override
applies again if present, otherwise stock. Installing the plugin changes nothing until you enable routing and Save & Apply.

## Preset routes

The plugin seeds this policy on a fresh install, with routing disabled; the manual override ships it fixed.
Canonical source: [`reference/effective-settings.json`](reference/effective-settings.json).

| Resolver | Relays |
|---|---|
| `scaleway-ams` | `anon-cs-de`, `anon-cs-fr` |
| `cs-de` | `anon-scaleway-ams`, `anon-scaleway` |
| `nwps.fi` | `anon-cs-de`, `anon-scaleway-ams` |
| `dorriere-fr` | `anon-cs-de`, `anon-scaleway-ams` |
| `dnscry.pt-nuremberg-ipv4` | `anon-cs-de`, `anon-scaleway-ams` |

Cryptostorm resolvers stay away from Cryptostorm relays (`anon-cs-*`), Scaleway resolvers from Scaleway
relays (`anon-scaleway*`); the other three operators may use either. Further settings: `lb_strategy = "wp2"`,
`skip_incompatible = true`, `direct_cert_fallback = true`. ECS: the manual override sends the synthetic
`146.70.82.0/24`; in the plugin ECS is off by default, with that subnet pre-filled.

## Caveats

- Operator separation is application-level, based on the catalog and the operator tags you enter. It is
  not proof against collusion or shared hosting. Recheck ownership before changing the pool.
- Explicit server names bypass dnscrypt-proxy's `require_dnssec`/`require_nolog`/`require_nofilter`
  filters, so vet the selected resolvers yourself. Advertised DNSSEC/no-log/no-filter flags are
  declarations, not proof.[2]
- `wp2` compares two random candidates from the live pool by latency and success scores. It does not spread
  load evenly and does not promise seamless failover.[4]
- ECS is a default hint, not enforcement: in dnscrypt-proxy 2.1.15 an ECS option already present in a query
  is kept. A CDN benefit was never demonstrated. Never use your real WAN subnet.[3]
- `direct_cert_fallback = true` lets certificate fetches go direct; user queries never do, except
  forwarding rules (below).
- The relay-only guarantee (while routing is enabled and `skip_incompatible` is on, every query goes
  through a relay or fails, except forwarding rules) relies on dnscrypt-proxy 2.1.15 behaviour. The test
  VM checks that every preset resolver goes only through relays, with no direct server, and that a
  broken configuration fails closed. The drift case (a catalog resolver that changes protocol) is
  covered by the offline tests only.
- Forwarding rules (stock Configuration page, tab *Forwarders*) still send matching queries straight to
  their configured servers as plain, unencrypted DNS, outside the relays, also while routing is enabled.
- Save & Test sends real queries to the selected resolvers and relays.

## Layout

| Path | Content |
|---|---|
| `plugin/dns/dnscrypt-routes/` | the plugin source |
| `artifacts/`, `reference/` | manual override files and the stock baselines (kept byte-identical) |
| `tests/` | offline tests (Python only) |
| `test-vm/` | disposable OPNsense test VM, see [test-vm/README.md](test-vm/README.md) |
| `docs/` | plan, guides, [revision history](docs/revision-history.md) |

Offline tests: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest -q`.
The tag `pre-revision` marks the repository before this revision; read removed documents with `git show pre-revision:<path>`.

## Sources

[1] https://docs.opnsense.org/development/backend/templates.html
[2] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/example-dnscrypt-proxy.toml
[3] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/plugin_ecs.go
[4] https://raw.githubusercontent.com/DNSCrypt/dnscrypt-proxy/2.1.15/dnscrypt-proxy/serversInfo.go
