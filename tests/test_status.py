"""WP-08: status.py (plain Python, fully tested) and source checks of the PHP controllers and configd actions.

The PHP cannot be executed offline (R-20); the checks on it only pin structure: which methods call the rule
check, where the model is saved, the order in reconfigure. WP-11 runs the behavior on the VM.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPN = ROOT / "plugin/dns/dnscrypt-routes/src/opnsense"
SCRIPTS = OPN / "scripts/dnscrypt_routes"
API = OPN / "mvc/app/controllers/OPNsense/DnscryptRoutes/Api"
ACTIONS = OPN / "service/conf/actions.d/actions_dnscryptroutes.conf"
FIX = ROOT / "tests/fixtures/status"
sys.path.insert(0, str(SCRIPTS))
import status  # noqa: E402

MAPPING = "dnscrypt-proxy-eu.toml:/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
HASH = "a" * 64


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every path status.py reads or writes into tmp_path; the service check is a stub."""
    tpl = tmp_path / "tpl"
    (tpl / "+TARGETS.D").mkdir(parents=True)
    monkeypatch.setattr(status, "GENERATED", str(tmp_path / "dnscrypt-proxy.toml"))
    monkeypatch.setattr(status, "LOG_FILE", str(tmp_path / "dnscrypt-proxy.log"))
    monkeypatch.setattr(status, "TEMPLATE_DIR", str(tpl))
    monkeypatch.setattr(status, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(status, "service_running", lambda: True)
    return tmp_path


def put(env, name, text):
    (env / name).write_text(text)


# ----------------------------------------------------------------------------- log

def test_live_servers_come_from_the_last_startup_block():
    live, _ = status.log_facts((FIX / "dnscrypt-proxy.log").read_text())
    assert live == 3  # the first block says 2


def test_direct_servers_are_live_servers_without_a_route():
    _, direct = status.log_facts((FIX / "dnscrypt-proxy.log").read_text())
    # good-dnscrypt is routed; doh-one (DoH) and direct-one have no route line; slow-one timed out
    assert direct == ["doh-one", "direct-one"]


def test_old_block_does_not_leak_into_the_last_one():
    _, direct = status.log_facts((FIX / "dnscrypt-proxy.log").read_text())
    assert "old-two" not in direct and "old-one" not in direct


def test_all_routed_gives_no_direct_servers():
    live, direct = status.log_facts((FIX / "dnscrypt-proxy-routed.log").read_text())
    assert (live, direct) == (1, [])


def test_log_without_startup_line_uses_everything():
    text = "[2026-10-12 10:00:02] [NOTICE] [a] OK (DNSCrypt) - rtt: 41ms\n" \
           "[2026-10-12 10:00:03] [NOTICE] Server with the lowest initial latency: a (rtt: 41ms), live servers: 1\n"
    assert status.log_facts(text) == (1, ["a"])


@pytest.mark.parametrize("text", [None, "", "garbage\n"])
def test_missing_or_empty_log(text):
    assert status.log_facts(text) == (None, [])


def test_log_tail_is_bounded(env):
    big = "x" * 100 + "\n"
    put(env, "dnscrypt-proxy.log", big * 10 + "[d] [NOTICE] dnscrypt-proxy 2.1.15\n")
    tail = status._read(str(env / "dnscrypt-proxy.log"), 60)
    assert len(tail) == 60 and tail.endswith("2.1.15\n")


# ----------------------------------------------------------------------------- markers

@pytest.mark.parametrize("fixture,expected", [
    ("managed.toml", "applied"),
    ("override-not-applied.toml", "not-applied"),
    ("invariant-violated.toml", "invariant-violated"),
    ("plain.toml", "disabled"),
])
def test_override_markers(fixture, expected):
    assert status.override_state((FIX / fixture).read_text()) == expected


def test_override_empty_file_is_base_disabled():
    assert status.override_state("") == "base-disabled"
    assert status.override_state("\n  \n") == "base-disabled"


def test_override_missing_file_is_disabled():
    assert status.override_state(None) == "disabled"


def test_marker_must_be_the_first_line():
    assert status.override_state("server_names = []\n# dnscrypt-routes: managed\n") == "disabled"


def test_server_names_total():
    assert status.server_names((FIX / "managed.toml").read_text()) == ["good-dnscrypt", "direct-one"]
    assert status.server_names((FIX / "invariant-violated.toml").read_text()) == []
    assert status.server_names("") == [] and status.server_names(None) == []


# ----------------------------------------------------------------------------- manual override (R-01 test)

def manual(env, mapping=None, template=False):
    tpl = Path(status.TEMPLATE_DIR)
    if mapping is not None:
        (tpl / "+TARGETS.D" / "90-eu.TARGET").write_text(mapping)
    if template:
        (tpl / "dnscrypt-proxy-eu.toml").write_text("# manual\n")
    return status.manual_state()


def test_manual_active_mapping(env):
    assert manual(env, MAPPING + "\n", True) == (True, False)


def test_manual_active_mapping_with_surrounding_whitespace(env):
    assert manual(env, "  " + MAPPING + "  \r\n", True) == (True, False)


def test_manual_no_mapping(env):
    assert manual(env, None, True) == (False, True)


def test_manual_mapping_points_elsewhere(env):
    other = "dnscrypt-proxy-eu.toml:/usr/local/etc/dnscrypt-proxy/other.toml\n"
    assert manual(env, other, True) == (False, True)


def test_manual_mapping_without_template(env):
    assert manual(env, MAPPING + "\n", False) == (False, False)


def test_manual_nothing_present(env):
    assert manual(env) == (False, False)


# ----------------------------------------------------------------------------- applied.json

def test_mark_applied_writes_and_replaces_atomically(env):
    assert status.mark_applied(HASH) == {"ok": True}
    first = status.read_applied()
    assert first["hash"] == HASH and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", first["time"])
    assert status.mark_applied("b" * 64) == {"ok": True}
    assert status.read_applied()["hash"] == "b" * 64
    # no temp files are left behind
    assert sorted(os.listdir(status.STATE_DIR)) == ["applied.json"]


def test_mark_applied_failure_keeps_the_old_file(env, monkeypatch):
    status.mark_applied(HASH)
    before = Path(status.applied_path()).read_text()

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    result = status.mark_applied("c" * 64)
    assert result["ok"] is False
    assert Path(status.applied_path()).read_text() == before
    assert sorted(os.listdir(status.STATE_DIR)) == ["applied.json"]


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64, HASH + "0", "a; rm -rf /", None])
def test_mark_applied_rejects_bad_hash(env, bad):
    assert status.mark_applied(bad)["ok"] is False
    assert not os.path.exists(status.applied_path())


def test_read_applied_missing_or_corrupt(env):
    assert status.read_applied() is None
    os.makedirs(status.STATE_DIR)
    for text in ("{not json", "[]", '{"hash": 1, "time": "x"}', '{"hash": "x"}'):
        Path(status.applied_path()).write_text(text)
        assert status.read_applied() is None


# ----------------------------------------------------------------------------- build_status

def test_build_status_everything_present(env):
    put(env, "dnscrypt-proxy.toml", (FIX / "managed.toml").read_text())
    put(env, "dnscrypt-proxy.log", (FIX / "dnscrypt-proxy.log").read_text())
    manual(env, MAPPING + "\n", True)
    status.mark_applied(HASH)
    result = status.build_status()
    assert set(result) == {"running", "live_servers", "total_servers", "override", "direct_servers",
                           "manual_override_present", "manual_template_without_mapping", "applied"}
    assert result["running"] is True
    assert result["live_servers"] == 3 and result["total_servers"] == 2
    assert result["override"] == "applied"
    assert result["direct_servers"] == ["doh-one", "direct-one"]
    assert result["manual_override_present"] is True and result["manual_template_without_mapping"] is False
    assert result["applied"]["hash"] == HASH
    json.dumps(result)


def test_build_status_all_files_missing(env):
    assert status.build_status() == {
        "running": True, "live_servers": None, "total_servers": 0, "override": "disabled",
        "direct_servers": [], "manual_override_present": False, "manual_template_without_mapping": False,
        "applied": None}


def test_build_status_invariant_violated(env):
    put(env, "dnscrypt-proxy.toml", (FIX / "invariant-violated.toml").read_text())
    result = status.build_status()
    assert result["override"] == "invariant-violated" and result["total_servers"] == 0


def test_service_running_false_when_rc_fails(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("service")
    monkeypatch.setattr(subprocess, "call", missing)
    assert status.service_running() is False
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: 1)
    assert status.service_running() is False
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: 0)
    assert status.service_running() is True


def test_cli_status_and_mark_applied(tmp_path):
    # the real script as configd runs it; paths do not exist here, so only the neutral values appear
    out = subprocess.run([sys.executable, str(SCRIPTS / "status.py"), "status"],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    assert data["applied"] is None or isinstance(data["applied"], dict)
    bad = subprocess.run([sys.executable, str(SCRIPTS / "status.py"), "mark-applied", "nothex"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and json.loads(bad.stdout)["ok"] is False
    usage = subprocess.run([sys.executable, str(SCRIPTS / "status.py")], capture_output=True, text=True)
    assert usage.returncode == 2


# ----------------------------------------------------------------------------- configd actions (C-02)

def parse_actions():
    actions = {}
    current = None
    for line in ACTIONS.read_text().splitlines():
        if not line.strip():
            continue
        head = re.match(r"^\[([^\]]+)\]$", line)
        if head:
            current = actions.setdefault(head.group(1), {})
            continue
        key, _, value = line.partition(":")
        current[key] = value
    return actions


def test_actions_are_exactly_c02():
    assert set(parse_actions()) == {"status", "catalog", "mark-applied", "test-start", "test-status"}


def test_action_commands_and_parameters():
    actions = parse_actions()
    py = "/usr/local/bin/python3 /usr/local/opnsense/scripts/dnscrypt_routes/"
    assert actions["status"]["command"] == py + "status.py status"
    assert actions["catalog"]["command"] == py + "catalog.py"
    assert actions["mark-applied"]["command"] == py + "status.py mark-applied"
    assert actions["test-start"]["command"] == py + "testrun.py start"
    assert actions["test-status"]["command"] == py + "testrun.py status"
    for name, action in actions.items():
        assert action["type"] == "script_output", name
        assert action["parameters"] == ("%s" if name == "mark-applied" else ""), name
        assert action["message"], name


def test_action_scripts_exist_and_take_these_arguments():
    for script, args in (("status.py", ("status", "mark-applied")), ("testrun.py", ("start", "status"))):
        text = (SCRIPTS / script).read_text()
        for arg in args:
            assert arg in text, (script, arg)
    assert (SCRIPTS / "catalog.py").is_file()


# ----------------------------------------------------------------------------- PHP source checks

def php(name):
    return (API / name).read_text()


def method(src, name):
    m = re.search(rf"function {name}\(.*?\n    \}}\n", src, re.S)
    assert m, name
    return m.group(0)


def test_php_files_are_balanced_and_namespaced():
    for path in API.glob("*.php"):
        text = path.read_text()
        assert text.startswith("<?php\n\nnamespace OPNsense\\DnscryptRoutes\\Api;"), path.name
        assert text.count("{") == text.count("}"), path.name
        assert text.count("(") == text.count(")"), path.name
        assert "?>" not in text, path.name
    assert {p.name for p in API.glob("*.php")} == {
        "CatalogController.php", "RuleCheckTrait.php", "ServiceController.php", "SettingsController.php"}


def test_php_controller_bases():
    settings, service, catalog = php("SettingsController.php"), php("ServiceController.php"), php("CatalogController.php")
    assert "class SettingsController extends ApiMutableModelControllerBase" in settings
    assert "protected static $internalModelName = 'dnscryptroutes';" in settings
    assert "protected static $internalModelClass = 'OPNsense\\DnscryptRoutes\\DnscryptRoutes';" in settings
    assert "class ServiceController extends ApiMutableServiceControllerBase" in service
    assert "protected static $internalServiceTemplate = 'OPNsense/Dnscryptproxy';" in service
    assert "protected static $internalServiceName = 'dnscryptproxy';" in service
    # the stock plugin's own ServiceController: the General model, mounted at //OPNsense/dnscryptproxy/general
    assert "protected static $internalServiceClass = '\\OPNsense\\Dnscryptproxy\\General';" in service
    assert "protected static $internalServiceEnabled = 'enabled';" in service
    assert "class CatalogController extends ApiControllerBase" in catalog


def test_php_settings_has_exactly_the_c03_endpoints():
    src = php("SettingsController.php")
    actions = set(re.findall(r"public function (\w+)Action\(", src))
    assert actions == {"set", "searchRelay", "getRelay", "addRelay", "setRelay", "delRelay",
                       "searchResolver", "getResolver", "addResolver", "setResolver", "delResolver"}


def test_php_every_write_path_goes_through_the_rule_check_before_saving():
    src = php("SettingsController.php")
    # the only place that serializes or saves
    # no direct serialize/Config save: core save() does the read-only check, admin check and audit message
    assert "serializeToConfig" not in src and "Config::getInstance()->save" not in src
    assert src.count("$this->save(false, true);") == 1
    save = method(src, "checkAndSave")
    assert save.index("ruleErrors(") < save.index("$this->save(false, true);")
    # the refusal itself: guard and early return come before the save
    guard = "if (count($errors) > 0) {\n            return $this->failure($errors);\n        }"
    assert guard in save and save.index(guard) < save.index("$this->save(")
    # config lock before the model is loaded, on every write path
    for name in ("setAction", "writeItem", "deleteItem"):
        body = method(src, name)
        assert body.index("Config::getInstance()->lock();") < body.index("$this->getModel()"), name
    assert "->validateRouting(" not in src  # lives in the trait, not duplicated
    # all write endpoints end in checkAndSave via set / writeItem / deleteItem
    for name in ("setAction",):
        assert "checkAndSave(" in method(src, name)
    assert "checkAndSave(" in method(src, "writeItem") and "checkAndSave(" in method(src, "deleteItem")
    for name in ("addRelayAction", "setRelayAction", "addResolverAction", "setResolverAction"):
        assert "writeItem(" in method(src, name), name
    for name in ("delRelayAction", "delResolverAction"):
        assert "deleteItem(" in method(src, name), name
    assert "'warnings'" in save and "getWarnings(" in save
    assert "isRelayReferenced" in method(src, "deleteItem")
    assert "deleteItem('relays.relay', $uuid, true)" in method(src, "delRelayAction")
    assert "deleteItem('resolvers.resolver', $uuid, false)" in method(src, "delResolverAction")


def test_php_write_endpoints_require_post():
    src = php("SettingsController.php")
    for name in ("setAction", "writeItem", "deleteItem"):
        assert "isPost()" in method(src, name), name


def test_php_rule_check_composition_and_path_prefix():
    trait = php("RuleCheckTrait.php")
    body = method(trait, "ruleErrors")
    assert "foreach ($mdl->performValidation(true) as $msg) {" in body
    assert "$errors[$path] = isset($errors[$path]) ? $errors[$path] . ' ' . $msg->getMessage() : $msg->getMessage();" in body
    loop = body[body.index("foreach ($mdl->validateRouting($catalog)"):]
    assert "$errors[$path] = isset($errors[$path]) ? $errors[$path] . ' ' . $message : $message;" in loop
    assert body.rstrip().endswith("return $errors;\n    }")
    # performValidation() is model-relative (WP-03 Notes), validateRouting() is already full
    assert "'dnscryptroutes.' . $msg->getField()" in body
    assert re.search(r"validateRouting\(\$catalog\) as \$path => \$message", body)
    assert "dnscryptroutes catalog" in method(trait, "loadCatalog")
    assert "['result' => 'failed', 'validations' => $errors]" in method(trait, "failure")


def test_php_reconfigure_checks_first_then_parent_then_marks_applied():
    body = method(php("ServiceController.php"), "reconfigureAction")
    assert "new DnscryptRoutes()" in body and "$this->getModel()" not in body.replace("not $this->getModel()", "")
    assert body.index("ruleErrors(") < body.index("parent::reconfigureAction()") < body.index("mark-applied")
    # a refused reconfigure returns before the parent runs
    refusal = body[:body.index("parent::reconfigureAction()")]
    assert "if (count($errors) > 0) {\n            return ['status' => 'failed'" in refusal
    assert "return ['status' => 'failed', 'result' => 'failed', 'validations' => $errors];" in refusal
    assert body.count("parent::reconfigureAction()") == 1


def test_php_service_status_and_test_proxies():
    src = php("ServiceController.php")
    status_body = method(src, "statusAction")
    assert "parent::statusAction()" in status_body and "dnscryptroutes status" in status_body
    assert "'pending'" in status_body and "modelHash()" in status_body
    assert "dnscryptroutes test-start" in method(src, "testStartAction")
    assert "dnscryptroutes test-status" in method(src, "testStatusAction")
    assert "isPost()" in method(src, "testStartAction")


def test_php_actions_called_exist_in_actions_conf():
    called = set()
    for path in API.glob("*.php"):
        called |= set(re.findall(r"dnscryptroutes ([a-z-]+)", path.read_text()))
    assert called == set(parse_actions())


def test_php_test_status_failure_is_a_complete_c04_object():
    body = method(php("ServiceController.php"), "testStatusAction")
    for key in ("state", "started", "finished", "duration_s", "error", "check", "live_servers", "resolvers", "queries"):
        assert f"'{key}'" in body, key
    assert "'ok' => false" in body


def test_php_reconfigure_passes_a_failed_record_through():
    body = method(php("ServiceController.php"), "reconfigureAction")
    assert "empty($recorded['ok'])" in body and "$result['status'] = 'failed';" in body


def test_php_configd_results_are_null_safe():
    for path in API.glob("*.php"):
        for call in re.findall(r"trim\(\(new Backend\(\)\)->configdRun\([^;]*", path.read_text()):
            assert "?? ''" in call, (path.name, call)


# ----------------------------------------------------------------------------- running check (F2), hash anchoring (F8)

def test_running_check_calls_the_stock_rc_script(monkeypatch):
    assert status.status_command() == ["/usr/local/etc/rc.d/dnscrypt-proxy", "onestatus"]
    seen = []
    monkeypatch.setattr(subprocess, "call", lambda cmd, **k: seen.append(cmd) or 0)
    assert status.service_running() is True
    assert seen == [["/usr/local/etc/rc.d/dnscrypt-proxy", "onestatus"]]


def test_mark_applied_rejects_trailing_newline(env):
    assert status.mark_applied(HASH + "\n")["ok"] is False


# ----------------------------------------------------------------------------- WP-M4-fix-2: no bytecode (WP11-F1), stable hash (WP11-F2)

def test_action_scripts_leave_no_bytecode_cache(tmp_path):
    # configd runs the scripts as root with plain python3; a __pycache__ next to them would survive pkg remove (R-04)
    copy = tmp_path / "scripts"
    copy.mkdir()
    for script in SCRIPTS.glob("*.py"):
        (copy / script.name).write_text(script.read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    called = {cmd.split()[1].rsplit("/", 1)[1] for cmd in (a["command"] for a in parse_actions().values())}
    assert called == {"status.py", "catalog.py", "testrun.py"}
    for script in sorted(called):
        # an unknown option: every script imports everything, then stops with a usage error and does nothing else
        run = subprocess.run([sys.executable, str(copy / script), "--no-such-option"], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        assert run.returncode == 2, (script, run.stderr)
    assert not list(copy.rglob("__pycache__")) and not list(copy.rglob("*.pyc"))


def test_php_model_hash_ignores_persisted_at_and_is_the_only_hash():
    body = method(php("RuleCheckTrait.php"), "modelHash")
    # core BaseModel::toXML() stamps persisted_at on every save; hash a copy without it
    assert "$copy = new \\SimpleXMLElement((string)$node->asXML());" in body
    assert body.index("unset($copy['persisted_at']);") < body.index("hash('sha256', (string)$copy->asXML())")
    assert "$node->asXML())" not in body.replace("new \\SimpleXMLElement((string)$node->asXML())", "")
    # the hash recorded at apply and the one compared for pending come from this one function
    service = php("ServiceController.php")
    assert "$hash = $this->modelHash();" in method(service, "reconfigureAction")
    assert "!== $this->modelHash()" in method(service, "statusAction")
    for path in API.glob("*.php"):
        text = path.read_text()
        assert text.count("hash('sha256'") == (2 if path.name == "RuleCheckTrait.php" else 0), path.name
