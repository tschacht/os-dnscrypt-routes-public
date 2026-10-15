"""Runs in the guest (vm test, via `python3 - <cmd>` on stdin). Prints JSON facts about the live service.

  snap               config/TOML hashes, service pid, live log inode/size, listeners, dnscrypt-proxy processes
                     (side: the Save & Test instance), sandbox, catalog
  log OFFSET         lines of the live log from byte OFFSET that mention the side instance (5354, sandbox)
  block              service pid; for the last startup block of the live log: its time (epoch), whether the
                     public-resolvers source loaded (past the network wait), the last FATAL line, live
                     servers, servers OK (with protocol), routes
  watch STOPFILE     follow the live log until STOPFILE exists (at most 600 s; STOPFILE.ready is written once
                     it runs): startup lines seen and service pids seen. dnscrypt-proxy truncates its log at
                     each start, so restarts cannot be counted from the file afterwards.
  toml               owned keys of the generated dnscrypt-proxy.toml (tomllib), plus its first line
  leftovers          plugin files outside /var/db and /var/run (path names containing dnscrypt-routes and
                     its spellings), skipping the build tree /root/plugins and core's compiled Volt template
                     cache /var/lib/php/cache (core writes it for every page viewed and keeps it)
Only the standard library; reads files and runs sockstat/ps, changes nothing.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

CONFIG = "/conf/config.xml"
GENERATED = "/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
LIVE_DIR = "/usr/local/etc/dnscrypt-proxy"
LOG = "/var/log/dnscrypt-proxy/dnscrypt-proxy.log"
PIDFILE = "/var/run/dnscrypt-proxy.pid"
SANDBOX = "/var/run/dnscrypt-routes/test"
PREFIX = re.compile(r"^\[[^\]]*\]\s+\[[A-Z]+\]\s+")
STARTUP = re.compile(r"^dnscrypt-proxy \d+\.\d+")
OK = re.compile(r"^\[([^\]]+)\] OK \(([^)]*)\)")
ROUTE = re.compile(r"^Anonymizing queries for \[([^\]]+)\] via \[([^\]]+)\]")
LIVE = re.compile(r"live servers: (\d+)")
NAME = re.compile(r"dnscrypt[-_]?routes", re.I)


def sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def lines_from(offset=0):
    try:
        with open(LOG, "rb") as fh:
            fh.seek(offset)
            return [PREFIX.sub("", l, count=1) for l in fh.read().decode("utf-8", "replace").splitlines()]
    except OSError:
        return []


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode("utf-8", "replace")


def listeners(port):
    """[(pid, local address)] of sockets listening/bound on <port> (sockstat -l)."""
    out = []
    for line in run(["sockstat", "-46l", "-p", str(port)]).splitlines()[1:]:
        f = line.split()
        if len(f) >= 6 and f[2].isdigit():
            out.append([int(f[2]), f[5]])
    return sorted(out)


def service_pid():
    try:
        pid = int(open(PIDFILE).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def snap():
    pid = service_pid()
    procs, side = [], []
    for line in run(["ps", "-axww", "-o", "pid=", "-o", "comm=", "-o", "command="]).splitlines():
        f = line.split(None, 2)
        if len(f) == 3 and f[1] == "dnscrypt-proxy":
            procs.append(int(f[0]))
            if SANDBOX + "/work/" in f[2] and " -check" not in f[2]:
                side.append(int(f[0]))
    try:
        st = os.stat(LOG)
        log = {"inode": st.st_ino, "size": st.st_size}
    except OSError:
        log = None
    catalog = {}
    for name in sorted(os.listdir(LIVE_DIR)):
        if name.endswith(".md") or name.endswith(".md.minisig"):
            catalog[name] = sha(os.path.join(LIVE_DIR, name))
    return {"config": sha(CONFIG), "toml": sha(GENERATED), "pid": pid, "procs": sorted(procs), "side": side,
            "log": log,
            "l5353": listeners(5353), "l5354": listeners(5354), "sandbox": os.path.exists(SANDBOX),
            "catalog": catalog}


def log_since(offset):
    lines = lines_from(offset)
    return {"side": [l for l in lines if "127.0.0.1:5354" in l or SANDBOX in l]}


def block():
    try:
        raw = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        raw = []
    lines = [PREFIX.sub("", l, count=1) for l in raw]
    start = 0
    for i, l in enumerate(lines):
        if STARTUP.match(l):
            start = i
    since = None
    try:
        since = int(time.mktime(time.strptime(raw[start][1:20], "%Y-%m-%d %H:%M:%S")))
    except (IndexError, ValueError):
        pass
    live, ok, routes, loaded, fatal = None, {}, {}, False, None
    for r, l in zip(raw[start:], lines[start:]):
        if l.startswith("Source [public-resolvers] loaded"):
            loaded = True
        if "] [FATAL] " in r:
            fatal = l
        m = OK.match(l)
        if m:
            ok[m.group(1)] = m.group(2)
        m = ROUTE.match(l)
        if m:
            routes.setdefault(m.group(1), []).append(m.group(2))
        m = LIVE.search(l)
        if m:
            live = int(m.group(1))
    return {"pid": service_pid(), "since": since, "loaded": loaded, "fatal": fatal, "live": live, "ok": ok,
            "routes": routes}


def first_line():
    try:
        with open(LOG, "rb") as fh:
            return fh.readline()
    except OSError:
        return b""


def watch(stop):
    pos, head, buf, starts, pids = 0, first_line(), b"", 0, []
    try:
        pos = os.path.getsize(LOG)
    except OSError:
        pass
    open(stop + ".ready", "w").close()
    end = time.time() + 600
    while time.time() < end:
        try:
            size = os.path.getsize(LOG)
        except OSError:
            size = 0
        now = first_line()
        if size < pos or now != head:  # truncated or replaced at a start
            pos, head, buf = 0, now, b""
        if size > pos:
            with open(LOG, "rb") as fh:
                fh.seek(pos)
                chunk = fh.read(size - pos)
            pos += len(chunk)
            parts = (buf + chunk).split(b"\n")
            buf = parts.pop()
            starts += sum(1 for l in parts if STARTUP.match(PREFIX.sub("", l.decode("utf-8", "replace"), count=1)))
        pid = service_pid()
        if pid is not None and pid not in pids:
            pids.append(pid)
        if os.path.exists(stop):
            break
        time.sleep(0.1)
    return {"starts": starts, "pids": pids}


def toml():
    import tomllib
    try:
        raw = open(GENERATED, "rb").read()
    except OSError:
        return {"exists": False}
    out = {"exists": True, "first_line": raw.decode("utf-8", "replace").split("\n", 1)[0]}
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        out["error"] = str(exc)
        return out
    anon = data.get("anonymized_dns", {})
    for key in ("server_names", "lb_strategy", "edns_client_subnet", "dnscrypt_servers", "doh_servers",
                "odoh_servers"):
        out[key] = data.get(key)
    for key in ("routes", "skip_incompatible", "direct_cert_fallback"):
        out[key] = anon.get(key)
    return out


def leftovers():
    found = []
    for top in ("/usr/local", "/etc", "/var", "/boot", "/conf", "/root"):
        for root, dirs, files in os.walk(top):
            skip = ("/var/db", "/var/run", "/root/plugins", "/var/lib/php/cache")
            if root in skip or root.startswith(tuple(s + "/" for s in skip)):
                dirs[:] = []
                continue
            for name in dirs + files:
                if NAME.search(name):
                    found.append(os.path.join(root, name))
    return sorted(found)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "snap":
        out = snap()
    elif cmd == "log" and len(argv) == 3:
        out = log_since(int(argv[2]))
    elif cmd == "block":
        out = block()
    elif cmd == "watch" and len(argv) == 3:
        out = watch(argv[2])
    elif cmd == "toml":
        out = toml()
    elif cmd == "leftovers":
        out = leftovers()
    else:
        sys.stderr.write("usage: probe.py snap | log OFFSET | block | watch STOPFILE | toml | leftovers\n")
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
