#!/usr/bin/env python3
"""Save & Test backend: run a throw-away dnscrypt-proxy in a sandbox (R-13, C-04, C-06).

Subcommands (configd actions call these):
  start   detached; refuses with reason "already-running" while a run is active (C-02)
  status  print the C-04 result
  run     the foreground worker started by `start`

The side instance listens on 127.0.0.1:5354 only. Everything it writes (config, log, catalog
copies) lives in the sandbox /var/run/dnscrypt-routes/test/, which is deleted at the end.
The live config, log, catalog cache and listener are never touched.

Log format (dnscrypt-proxy 2.1.15, https://github.com/DNSCrypt/dnscrypt-proxy/tree/2.1.15/dnscrypt-proxy):
  dnscrypt_certs.go:180,182  "[%s] OK (DNSCrypt) - rtt: %dms%s"   (Notice when new, Info otherwise)
  dnscrypt_certs.go:71       "[%s] TIMEOUT"
  dnscrypt_certs.go:92,109,116,88  per-server certificate warnings ("[%v] Invalid cert magic", ...)
  serversInfo.go:950,952     "[%s] OK (DoH) - rtt: %dms"
  serversInfo.go:1129,1131   "[%s] OK (ODoH) - rtt: %dms"
  serversInfo.go:651,688     "Anonymizing queries for [%v] via [%v]"   (one line per relay route)
  serversInfo.go:739,742     "[%v] couldn't be reached anonymously"
  serversInfo.go:593         "Server [%v]'s protocol doesn't support anonymization"
  serversInfo.go:291         "... (rtt: %dms), live servers: %d"
Each line is prefixed by dlog as "[YYYY-MM-DD HH:MM:SS] [LEVEL] ".
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import secrets
import signal
import subprocess
import sys
import threading
import time

RUN_DIR = "/var/run/dnscrypt-routes"          # C-06
LIVE_DIR = "/usr/local/etc/dnscrypt-proxy"    # live config dir; catalogs are cached here
RENDERED_CONFIG = "usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml"  # target of the 95-dnscrypt-routes mapping
CORE_SERVICE = "/usr/local/opnsense/service"   # holds core's `modules` package (configd's sys.path entry)
CORE_CONFIG = "/conf/config.xml"
FAIL_CLOSED_MARKERS = ("invariant-violated", "override-not-applied")  # C-06 first lines of a refused render
NOTE_CAP = 1500                                # longest failure note appended to check.output
DEFAULT_BINARY = "/usr/local/sbin/dnscrypt-proxy"
DEFAULT_DEADLINE = 90.0
LISTEN = "127.0.0.1:5354"
DRILL = "drill"
QUERIES = [("example.com", "A"), ("example.org", "AAAA"), ("dnscrypt.info", "A")]
DROPPED_SECTIONS = ("query_log", "nx_log", "local_doh", "monitoring_ui")
MARKER_CONSEQUENCE = {
    "override-not-applied": "Apply would stop DNS (fail closed): the stock os-dnscrypt-proxy template no longer "
                            "has the lines this plugin patches. Update os-dnscrypt-routes, or untick Enable "
                            "anonymized routing.",
    "invariant-violated": "Apply would stop DNS (fail closed): the saved routes break the relay-only rule; "
                          "fix them first.",
}
ERRORS = ("timeout", "check-failed", "crashed")


class TestFailure(Exception):
    """The run ends as failed with one of the C-04 error codes."""

    __test__ = False  # not a pytest class

    def __init__(self, code, message=""):
        Exception.__init__(self, message or code)
        self.code = code


# --------------------------------------------------------------------------- paths and time

def sandbox_dir():
    return os.path.join(RUN_DIR, "test")


def result_path():
    return os.path.join(RUN_DIR, "test-result.json")


def lock_path():
    return os.path.join(sandbox_dir(), "lock")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Deadline:
    def __init__(self, seconds):
        self.seconds = seconds
        self.end = time.monotonic() + seconds

    def remaining(self):
        return self.end - time.monotonic()

    def check(self):
        if self.remaining() <= 0:
            raise TestFailure("timeout", "deadline of %gs passed" % self.seconds)


def deadline_seconds():
    try:
        value = float(os.environ.get("DNSCRYPT_ROUTES_TEST_DEADLINE", ""))
        if value > 0:
            return value
    except ValueError:
        pass
    return DEFAULT_DEADLINE


# --------------------------------------------------------------------------- result file (C-04)

def new_result(state="idle"):
    return {"state": state, "started": None, "finished": None, "duration_s": None, "error": None,
            "check": {"ok": False, "output": ""}, "live_servers": None, "resolvers": [], "queries": []}


def write_result(result):
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = "%s.tmp.%d" % (result_path(), os.getpid())
    with open(tmp, "w") as handle:
        json.dump(result, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, result_path())


def read_result():
    try:
        with open(result_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return new_result()


# --------------------------------------------------------------------------- lock
# The lock file test/lock names the owning worker (pid, token). Orphans of a dead worker are found by
# the sandbox path on their command line, not by a remembered pid. Every change to the lock or the
# sandbox happens while holding `guard()`, an flock on RUN_DIR/guard.lock that the OS drops when its
# holder dies. That serialises starters, stale takeover, status and release, so exactly one starter wins.

@contextlib.contextmanager
def guard():
    os.makedirs(RUN_DIR, exist_ok=True)
    fd = os.open(os.path.join(RUN_DIR, "guard.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock():
    """The lock's JSON, {} if unreadable, None if there is no lock."""
    try:
        with open(lock_path()) as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _pid_runs_token(pid, token):
    """True if `pid` is alive and, unless it is this very process, carries the run's token in its
    command line (the worker is started as `testrun.py run --token T`), so a reused pid does not count."""
    if not _pid_alive(pid):
        return False
    if pid == os.getpid() or not token:
        return True
    try:
        out = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot tell: refuse a second run rather than allow one
    return token in out.decode(errors="replace").split()


def lock_active():
    data = read_lock()
    if data is None:
        return False
    try:
        return _pid_runs_token(int(data["pid"]), data.get("token"))
    except (KeyError, TypeError, ValueError):
        try:
            return time.time() - os.path.getmtime(lock_path()) < 10  # half-written lock
        except OSError:
            return False


def _write_lock(data):
    tmp = "%s.%d" % (lock_path(), os.getpid())
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, lock_path())


def wipe_sandbox():
    """Delete the sandbox including the lock. Caller holds guard()."""
    shutil.rmtree(sandbox_dir(), ignore_errors=True)


def _is_ours(command, sandbox):
    """The command lines our own children carry: `... -config <sandbox>/work/...` (instance, -check)
    and `... render <sandbox>/render ...` (core render). A bystander that merely mentions the sandbox
    path (tail, ls, ssh) does not match."""
    sb = re.escape(sandbox.rstrip("/"))
    return bool(re.search(r"(?:^|\s)-config %s/work/\S+(?:\s|$)" % sb, command)
                or re.search(r"(?:^|\s)render %s/render(?:\s|$)" % sb, command))


def sandbox_pids():
    """Pids of our own sandbox children (see _is_ours). Matching on the command line, never on a
    remembered pid or group, cannot hit an unrelated process after pid reuse."""
    sandbox = sandbox_dir()
    try:
        out = subprocess.run(["ps", "-axww", "-o", "pid=", "-o", "command="], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in out.decode(errors="replace").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and _is_ours(parts[1], sandbox) and int(parts[0]) != os.getpid():
            pids.append(int(parts[0]))
    return pids


def kill_sandbox_processes():
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = sandbox_pids()
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(0.3)


def reap_stale():
    """Caller holds guard(). If the lock's worker is dead: kill its orphaned instance and wipe the
    sandbox. Returns True when the sandbox is free (no lock or a stale one was removed)."""
    data = read_lock()
    if data is not None and lock_active():
        return False
    kill_sandbox_processes()  # orphans of a killed worker, wherever the kill caught it
    wipe_sandbox()
    return True


def _acquire_locked(token):
    """Caller holds guard(). Take the lock for `token`, or return False if a run is active."""
    if not reap_stale():
        return False
    os.makedirs(sandbox_dir(), exist_ok=True)
    fd = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"pid": os.getpid(), "token": token, "time": now_iso()}, handle)
    return True


def release_lock():
    with guard():
        wipe_sandbox()


# --------------------------------------------------------------------------- patch_config

_HEADER = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.'\" -]+?)\s*\]\]?\s*(#.*)?$")
_KEY = re.compile(r"^(\s*)(listen_addresses|log_file|cache_file|use_syslog|tls_key_log_file)\s*=\s*(.*)$")
# section -> key naming a list file that is read relative to the config dir but not rendered by the template
LIST_FILES = {"blocked_names": "blocked_names_file", "allowed_names": "allowed_names_file",
              "blocked_ips": "blocked_ips_file", "allowed_ips": "allowed_ips_file"}
_QUOTED = re.compile(r"""['"]([^'"]*)['"]""")


def _bracket_balance(text):
    depth, quote = 0, None
    for char in text:
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#":
            break
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _section_slug(section):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", section).strip("_") or "section"


def cache_file_names(text):
    """Base names of every cache_file in a rendered config."""
    names = []
    for line in text.splitlines():
        match = _KEY.match(line)
        if match and match.group(2) == "cache_file":
            quoted = _QUOTED.search(match.group(3))
            if quoted and os.path.basename(quoted.group(1)) not in names:
                names.append(os.path.basename(quoted.group(1)))
    return names


def provide_list_files(text, work):
    """Make the list files the config reads (e.g. blacklist.txt) available read-only in `work`.

    A file the template does not render is copied from LIVE_DIR; if the live file is missing too, its
    section is dropped so that -check does not fail on it. Returns the sections to drop."""
    drop = []
    for section, key in LIST_FILES.items():
        match = re.search(r"^\s*%s\s*=\s*['\"]([^'\"]+)['\"]" % key, text, re.M)
        if not match or os.path.isabs(match.group(1)):
            continue
        name = match.group(1)
        if os.path.basename(name) != name or name in (".", ".."):  # only plain names in the config dir
            drop.append(section)
            continue
        if os.path.exists(os.path.join(work, name)):
            continue
        source = os.path.join(LIVE_DIR, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(work, name))
        else:
            drop.append(section)
    return drop


def patch_config(text, tmpdir, drop_sections=()):
    """Make a rendered dnscrypt-proxy.toml safe to run beside the live service.

    Listen on 127.0.0.1:5354 only, write all logs into tmpdir, drop the query/nx logs (and the
    local DoH and monitoring listeners, and any section in drop_sections), drop tls_key_log_file and
    point every cache_file at tmpdir.
    """
    tmpdir = tmpdir.rstrip("/")
    lines = text.splitlines()
    out = []
    section = ""
    skipping = False
    seen_top = set()
    first_header = None
    i = 0
    while i < len(lines):
        line = lines[i]
        header = _HEADER.match(line)
        if header:
            name = header.group(1).replace("'", "").replace('"', "")
            section = name
            skipping = name in DROPPED_SECTIONS or name in drop_sections
            if first_header is None:
                first_header = len(out)
            if skipping:
                i += 1
                continue
        elif skipping:
            i += 1
            continue
        key = _KEY.match(line)
        if key is None:
            out.append(line)
            i += 1
            continue
        indent, name, value = key.groups()
        consumed = 1
        if name == "tls_key_log_file":  # would write TLS secrets outside the sandbox
            i += 1
            continue
        if name == "listen_addresses":
            joined = value
            while _bracket_balance(joined) > 0 and i + consumed < len(lines):
                joined += "\n" + lines[i + consumed]
                consumed += 1
            out.append("%slisten_addresses = ['%s']" % (indent, LISTEN))
        elif name == "log_file":
            slug = "dnscrypt-proxy" if not section else _section_slug(section)
            out.append("%slog_file = '%s/%s.log'" % (indent, tmpdir, slug))
        elif name == "use_syslog":
            out.append("%suse_syslog = false" % indent)
        else:  # cache_file
            quoted = _QUOTED.search(value)
            base = os.path.basename(quoted.group(1)) if quoted else "catalog.md"
            out.append("%scache_file = '%s/%s'" % (indent, tmpdir, base))
        if not section:
            seen_top.add(name)
        i += consumed
    missing = []
    if "listen_addresses" not in seen_top:
        missing.append("listen_addresses = ['%s']" % LISTEN)
    if "log_file" not in seen_top:
        missing.append("log_file = '%s/dnscrypt-proxy.log'" % tmpdir)
    if "use_syslog" not in seen_top:
        missing.append("use_syslog = false")
    at = len(out) if first_header is None else first_header
    out[at:at] = missing
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- parse_log

_PREFIX = re.compile(r"^\[[^\]]*\]\s+\[[A-Z]+\]\s+")
_OK = re.compile(r"^\[([^\]]+)\] OK \(([^)]*)\) - rtt: (\d+)ms")
_TIMEOUT = re.compile(r"^\[([^\]]+)\] TIMEOUT")
_ROUTE = re.compile(r"^Anonymizing queries for \[([^\]]+)\] via \[([^\]]+)\]")
_NOANON = re.compile(r"^\[([^\]]+)\] couldn't be reached anonymously")
_NOPROTO = re.compile(r"^Server \[([^\]]+)\]'s protocol doesn't support anonymization")
_CERT_ERR = re.compile(
    r"^\[([^\]]+)\] (Certificate too short|Invalid cert magic|Incorrect signature|"
    r"certificate ends before it starts|Certificate hash \S+ not found)")
_LIVE = re.compile(r"live servers: (\d+)")


def _strip(line):
    return _PREFIX.sub("", line.rstrip("\n"), count=1)


def parse_live_servers(lines):
    """Last `live servers: N` value in the log, or None."""
    value = None
    for line in lines:
        match = _LIVE.search(line)
        if match:
            value = int(match.group(1))
    return value


def parse_log(lines):
    """Per-resolver result entries (C-04 `resolvers`) in order of first appearance."""
    resolvers = {}
    order = []

    def entry(name):
        if name not in resolvers:
            resolvers[name] = {"name": name, "routes": [], "cert": "unknown", "rtt_ms": None,
                               "proto": "unknown", "direct": False, "pass": False}
            order.append(name)
        return resolvers[name]

    for raw in lines:
        line = _strip(raw)
        match = _ROUTE.match(line)
        if match:
            item = entry(match.group(1))
            if match.group(2) not in item["routes"]:
                item["routes"].append(match.group(2))
            continue
        match = _OK.match(line)
        if match:
            item = entry(match.group(1))
            item["cert"] = "ok"
            item["proto"] = match.group(2).strip().lower()
            item["rtt_ms"] = int(match.group(3))
            continue
        match = _TIMEOUT.match(line)
        if match:
            item = entry(match.group(1))
            if item["cert"] != "ok":
                item["cert"] = "timeout"
            continue
        match = _NOANON.match(line) or _NOPROTO.match(line)
        if match:  # a later reachability error invalidates an earlier OK
            entry(match.group(1))["cert"] = "error"
            continue
        match = _CERT_ERR.match(line)
        if match:
            item = entry(match.group(1))
            if item["cert"] != "ok":
                item["cert"] = "error"
    result = []
    for name in order:
        item = resolvers[name]
        item["direct"] = item["cert"] == "ok" and not item["routes"]
        item["pass"] = (item["cert"] == "ok" and item["proto"] == "dnscrypt"
                        and bool(item["routes"]) and not item["direct"])
        result.append(item)
    return result


def rendered_server_names(text):
    """Names in the top-level `server_names = [...]` of a rendered config (quote and comment aware, may span lines)."""
    start = re.search(r"(?m)^server_names[ \t]*=[ \t]*\[", text)
    if not start:
        return []
    names = []
    # quoted strings are consumed whole, so a `#` or `]` inside one is data; a `#` outside starts a comment
    for match in re.finditer(r"'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|(#[^\n]*)|(\])", text[start.end():]):
        if match.group(4):
            break
        if match.group(3):
            continue
        if match.group(1) is not None:
            names.append(match.group(1))
        else:
            names.append(re.sub(r"\\(.)", r"\1", match.group(2)))
    return names


def resolver_rows(lines, names):
    """parse_log rows plus a failing row for every listed name the log never mentions (dnscrypt-proxy skips
    unusable names silently: not in the catalog, or dropped by the forced doh/odoh filters)."""
    rows = parse_log(lines)
    seen = {row["name"] for row in rows}
    for name in names:
        if name and name not in seen:
            seen.add(name)
            rows.append({"name": name, "routes": [], "cert": "unknown", "rtt_ms": None,
                         "proto": "unknown", "direct": False, "pass": False})
    return rows


_ERROR_LINE = re.compile(r"\[(?:ERROR|CRITICAL|FATAL|WARNING)\]|\b(?:fatal|panic|error)\b", re.I)


def failure_note(message, work):
    """Short reason for check.output: the failure message plus the last error lines of the instance's log
    and stdout (capped)."""
    parts = [message]
    for name in ("dnscrypt-proxy.log", "stdout.log"):
        lines = [_strip(line) for line in _read_lines(os.path.join(work, name))]
        errors = [line for line in lines if _ERROR_LINE.search(line)]
        if not errors and name == "stdout.log":
            errors = lines[-2:]
        if errors:
            parts.append("%s: %s" % (name, " | ".join(errors[-3:])))
    return "\n".join(parts)[:NOTE_CAP]


# --------------------------------------------------------------------------- run steps

def _render_core(root, service=CORE_SERVICE, config=CORE_CONFIG):
    """Same calls as core's configd `template.reload` (modules/actions/inline.py): the package is imported as
    `modules.*` (its modules use package-relative imports) and the engine needs the parsed config.xml."""
    if service not in sys.path:
        sys.path.insert(0, service)
    from modules.config import Config  # noqa: E402  (OPNsense core)
    from modules.template import Template  # noqa: E402
    engine = Template(target_root_directory=root)
    engine.set_config(Config(config).get())
    if not engine.generate("OPNsense/Dnscryptproxy"):  # core returns None after logging the error to syslog
        raise RuntimeError("core Template.generate failed for OPNsense/Dnscryptproxy (see the system log)")


_RENDER = {"proc": None}


def render_with_core(root):
    """Render OPNsense/Dnscryptproxy into root with core's own Template engine (same output as Apply).

    Runs as a child process so that the run's deadline can kill it."""
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "render", root, "--modules", CORE_SERVICE,
                             "--config", CORE_CONFIG],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    _RENDER["proc"] = proc
    out = proc.communicate()[0].decode(errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(out.strip()[-2000:] or "render exited with %s" % proc.returncode)


def _kill_render():
    proc, _RENDER["proc"] = _RENDER["proc"], None
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass


def _call_render(render, root, deadline):
    """Run the renderer so that it cannot outlive the deadline (an overrunning render is abandoned)."""
    box = {}

    def target():
        try:
            render(root)
        except BaseException as exc:  # noqa: B902
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(max(deadline.remaining(), 0))
    if thread.is_alive():
        raise TestFailure("timeout", "render did not finish before the deadline")
    if "error" in box:
        raise box["error"]


def _read_lines(path):
    try:
        with open(path, errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def _run_check(binary, config, cwd, deadline):
    try:
        proc = subprocess.run([binary, "-check", "-config", config], cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=max(deadline.remaining(), 0.01))
    except subprocess.TimeoutExpired:
        raise TestFailure("timeout", "dnscrypt-proxy -check did not finish in time")
    except OSError as exc:
        return False, "cannot run %s: %s" % (binary, exc)
    return proc.returncode == 0, proc.stdout.decode(errors="replace")[-4000:]


def _kill(proc):
    """Stop the instance. The group is only signalled while the child is unreaped (its pid cannot be
    reused then); the sandbox sweep catches anything else."""
    if proc is not None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if proc.poll() is not None:
                break
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                pass
            try:
                proc.wait(0.5 if sig == signal.SIGTERM else 2)
            except subprocess.TimeoutExpired:
                continue


def _query(name, rtype, deadline):
    timeout = min(5.0, deadline.remaining())
    if timeout <= 0:
        raise TestFailure("timeout", "deadline passed during queries")
    try:
        proc = subprocess.run([DRILL, "-p", LISTEN.split(":")[1], name, rtype, "@127.0.0.1"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "error"
    match = re.search(r"rcode:\s*([A-Z]+)", proc.stdout.decode(errors="replace"))
    return match.group(1) if match else "error"


def _execute(result, state, deadline, render, binary):
    """Steps of one run. Returns the Popen of the instance (or None) via state['proc']."""
    root = sandbox_dir()
    render_root = os.path.join(root, "render")
    work = os.path.join(root, "work")
    deadline.check()
    try:
        _call_render(render, render_root, deadline)
    except TestFailure:
        raise
    except Exception as exc:  # the saved config could not be rendered
        result["check"] = {"ok": False, "output": "render failed: %s" % exc}
        raise TestFailure("check-failed", "render failed")
    deadline.check()
    rendered = os.path.join(render_root, RENDERED_CONFIG)
    if not os.path.isfile(rendered):
        result["check"] = {"ok": False, "output": "render produced no %s" % RENDERED_CONFIG}
        raise TestFailure("check-failed", "no rendered config")
    shutil.copytree(os.path.dirname(rendered), work)  # rules/list files sit beside the config
    config = os.path.join(work, os.path.basename(rendered))
    with open(config) as handle:
        original = handle.read()
    first = original.split("\n", 1)[0].strip()
    for marker in FAIL_CLOSED_MARKERS:  # C-06: the template refused to render the routes; DNS is stopped
        if first == "# dnscrypt-routes: " + marker:
            result["check"] = {"ok": False, "output": "the rendered config is marked `%s`; the instance was "
                               "not started. %s" % (marker, MARKER_CONSEQUENCE[marker])}
            raise TestFailure("check-failed", MARKER_CONSEQUENCE[marker])  # already in check.output: no extra note
    names = rendered_server_names(original)
    for name in cache_file_names(original):
        for suffix in ("", ".minisig"):
            source = os.path.join(LIVE_DIR, name + suffix)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(work, name + suffix))
    with open(config, "w") as handle:
        handle.write(patch_config(original, work, provide_list_files(original, work)))
    deadline.check()
    ok, output = _run_check(binary, config, work, deadline)
    result["check"] = {"ok": ok, "output": output}
    if not ok:
        raise TestFailure("check-failed", "dnscrypt-proxy -check failed")
    log_path = os.path.join(work, "dnscrypt-proxy.log")
    with open(os.path.join(work, "stdout.log"), "w") as out:
        proc = subprocess.Popen([binary, "-config", config], cwd=work, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    state["proc"] = proc
    while True:
        lines = _read_lines(log_path)
        live = parse_live_servers(lines)
        if live is not None:
            result["live_servers"] = live
            break
        if proc.poll() is not None:
            result["resolvers"] = resolver_rows(lines, names)
            raise TestFailure("crashed", "dnscrypt-proxy exited with %s" % proc.returncode)
        if deadline.remaining() <= 0:
            result["resolvers"] = resolver_rows(lines, names)
            raise TestFailure("timeout", "no `live servers` line before the deadline")
        time.sleep(min(0.2, max(deadline.remaining(), 0.01)))
    try:
        for name, rtype in QUERIES:
            if proc.poll() is not None:
                raise TestFailure("crashed", "dnscrypt-proxy exited during the queries")
            result["queries"].append({"name": name, "type": rtype, "rcode": _query(name, rtype, deadline)})
    except TestFailure:  # still report per resolver (R-13)
        result["resolvers"] = resolver_rows(_read_lines(log_path), names)
        raise
    result["resolvers"] = resolver_rows(_read_lines(log_path), names)
    result["state"] = "done"


def _finish(result, token):
    """Sweep, publish the result and free the sandbox, but only while the lock still holds our token:
    a worker whose lock was taken over must not touch the next run's processes, result or lock."""
    with guard():
        data = read_lock()
        if not data or data.get("token") != token:
            return
        try:
            kill_sandbox_processes()
            write_result(result)
        finally:
            wipe_sandbox()


def _add_note(result, message):
    """Keep the reason of a failed run inside C-04: appended to check.output, before the sandbox goes."""
    try:
        note = failure_note(message, os.path.join(sandbox_dir(), "work"))
    except Exception:
        note = message[:NOTE_CAP]
    output = result["check"].get("output") or ""
    if message and message in output:
        return
    result["check"]["output"] = (output.rstrip("\n") + "\n" if output else "") + note


def run(render=None, token=None):
    """Foreground worker. Always kills the instance, writes the result, deletes the sandbox, frees the lock.

    Only runs when the lock names this token (handed over by `start`); otherwise it touches nothing."""
    render = render or render_with_core
    with guard():
        data = read_lock()
        if not token or not data or data.get("token") != token:
            return None
        _write_lock({"pid": os.getpid(), "token": token, "time": now_iso()})  # the lock now names this worker
    binary = os.environ.get("DNSCRYPT_ROUTES_TEST_BINARY") or DEFAULT_BINARY
    deadline = Deadline(deadline_seconds())
    began = time.monotonic()
    result = new_result("running")
    result["started"] = now_iso()
    state = {"proc": None}
    try:
        _execute(result, state, deadline, render, binary)
    except TestFailure as exc:
        result["state"], result["error"] = "failed", exc.code
        _add_note(result, str(exc))
    except BaseException as exc:  # noqa: B902  (also SIGTERM -> SystemExit): still clean up in finally
        result["state"], result["error"] = "failed", "crashed"
        _add_note(result, "%s: %s" % (type(exc).__name__, exc))
    finally:
        try:
            _kill(state["proc"])
        except Exception:
            pass
        _kill_render()
        result["finished"] = now_iso()
        result["duration_s"] = round(time.monotonic() - began, 2)
        if result["state"] == "running":
            result["state"], result["error"] = "failed", "crashed"
        _finish(result, token)
    return result


def _spawn_worker(token):
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", "--token", token],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    return proc.pid


def start(spawn=_spawn_worker):
    """Start a detached run. A refused start never touches the running test's result file."""
    token = secrets.token_hex(8)
    with guard():
        if not _acquire_locked(token):
            return {"started": False, "reason": "already-running"}
        running = new_result("running")
        running["started"] = now_iso()
        try:
            write_result(running)
            pid = spawn(token)
            _write_lock({"pid": pid, "token": token, "time": now_iso()})
        except Exception as exc:
            failed = new_result("failed")
            failed["started"] = failed["finished"] = now_iso()
            failed["error"] = "crashed"
            failed["check"]["output"] = "could not start the worker: %s" % exc
            write_result(failed)
            wipe_sandbox()
            return {"started": False, "reason": "spawn-failed"}
    return {"started": True, "reason": None}


def status():
    result = read_result()
    if result.get("state") == "running" and not lock_active():  # worker may have died
        with guard():
            result = read_result()
            if result.get("state") == "running" and reap_stale():
                result["state"], result["error"] = "failed", "crashed"
                result["check"] = {"ok": False, "output": "the test worker stopped unexpectedly; "
                                   "run Save & Test again"}
                result["finished"] = now_iso()
                write_result(result)
    return result


def _on_term(signum, frame):
    raise SystemExit(128 + signum)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Save & Test side-instance backend")
    parser.add_argument("command", choices=["start", "status", "run", "render"])
    parser.add_argument("--token")
    parser.add_argument("root", nargs="?")
    parser.add_argument("--modules", default=CORE_SERVICE, help="core's service directory (holds modules/)")
    parser.add_argument("--config", default=CORE_CONFIG)
    args = parser.parse_args(argv)
    if args.command == "start":
        print(json.dumps(start()))
    elif args.command == "status":
        print(json.dumps(status()))
    elif args.command == "render":  # internal: killable render step
        _render_core(args.root, args.modules, args.config)
    else:
        signal.signal(signal.SIGTERM, _on_term)
        run(token=args.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
