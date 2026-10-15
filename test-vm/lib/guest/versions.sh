#!/bin/sh
# Runs in the guest (vm export, via `sh -s`). Prints KEY=VALUE lines for the snapshot manifest.
# A package that is not installed is printed with an empty value.
echo "opnsense=$(opnsense-version)"
echo "kernel=$(uname -sr)"
echo "config_sha256=$(sha256 -q /conf/config.xml)"
for p in os-dnscrypt-proxy dnscrypt-proxy2 os-dnscrypt-routes unbound; do
	echo "pkg:$p=$(pkg query %v "$p" 2>/dev/null)"
done
