#!/bin/sh
# Runs in the guest (vm deploy, via `sh -s`).
#   checkout <commit>   shallow checkout of opnsense/plugins at <commit> in /root/plugins
#   build               make package for dns/dnscrypt-routes (rsynced in by the host), then install or
#                       upgrade it with pkg add; prints "<name> <version> <sha256> <file>"
# Mirrors the plugins tree's own "make upgrade" (Mk/plugins.mk) without its pkg delete step, so an
# upgrade keeps the plugin's settings and never runs the deinstall hooks. The package is then registered
# like a firmware install does (scripts/firmware/register.php install); otherwise the next boot's
# "register.php sync" (config.inc convert_config) would add it and change config.xml.
set -eu
TREE=/root/plugins
PLUGIN=$TREE/dns/dnscrypt-routes

case "${1:-}" in
checkout)
	C="${2:?commit}"
	if [ ! -d "$TREE/.git" ]; then
		git init -q "$TREE"
		git -C "$TREE" remote add origin https://github.com/opnsense/plugins.git
	fi
	if [ "$(git -C "$TREE" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null || true)" != "$C" ]; then
		git -C "$TREE" fetch -q --depth 1 origin "$C"
		git -C "$TREE" checkout -q -f --detach FETCH_HEAD
	fi
	[ "$(git -C "$TREE" rev-parse HEAD)" = "$C" ] || { echo "deploy: $TREE is not at $C" >&2; exit 1; }
	mkdir -p "$PLUGIN"
	;;
build)
	[ -f "$PLUGIN/Makefile" ] || { echo "deploy: no plugin source in $PLUGIN" >&2; exit 1; }
	rm -rf "$PLUGIN/work"
	make -C "$PLUGIN" package >&2
	set -- "$PLUGIN"/work/pkg/*.pkg
	[ $# -eq 1 ] && [ -f "$1" ] || { echo "deploy: expected one package in $PLUGIN/work/pkg" >&2; exit 1; }
	FILE="$1"
	NAME=$(pkg query -F "$FILE" %n)
	VERSION=$(pkg query -F "$FILE" %v)
	if pkg info -e "$NAME"; then
		# same or newer version: replace the installed files, keep the configuration
		pkg add -f "$FILE" >&2
	else
		pkg add "$FILE" >&2
	fi
	[ "$(pkg query %v "$NAME")" = "$VERSION" ] || { echo "deploy: $NAME $VERSION is not installed" >&2; exit 1; }
	/usr/local/opnsense/scripts/firmware/register.php install "$NAME" >&2
	echo "$NAME $VERSION $(sha256 -q "$FILE") $FILE"
	;;
*)
	echo "usage: deploy.sh checkout <commit> | build" >&2
	exit 2
	;;
esac
