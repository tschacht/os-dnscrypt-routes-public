"""Config fixtures (plain dicts, core config.xml shape) for the template render tests.

The routing data comes from reference/effective-settings.json, the same source WP-03's preset.json is verified
against. Operator tags follow the C-05 operator_guess vectors.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EFFECTIVE = json.loads((ROOT / "reference/effective-settings.json").read_text())

ALIASES = {"cs": "cryptostorm", "nwps.fi": "nwps"}


def operator_guess(name):
    base = re.sub(r"^anon-", "", name).split("-")[0]
    return ALIASES.get(base, base).lower()


def _uuid(kind, name):
    return "%s-%s" % (kind, re.sub(r"[^a-z0-9]+", "-", name.lower()))


def stock_general():
    """OPNsense.dnscryptproxy.general as the router has it (reference/effective-settings.json), stock lists empty."""
    e = EFFECTIVE
    flag = lambda v: "1" if v else "0"
    return {
        "enabled": "1",
        "listen_addresses": ",".join(e["listen_addresses"]),
        "max_clients": str(e["max_clients"]),
        "ipv4_servers": flag(e["ipv4_servers"]),
        "ipv6_servers": flag(e["ipv6_servers"]),
        "dnscrypt_servers": flag(e["dnscrypt_servers"]),
        "doh_servers": flag(e["doh_servers"]),
        "odoh_servers": flag(e["odoh_servers"]),
        "require_dnssec": flag(e["require_dnssec"]),
        "require_nolog": flag(e["require_nolog"]),
        "require_nofilter": flag(e["require_nofilter"]),
        "force_tcp": flag(e["force_tcp"]),
        "timeout": str(e["timeout"]),
        "keepalive": str(e["keepalive"]),
        "cert_refresh_delay": str(e["cert_refresh_delay"]),
        "dnscrypt_ephemeral_keys": flag(e["dnscrypt_ephemeral_keys"]),
        "tls_disable_session_tickets": flag(e["tls_disable_session_tickets"]),
        "fallback_resolver": ",".join(e["bootstrap_resolvers"]),
        "ignore_system_dns": flag(e["ignore_system_dns"]),
        "block_ipv6": flag(e["block_ipv6"]),
        "cache": flag(e["cache"]),
        "query_logs": flag(e["query_log_configured"]),
    }


def _plugin(enabled, ecs, ecs_subnet):
    e = EFFECTIVE
    anon = e["anonymized_dns"]
    relay_names = []
    for route in anon["routes"]:
        for via in route["via"]:
            if via not in relay_names:
                relay_names.append(via)
    relays = [
        {"@uuid": _uuid("relay", n), "name": n, "operator": operator_guess(n)} for n in relay_names
    ]
    resolvers = [
        {
            "@uuid": _uuid("resolver", r["server_name"]),
            "enabled": "1",
            "name": r["server_name"],
            "operator": operator_guess(r["server_name"]),
            "relays": ",".join(_uuid("relay", v) for v in r["via"]),
        }
        for r in anon["routes"]
    ]
    general = {
        "enabled": "1" if enabled else "0",
        "lbStrategy": e["lb_strategy"],
        "skipIncompatible": "1" if anon["skip_incompatible"] else "0",
        "directCertFallback": "1" if anon["direct_cert_fallback"] else "0",
        "ecsEnabled": "1" if ecs else "0",
        "ecsSubnet": ecs_subnet,
    }
    return {"general": general, "relays": {"relay": relays}, "resolvers": {"resolver": resolvers}}


PRESET_ECS_SUBNET = EFFECTIVE["edns_client_subnet"][0]


def config(enabled=True, ecs=False, ecs_subnet=PRESET_ECS_SUBNET):
    return {
        "OPNsense": {
            "dnscryptproxy": {"general": stock_general()},
            "dnscryptroutes": _plugin(enabled, ecs, ecs_subnet),
        }
    }


def base_only():
    """Stock only: the plugin model is not in config.xml at all."""
    c = config()
    del c["OPNsense"]["dnscryptroutes"]
    return c


def preset_disabled():
    return config(enabled=False)


def preset_enabled():
    return config(enabled=True)


def ecs_preset_subnet():
    return config(ecs=True)


def ecs_custom_subnet():
    return config(ecs=True, ecs_subnet="198.51.100.0/24")


def stock_lists_set(enabled=True):
    c = config(enabled=enabled)
    g = c["OPNsense"]["dnscryptproxy"]["general"]
    g["serverlist"] = "cloudflare,google"
    g["relaylist"] = "anon-a,anon-b"
    return c


def base_disabled():
    c = config()
    c["OPNsense"]["dnscryptproxy"]["general"]["enabled"] = "0"
    return c


def stock_protocols_swapped():
    """Stock UI sets doh/odoh on and dnscrypt off; the plugin must force them back."""
    c = config()
    g = c["OPNsense"]["dnscryptproxy"]["general"]
    g["dnscrypt_servers"], g["doh_servers"], g["odoh_servers"] = "0", "1", "1"
    return c


def no_enabled_resolver():
    c = config()
    for r in c["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"]:
        r["enabled"] = "0"
    return c


def resolver_without_relays():
    c = config()
    del c["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][1]["relays"]
    return c


def dangling_relay_uuid():
    c = config()
    c["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][0]["relays"] += ",relay-does-not-exist"
    return c


def relay_reference_is_a_resolver():
    """A relay reference that points at a row which exists but is not a relay."""
    c = config()
    c["OPNsense"]["dnscryptroutes"]["resolvers"]["resolver"][0]["relays"] = _uuid("resolver", "cs-de")
    return c


# --- stock template variants (text transformations of reference/stock-template.toml) ---

def stock_without_anchor(text):
    out = text.replace("[anonymized_dns]", "[anonymized_dns_renamed]")
    assert out != text
    return out


def stock_without_line(text, key):
    """Remove the whole `{% if ... key ... %}...{% endif %}` group that emits `key`."""
    pattern = r"\{%\s+if helpers\.exists\('OPNsense\.dnscryptproxy\.general\.KEY'\).*?\{%\s+endif %\}\n\n".replace("KEY", key)
    out = re.sub(pattern, "", text, count=1, flags=re.S)
    assert out != text and not re.search(r"(?m)^%s =" % key, out)
    return out
