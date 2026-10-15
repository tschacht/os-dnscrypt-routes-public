#!/usr/bin/env bash
# vm deploy: build os-dnscrypt-routes from this checkout's plugin/ inside the guest and install it.
#   1. shallow checkout of opnsense/plugins at PLUGINS_COMMIT (vm.env) in /root/plugins
#   2. rsync plugin/dns/dnscrypt-routes/ to /root/plugins/dns/dnscrypt-routes/ (--delete)
#   3. make package, then install or upgrade with pkg add (lib/guest/deploy.sh)
# Prints the package name, version and SHA-256.

# shellcheck source=cmd-provision.sh
. "$VM_DIR/lib/cmd-provision.sh"

cmd_deploy() {
  [ $# -eq 0 ] || usage_err "usage: vm deploy"
  require_lock
  require_not_tainted
  require_vm_up
  local src="$VM_WORKTREE/plugin/dns/dnscrypt-routes"
  [ -f "$src/Makefile" ] || die "no plugin source at $src"
  case "$PLUGINS_COMMIT" in
    *[!0-9a-f]*|'') die "PLUGINS_COMMIT in vm.env must be a full commit hash" ;;
  esac
  [ "${#PLUGINS_COMMIT}" -eq 40 ] || die "PLUGINS_COMMIT in vm.env must be a full commit hash"
  # rsync -e takes one command string; a key path with blanks would be split
  case "$SSH_KEY" in *[[:space:]]*) die "SSH_KEY path contains blanks, which rsync -e cannot pass" ;; esac
  # provision leaves the baseline snapshot and the packages the build needs; without them the DNS wait
  # below would only time out
  { has_baseline && gssh "pkg info -e os-dnscrypt-proxy && test -x /usr/local/bin/rsync && test -x /usr/local/bin/git"; } \
    || die "VM not provisioned; run 'vm provision' first"

  # right after a boot (reset, update) DNSCrypt needs a minute before Unbound can resolve github.com
  wait_noerror "(Unbound)"
  log "checking out opnsense/plugins $PLUGINS_COMMIT in the guest"
  guest_sh deploy.sh checkout "$PLUGINS_COMMIT" >&2 || die "plugins checkout failed"

  log "rsync $src/ -> guest:/root/plugins/dns/dnscrypt-routes/"
  ssh_opts
  rsync -a --delete --exclude /work/ --exclude __pycache__/ --exclude .DS_Store \
    --rsync-path=/usr/local/bin/rsync -e "ssh ${SSH_OPTS[*]}" \
    "$src/" root@127.0.0.1:/root/plugins/dns/dnscrypt-routes/ || die "rsync failed"

  log "building and installing the package (make package, pkg add)"
  local out name version sha file
  out="$(guest_sh deploy.sh build)" || die "build or install failed"
  read -r name version sha file <<< "$(printf '%s\n' "$out" | tail -n 1)"
  [ -n "$file" ] || die "unexpected build output: $out"
  log "installed $name $version"
  echo "package: ${file##*/}"
  echo "sha256 : $sha"
}
