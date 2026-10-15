"""WP-07: Save & Test backend (testrun.py): pure functions and lifecycle with a stub dnscrypt-proxy."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin/dns/dnscrypt-routes/src/opnsense/scripts/dnscrypt_routes"))
import testrun  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "testrun"
LIVE_PATHS = ("/var/log/dnscrypt-proxy", "/usr/local/etc/dnscrypt-proxy", ":5353")


# ----------------------------------------------------------------------------- patch_config

def _values(text, key):
    return [line.split("=", 1)[1].strip() for line in text.splitlines()
            if line.strip().startswith(key + " ") or line.strip().startswith(key + "=")]


def test_patch_config_keeps_nothing_live():
    patched = testrun.patch_config((FIX / "rendered.toml").read_text(), "/sbx/work")
    for live in LIVE_PATHS:
        assert live not in patched
    assert _values(patched, "listen_addresses") == ["['127.0.0.1:5354']"]
    assert "[query_log]" not in patched and "[nx_log]" not in patched
    assert "/var/log" not in patched
    for value in _values(patched, "log_file") + _values(patched, "cache_file"):
        assert value.startswith("'/sbx/work/"), value
    assert _values(patched, "cache_file") == ["'/sbx/work/public-resolvers.md'", "'/sbx/work/relays.md'"]
    assert "use_syslog = false" in patched
    # unrelated routing settings survive
    assert "via=['anon-relay-a','anon-relay-b']" in patched
    assert "skip_incompatible = true" in patched


def test_patch_config_multiline_ipv6_listen_and_extra_listeners():
    text = ("listen_addresses = [\n  '127.0.0.1:5353',\n  '[::1]:5353'\n]\nlog_level = 2\n"
            "use_syslog = true\n\n[local_doh]\n  listen_addresses = ['127.0.0.1:3000']\n"
            "  cert_file = '/etc/c.pem'\n\n[monitoring_ui]\n  enabled = true\n  listen_address = '127.0.0.1:8080'\n\n"
            "[blocked_ips]\n  log_file = '/var/log/dnscrypt-proxy/ip.log'\n")
    patched = testrun.patch_config(text, "/sbx/w")
    assert "5353" not in patched and "3000" not in patched and "8080" not in patched
    assert "[::1]" not in patched and "/etc/c.pem" not in patched
    assert _values(patched, "listen_addresses") == ["['127.0.0.1:5354']"]
    assert "use_syslog = false" in patched and "use_syslog = true" not in patched
    assert "log_file = '/sbx/w/dnscrypt-proxy.log'" in patched  # inserted, top level
    assert "log_file = '/sbx/w/blocked_ips.log'" in patched
    assert patched.index("log_file = '/sbx/w/dnscrypt-proxy.log'") < patched.index("[blocked_ips]")


def test_patch_config_adds_missing_keys_without_sections():
    patched = testrun.patch_config("server_names = ['x']\n", "/s")
    assert "listen_addresses = ['127.0.0.1:5354']" in patched
    assert "log_file = '/s/dnscrypt-proxy.log'" in patched


def test_cache_file_names():
    assert testrun.cache_file_names((FIX / "rendered.toml").read_text()) == ["public-resolvers.md", "relays.md"]


# ----------------------------------------------------------------------------- parse_log

def _by_name(lines):
    return {r["name"]: r for r in testrun.parse_log(lines)}


def test_parse_log_ok_timeout_and_missing_route():
    lines = (FIX / "log-mixed.txt").read_text().splitlines()
    got = _by_name(lines)
    good = got["good-dnscrypt"]
    assert good == {"name": "good-dnscrypt", "routes": ["anon-relay-a", "anon-relay-b"], "cert": "ok",
                    "rtt_ms": 41, "proto": "dnscrypt", "direct": False, "pass": True}
    assert got["slow-one"]["cert"] == "timeout" and got["slow-one"]["pass"] is False
    assert got["slow-one"]["rtt_ms"] is None and got["slow-one"]["routes"] == ["anon-relay-a"]
    assert testrun.parse_live_servers(lines) == 3


def test_parse_log_doh_is_not_a_pass():
    doh = _by_name(["[2026-10-12 10:00:00] [NOTICE] [doh-one] OK (DoH) - rtt: 20ms"])["doh-one"]
    assert doh["proto"] == "doh" and doh["pass"] is False


def test_parse_log_live_without_route_is_direct():
    direct = _by_name(["[2026-10-12 10:00:00] [NOTICE] [direct-one] OK (DNSCrypt) - rtt: 30ms"])["direct-one"]
    assert direct["direct"] is True and direct["pass"] is False and direct["routes"] == []


def test_parse_log_later_anonymity_error_overrides_ok():
    got = _by_name([
        "[t] [NOTICE] Anonymizing queries for [r] via [a]",
        "[t] [NOTICE] [r] OK (DNSCrypt) - rtt: 5ms",
        "[t] [INFO] [r] couldn't be reached anonymously, it will be ignored",
    ])["r"]
    assert got["cert"] == "error" and got["pass"] is False


def test_parse_log_without_dlog_prefix_and_no_live_line():
    lines = ["Anonymizing queries for [r] via [a]", "[r] OK (DNSCrypt) - rtt: 5ms"]
    assert _by_name(lines)["r"]["pass"] is True
    assert testrun.parse_live_servers(lines) is None


# ----------------------------------------------------------------------------- lifecycle

@pytest.fixture
def env(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    live = tmp_path / "live"
    live.mkdir()
    (live / "public-resolvers.md").write_text("signed catalog")
    monkeypatch.setattr(testrun, "RUN_DIR", str(run_dir))
    monkeypatch.setattr(testrun, "LIVE_DIR", str(live))
    monkeypatch.setattr(testrun, "DRILL", str(FIX / "stub-drill"))
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_BINARY", str(FIX / "stub-dnscrypt-proxy"))
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "3")
    monkeypatch.setenv("STUB_PIDFILE", str(tmp_path / "pid"))
    monkeypatch.setenv("STUB_TRACE", str(tmp_path / "trace"))
    return tmp_path


def fake_render(root):
    target = Path(root) / testrun.RENDERED_CONFIG
    target.parent.mkdir(parents=True)
    shutil.copy(FIX / "rendered.toml", target)
    (target.parent / "whitelist.txt").write_text("")


def go(render=None):
    """Run the worker in-process the way `start` hands it over: lock taken under the guard, token passed."""
    with testrun.guard():
        assert testrun._acquire_locked("tok")
    return testrun.run(render=render or fake_render, token="tok")


def assert_clean(env):
    assert not (env / "run" / "test").exists(), "sandbox not deleted"
    assert (env / "run" / "test-result.json").is_file()
    pidfile = env / "pid"
    if pidfile.exists():
        pid = int(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def trace(env):
    path = env / "trace"
    return path.read_text().split() if path.exists() else []


def test_run_done(env):
    result = go()
    assert result["state"] == "done" and result["error"] is None
    assert result["check"]["ok"] is True and result["live_servers"] == 3
    assert [q["rcode"] for q in result["queries"]] == ["NOERROR"] * 3
    passed = {r["name"]: r["pass"] for r in result["resolvers"]}
    assert passed == {"good-dnscrypt": True, "doh-one": False, "direct-one": False, "slow-one": False}
    assert testrun.status()["state"] == "done"
    assert trace(env) == ["check", "start"]
    assert_clean(env)


def test_run_timeout_when_never_live(env, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "no-live")
    began = time.monotonic()
    result = go()
    assert time.monotonic() - began < 3 + 3
    assert (result["state"], result["error"]) == ("failed", "timeout")
    assert result["resolvers"] and result["resolvers"][0]["name"] == "good-dnscrypt"
    assert_clean(env)


def test_run_crashed_at_start(env, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "crash")
    result = go()
    assert (result["state"], result["error"]) == ("failed", "crashed")
    assert trace(env) == ["check", "start"]
    assert_clean(env)


def test_run_check_failed_never_starts(env, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "check-fail")
    result = go()
    assert (result["state"], result["error"]) == ("failed", "check-failed")
    assert result["check"]["ok"] is False and "boom" in result["check"]["output"]
    assert trace(env) == ["check"]
    assert not (env / "pid").exists()
    assert_clean(env)


def test_run_render_failure_is_check_failed(env):
    def broken(root):
        raise RuntimeError("template exploded")
    result = go(broken)
    assert (result["state"], result["error"]) == ("failed", "check-failed")
    assert "template exploded" in result["check"]["output"]
    assert_clean(env)


def test_run_uses_sandbox_only(env, monkeypatch):
    """The patched config handed to the instance lives in the sandbox; live catalog is copied, not used."""
    seen = {}
    real = testrun._run_check

    def spy(binary, config, cwd, deadline):
        seen["config"] = Path(config).read_text()
        seen["catalog"] = (Path(cwd) / "public-resolvers.md").read_text()
        seen["cwd"] = cwd
        return real(binary, config, cwd, deadline)

    monkeypatch.setattr(testrun, "_run_check", spy)
    go()
    assert seen["catalog"] == "signed catalog"
    assert seen["cwd"].startswith(str(env / "run" / "test"))
    for live in LIVE_PATHS:
        assert live not in seen["config"]


def test_second_start_while_active_is_refused(env, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "no-live")
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "3")
    workers = []

    def spawn(token):  # in-process stand-in for the detached worker; same pid is alive for the lock
        thread = threading.Thread(target=testrun.run, kwargs={"render": fake_render, "token": token})
        thread.start()
        workers.append(thread)
        return os.getpid()

    assert testrun.start(spawn=spawn) == {"started": True, "reason": None}
    result_file = env / "run" / "test-result.json"
    before = result_file.read_bytes()
    assert json.loads(before)["state"] == "running"
    assert testrun.status()["state"] == "running"
    time.sleep(0.5)
    assert result_file.read_bytes() == before
    assert testrun.start(spawn=spawn) == {"started": False, "reason": "already-running"}
    assert len(workers) == 1
    assert result_file.read_bytes() == before, "refused start touched the running test's result"
    workers[0].join(20)
    final = json.loads(result_file.read_text())
    assert (final["state"], final["error"]) == ("failed", "timeout")
    assert_clean(env)
    assert testrun.start(spawn=lambda token: os.getpid())["started"] is True  # lock was released
    testrun.release_lock()


def test_stale_lock_of_dead_worker_is_taken_over(env):
    os.makedirs(env / "run" / "test")
    (env / "run" / "test" / "lock").write_text(json.dumps({"pid": 2 ** 22 + 12345}))
    (env / "run" / "test" / "leftover").write_text("x")
    assert testrun.start(spawn=lambda token: os.getpid())["started"] is True
    assert not (env / "run" / "test" / "leftover").exists()
    testrun.release_lock()


def test_status_of_dead_running_worker_is_failed_and_idle_without_file(env):
    assert testrun.status()["state"] == "idle"
    os.makedirs(env / "run")
    running = testrun.new_result("running")
    testrun.write_result(running)
    got = testrun.status()
    assert (got["state"], got["error"]) == ("failed", "crashed")
    assert got["check"]["output"] == "the test worker stopped unexpectedly; run Save & Test again"  # M2-B-F12


def test_spawn_failure_releases_lock(env):
    def boom(token):
        raise OSError("no fork")
    assert testrun.start(spawn=boom) == {"started": False, "reason": "spawn-failed"}
    assert testrun.status()["error"] == "crashed"
    assert not (env / "run" / "test").exists()


# ----------------------------------------------------------------------------- round 1 fixes

def _render_with(extra):
    def render(root):
        fake_render(root)
        target = Path(root) / testrun.RENDERED_CONFIG
        target.write_text(target.read_text() + extra)
    return render


BLOCKED = "\n[blocked_names]\n  blocked_names_file = 'blacklist.txt'\n  log_file = '/var/log/dnscrypt-proxy/blocked.log'\n"


def test_blacklist_is_copied_from_live_dir(env):  # WP07-F01
    (env / "live" / "blacklist.txt").write_text("ads.example\n")
    result = go(_render_with(BLOCKED))
    assert result["state"] == "done", result["check"]
    assert (env / "live" / "blacklist.txt").read_text() == "ads.example\n"  # live file untouched


def test_blocked_names_dropped_when_no_blacklist_exists(env):  # WP07-F01
    result = go(_render_with(BLOCKED))
    assert result["state"] == "done", result["check"]


def test_missing_list_file_section_is_dropped(env):
    text = (FIX / "rendered.toml").read_text() + BLOCKED
    (env / "whitelist.txt").write_text("")
    assert testrun.provide_list_files(text, str(env)) == ["blocked_names"]
    assert "blocked_names" not in testrun.patch_config(text, "/s", ["blocked_names"])


def test_concurrent_starts_over_stale_lock_have_one_winner(env):  # WP07-F02
    os.makedirs(env / "run" / "test")
    (env / "run" / "test" / "lock").write_text(json.dumps({"pid": 2 ** 22 + 12345}))
    results = []
    barrier = threading.Barrier(8)

    def racer():
        barrier.wait()
        results.append(testrun.start(spawn=lambda token: os.getpid())["started"])

    threads = [threading.Thread(target=racer) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert sorted(results) == [False] * 7 + [True]
    testrun.release_lock()


def _spawn_harness(env, procs):
    def spawn(token):
        proc = subprocess.Popen([sys.executable, str(FIX / "worker_harness.py"), str(env / "run"),
                                 str(env / "live"), token])
        procs.append(proc)
        return proc.pid
    return spawn


def _killed_worker(env, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "no-live")
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "60")
    procs = []
    assert testrun.start(spawn=_spawn_harness(env, procs))["started"] is True
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (env / "pid").exists():
            break
        time.sleep(0.1)
    else:
        procs[0].kill()
        pytest.fail("worker never started the instance")
    stub_pid = int(( env / "pid").read_text())
    procs[0].kill()  # SIGKILL: no finally runs, the instance keeps running in its own session
    procs[0].wait()
    os.kill(stub_pid, 0)
    return stub_pid


def _force_kill(pid):
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


def _gone(pid, tries=50):
    for _ in range(tries):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def test_status_reaps_instance_of_killed_worker(env, monkeypatch):  # WP07-F03
    stub_pid = _killed_worker(env, monkeypatch)
    try:
        got = testrun.status()
        assert (got["state"], got["error"]) == ("failed", "crashed")
        assert _gone(stub_pid)
        assert not (env / "run" / "test").exists()
        assert json.loads((env / "run" / "test-result.json").read_text())["state"] == "failed"
    finally:
        _force_kill(stub_pid)


def test_start_takeover_reaps_instance_of_killed_worker(env, monkeypatch):  # WP07-F03
    stub_pid = _killed_worker(env, monkeypatch)
    try:
        assert testrun.start(spawn=lambda token: os.getpid())["started"] is True
        assert _gone(stub_pid)
        testrun.release_lock()
    finally:
        _force_kill(stub_pid)


def test_render_past_deadline_ends_as_timeout(env, monkeypatch):  # WP07-F04
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "1")
    began = time.monotonic()
    result = go(lambda root: time.sleep(6))
    assert time.monotonic() - began < 1 + 3
    assert (result["state"], result["error"]) == ("failed", "timeout")
    assert_clean(env)


def test_run_without_its_lock_touches_nothing(env):  # WP07-F05
    with testrun.guard():
        assert testrun._acquire_locked("other")
    (env / "run" / "test" / "marker").write_text("x")
    testrun.write_result({"state": "running", "marker": 1})
    before = (env / "run" / "test-result.json").read_bytes()
    lock_before = (env / "run" / "test" / "lock").read_bytes()
    for token in (None, "", "mine"):
        assert testrun.run(render=fake_render, token=token) is None
    assert (env / "run" / "test-result.json").read_bytes() == before
    assert (env / "run" / "test" / "lock").read_bytes() == lock_before
    assert (env / "run" / "test" / "marker").exists()
    testrun.release_lock()


PATH_KEYS = ("log_file", "cache_file", "file", "tls_key_log_file", "pidfile", "state_file")


def _written_paths(text):
    """Absolute paths in keys that dnscrypt-proxy writes to."""
    found = []
    for line in text.splitlines():
        key, _, value = line.partition("=")
        key = key.strip()
        if key in PATH_KEYS or key.endswith("_log_file"):
            found += [v for v in testrun._QUOTED.findall(value) if v.startswith("/")]
    return found


@pytest.mark.parametrize("extra", [
    "",
    "tls_key_log_file = '/var/log/dnscrypt-proxy/keys.log'\n",
    "\n[blocked_ips]\n  blocked_ips_file = 'ips.txt'\n  log_file = '/var/log/dnscrypt-proxy/ips.log'\n",
    "\n[local_doh]\n  listen_addresses = ['127.0.0.1:3000']\n  path = '/dns-query'\n",
])
def test_no_write_path_survives_patch(extra):  # WP07-F06
    text = (FIX / "rendered.toml").read_text()
    text = extra + text if extra.startswith("tls_key") else text + extra
    patched = testrun.patch_config(text, "/sbx/work")
    assert _written_paths(text), "fixture must contain write paths"
    for path in _written_paths(patched):
        assert path.startswith("/sbx/work/"), path
    assert "tls_key_log_file" not in patched


# ----------------------------------------------------------------------------- round 2 fixes

def test_unrelated_process_is_never_killed_on_takeover(env):  # WP07-F07
    other = subprocess.Popen(["sleep", "60"], start_new_session=True)  # own group, like a reused pgid
    try:
        os.makedirs(env / "run" / "test")
        (env / "run" / "test" / "lock").write_text(json.dumps(
            {"pid": 2 ** 22 + 12345, "token": "x", "instance": other.pid}))  # stale lock naming it
        assert testrun.start(spawn=lambda token: os.getpid())["started"] is True
        time.sleep(0.5)
        assert other.poll() is None, "unrelated process group was killed"
        testrun.release_lock()
    finally:
        other.kill()
        other.wait()


def test_live_pid_without_the_runs_token_is_a_stale_lock(env):  # WP07-F07 (pid reuse)
    other = subprocess.Popen(["sleep", "60"])
    try:
        os.makedirs(env / "run" / "test")
        (env / "run" / "test" / "lock").write_text(json.dumps({"pid": other.pid, "token": "tok-not-on-cmdline"}))
        assert testrun.lock_active() is False
        (env / "run" / "test" / "lock").write_text(json.dumps({"pid": other.pid}))  # no token: pid decides
        assert testrun.lock_active() is True
    finally:
        other.kill()
        other.wait()


def test_old_lock_of_a_live_worker_is_not_stale(env, monkeypatch):  # WP07-F12
    monkeypatch.setenv("STUB_MODE", "no-live")
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "60")
    procs = []
    assert testrun.start(spawn=_spawn_harness(env, procs))["started"] is True
    try:
        for _ in range(100):
            if (env / "pid").exists():
                break
            time.sleep(0.1)
        lock = env / "run" / "test" / "lock"
        old = time.time() - 100000
        os.utime(lock, (old, old))
        assert testrun.start(spawn=lambda token: os.getpid()) == {"started": False, "reason": "already-running"}
    finally:
        procs[0].kill()
        procs[0].wait()
        testrun.status()  # reaps the instance


def test_worker_that_lost_its_lock_touches_nothing(env, monkeypatch):  # WP07-F12
    monkeypatch.setenv("STUB_MODE", "no-live")
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "2")
    with testrun.guard():
        assert testrun._acquire_locked("A")
    worker = threading.Thread(target=testrun.run, kwargs={"render": fake_render, "token": "A"})
    worker.start()
    for _ in range(100):
        if (env / "pid").exists():
            break
        time.sleep(0.1)
    with testrun.guard():  # a takeover hands the sandbox to run B while A is still alive
        testrun._write_lock({"pid": os.getpid(), "token": "B"})
        testrun.write_result({"state": "running", "owner": "B"})
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "-config",
                                  str(env / "run" / "test" / "work" / "b.toml")], start_new_session=True)
    try:
        worker.join(20)
        assert json.loads((env / "run" / "test-result.json").read_text()) == {"state": "running", "owner": "B"}
        assert json.loads((env / "run" / "test" / "lock").read_text())["token"] == "B"
        assert bystander.poll() is None, "old worker swept the next run's processes"
    finally:
        bystander.kill()
        bystander.wait()
        testrun.release_lock()


@pytest.mark.parametrize("name", ["../../../up.txt", "sub/x.txt", "..", "/abs/list.txt"])
def test_list_file_names_must_be_plain(env, tmp_path, name):  # WP07-F08
    (env / "live" / "x.txt").write_text("")
    live_parent = env / "up.txt"
    live_parent.write_text("secret")
    work = tmp_path / "work"
    work.mkdir()
    text = "[blocked_names]\n  blocked_names_file = '%s'\n" % name
    drop = testrun.provide_list_files(text, str(work))
    if name.startswith("/"):
        assert drop == []  # absolute names are read-only inputs and left alone
    else:
        assert drop == ["blocked_names"]
    assert sorted(p.name for p in work.rglob("*")) == []
    assert live_parent.read_text() == "secret"
    assert not (tmp_path.parent / "up.txt").exists()


def _orphan(*args):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *args], start_new_session=True)


def test_orphans_without_a_recorded_instance_are_reaped(env):  # WP07-F09, WP07-F13
    """Worker killed before the instance was recorded anywhere: found by its own argv."""
    sandbox = env / "run" / "test"
    os.makedirs(sandbox / "work")
    (sandbox / "lock").write_text(json.dumps({"pid": 2 ** 22 + 12345, "token": "x"}))
    orphan = _orphan("-check", "-config", str(sandbox / "work" / "dnscrypt-proxy.toml"))
    render_orphan = _orphan("render", str(sandbox / "render"), "--modules", "/x")
    try:
        time.sleep(0.5)
        assert orphan.poll() is None and render_orphan.poll() is None, "orphans must be alive before start"
        assert testrun.start(spawn=lambda token: os.getpid())["started"] is True
        assert orphan.wait(5) is not None and render_orphan.wait(5) is not None
        testrun.release_lock()
    finally:
        for proc in (orphan, render_orphan):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_bystanders_naming_the_sandbox_are_not_killed(env):  # WP07-F11
    sandbox = env / "run" / "test"
    os.makedirs(sandbox / "work")
    (sandbox / "x").write_text("")
    bystanders = [
        subprocess.Popen(["tail", "-F", str(sandbox / "x")]),
        subprocess.Popen(["sh", "-c", "sleep 60; ls %s" % sandbox]),
        _orphan(str(sandbox)),
        _orphan(str(sandbox / "work" / "dnscrypt-proxy.log")),
        _orphan("-config", str(env / "run" / "elsewhere.toml")),
    ]
    orphan = _orphan("-config", str(sandbox / "work" / "dnscrypt-proxy.toml"))
    try:
        time.sleep(0.5)
        assert all(p.poll() is None for p in bystanders + [orphan])
        testrun.kill_sandbox_processes()
        assert orphan.wait(5) is not None
        assert all(p.poll() is None for p in bystanders), "a bystander was killed"
    finally:
        for proc in bystanders + [orphan]:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


# Package-shaped double of opnsense/core's `service` tree (checked against core 8e6f3f3):
#   modules/__init__.py        syslog_* helpers (template.py does `from . import syslog_error`)
#   modules/addons/__init__.py + template_helpers.py   (template.py does `from .addons import template_helpers`)
#   modules/config.py          Config(path).get() parses config.xml (`<opnsense>` children become dict entries)
#   modules/template.py        relative imports; Template() starts with an empty config, and only after
#                              set_config() has the engine anything to render (without it core writes 0 bytes)
FAKE_CORE = {
    "modules/__init__.py": "def syslog_error(message):\n    pass\n\ndef syslog_notice(message):\n    pass\n",
    "modules/addons/__init__.py": "",
    "modules/addons/template_helpers.py": "VERSION = 1\n",
    "modules/config.py": '''
import xml.etree.ElementTree as ElementTree


class Config(object):
    def __init__(self, filename):
        self._data = {child.tag: child.text for child in ElementTree.parse(filename).getroot()}

    def get(self):
        return self._data
''',
    "modules/template.py": '''
import os
import shutil
import time
from .addons import template_helpers
from . import syslog_error, syslog_notice


class Template(object):
    def __init__(self, target_root_directory="/"):
        self._config = {}
        self.root = target_root_directory

    def set_config(self, config_data):
        self._config = config_data if isinstance(config_data, dict) else {}

    def generate(self, section):
        assert section == "OPNsense/Dnscryptproxy"
        assert template_helpers.VERSION == 1
        if os.environ.get("FAKE_RENDER_SLEEP"):
            with open(os.environ["FAKE_RENDER_PIDFILE"], "w") as handle:
                handle.write(str(os.getpid()))
            time.sleep(float(os.environ["FAKE_RENDER_SLEEP"]))
        if not self._config:  # core would write an empty file; the double refuses so the defect is loud
            syslog_error("no config set")
            return None
        target = os.path.join(self.root, "usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml")
        os.makedirs(os.path.dirname(target))
        with open(os.environ["FAKE_RENDERED"]) as handle:
            text = handle.read()
        names = ",".join("'%s'" % n for n in self._config["server_names"].split(","))
        text = text.replace("server_names = ['good-dnscrypt']", "server_names = [%s]" % names)
        with open(target, "w") as handle:
            handle.write(text)
        return [target]
''',
}


@pytest.fixture
def fake_core(env, monkeypatch):
    service = env / "core-service"
    for name, text in FAKE_CORE.items():
        path = service / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    config = env / "config.xml"
    config.write_text("<opnsense><server_names>good-dnscrypt,extra-one</server_names></opnsense>")
    monkeypatch.setattr(testrun, "CORE_SERVICE", str(service))
    monkeypatch.setattr(testrun, "CORE_CONFIG", str(config))
    monkeypatch.setenv("FAKE_RENDERED", str(FIX / "rendered.toml"))
    monkeypatch.setenv("FAKE_RENDER_PIDFILE", str(env / "render-pid"))
    return service


def test_core_double_has_the_package_shape_of_core(fake_core):  # M2-A-F1 (a): the old flat import fails
    code = "import sys; sys.path.insert(0, %r); from template import Template" % str(fake_core / "modules")
    proc = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode != 0 and b"relative import" in proc.stdout


def test_real_render_subprocess_path_works(env, fake_core, monkeypatch):  # WP07-F10, M2-A-F1
    seen = {}
    real = testrun._run_check

    def spy(binary, config, cwd, deadline):
        seen["config"] = Path(config).read_text()
        return real(binary, config, cwd, deadline)

    monkeypatch.setattr(testrun, "_run_check", spy)
    result = go(testrun.render_with_core)
    assert result["state"] == "done", result
    assert "server_names = ['good-dnscrypt','extra-one']" in seen["config"]  # the output carries the config
    assert {r["name"] for r in result["resolvers"]} >= {"good-dnscrypt", "extra-one"}
    assert_clean(env)


def test_render_with_an_empty_config_is_a_failed_render(env, fake_core):  # M2-A-F1 (b): generate returns None
    (env / "config.xml").write_text("<opnsense></opnsense>")
    result = go(testrun.render_with_core)
    assert (result["state"], result["error"]) == ("failed", "check-failed")
    assert "Template.generate failed" in result["check"]["output"]
    assert_clean(env)


def test_render_with_unreadable_config_xml_is_check_failed(env, fake_core):  # M2-A-F1
    (env / "config.xml").unlink()
    result = go(testrun.render_with_core)
    assert (result["state"], result["error"]) == ("failed", "check-failed")
    assert "config.xml" in result["check"]["output"]
    assert_clean(env)


def test_real_render_subprocess_is_killed_at_the_deadline(env, fake_core, monkeypatch):  # WP07-F10
    monkeypatch.setenv("FAKE_RENDER_SLEEP", "30")
    monkeypatch.setenv("DNSCRYPT_ROUTES_TEST_DEADLINE", "1")
    began = time.monotonic()
    result = go(testrun.render_with_core)
    assert time.monotonic() - began < 1 + 3
    assert (result["state"], result["error"]) == ("failed", "timeout")
    assert _gone(int((env / "render-pid").read_text())), "render child survived the deadline"
    assert_clean(env)


# ----------------------------------------------------------------------------- M2 round 1 fixes

def _render_marked(marker):
    def render(root):
        fake_render(root)
        target = Path(root) / testrun.RENDERED_CONFIG
        target.write_text("# dnscrypt-routes: %s\n" % marker +
                          target.read_text().split("\n", 1)[1].replace("server_names = ['good-dnscrypt']",
                                                                      "server_names = ['dnscrypt-routes-invalid-config']"))
    return render


MARKER_TEXT = {  # M2-B-F10: consequence and next step, in plain words
    "override-not-applied": "Apply would stop DNS (fail closed): the stock os-dnscrypt-proxy template no longer "
                            "has the lines this plugin patches. Update os-dnscrypt-routes, or untick Enable "
                            "anonymized routing.",
    "invariant-violated": "Apply would stop DNS (fail closed): the saved routes break the relay-only rule; "
                          "fix them first.",
}


@pytest.mark.parametrize("marker", ["invariant-violated", "override-not-applied"])
def test_fail_closed_marker_ends_the_run_without_an_instance(env, marker):  # M2-A-F4
    result = go(_render_marked(marker))
    assert (result["state"], result["error"]) == ("failed", "check-failed")
    assert result["check"]["ok"] is False and marker in result["check"]["output"]
    assert "(C-06)" not in result["check"]["output"]
    assert MARKER_TEXT[marker] in result["check"]["output"]
    assert result["check"]["output"] == ("the rendered config is marked `%s`; the instance was not started. %s"
                                         % (marker, MARKER_TEXT[marker]))  # one message, no trailing note
    assert trace(env) == []  # not even -check ran
    assert not (env / "pid").exists()
    assert_clean(env)


def test_managed_marker_is_not_refused(env):  # M2-A-F4
    assert (FIX / "rendered.toml").read_text().startswith("# dnscrypt-routes: managed\n")
    assert go()["state"] == "done"


def test_crashed_run_keeps_the_reason(env, monkeypatch):  # M2-B-F4
    monkeypatch.setenv("STUB_MODE", "crash")
    result = go()
    assert (result["state"], result["error"]) == ("failed", "crashed")
    output = result["check"]["output"]
    assert "dnscrypt-proxy exited with 1" in output
    assert "address already in use" in output  # the instance's own fatal line (stdout.log)
    assert len(output) <= testrun.NOTE_CAP + 200
    assert [(r["name"], r["cert"], r["pass"]) for r in result["resolvers"]] == [("good-dnscrypt", "unknown", False)]  # M2-B-F5
    assert_clean(env)


def test_timeout_run_keeps_the_reason(env, monkeypatch):  # M2-B-F4
    monkeypatch.setenv("STUB_MODE", "no-live")
    result = go()
    assert (result["state"], result["error"]) == ("failed", "timeout")
    output = result["check"]["output"]
    assert "no `live servers` line before the deadline" in output
    assert "still starting" in output
    assert_clean(env)


def test_unexpected_exception_keeps_its_text_and_the_note_is_capped(env, monkeypatch):  # M2-B-F4
    def boom(*args):
        raise ValueError("odd " + "x" * 5000)
    monkeypatch.setattr(testrun, "_run_check", boom)
    result = go()
    assert (result["state"], result["error"]) == ("failed", "crashed")
    assert result["check"]["output"].startswith("ValueError: odd")
    assert len(result["check"]["output"]) <= testrun.NOTE_CAP
    assert_clean(env)


def _render_names(names):
    def render(root):
        fake_render(root)
        target = Path(root) / testrun.RENDERED_CONFIG
        target.write_text(target.read_text().replace("server_names = ['good-dnscrypt']", "server_names = [%s]" % names))
    return render


def test_listed_resolver_missing_from_the_log_gets_a_failing_row(env):  # M2-B-F5
    result = go(_render_names("'good-dnscrypt', 'not-in-catalog', 'drifted-to-doh'"))
    assert result["state"] == "done", result
    rows = {r["name"]: r for r in result["resolvers"]}
    assert rows["good-dnscrypt"]["pass"] is True
    for name in ("not-in-catalog", "drifted-to-doh"):  # no log line: unknown name, or dropped by the forced filters
        assert rows[name] == {"name": name, "routes": [], "cert": "unknown", "rtt_ms": None,
                              "proto": "unknown", "direct": False, "pass": False}
    assert not all(r["pass"] for r in result["resolvers"])
    assert_clean(env)


def test_missing_rows_are_also_reported_when_the_run_fails(env, monkeypatch):  # M2-B-F5
    monkeypatch.setenv("STUB_MODE", "no-live")
    result = go(_render_names("'good-dnscrypt', 'never-logged'"))
    assert result["error"] == "timeout"
    assert [r["name"] for r in result["resolvers"]] == ["good-dnscrypt", "never-logged"]


def test_rendered_server_names_forms():  # M2-B-F5
    names = testrun.rendered_server_names
    assert names("# m\nserver_names = ['a','b c', \"d\"]\nx = 1\n") == ["a", "b c", "d"]
    assert names("server_names = [\n  'a]b',\n  'c'\n]\n[s]\n  server_names = ['no']\n") == ["a]b", "c"]
    assert names("listen_addresses = []\n") == [] and names("server_names = []\n") == []


def test_resolver_rows_keep_parse_log_untouched_and_never_duplicate():  # M2-B-F5
    lines = (FIX / "log-mixed.txt").read_text().splitlines()
    base = testrun.parse_log(lines)
    assert testrun.resolver_rows(lines, []) == base
    rows = testrun.resolver_rows(lines, ["good-dnscrypt", "late", "late"])
    assert rows[:len(base)] == base and [r["name"] for r in rows[len(base):]] == ["late"]
    assert testrun.parse_live_servers(lines) == 3


def test_marker_failure_names_the_marker_once(env):  # WPM2F1-F2
    result = go(_render_marked("invariant-violated"))
    assert result["check"]["output"].count("invariant-violated") == 1


def test_failure_note_falls_back_to_the_last_stdout_lines(env, monkeypatch):  # WPM2F1-F3
    monkeypatch.setenv("STUB_MODE", "crash-plain")
    result = go()
    output = result["check"]["output"]
    assert "plain line two | plain line three" in output and "plain line one" not in output
    assert_clean(env)


def test_rendered_server_names_comments_and_escapes():  # WPM2F1-F3
    names = testrun.rendered_server_names
    assert names("server_names = ['a', # 'b'\n 'c#d']\n") == ["a", "c#d"]
    assert names('server_names = ["a\\"b", \'x\']\n') == ['a"b', "x"]


def _kill_instance_then_query(env):
    def query(name, rtype, deadline):
        pid = int((env / "pid").read_text())
        os.kill(pid, 9)
        time.sleep(0.6)
        return "NOERROR"
    return query


def test_crash_during_the_queries_still_reports_every_resolver(env, monkeypatch):  # WPM2F1-F1
    monkeypatch.setattr(testrun, "_query", _kill_instance_then_query(env))
    result = go(_render_names("'good-dnscrypt', 'never-logged'"))
    assert (result["state"], result["error"]) == ("failed", "crashed")
    assert result["live_servers"] == 3
    rows = {r["name"]: r for r in result["resolvers"]}
    assert rows["good-dnscrypt"]["pass"] is True and rows["never-logged"]["cert"] == "unknown"
    assert_clean(env)


def test_timeout_during_the_queries_still_reports_every_resolver(env, monkeypatch):  # WPM2F1-F1
    def query(name, rtype, deadline):
        raise testrun.TestFailure("timeout", "deadline passed during queries")
    monkeypatch.setattr(testrun, "_query", query)
    result = go(_render_names("'good-dnscrypt', 'never-logged'"))
    assert (result["state"], result["error"]) == ("failed", "timeout")
    assert result["live_servers"] == 3
    assert [r["name"] for r in result["resolvers"]] == ["good-dnscrypt", "doh-one", "direct-one", "slow-one", "never-logged"]
    assert_clean(env)
