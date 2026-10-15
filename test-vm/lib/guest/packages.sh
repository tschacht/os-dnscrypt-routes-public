#!/bin/sh
# Runs in the guest (vm provision, via `sh -s`). Installs os-dnscrypt-proxy the way the firmware
# install action does (scripts/firmware/install.sh: pkg install, then register.php install), minus its
# "core must be up to date" gate, which would force a full firmware update on the fresh 26.7 image.
# rsync and git are for vm deploy (rsync target, pinned opnsense/plugins checkout).
set -eu
# right after the first boot the mirror fetches can fail transiently ("error occurred while fetching
# package"); retry a few times before giving up
n=0
until pkg update -q && pkg install -y os-dnscrypt-proxy rsync git >/tmp/vm-packages.log 2>&1; do
	n=$((n + 1))
	if [ "$n" -ge 4 ]; then
		cat /tmp/vm-packages.log >&2
		exit 1
	fi
	echo "packages: attempt $n failed, retrying in 15s" >&2
	sleep 15
done
/usr/local/opnsense/scripts/firmware/register.php install os-dnscrypt-proxy >/dev/null
pkg query '%n %v' os-dnscrypt-proxy dnscrypt-proxy2 rsync git
