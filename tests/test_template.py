"""Render tests for dnscrypt-proxy-routes.toml against reference/stock-template.toml (R-01..R-04, R-21, C-06)."""
import json
import re

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # python < 3.11: needs tomli (see WP-02 notes)
    import tomli as tomllib

from fixtures.template import models as m
from fixtures.template.models import ROOT
from render import MANUAL_TARGET_NAME, MANUAL_TEMPLATE_NAME, STOCK_TEMPLATE_NAME

INVALID = ["dnscrypt-routes-invalid-config"]


def first_line(text):
    return text.split("\n", 1)[0]


def parse(text):
    return tomllib.loads(text)  # raises on invalid TOML, including duplicate keys


def stock_render(tree, config):
    return tree.render(STOCK_TEMPLATE_NAME, config)


def manual_render(tree, config):
    return tree.render(MANUAL_TEMPLATE_NAME, config)


def assert_fail_closed(out, marker):
    assert first_line(out) == "# dnscrypt-routes: " + marker
    doc = parse(out)
    assert doc["server_names"] == INVALID
    assert "routes" not in doc.get("anonymized_dns", {})
    assert not re.search(r"(?m)^\s*routes\s*=", out)
    assert out.count("server_names") == 1


# --- disabled plugin: output equals what would be generated without the plugin (R-01) ---

@pytest.mark.parametrize("config", [m.preset_disabled, m.base_only, lambda: m.stock_lists_set(enabled=False), m.base_disabled])
def test_disabled_no_manual_template_equals_stock(make_tree, config):
    tree = make_tree()
    assert tree.render_plugin(config()) == stock_render(tree, config())


def test_disabled_with_active_manual_mapping_equals_manual_render(make_tree):
    tree = make_tree(manual_template=True, manual_target=True)
    cfg = m.preset_disabled()
    out = tree.render_plugin(cfg)
    assert out == manual_render(tree, cfg)
    assert out != stock_render(tree, cfg)


def test_disabled_manual_template_without_target_equals_stock(make_tree):
    tree = make_tree(manual_template=True)
    cfg = m.preset_disabled()
    assert tree.render_plugin(cfg) == stock_render(tree, cfg)


@pytest.mark.parametrize(
    "target_text",
    [
        "dnscrypt-proxy-other.toml:/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml\n",
        "dnscrypt-proxy-eu.toml:/usr/local/etc/dnscrypt-proxy/elsewhere.toml\n",
        "dnscrypt_proxy:/etc/rc.conf.d/dnscrypt_proxy\n",
    ],
)
def test_disabled_target_mapping_something_else_equals_stock(make_tree, target_text):
    tree = make_tree(manual_template=True)
    tree.write(MANUAL_TARGET_NAME, target_text)
    cfg = m.preset_disabled()
    assert tree.render_plugin(cfg) == stock_render(tree, cfg)


def test_disabled_active_target_but_manual_template_missing_equals_stock(make_tree):
    tree = make_tree(manual_target=True)  # mapping present, template file absent
    cfg = m.preset_disabled()
    assert tree.render_plugin(cfg) == stock_render(tree, cfg)


# --- enabled (R-02, R-03) ---

def test_enabled_with_manual_template_still_wraps_stock(make_tree):
    cfg = m.preset_enabled()
    plain = make_tree().render_plugin(cfg)
    tree = make_tree(manual_template=True, manual_target=True)
    out = tree.render_plugin(cfg)
    assert out == plain
    manual = manual_render(tree, cfg)
    manual_only = [ln for ln in manual.splitlines() if ln.strip() and ln not in plain.splitlines()]
    assert manual_only, "the manual render must differ from the plugin render for this test to mean anything"
    assert not set(manual_only) & set(out.splitlines())
    assert first_line(out) == "# dnscrypt-routes: managed"


def test_enabled_parses_and_owned_keys_equal_expected(make_tree):
    out = make_tree().render_plugin(m.preset_enabled())
    assert first_line(out) == "# dnscrypt-routes: managed"
    doc = parse(out)
    assert doc["server_names"] == ["scaleway-ams", "cs-de", "nwps.fi", "dorriere-fr", "dnscry.pt-nuremberg-ipv4"]
    assert doc["lb_strategy"] == "wp2"
    anon = doc["anonymized_dns"]
    assert anon["skip_incompatible"] is True
    assert anon["direct_cert_fallback"] is True
    assert [r["server_name"] for r in anon["routes"]] == doc["server_names"]
    assert doc["dnscrypt_servers"] is True and doc["doh_servers"] is False and doc["odoh_servers"] is False
    assert "edns_client_subnet" not in doc
    # stock settings flow through
    assert doc["listen_addresses"] == ["127.0.0.1:5353"]
    assert doc["max_clients"] == 250


def test_ecs_off_has_no_edns_client_subnet(make_tree):
    out = make_tree().render_plugin(m.config(ecs=False))
    assert "edns_client_subnet" not in out


def test_ecs_on_with_preset_subnet(make_tree):
    doc = parse(make_tree().render_plugin(m.ecs_preset_subnet()))
    assert doc["edns_client_subnet"] == ["146.70.82.0/24"]


def test_ecs_on_with_custom_subnet(make_tree):
    out = make_tree().render_plugin(m.ecs_custom_subnet())
    assert parse(out)["edns_client_subnet"] == ["198.51.100.0/24"]
    assert out.count("edns_client_subnet") == 1


def test_disabled_resolver_is_left_out(make_tree):
    cfg = m.preset_enabled()
    cfg["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][4]["enabled"] = "0"
    doc = parse(make_tree().render_plugin(cfg))
    assert "dnscry.pt-nuremberg-ipv4" not in doc["server_names"]
    assert len(doc["anonymized_dns"]["routes"]) == 4


def test_stock_lists_set_are_stripped(make_tree):
    tree = make_tree()
    cfg = m.stock_lists_set()
    stock = stock_render(tree, cfg)
    assert "server_names = ['cloudflare','google']" in stock and "anon-a" in stock  # fixture has something to strip
    out = tree.render_plugin(cfg)
    doc = parse(out)
    assert first_line(out) == "# dnscrypt-routes: managed"
    assert doc["server_names"] == m.EFFECTIVE["server_names"]
    assert "cloudflare" not in out and "anon-a" not in out
    assert "*" not in [r["server_name"] for r in doc["anonymized_dns"]["routes"]]
    assert out.count("server_names") == 1 and len(re.findall(r"(?m)^\s*routes\s*=", out)) == 1


def test_stock_protocol_lines_are_forced_each_exactly_once(make_tree):
    tree = make_tree()
    cfg = m.stock_protocols_swapped()
    stock = stock_render(tree, cfg)
    assert "doh_servers = true" in stock and "odoh_servers = true" in stock and "dnscrypt_servers = false" in stock
    out = tree.render_plugin(cfg)
    for line in ("dnscrypt_servers = true", "doh_servers = false", "odoh_servers = false"):
        assert len(re.findall(r"(?m)^%s$" % line, out)) == 1, line
    assert len(re.findall(r"(?m)^(?:dnscrypt|doh|odoh)_servers\b", out)) == 3
    assert first_line(out) == "# dnscrypt-routes: managed"
    parse(out)


@pytest.mark.parametrize("key", ["dnscrypt_servers", "doh_servers", "odoh_servers"])
def test_stock_variant_without_protocol_line_fails_closed(make_tree, stock_text, key):
    tree = make_tree(stock_text=m.stock_without_line(stock_text, key))
    out = tree.render_plugin(m.preset_enabled())
    assert_fail_closed(out, "override-not-applied")


def test_base_disabled_is_empty_like_stock(make_tree):
    tree = make_tree()
    cfg = m.base_disabled()
    out = tree.render_plugin(cfg)
    assert out == stock_render(tree, cfg)
    assert out.strip() == ""


def test_default_stock_lists_empty_is_normal_managed(make_tree):
    tree = make_tree()
    cfg = m.preset_enabled()
    stock = stock_render(tree, cfg)
    assert not re.search(r"(?m)^\s*(server_names|routes)\s*=", stock)  # nothing to strip
    out = tree.render_plugin(cfg)
    assert first_line(out) == "# dnscrypt-routes: managed"
    assert "override-not-applied" not in out


def test_anchor_missing_fails_closed_with_override_not_applied(make_tree, stock_text):
    tree = make_tree(stock_text=m.stock_without_anchor(stock_text))
    out = tree.render_plugin(m.preset_enabled())
    assert_fail_closed(out, "override-not-applied")


def test_anchor_missing_with_stock_lists_still_has_no_routes(make_tree, stock_text):
    tree = make_tree(stock_text=m.stock_without_anchor(stock_text))
    out = tree.render_plugin(m.stock_lists_set())
    assert_fail_closed(out, "override-not-applied")
    assert "anon-a" not in out


# --- fail closed on a broken model (R-03, R-21) ---

FAIL_CLOSED_FIXTURES = {
    "no-enabled-resolver": m.no_enabled_resolver,
    "resolver-without-relays": m.resolver_without_relays,
    "dangling-relay-uuid": m.dangling_relay_uuid,
    "relay-reference-is-a-resolver": m.relay_reference_is_a_resolver,
}


@pytest.mark.parametrize("name", sorted(FAIL_CLOSED_FIXTURES))
def test_invariant_violation_fails_closed(make_tree, name):
    out = make_tree().render_plugin(FAIL_CLOSED_FIXTURES[name]())
    assert_fail_closed(out, "invariant-violated")


def test_invariant_violation_with_no_resolver_rows_fails_closed(make_tree):
    cfg = m.preset_enabled()
    del cfg["OPNsense"]["dnscryptroutes"]["resolvers"]
    assert_fail_closed(make_tree().render_plugin(cfg), "invariant-violated")


def test_invariant_violation_strips_stock_lists_too(make_tree):
    cfg = m.stock_lists_set()
    cfg["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][0]["relays"] = "relay-does-not-exist"
    out = make_tree().render_plugin(cfg)
    assert_fail_closed(out, "invariant-violated")
    assert "cloudflare" not in out and "anon-a" not in out


def _set_resolver_name(c, v):
    c["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][0]["name"] = v


def _set_relay_name(c, v):
    c["OPNsense"]["dnscryptroutes"]["relays"]["relay"][0]["name"] = v


def _set_lb(c, v):
    c["OPNsense"]["dnscryptroutes"]["general"]["lbStrategy"] = v


def _set_ecs(c, v):
    g = c["OPNsense"]["dnscryptroutes"]["general"]
    g["ecsEnabled"] = "1"
    g["ecsSubnet"] = v


BAD_VALUES = ["bad'x", "bad\nx", "bad\rx", "bad\x01x", "bad\x7fx", "bad\x00x", "bad\x1fx"]
BAD_CASES = (
    [("resolver-name", _set_resolver_name, v) for v in BAD_VALUES + [""]]
    + [("relay-name", _set_relay_name, v) for v in BAD_VALUES + [""]]
    + [("lb-strategy", _set_lb, v) for v in BAD_VALUES + [""]]
    + [("ecs-subnet", _set_ecs, v) for v in BAD_VALUES + [""]]
)


@pytest.mark.parametrize("setter,value", [(s, v) for _, s, v in BAD_CASES],
                         ids=["%s-%r" % (n, v) for n, _, v in BAD_CASES])
def test_unusable_value_fails_closed(make_tree, setter, value):
    cfg = m.preset_enabled()
    setter(cfg, value)
    assert_fail_closed(make_tree().render_plugin(cfg), "invariant-violated")


# dnscrypt-proxy 2.1.15 route() (serversInfo.go:598-614) reads a via entry "*" as any registered relay and
# "sdns:..." as a relay stamp; either would bypass the operator rule (M4-A-F1)
WILDCARD_RELAY_NAMES = ["*", "sdns://gQ8xNjMuMTcyLjE4MC4xMjU", "sdns:gQ8xNjMuMTcyLjE4MC4xMjU", "SDNS:x", "anon-*"]


@pytest.mark.parametrize("value", WILDCARD_RELAY_NAMES)
def test_wildcard_or_stamp_relay_name_fails_closed(make_tree, value):
    cfg = m.preset_enabled()
    _set_relay_name(cfg, value)
    out = make_tree().render_plugin(cfg)
    assert_fail_closed(out, "invariant-violated")
    assert "via=" not in out


@pytest.mark.parametrize("value", ["anon-sdns-x", "xsdns:y"])
def test_relay_name_containing_sdns_elsewhere_is_managed(make_tree, value):
    cfg = m.preset_enabled()
    _set_relay_name(cfg, value)
    assert first_line(make_tree().render_plugin(cfg)) == "# dnscrypt-routes: managed"


@pytest.mark.parametrize("value", ["any", "ANY", "192.0.2.0", "2001:db8::1", "no-slash"])
def test_ecs_value_without_slash_fails_closed(make_tree, value):
    # defense in depth behind the model's WildcardEnabled=N / NetMaskRequired=Y
    cfg = m.preset_enabled()
    _set_ecs(cfg, value)
    assert_fail_closed(make_tree().render_plugin(cfg), "invariant-violated")


@pytest.mark.parametrize("value", ["any", "192.0.2.0"])
def test_ecs_off_ignores_value_without_slash(make_tree, value):
    cfg = m.preset_enabled()
    cfg["OPNsense"]["dnscryptroutes"]["general"]["ecsSubnet"] = value
    out = make_tree().render_plugin(cfg)
    assert first_line(out) == "# dnscrypt-routes: managed"


@pytest.mark.parametrize("name", sorted(FAIL_CLOSED_FIXTURES))
def test_fail_closed_explains_itself_after_the_marker(make_tree, name):
    out = make_tree().render_plugin(FAIL_CLOSED_FIXTURES[name]())
    lines = out.split("\n")
    assert lines[0] == "# dnscrypt-routes: invariant-violated"
    assert lines[1].startswith("# DNS is stopped on purpose")
    assert lines[2].startswith("# Fix:") and "correct the settings" in lines[2] and "untick Enable anonymized routing and Save" in lines[2]
    assert lines[3] == "server_names = ['dnscrypt-routes-invalid-config']"
    parse(out)


def test_override_not_applied_explains_itself_after_the_marker(make_tree, stock_text):
    tree = make_tree(stock_text=m.stock_without_anchor(stock_text))
    out = tree.render_plugin(m.preset_enabled())
    lines = out.split("\n")
    assert lines[0] == "# dnscrypt-routes: override-not-applied"
    assert lines[1].startswith("# DNS is stopped on purpose")
    assert lines[2].startswith("# Fix: the stock os-dnscrypt-proxy template changed; untick Enable anonymized routing")
    assert "update os-dnscrypt-routes" in lines[2] and "correct the settings" not in lines[2]
    assert lines[3] == "server_names = ['dnscrypt-routes-invalid-config']"
    parse(out)


@pytest.mark.parametrize("value", ["bad'x", "bad\nx", "bad\x01x", ""])
def test_ecs_off_ignores_bad_subnet(make_tree, value):
    cfg = m.preset_enabled()
    cfg["OPNsense"]["dnscryptroutes"]["general"]["ecsSubnet"] = value
    out = make_tree().render_plugin(cfg)
    assert first_line(out) == "# dnscrypt-routes: managed"
    assert "edns_client_subnet" not in parse(out)


def test_tab_in_name_is_allowed(make_tree):
    cfg = m.preset_enabled()
    _set_resolver_name(cfg, "a\tb")
    assert first_line(make_tree().render_plugin(cfg)) == "# dnscrypt-routes: managed"


# --- the proof that today's router policy is reproduced ---

def test_preset_matches_effective_settings(make_tree):
    ref = m.EFFECTIVE
    doc = parse(make_tree().render_plugin(m.preset_enabled()))
    assert doc["server_names"] == ref["server_names"]
    assert doc["lb_strategy"] == ref["lb_strategy"]
    anon, ref_anon = doc["anonymized_dns"], ref["anonymized_dns"]
    assert anon["routes"] == ref_anon["routes"]
    assert anon["skip_incompatible"] == ref_anon["skip_incompatible"]
    assert anon["direct_cert_fallback"] == ref_anon["direct_cert_fallback"]
    # ECS is off in the preset (owner decision); with the preset subnet on, it equals the reference value
    assert "edns_client_subnet" not in doc
    assert parse(make_tree().render_plugin(m.ecs_preset_subnet()))["edns_client_subnet"] == ref["edns_client_subnet"]
    for key in ("dnscrypt_servers", "doh_servers", "odoh_servers"):
        assert doc[key] == ref[key], key
    # the stock-owned settings of the reference come through unchanged
    for key in (
        "listen_addresses", "ipv4_servers", "ipv6_servers", "require_dnssec", "require_nolog", "require_nofilter",
        "dnscrypt_ephemeral_keys", "cert_refresh_delay", "cache", "block_ipv6", "force_tcp", "timeout",
        "bootstrap_resolvers", "ignore_system_dns", "log_level", "use_syslog", "netprobe_timeout", "max_clients",
        "keepalive", "tls_disable_session_tickets",
    ):
        assert doc[key] == ref[key], key


def test_target_file_content(make_tree):
    from render import PLUGIN_TARGET_NAME, PLUGIN_TEMPLATES

    text = (PLUGIN_TEMPLATES / PLUGIN_TARGET_NAME).read_text()
    assert text == "dnscrypt-proxy-routes.toml:/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml\n"


def test_render_from_preset_json_equals_effective_settings(make_tree):
    """The template fed with preset.json itself (name-to-uuid mapping as in M1_0_0), not the reference-derived fixture."""
    preset = json.loads(
        (ROOT / "plugin/dns/dnscrypt-routes/src/opnsense/mvc/app/models/OPNsense/DnscryptRoutes/preset.json").read_text()
    )
    relay_uuid = {r["name"]: "relay-uuid-%d" % i for i, r in enumerate(preset["relays"])}
    cfg = m.preset_enabled()
    cfg["OPNsense"]["dnscryptroutes"]["relays"] = {
        "relay": [{"@uuid": relay_uuid[r["name"]], "name": r["name"], "operator": r["operator"]} for r in preset["relays"]]
    }
    cfg["OPNsense"]["dnscryptroutes"]["resolvers"] = {
        "resolver": [
            {
                "@uuid": "resolver-uuid-%d" % i,
                "enabled": "1" if r["enabled"] else "0",
                "name": r["name"],
                "operator": r["operator"],
                "relays": ",".join(relay_uuid[n] for n in r["relays"]),
            }
            for i, r in enumerate(preset["resolvers"])
        ]
    }
    ref = m.EFFECTIVE
    out = make_tree().render_plugin(cfg)
    assert first_line(out) == "# dnscrypt-routes: managed"
    doc = parse(out)
    assert doc["server_names"] == ref["server_names"]
    assert doc["lb_strategy"] == ref["lb_strategy"]
    assert doc["anonymized_dns"]["routes"] == ref["anonymized_dns"]["routes"]
