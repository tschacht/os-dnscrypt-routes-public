# Test VM

A throw-away OPNsense guest (26.7 nano image, amd64) for building and testing the plugin. It runs under
full software emulation in a pinned `qemux/qemu` container. SSH, HTTPS and VNC are forwarded to
127.0.0.1 only. One entry point, `test-vm/vm <command>`, drives the whole lifecycle; `test-vm/vm help`
lists the commands.

## Prerequisites

- Docker with Compose; on macOS, OrbStack. `compose.yaml` gives the guest 4 GB RAM (`RAM_SIZE`).
- An arm64 host such as Apple silicon: the `qemux/qemu` image pinned in `lib/common.sh` is an arm64-only
  manifest and `compose.yaml` pins `platform: linux/arm64`. Other hosts are untested; they would need both
  pins changed.
- Host tools: `curl`, `openssl`, `bunzip2`, `expect`, `ssh`, `ssh-keygen`, `shasum` (checked by `create`),
  `python3` and `rsync`.

## vm.env

[`vm.env`](vm.env) holds the settings: VM name, the pinned image (`IMAGE_URL`, its `IMAGE_SHA256` and
`IMAGE_PUBKEY_SHA256`, the hash of the OPNsense signing key the image signature is checked against), the
pinned `opnsense/plugins` commit (`PLUGINS_COMMIT`, used by `deploy`), ports (SSH 12222, HTTPS 14443,
VNC 15900), the NAT subnet and the guest's root password. The credentials are throw-away and committed
on purpose.

- A new OPNsense series (e.g. 27.1) needs manual edits: `OPNSENSE_VERSION`, `IMAGE_URL`, `IMAGE_SHA256`,
  `IMAGE_PUBKEY_SHA256`, and probably `PLUGINS_COMMIT`. Within a series, `vm update` takes the guest to the
  newest release (26.7 → 26.7.7 in the last run).
- Only `VM_STATE_DIR` is read from the environment. Any other key can be overridden for one run with a
  `VM_ENV_` prefix, e.g. `VM_ENV_SSH_PORT=22222`.

## State directory and lock

All state lives in `$VM_STATE_DIR`, by default `work/vm-state/` in the main checkout (git-ignored), shared
by every git worktree: `disk/` (the guest disk with its `baseline` snapshot), `images/` (verified
downloads), `vm_ed25519` and `vm_ed25519.pub` (SSH key), `api.env` (API key for root), `lock/`, the
marker file `.vm-state-dir`, and `golden.qcow2` if one was made by hand (`create` clones it instead of
the image).

`test-vm/vm lock <ID>` takes the single VM lock (`<ID>`: any short name of letters, digits, `.`, `_`
or `-`, recorded as the holder) and `test-vm/vm unlock` releases it. Every command that can change the VM (`create`, `destroy`,
`start`, `stop`, `ssh`, `provision`, `reset`, `deploy`, `update`, `export`, `restore`, `test`) needs the
lock taken from the same checkout; otherwise it exits 3. `help`, `status` and `console` do not.
Exit codes: 0 ok, 1 failure, 2 usage, 3 lock missing or held by another checkout.

## Typical session

```sh
test-vm/vm lock dev
test-vm/vm create
test-vm/vm provision
test-vm/vm deploy
test-vm/vm test
# destroy deletes the only copy of the built package; to keep it, copy it out first (docs/plugin.md, Install)
test-vm/vm destroy
test-vm/vm unlock
```

Between runs, `test-vm/vm reset` followed by `test-vm/vm deploy` is the fast way back to a clean state.

## Commands

Timings are from this project's runs on an Apple silicon host under emulation.

| Command | What it does | Time |
|---|---|---|
| `create` | download and verify the image (SHA-256 and signature), build the disk, start the container, set root password, SSH key and DHCP over the serial console, wait for SSH. Idempotent. | ~5 min |
| `provision [--logging]` | install `os-dnscrypt-proxy` (not this plugin), `rsync` and `git`; apply the DNSCrypt base settings from `reference/effective-settings.json` (listening on 127.0.0.1:5353); make Unbound forward to it; create the API key; take the `baseline` snapshot. `--logging` also turns on DNSCrypt and Unbound query logging. | ~5 min |
| `deploy` | build this checkout's plugin in the guest and install or upgrade it (settings kept); prints package and SHA-256 | ~0.5 min |
| `reset` | revert the disk to the `baseline` snapshot and start the VM. The baseline has no plugin, so run `deploy` again afterwards. | ~2.5-3 min |
| `update` | firmware and package update in the guest (waits through its reboot), then `deploy` | ~7.5 min |
| `test [check...]` | on-device smoke tests, see below | ~14 min |
| `export [--to <dir>]` | save the guest's `config.xml` and a `manifest.json` to `test-vm/snapshots/<UTC date>/` or `<dir>` | seconds |
| `restore <dir>` | configuration import only, see below | ~2-3 min |
| `start`, `stop` | start the stopped container and wait for SSH (~1.5 min); clean power-off | |
| `status` | lock holder, container, taint, baseline snapshot, ports, SSH | |
| `ssh [cmd...]` | root shell or command in the guest, e.g. `test-vm/vm ssh drill -p 5353 @127.0.0.1 example.com` | |
| `console` | print the VNC address | |
| `destroy [--all [--yes]]` | see below | seconds |

The web GUI is at https://127.0.0.1:14443 (user `root`, password from `vm.env`).

## vm test

`test-vm/vm test` installs this checkout's plugin and runs these checks, in order: `install` (install
without a DNS restart), `preset` (the seeded preset), `php` (`php -l`), `disabled` (disabled = stock
output), `apply` (apply the preset via the API: exactly one restart, live servers, no direct server,
drill through Unbound), `vectors` (validation vectors), `savetest` (Save & Test isolation), `killed`
and `timeout` (a killed and a timed-out test), `failclosed`, `uninstall`, `coexist` (coexistence with
the manual override) and `end` (end state: `vm reset`, `vm deploy`). It prints `ok`/`FAIL` per check
and a summary, and exits 1 if any check failed.

A catalog drift fixture and a scripted UI check were left out to keep the VM tests lean. `failclosed`
proves the template's fail-closed path (a saved configuration that breaks the relay-only rule stops DNS
instead of going direct); `apply` shows no direct server with the preset. The runtime log check (the
"Direct connection detected" alert, direct or non-DNSCrypt rows failing in Save & Test) is proven by
the offline tests only (`tests/test_status.py`, `tests/test_testrun.py`).

- It always starts with `vm reset`, i.e. from the `baseline` snapshot that `provision` took on the stock
  26.7 image (`update` does not move it), and ends reset and deployed with routing disabled (its last
  check, `end`). So it cannot test a guest after `vm update`. For an updated guest, run `reset`, then
  `update` (which deploys a fresh plugin), then the reset-free subset:

  ```sh
  test-vm/vm test preset php apply vectors savetest killed timeout failclosed
  ```

- Check names run only those checks, in the order above, e.g. `test-vm/vm test failclosed`. Each
  check relies on the state the earlier ones leave, so a subset only works from a matching state.
- Each dnscrypt-proxy start on this VM waits about 60 s for the network, so live servers appear about
  60-65 s after every start, and Save & Apply on the page takes about as long.

## Snapshots and restore

`vm restore <dir>` imports a saved configuration and reboots. It installs no packages and restores no
files.

- A snapshot made by `vm export` restores onto any provisioned VM: root's SSH key and API key in the
  uploaded copy are replaced by this VM's, so it works on any state directory. To get a working setup,
  `deploy` first. The import and the reboot come first; then the restore waits until DNS through
  Unbound answers and exits 1 otherwise. The imported configuration stays live either way (`vm reset`
  returns to the baseline), so use it for configurations with working DNS.
- Any other configuration whose root key is not this VM's (the historical bundle below) replaces the
  credentials. The VM is then tainted and only `vm destroy` may follow.

[`snapshots/2026-10-15/`](snapshots/2026-10-15/manifest.json) is the committed export of a VM after
`reset` and `deploy`: OPNsense 26.7, the DNSCrypt and Unbound baseline, and the plugin with its seeded
preset, routing disabled. Versions and SHA-256 are in its manifest. It contains throw-away material only:
the GUI's self-signed certificate with its private key, root's password hash (of the `vm.env` password),
the VM's public SSH key and an API key (secret stored hashed); a restore replaces both keys.

[`restore/2026-10-11/`](restore/2026-10-11/README.md) is the historical bundle of the earlier test VM. It
stays byte-identical and is import-only: `vm restore test-vm/restore/2026-10-11` loads its configuration,
not a working historical installation (its package and companion files are not installed). Root login
then needs that snapshot's own SSH key, which is not in the repository. Its README links to documents that
were removed in this revision; read them under the `pre-revision` tag, e.g.
`git show pre-revision:docs/disposable-vm-proposal.md`.

## destroy

- `vm destroy` removes the container and `disk/` (with the baseline snapshot). It keeps `images/`,
  `golden.qcow2`, the SSH key, `api.env` and the lock, so the next `create` downloads nothing.
- `vm destroy --all` also removes the whole state directory, including the lock, so the next `create`
  downloads the image again. It refuses while another checkout holds the lock, refuses (nothing removed)
  while the directory holds entries vm did not create, and needs `--yes` if a `golden.qcow2` exists (it
  would have to be rebuilt by hand).
