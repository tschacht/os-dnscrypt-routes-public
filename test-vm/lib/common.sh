#!/usr/bin/env bash
# Shared helpers for test-vm/vm. Sourced; defines no commands.
unset CDPATH

die()  { echo "vm: $*" >&2; exit 1; }
usage_err() { echo "vm: $*" >&2; exit 2; }
log()  { echo "vm: $*" >&2; }

# Settings come from vm.env (C-07). The environment overrides only VM_STATE_DIR (C-07), so ordinary
# exported names such as SSH_KEY or VM_NAME never leak in. For local runs any vm.env key can be overridden
# explicitly with a VM_ENV_ prefix (e.g. VM_ENV_SSH_PORT=22222, VM_ENV_RAM_SIZE=2G). Only plain KEY=VALUE
# lines are read; values may reference $VM_STATE_DIR.
load_env() {
  local line key val ovr
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in VM_STATE_DIR) continue ;; *[!A-Z0-9_]*|'') die "vm.env: bad line '$line'" ;; esac
    ovr="VM_ENV_$key"
    if [ -n "${!ovr+x}" ]; then
      val="${!ovr}"
    else
      eval "val=\"$val\""
    fi
    printf -v "$key" '%s' "$val"
    export "${key?}"
  done < "$VM_DIR/vm.env"
}

# VM_STATE_DIR: environment, then vm.env, then <main checkout>/work/vm-state (C-07). It must be absolute,
# so the scripts, compose bind mounts and docker run -v all see the same directory from any cwd.
resolve_state_dir() {
  if [ -z "${VM_STATE_DIR:-}" ]; then
    local v
    v="$(sed -n 's/^VM_STATE_DIR=//p' "$VM_DIR/vm.env" | tail -n 1)"
    [ -n "$v" ] && VM_STATE_DIR="$v"
  fi
  if [ -z "${VM_STATE_DIR:-}" ]; then
    VM_STATE_DIR="$(default_state_dir)" || usage_err "cannot locate the main checkout (git rev-parse failed)"
  fi
  case "$VM_STATE_DIR" in
    *[[:cntrl:]]*) usage_err "VM_STATE_DIR must not contain control characters (newline, tab, ...)" ;;
    /*) ;;
    *) usage_err "VM_STATE_DIR must be an absolute path, got '$VM_STATE_DIR'" ;;
  esac
  # drop trailing slashes so every caller derives the same paths and lock identity
  while [ "${#VM_STATE_DIR}" -gt 1 ] && [ "${VM_STATE_DIR%/}" != "$VM_STATE_DIR" ]; do VM_STATE_DIR="${VM_STATE_DIR%/}"; done
  # From here on VM_STATE_DIR is the physical path and every derived path uses it; the spelling the
  # user gave is kept only for messages, under a name nothing else uses.
  VM_STATE_DIR_RAW="$VM_STATE_DIR"
  VM_STATE_DIR="$(physical_path "$VM_STATE_DIR_RAW")" \
    || usage_err "VM_STATE_DIR must not contain . or .. components and must resolve, got '$VM_STATE_DIR_RAW'"
  export VM_STATE_DIR VM_STATE_DIR_RAW
}

# Physical form of an absolute path that may not exist yet: the nearest existing ancestor is resolved
# (cd -P, so symlinks such as macOS /tmp are followed), the missing tail is appended. . and .. are refused.
physical_path() {
  local p="$1" rest="" head
  case "$p/" in */./*|*/../*) return 1 ;; esac
  while [ ! -d "$p" ]; do
    rest="/${p##*/}$rest"
    p="${p%/*}"
    [ -n "$p" ] || p=/
  done
  head="$(canonical_dir "$p")" || return 1
  [ "$head" = / ] && head=""
  printf '%s\n' "$head$rest"
}

# The main checkout is the parent of the git common dir (C-07); prints nothing and fails if unknown.
main_checkout() {
  local common
  common="$(cd -P -- "$VM_DIR" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  case "$common" in /?*) ;; *) return 1 ;; esac
  dirname -- "$common"
}

default_state_dir() {
  local main
  main="$(main_checkout)" || return 1
  echo "$main/work/vm-state"
}

# Physical absolute path of an existing directory, or failure (never the cwd for an empty argument).
# A sentinel keeps $(...) from stripping trailing newlines; paths with control characters are refused.
canonical_dir() {
  local d
  [ -n "${1:-}" ] || return 1
  d="$(cd -P -- "$1" 2>/dev/null && pwd -P && echo .)" || return 1
  d="${d%.}"; d="${d%?}"
  case "$d" in /*) ;; *) return 1 ;; esac
  case "$d" in *[[:cntrl:]]*) return 1 ;; esac
  printf '%s\n' "$d"
}

# A state directory carries this marker; destroy removes only marked directories (or the default one).
STATE_MARKER=".vm-state-dir"

# The single list of entries vm creates in a state directory (C-07 "generated", plus the marker), in
# removal order: destroy --all removes exactly these by name, lock/ last, then rmdir's the directory.
# console.log and console.exp live in disk/. New top-level state entries belong under disk/ or images/;
# anything else needs a fix packet for this list.
STATE_ENTRIES="disk images golden.qcow2 vm_ed25519 vm_ed25519.pub api.env $STATE_MARKER lock"
is_state_entry() {
  local e
  for e in $STATE_ENTRIES; do [ "$1" = "$e" ] && return 0; done
  return 1
}

# Status 0: empty, 1: not empty, 2: cannot be listed or is a symlink (callers treat 2 as "refuse").
# Callers pass the physical path.
dir_is_empty() {
  local out
  [ ! -L "$1" ] && [ -d "$1" ] && [ -r "$1" ] && [ -x "$1" ] || return 2
  out="$(find "$1" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" || return 2
  [ -z "$out" ]
}

# Prints the names of entries in <dir> that vm does not create, one per line; fails if <dir> cannot be listed.
foreign_entries() {
  local dir="$1" p n
  dir_is_empty "$dir" && return 0
  [ $? -eq 1 ] || return 1
  for p in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
    [ -e "$p" ] || [ -L "$p" ] || continue
    n="${p##*/}"
    is_state_entry "$n" || printf '%s\n' "$n"
  done
}

# Check before any change: vm never creates symlinks, so a named entry that is one is refused (the
# link is never followed, written through or removed). Dies with "nothing removed".
check_no_symlinks() {
  local e
  for e in $STATE_ENTRIES; do
    [ -L "$1/$e" ] && die "'$1/$e' is a symbolic link, which vm never creates; refusing (nothing removed)"
  done
  [ -L "$1/lock/holder" ] && die "'$1/lock/holder' is a symbolic link, which vm never creates; refusing (nothing removed)"
  return 0
}

# Check before any change: lock/ must be what `vm lock` wrote, a real directory holding exactly a
# regular file named holder. Dies with "nothing removed".
check_lock_dir() {
  local l="$1/lock" out
  [ -d "$l" ] && [ ! -L "$l" ] || die "'$l' is not a lock directory written by vm (nothing removed)"
  [ -f "$l/holder" ] && [ ! -L "$l/holder" ] || die "'$l' has no regular holder file, so it is not a vm lock (nothing removed)"
  out="$(find "$l" -mindepth 1 -maxdepth 1 ! -name holder -print 2>/dev/null)" || die "cannot list '$l' (nothing removed)"
  [ -z "$out" ] || die "'$l' holds entries that vm did not write (nothing removed)"
}

# Sets MAIN_CHECKOUT and DEFAULT_STATE_DIR for the guards below, or exits 2: the guards fail closed.
require_guards() {
  MAIN_CHECKOUT="$(main_checkout)" \
    || usage_err "cannot locate the main checkout (git rev-parse failed); refusing to touch any state directory"
  DEFAULT_STATE_DIR="$MAIN_CHECKOUT/work/vm-state"
  case "${HOME:-}" in
    /?*) ;;
    *) usage_err "HOME must be set to an absolute path; refusing to touch any state directory" ;;
  esac
}

# True when <dir> is /, $HOME or the main checkout, or contains one of them. Compared by identity (-ef:
# same device and inode), so case-insensitive spellings, symlinks and firmlinks cannot slip past.
# Needs require_guards first.
is_guarded_dir() {
  local dir="$1" g a up
  # each guard as given and as its physical path: their lexical ancestors differ when the guard is
  # spelled through a symlink (FreeBSD /home -> /usr/home)
  for g in / "$HOME" "$(canonical_dir "$HOME" || true)" "$MAIN_CHECKOUT" "$(canonical_dir "$MAIN_CHECKOUT" || true)"; do
    [ -n "$g" ] || continue
    a="$g"
    while :; do
      [ "$dir" -ef "$a" ] && return 0
      up="$(dirname -- "$a")"
      [ "$up" = "$a" ] && break
      a="$up"
    done
  done
  return 1
}

# The state directory if it may be touched: it exists, still resolves to the physical path everything
# was derived from, is not guarded, and is either the default directory or carries a regular marker.
# Needs require_guards first. Prints the path on success.
safe_state_dir() {
  local dir
  dir="$(canonical_dir "$VM_STATE_DIR")" || return 1
  [ "$dir" = "$VM_STATE_DIR" ] || return 1
  is_guarded_dir "$dir" && return 1
  if { [ -f "$dir/$STATE_MARKER" ] && [ ! -L "$dir/$STATE_MARKER" ]; } || [ "$dir" -ef "$DEFAULT_STATE_DIR" ]; then
    printf '%s\n' "$dir"
    return 0
  fi
  return 1
}

# Remove a lock directory after check_lock_dir passed: its holder file, then rmdir (never recursive).
remove_lock_dir() {
  rm -f -- "$1/lock/holder"
  rmdir -- "$1/lock" || die "could not remove '$1/lock'"
}

# Create the state directory if needed and mark it. A guarded directory, an existing non-empty
# directory without the marker, or one that cannot be listed is refused, so a mistyped VM_STATE_DIR
# (e.g. $HOME) never becomes a state directory. Works on the physical path only.
ensure_state_dir() {
  require_guards
  if [ -e "$VM_STATE_DIR" ] || [ -L "$VM_STATE_DIR" ]; then
    [ -d "$VM_STATE_DIR" ] && [ ! -L "$VM_STATE_DIR" ] || usage_err "VM_STATE_DIR '$VM_STATE_DIR_RAW' is not a directory; refusing"
  else
    mkdir -p -- "$VM_STATE_DIR"
  fi
  [ "$(canonical_dir "$VM_STATE_DIR")" = "$VM_STATE_DIR" ] \
    || usage_err "VM_STATE_DIR '$VM_STATE_DIR_RAW' no longer resolves to '$VM_STATE_DIR'; refusing"
  if is_guarded_dir "$VM_STATE_DIR"; then
    usage_err "VM_STATE_DIR '$VM_STATE_DIR_RAW' is /, \$HOME or the main checkout, or contains one; refusing"
  fi
  [ -L "$VM_STATE_DIR/$STATE_MARKER" ] && usage_err "'$VM_STATE_DIR/$STATE_MARKER' is a symbolic link; refusing"
  [ -f "$VM_STATE_DIR/$STATE_MARKER" ] && return 0
  local empty=0
  dir_is_empty "$VM_STATE_DIR" || empty=$?
  [ "$empty" -ne 2 ] || usage_err "VM_STATE_DIR '$VM_STATE_DIR_RAW' cannot be listed; refusing"
  if [ "$empty" -eq 0 ] || [ "$VM_STATE_DIR" -ef "$DEFAULT_STATE_DIR" ]; then
    : > "$VM_STATE_DIR/$STATE_MARKER"; return 0
  fi
  usage_err "VM_STATE_DIR '$VM_STATE_DIR_RAW' exists, is not empty and is not a VM state directory (no $STATE_MARKER)"
}

resolve_state_dir
load_env
export VM_NAME OPNSENSE_VERSION IMAGE_URL IMAGE_SHA256 PLUGINS_COMMIT SSH_PORT HTTPS_PORT VNC_PORT NAT_NET ROOT_PASSWORD SSH_KEY RAM_SIZE

# Root of the checkout this script lives in; identifies the lock holder's worktree.
VM_WORKTREE="$(cd "$VM_DIR/.." && pwd -P)"
LOCK_DIR="$VM_STATE_DIR/lock"
DISK_DIR="$VM_STATE_DIR/disk"
IMAGES_DIR="$VM_STATE_DIR/images"
COMPOSE_FILE="$VM_DIR/compose.yaml"

export DISK_DIR IMAGES_DIR
export QEMU_IMAGE_REF="qemux/qemu@sha256:099637a6a59cc1fe7bb1b71780e24cf41c1f68cc484f3e6f7d8bb1e7bee6d019"

# The marker `vm restore` writes after importing a configuration with foreign credentials (WP-06).
# Only `vm destroy` may follow, so the commands that would use or start the VM refuse.
vm_tainted() { [ -e "$DISK_DIR/tainted" ]; }
TAINT_MESSAGE="the VM is tainted by a configuration import with foreign credentials ('vm restore'); only 'vm destroy' may follow"
die_if_tainted() { ! vm_tainted || die "$TAINT_MESSAGE"; }

compose() {
  docker compose -f "$COMPOSE_FILE" --project-directory "$VM_DIR" -p "$VM_NAME" "$@"
}

lock_field() { sed -n "s/^$1=//p" "$LOCK_DIR/holder" 2>/dev/null | head -n 1; }

lock_holder_desc() {
  if [ -d "$LOCK_DIR" ]; then
    echo "packet=$(lock_field packet) agent=$(lock_field agent) worktree=$(lock_field worktree) since=$(lock_field time)"
  else
    echo "none"
  fi
}

# True when the lock exists and was taken from this worktree.
lock_is_mine() {
  [ -d "$LOCK_DIR" ] && [ ! -L "$LOCK_DIR" ] && [ "$(lock_field worktree)" = "$VM_WORKTREE" ]
}

# Every mutating command calls this first (exit 3 without the lock).
require_lock() {
  if [ ! -d "$LOCK_DIR" ]; then
    echo "vm: no VM lock held; run 'test-vm/vm lock <ID>' first" >&2
    exit 3
  fi
  if ! lock_is_mine; then
    echo "vm: VM lock held by another worktree: $(lock_holder_desc)" >&2
    exit 3
  fi
}

container_exists() { [ -n "$(docker ps -aq --filter "name=^${VM_NAME}\$")" ]; }
container_running() { [ -n "$(docker ps -q --filter "name=^${VM_NAME}\$")" ]; }

# usage: ssh_opts [interactive]   sets SSH_OPTS; BatchMode=yes unless interactive (ssh keeps the first value)
ssh_opts() {
  SSH_OPTS=(-i "$SSH_KEY" -p "$SSH_PORT" -o IdentitiesOnly=yes -o IdentityAgent=none
            -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
            -o ConnectTimeout=10)
  [ "${1:-}" = interactive ] || SSH_OPTS+=(-o BatchMode=yes)
}

ssh_ready() { ssh_opts; ssh "${SSH_OPTS[@]}" root@127.0.0.1 true >/dev/null 2>&1; }

wait_ssh() {
  local timeout="${1:-1800}" start now
  start=$(date +%s)
  while :; do
    ssh_ready && return 0
    container_running || die "container ${VM_NAME} is not running (docker logs ${VM_NAME})"
    now=$(date +%s)
    [ $((now - start)) -ge "$timeout" ] && die "timed out after ${timeout}s waiting for SSH on 127.0.0.1:${SSH_PORT}"
    sleep 10
  done
}

# Run shell commands on the guest through the serial console (login root, then sh).
# usage: console_run <timeout-seconds> <command>...   Prints output; stops at the first failing command and
# returns its status (0 if all succeed, 255 on console failure). Logs in with the stock "opnsense" (unseeded guest), falling back to ROOT_PASSWORD (seeded
# guest). The session is appended to $DISK_DIR/console.log. The expect script is embedded here because
# the console is only needed by create/provision, and lib/ files are owned per packet.
console_run() {
  local total="$1"; shift
  local script="$DISK_DIR/console.exp"
  # the script lives in disk/, so an interrupted run leaves nothing outside $VM_STATE_DIR (destroy removes it)
  mkdir -p "$DISK_DIR"
  cat > "$script" <<'EXPECT'
set container [lindex $argv 0]
# the password comes through the environment, not argv (host process list)
set passes [list opnsense $env(VM_CONSOLE_ROOT_PASSWORD)]
set logfile [lindex $argv 1]
set total [lindex $argv 2]
set cmds [lrange $argv 3 end]
set timeout $total
set pi 0
log_user 0
# no local echo on the spawn pty (docker exec -i has no tty): it would echo the password back into the log
set stty_init -echo
log_file -a $logfile
set deadline [expr {[clock seconds] + $total}]
set connected 0
while {!$connected} {
  # the socket accepts one client; drop leftovers of an earlier session
  catch {exec docker exec $container pkill -f {nc -U /run/serial.sock}}
  spawn docker exec -i $container timeout [expr {$total + 60}] nc -U /run/serial.sock
  set status 255
  # Never type while the guest is booting: the tty buffers keys, a key during the loader countdown
  # stops autoboot, and a key at "Press any key to start the configuration importer" starts the
  # interactive importer, whose zpool probe hangs. Enter is sent only at the loader menu, or once
  # when nothing at all has arrived for 20 s on this connection (the guest already sits at a prompt).
  set seen 0
  set timeout 20
  expect {
    -re {login: $} { set seen 1; send "root\r"; exp_continue }
    -re {Password:$} {
      # keep the password out of console.log: log_file also records what is sent
      set seen 1; log_file; send "[lindex $passes [expr {$pi % 2}]]\r"; log_file -a $logfile; incr pi; exp_continue
    }
    -re {Enter an option: $} { send "8\r"; expect -re {root@[^\r\n]*# $}; set connected 1 }
    -re {root@[^\r\n]*# $} { set connected 1 }
    -re {VMSH> $} { set connected 1 }
    -re {Boot Multi user} { set seen 1; send "\r"; exp_continue }
    -re {\n} {
      # boot output: note it, check the deadline, keep waiting
      set seen 1
      if {[clock seconds] > $deadline} { puts stderr "console: timed out waiting for login"; exit 255 }
      exp_continue
    }
    timeout {
      if {[clock seconds] > $deadline} { puts stderr "console: timed out waiting for login"; exit 255 }
      if {!$seen} { set seen 1; send "\r" }
      exp_continue
    }
    eof {
      # container or socket not up yet: retry until the deadline
      if {[clock seconds] > $deadline} { puts stderr "console: connection closed"; exit 255 }
      catch {close}; catch {wait}
      sleep 5
    }
  }
}
set timeout $total
# root's login shell is csh; use sh so that $? works
send "exec sh\r"
sleep 2
send "PS1='VMSH> '\r"
expect -re {VMSH> $}
foreach c $cmds {
  send "$c; echo __DONE_\$?__\r"
  expect {
    -re {__DONE_([0-9]+)__} { set status $expect_out(1,string) }
    timeout { puts stderr "console: timed out running: $c"; exit 255 }
    eof { puts stderr "console: connection closed while running: $c"; exit 255 }
  }
  set out $expect_out(buffer)
  regsub {__DONE_[0-9]+__.*$} $out "" out
  foreach l [split $out "\n"] {
    if {[string first {__DONE_$?__} $l] >= 0} continue
    puts [string trimright $l "\r"]
  }
  # stop at the first failing command
  if {$status != 0} break
}
send "exit\r"
sleep 1
exit $status
EXPECT
  local rc=0
  VM_CONSOLE_ROOT_PASSWORD="$ROOT_PASSWORD" expect -f "$script" "$VM_NAME" "$DISK_DIR/console.log" "$total" "$@" || rc=$?
  rm -f "$script"
  return "$rc"
}
