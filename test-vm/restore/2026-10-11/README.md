# Disposable test VM restore backup — 2026-10-11

The owner requested this backup of **`dnscrypt-eu-offline-20261011`**, explicitly authorized its test credentials in this private Git repository, and requested an **unencrypted** download. It contains no production configuration. Production was untouched.

The final export contains these enabled native UI settings:

| Location | Setting |
|---|---|
| Services → DNSCrypt-Proxy → General | Enable query logs |
| Services → Unbound DNS → Advanced | Log Queries |
| Services → Unbound DNS → Advanced | Log Replies |

Unbound's catch-all Query Forwarding row remains `127.0.0.1:5353`, with Use System Nameservers and Forward first off. DNSCrypt retains the fixed five EU resolvers, eligible anonymized routes, `wp2`, `skip_incompatible=true` and the existing synthetic ECS-off policy. These are separately requested VM administrative changes; they add no companion feature or automatic activation.

## Files

| File | Contents |
|---|---|
| [opnsense-test-vm.xml](opnsense-test-vm.xml) | Actual whole-configuration download from System → Configuration → Backups, including the test VM's credentials and certificate material. No Encrypt field/password was submitted; RRD data was omitted. |
| [companion-files.tar.gz](companion-files.tar.gz) | 104 regular file/directory members preserving the VM's DNSCrypt runtime/rules/catalogs, companion settings/journal/backups, active generator pair, service override and test SSH authorized public keys. Includes the matching local companion package candidate. |
| [evidence.json](evidence.json) | Actual sanitized native download/archive evidence. |
| [manifest.json](manifest.json) | Versions, source revision, checksums, administrative counts and restore limitations. |

Application/query logs, RRD history, VM disks, package database, host SSH private key and authenticated HTTP session fixtures are excluded. The older export made before Unbound logging was enabled is not committed. OPNsense's normal XML backup does not contain the supplemental filesystem files. See the native [Configuration Backups documentation](https://docs.opnsense.org/manual/backups.html).

## Restore the configuration on the retained test VM disk

1. Use only this isolated disposable test VM. Preserve its current configuration before restoring. The recorded baseline is OPNsense `26.7.6_3` amd64, Unbound `1.25.1`, `os-dnscrypt-proxy 1.17`, DNSCrypt binary `2.1.15` and companion `0.1` from implementation `53815724250f467ecd6f02fa59db26aeaf22c47a`.
2. Verify the files with `shasum -a 256 opnsense-test-vm.xml companion-files.tar.gz`, from this directory. Expected values are below and in the manifest.
3. Open the test VM's System → Configuration → Backups page. Upload `opnsense-test-vm.xml` as the complete configuration. Leave encrypted-file/decryption options off and use no password. Review and perform the native restore/reboot deliberately when ready. The exported test VM credentials replace the current login configuration.
4. After boot, verify SSH/HTTPS management and native settings. The existing VM's management setup also uses a temporary guest return route described in the [VM setup record](../../../docs/disposable-vm-proposal.md#persistent-setup-and-authorized-management-networking); XML alone does not preserve that runtime route or the Docker/QEMU port forwards. Use the existing console to re-establish management if necessary.
5. Check Unbound's active catch-all forwarder and `log-queries`/`log-replies`, DNSCrypt's listener, fixed EU policy and package protection. Require fresh startup/process evidence after the reboot before treating companion Status as ready. The archived activation/PID evidence is historical.

The retained disk already has the installed package and supplemental files. Uploading the XML does not reinstall them. Package install/upgrade/Save remain inert under the companion contract; any deliberate backend recovery or Apply needs its normal explicit confirmation.

## Recovering onto a different disk

The XML is an importable native configuration, **not a full VM image**. A new disk additionally needs the pinned native packages and the companion files. The actual companion archive remains at:

```text
/Users/lumpy/dev/opnsense-dnscrypt-eu/work/native-packages/5381572/os-dnscrypt-eu-0.1.pkg
SHA-256 f1309c363d28ea4d8abe83987c3965608913e1b7bbd4313c3c00826118cbb953
```

The identical package is also the regular archive member `var/db/dnscrypt-eu/upgrade-candidate.pkg`. To recover that member into the current directory without overwriting system files:

```sh
umask 077
tar -xOf companion-files.tar.gz var/db/dnscrypt-eu/upgrade-candidate.pkg > os-dnscrypt-eu-0.1.pkg
shasum -a 256 os-dnscrypt-eu-0.1.pkg
```

A different-disk restore requires supervised placement of the supplemental files and re-establishment of companion ownership, package lock and startup evidence. Do not blindly extract the archive over `/` or reuse the journal as proof of current ownership/readiness: inode identities, process identity and package state do not survive disk replacement. Follow the [administrative recovery/build guide](../../../docs/plugin-build-and-install.md) with the preserved journal and runtime as evidence; a new-disk recovery sequence remains unverified. No second VM was created to exercise it.

## Actual verification and limits

| Check/action | Result |
|---|---|
| DNSCrypt native query-log model Save | **PASS:** one Save. The first helper then refused template generation through the companion's restricted runner before executing generation/restart; original exit 1 retained. A corrected administrative continuation did not repeat the Save. |
| DNSCrypt native template generation/restart | **PASS, exit 0:** one generation and one separately authorized restart; only native query/NX logging sections changed, fresh five-server/eligible-route/process/listener evidence established. Activation and owned runtime fingerprint were updated only after proof; other journal fields/backups/settings retained. No plugin Apply. |
| Unbound native query-log Save/apply | **PASS, exit 0:** one Save and one `configctl unbound restart`; active `get_option log-queries` is `yes`. DNSCrypt PID/files and unrelated settings preserved. |
| Unbound native reply-log Save/apply | **PASS, exit 0:** one Save and one `configctl unbound restart`; active `get_option log-replies` and `log-queries` are `yes`. Catch-all forwarding and DNSCrypt PID/files preserved. This separate action followed the owner's additional reply-log request. |
| Final native `diag_backup.php` GET/download POST | **PASS, exit 0:** HTTP 200/200, authenticated native form CSRF and strict TLS verified. Attachment bytes equal current `/conf/config.xml`; all three settings enabled. No service action during export. |
| Logging probe | **PASS:** final fresh synthetic UDP name through Unbound returned valid NOERROR/NODATA once; DNSCrypt query-log size increased. Only log metadata was read. An earlier successful export also used one fresh probe; neither probe was retried. |
| Supplemental archive | **PASS:** 104 members; regular file/directory types, safe relative paths, source bytes/mode/uid/gid verified. Before/after retained snapshots/PID unchanged. No log contents included. |
| Native restore parser | **PASS, exit 0:** `/usr/local/bin/php /root/dnscrypt-eu-work/check-test-vm-backup-parser.php` called native `load_config_from_file` read-only; all three preferences present, live config hash unchanged. No restore/service request. |
| Host copied-file verification | **PASS, exit 0:** `/opt/homebrew/bin/python3.13 -B work/disposable-vm-tools/verify-test-vm-backup.py`; hashes, XML forwarder/logging, archive member safety, embedded package checksum and fixed runtime policy verified. The first `/usr/bin/python3` invocation failed before verification because its standard library lacks `tomllib`; no dependency was installed. |
| Final native read-only state check | **PASS, exit 0:** `/usr/local/bin/python3 -B /root/dnscrypt-eu-work/check-test-vm-backup-final.py`; current readiness ready/running policy confirmed, native `pkg check -s os-dnscrypt-eu` and owned package-lock verification passed, live XML still matches export, snapshots/PID unchanged. Zero service requests and DNS queries. |
| Full restore/reboot/different-disk recovery | **NOT RUN:** format acceptance is verified; a restored installation, reboot persistence and renewed companion ownership/activation are unverified. Owner-deferred backend and interactive Task 5B acceptance remain open. |

The administrative helpers are retained under ignored `work/disposable-vm-tools/` and `/root/dnscrypt-eu-work/`; their hashes are in the manifest. They use native PHP model validation/Save and native administrative service commands over the dedicated localhost SSH target, with disposable markers checked. No hidden browser mutation API, automatic retry/rollback or explicit cache flush was used. Plugin source/package is unchanged; no new infrastructure or dependency installation, push or publication occurred.

```text
24945e66bc1caa9971d8cdb3b629c11d5576256cec15a31e22b7f8f27a519120  opnsense-test-vm.xml
f91d11327df926ed2f45564a571c88cd126194df1377779f5b868e6fddb9eca9  companion-files.tar.gz
```
