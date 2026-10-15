#!/bin/sh
# Runs in the guest (vm update, via `sh -s`). Starts the firmware update the GUI uses
# (configctl firmware update -> scripts/firmware/launcher.sh update -> update.sh: opnsense-update -pt,
# then base and kernel sets when available, then a reboot) and follows its progress file.
# Prints the progress log as it grows. Exit 0: finished without reboot; 10: finished, the guest reboots now; 1: failure.
set -u
P=/tmp/pkg_upgrade.progress
[ "$(configctl firmware running)" = ready ] || { echo "firmware: another firmware action is running" >&2; exit 1; }
# start from an empty progress file, so markers of an earlier run are never read as ours
: > "$P"
configctl firmware update >/dev/null || { echo "firmware: configctl firmware update failed" >&2; exit 1; }
# shown: lines of $P printed so far (the host follows them in disk/update.log)
shown=0
show_new() {
	n=$(wc -l < "$P" | tr -d ' ')
	if [ "$n" -gt "$shown" ]; then
		sed -n "$((shown + 1)),${n}p" "$P"
		shown=$n
	fi
}
i=0
while [ "$i" -lt 360 ]; do
	sleep 5
	i=$((i + 1))
	show_new
	if grep -q '^\*\*\*REBOOT\*\*\*' "$P"; then
		show_new
		exit 10
	fi
	if grep -q '^\*\*\*DONE\*\*\*' "$P"; then
		show_new
		if grep -q 'Partial update failure' "$P"; then exit 1; fi
		exit 0
	fi
done
show_new
echo "firmware: no result after 30 minutes" >&2
exit 1
