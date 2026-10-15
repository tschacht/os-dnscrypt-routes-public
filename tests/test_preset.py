"""WP-03: preset.json against the reference (C-01) and the catalog-independent R-06 rules."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "plugin/dns/dnscrypt-routes/src/opnsense/mvc/app/models/OPNsense/DnscryptRoutes"
PRESET = json.loads((MODEL / "preset.json").read_text())
REFERENCE = json.loads((ROOT / "reference/effective-settings.json").read_text())

ALIASES = {"cs": "cryptostorm", "nwps.fi": "nwps"}
# C-05 operator_guess vectors
VECTORS = {
    "cs-de": "cryptostorm",
    "anon-cs-fr": "cryptostorm",
    "scaleway-ams": "scaleway",
    "anon-scaleway-ams": "scaleway",
    "anon-scaleway": "scaleway",
    "nwps.fi": "nwps",
    "dorriere-fr": "dorriere",
    "dnscry.pt-nuremberg-ipv4": "dnscry.pt",
}


def operator_guess(name):
    name = name.removeprefix("anon-") if hasattr(name, "removeprefix") else re.sub(r"^anon-", "", name)
    head = name.split("-", 1)[0]
    return ALIASES.get(head, head).lower()


def relay_by_name():
    return {r["name"]: r for r in PRESET["relays"]}


def test_operator_guess_helper_matches_vectors():
    for name, op in VECTORS.items():
        assert operator_guess(name) == op, name


def test_servers_and_routes_equal_reference():
    names = [r["name"] for r in PRESET["resolvers"] if r["enabled"]]
    assert names == REFERENCE["server_names"]
    routes = {r["name"]: r["relays"] for r in PRESET["resolvers"]}
    ref_routes = {r["server_name"]: r["via"] for r in REFERENCE["anonymized_dns"]["routes"]}
    assert routes == ref_routes
    used = {n for via in ref_routes.values() for n in via}
    assert {r["name"] for r in PRESET["relays"]} == used


def test_operators_equal_catalog_guess():
    for entry in PRESET["resolvers"] + PRESET["relays"]:
        assert entry["operator"] == operator_guess(entry["name"]), entry["name"]
    for name, op in VECTORS.items():
        entry = next(e for e in PRESET["resolvers"] + PRESET["relays"] if e["name"] == name)
        assert entry["operator"] == op


def test_shape():
    for r in PRESET["resolvers"]:
        assert set(r) == {"name", "operator", "enabled", "relays"}
    for r in PRESET["relays"]:
        assert set(r) == {"name", "operator"}


def test_r06_rules_hold_for_preset():
    relays = relay_by_name()
    assert any(r["enabled"] for r in PRESET["resolvers"])
    for r in PRESET["resolvers"]:
        assert r["operator"].strip()
        if r["enabled"]:
            assert len(r["relays"]) >= 1, r["name"]
        for rel in r["relays"]:
            assert rel in relays, f"dangling relay {rel}"
            assert relays[rel]["operator"].strip()
            assert relays[rel]["operator"] != r["operator"], f"{r['name']} via {rel}"
            assert rel != "anon-" + r["name"], f"{r['name']} via its own relay"
    names = [r["name"] for r in PRESET["resolvers"]]
    assert len(names) == len(set(names))
    rnames = [r["name"] for r in PRESET["relays"]]
    assert len(rnames) == len(set(rnames))


def test_reference_matches_c01_defaults():
    xml = (MODEL / "DnscryptRoutes.xml").read_text()

    def default(tag):
        m = re.search(rf"<{tag} type=\"\w+\">.*?<Default>(.*?)</Default>", xml, re.S)
        assert m, tag
        return m.group(1)

    anon = REFERENCE["anonymized_dns"]
    assert REFERENCE["lb_strategy"] == default("lbStrategy") == "wp2"
    assert anon["skip_incompatible"] is (default("skipIncompatible") == "1")
    assert anon["direct_cert_fallback"] is (default("directCertFallback") == "1")
    assert REFERENCE["edns_client_subnet"] == [default("ecsSubnet")]
    assert default("enabled") == "0" and default("ecsEnabled") == "0"


def test_menu_uses_stock_group_node():
    # Stock os-dnscrypt-proxy Menu.xml: <Services><DNSCrypt-Proxy> (case-sensitive)
    menu = (MODEL / "Menu/Menu.xml").read_text()
    assert re.search(r"<Services>\s*<DNSCrypt-Proxy>", menu)
    assert 'url="/ui/dnscryptroutes"' in menu and 'order="15"' in menu


def test_php_path_forms():
    php = (MODEL / "DnscryptRoutes.php").read_text()
    # path builders are model-relative; the prefix is added only by full()
    assert php.count("self::PREFIX") == 1
    assert "return self::PREFIX . '.' . $path;" in php

    def body(name):
        m = re.search(rf"public function {name}\(.*?\n    \}}\n", php, re.S)
        assert m, name
        return m.group(0)

    assert "self::full(" not in body("performValidation")
    assert "self::full(" in body("validateRouting")
    assert "self::full($path)" in body("getWarnings")


def _php():
    return (MODEL / "DnscryptRoutes.php").read_text()


def test_stock_readers_use_the_real_stock_models():
    # opnsense/plugins dns/dnscrypt-proxy: models General (serverlist/relaylist at the root) and Server (servers.server[]);
    # there is no \OPNsense\Dnscryptproxy\Dnscryptproxy model (M2-A-F2).
    php = _php()
    assert "Dnscryptproxy\\Dnscryptproxy" not in php
    names = re.search(r"function stockStaticServerNames\(.*?\n    \}\n", php, re.S).group(0)
    lists = re.search(r"function stockListsInUse\(.*?\n    \}\n", php, re.S).group(0)
    assert "class_exists('\\\\OPNsense\\\\Dnscryptproxy\\\\Server')" in names
    assert "new \\OPNsense\\Dnscryptproxy\\Server()" in names
    assert "$stock->servers->server->iterateItems()" in names
    assert "class_exists('\\\\OPNsense\\\\Dnscryptproxy\\\\General')" in lists
    assert "new \\OPNsense\\Dnscryptproxy\\General()" in lists
    assert "$stock->serverlist" in lists and "$stock->relaylist" in lists
    assert "->general->" not in lists and "->server->servers" not in names


def test_ecs_subnet_refuses_any():
    # core NetworkField defaults to WildcardEnabled=Y and then skips its validator for "any" (M2-A-F3)
    xml = (MODEL / "DnscryptRoutes.xml").read_text()
    field = re.search(r'<ecsSubnet type="NetworkField">.*?</ecsSubnet>', xml, re.S).group(0)
    assert "<WildcardEnabled>N</WildcardEnabled>" in field
    assert "<NetMaskRequired>Y</NetMaskRequired>" in field


def test_lb_strategy_labels_are_descriptive_and_keys_unchanged():
    xml = (MODEL / "DnscryptRoutes.xml").read_text()
    opts = re.search(r"<lbStrategy .*?<OptionValues>(.*?)</OptionValues>", xml, re.S).group(1)
    found = dict(re.findall(r"<(\w+)>(.*?)</\1>", opts))
    assert list(found) == ["first", "p2", "ph", "random", "wp2"]
    for key, label in found.items():
        assert label.startswith(key + ": ") and len(label) > len(key) + 2, key
    assert "default" in found["wp2"]


def test_messages_name_the_row_and_the_next_step():
    php = _php()
    # (M2-B-F1, M2-B-F2) the messages are sprintf'd with the resolver/relay name; the unchanged return formats stay
    for text in (
        "Resolver %s has no operator.",
        "Relay %s has no operator.",
        "Resolver %s is enabled but has no relay. Choose at least one relay, or disable the resolver.",
        "Resolver %s refers to a relay that no longer exists.",
        "Relay %s has the same operator as resolver %s. Choose a relay run by a different operator.",
        "Relay %s is the same server as resolver %s. Choose a different relay.",
        "Routing needs at least one enabled resolver. Enable a resolver, or untick Enable anonymized routing.",
        "The enabled stock static server %s has the same name as this resolver",
        "Resolver %s is not in the signed resolver list (public-resolvers.md); it may be retired or mistyped. Check the name, or disable the resolver.",
        "The stock Server list / Relay list is not empty; it is overridden while anonymized routing is enabled, "
        "as are the stock DNSCrypt/DoH/ODoH protocol settings.",
        "Resolver %s is not a DNSCrypt server; only DNSCrypt resolvers can be anonymized.",
        "⚠ %s has a single relay. It is allowed but has no failover.",
        "Relay %s is not in the signed relay list (relays.md); it may be retired or mistyped. "
        "dnscrypt-proxy skips routes through an unknown relay.",
    ):
        assert text in php, text
    for old in (
        "The operator must not be empty.",
        "A referenced relay does not exist.",
        "Only one relay: no relay failover.",
        "The relay is not in the resolver list",
        "The resolver is not listed",
    ):
        assert old not in php, old


def _bad_relay_name(name):
    # mirror of the relay name rule in performValidation (M4-A-F1)
    name = name.strip().lower()
    return "*" in name or name.startswith("sdns:")


def test_relay_name_rule_applies_while_enabled_and_spares_real_names():
    php = _php()
    m = re.search(r"public function performValidation\(.*?\n    \}\n", php, re.S)
    body = m.group(0)
    rule = body.index("strpos($name, '*') !== false || strpos($name, 'sdns:') === 0")
    # after the early return for routing off (R-06: turning routing off is always allowed, M4-A-F3),
    # so enabling with a wildcard or stamp name is refused but unticking Enable never is
    early = body.index("if (!$this->routingEnabled()) {\n            return $messages;\n        }")
    assert early < rule
    assert body.count("$this->routingEnabled()") == 1
    assert body.index("$relays = $this->relayIndex();") < body.index("foreach ($relays as $uuid => $relay)") < rule
    assert "$add($this->relayPath($uuid, 'name'), sprintf(" in body[rule:]
    assert "Relay name %s is not a relay name: dnscrypt-proxy reads * as any relay and sdns: as a server stamp. " \
        "Enter the name from the signed relay list (relays.md)" in body
    for bad in ("*", " * ", "sdns://abc", "SDNS:abc", "anon-*"):
        assert _bad_relay_name(bad), bad
    names = [e["name"] for e in PRESET["resolvers"] + PRESET["relays"]]
    for md in ("relays.md", "public-resolvers.md"):
        names += re.findall(r"(?m)^## (.+)$", (ROOT / "tests/fixtures/catalog" / md).read_text())
    assert len(names) > 20
    assert not [n for n in names if _bad_relay_name(n)]
