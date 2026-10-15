#!/usr/bin/env python3
"""Status data for the status strip and the applied-hash record (R-09, R-10, C-02, C-06).

Subcommands (configd actions call these):
  status              print the C-02 status JSON
  mark-applied HASH   write /var/db/dnscrypt-routes/applied.json atomically, print {"ok": true}

Everything is derived from files: the generated dnscrypt-proxy.toml (first-line marker, server_names),
the dnscrypt-proxy log (last startup block) and the manual 90-eu override files. Missing or unreadable
files never raise; they give the neutral value (null, false, empty list).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # no __pycache__ next to the packaged scripts; pkg remove would leave it (R-04)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testrun  # noqa: E402  (log parsing shared with the Save & Test backend)

GENERATED = "/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml"     # target of the 95-dnscrypt-routes mapping
LOG_FILE = "/var/log/dnscrypt-proxy/dnscrypt-proxy.log"             # stock log_file
TEMPLATE_DIR = "/usr/local/opnsense/service/templates/OPNsense/Dnscryptproxy"
MANUAL_TEMPLATE = "dnscrypt-proxy-eu.toml"
MANUAL_MAPPING = "dnscrypt-proxy-eu.toml:/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
STATE_DIR = "/var/db/dnscrypt-routes"                               # C-06
RC_SCRIPT = "/usr/local/etc/rc.d/dnscrypt-proxy"                    # as the stock plugin's actions call it
LOG_TAIL_BYTES = 8 * 1024 * 1024
FAIL_CLOSED_NAME = "dnscrypt-routes-invalid-config"

MARKERS = {
    "# dnscrypt-routes: managed": "applied",
    "# dnscrypt-routes: override-not-applied": "not-applied",
    "# dnscrypt-routes: invariant-violated": "invariant-violated",
}
_STARTUP = re.compile(r"^dnscrypt-proxy \d+\.\d+")   # dlog.Noticef("dnscrypt-proxy %s", AppVersion)
_HASH = re.compile(r"^[0-9a-f]{64}$")                # sha256 hex, as C-03 defines pending


def _read(path, limit=None):
    """Text of a file, or None when missing or unreadable. With limit: only the last limit bytes."""
    try:
        with open(path, "rb") as handle:
            if limit is not None:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - limit))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return None


def status_command():
    return [RC_SCRIPT, "onestatus"]


def service_running():
    """Whether the stock rc script (not pgrep: the side instance has the same process name) reports the service as running (exit status 0)."""
    try:
        return subprocess.call(status_command(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10) == 0
    except (OSError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------------- generated file

def override_state(text):
    """C-02 `override` from the generated file: first line marker, empty file, no marker."""
    if text is None:
        return "disabled"
    if text.strip() == "":
        return "base-disabled"
    first = text.split("\n", 1)[0].strip()
    return MARKERS.get(first, "disabled")


def server_names(text):
    """Names from the generated `server_names = [...]` line, without the fail-closed placeholder."""
    if not text:
        return []
    match = re.search(r"(?m)^server_names[ \t]*=[ \t]*\[(.*)\][ \t]*$", text)
    if not match:
        return []
    names = re.findall(r"'([^']*)'|\"([^\"]*)\"", match.group(1))
    return [a or b for a, b in names if (a or b) != FAIL_CLOSED_NAME]


# --------------------------------------------------------------------------- log

def last_startup_block(lines):
    """Lines from the last dnscrypt-proxy startup line on; the whole log when none is found."""
    start = 0
    for index, line in enumerate(lines):
        if _STARTUP.match(testrun._strip(line)):
            start = index
    return lines[start:]


def log_facts(text):
    """(live_servers, direct_servers) from the last startup block of the log text."""
    if not text:
        return None, []
    block = last_startup_block(text.splitlines())
    live = testrun.parse_live_servers(block)
    direct = [item["name"] for item in testrun.parse_log(block) if item["direct"]]
    return live, direct


# --------------------------------------------------------------------------- manual override

def manual_state(template_dir=None):
    """(override_present, template_without_mapping), using the template's "mapping active" test (R-01)."""
    base = template_dir or TEMPLATE_DIR
    mapping = _read(os.path.join(base, "+TARGETS.D", "90-eu.TARGET"))
    active = mapping is not None and MANUAL_MAPPING in [line.strip() for line in mapping.splitlines()]
    exists = os.path.isfile(os.path.join(base, MANUAL_TEMPLATE))
    return active and exists, exists and not active


# --------------------------------------------------------------------------- applied.json

def applied_path():
    return os.path.join(STATE_DIR, "applied.json")


def read_applied():
    text = _read(applied_path())
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("hash"), str) and isinstance(data.get("time"), str):
        return {"hash": data["hash"], "time": data["time"]}
    return None


def mark_applied(value):
    """Write applied.json atomically (temp file in the same directory, fsync, rename)."""
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        return {"ok": False, "error": "invalid hash"}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        os.makedirs(STATE_DIR, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".applied.", suffix=".tmp", dir=STATE_DIR)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump({"hash": value, "time": stamp}, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, applied_path())
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


# --------------------------------------------------------------------------- status

def build_status():
    generated = _read(GENERATED)
    live, direct = log_facts(_read(LOG_FILE, LOG_TAIL_BYTES))
    present, orphan = manual_state()
    return {
        "running": service_running(),
        "live_servers": live,
        "total_servers": len(server_names(generated)),
        "override": override_state(generated),
        "direct_servers": direct,
        "manual_override_present": present,
        "manual_template_without_mapping": orphan,
        "applied": read_applied(),
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["status"] and len(argv) == 1:
        print(json.dumps(build_status()))
        return 0
    if argv[:1] == ["mark-applied"] and len(argv) == 2:
        result = mark_applied(argv[1])
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    sys.stderr.write("usage: status.py status | mark-applied HASH\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
