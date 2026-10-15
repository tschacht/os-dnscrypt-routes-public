"""Print the os-dnscrypt-proxy base settings for `vm provision` as an api/dnscryptproxy/general/set body.

usage: python3 -I dnscrypt-proxy.py <reference/effective-settings.json> [--logging]

Maps reference/effective-settings.json onto the fields of the stock model (OPNsense/Dnscryptproxy/General.xml,
os-dnscrypt-proxy 1.17). Not applied here:
  - routing owned by os-dnscrypt-routes (C-01): anonymized_dns, lb_strategy, edns_client_subnet;
  - keys without a stock model field: ignore_system_dns, log_level, use_syslog, netprobe_timeout;
  - query_log_configured: query logs follow --logging instead (off without it).
"""
import json
import sys


def onoff(value):
    return "1" if value else "0"


def main(argv):
    if len(argv) < 2 or len(argv) > 3 or (len(argv) == 3 and argv[2] != "--logging"):
        sys.stderr.write("usage: dnscrypt-proxy.py <effective-settings.json> [--logging]\n")
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        ref = json.load(fh)
    general = {
        "enabled": "1",
        "listen_addresses": ",".join(ref["listen_addresses"]),
        "serverlist": ",".join(ref["server_names"]),
        "fallback_resolver": ",".join(ref["bootstrap_resolvers"]),
        "proxy": "",
        "query_logs": onoff(len(argv) == 3),
    }
    for key in ("ipv4_servers", "ipv6_servers", "dnscrypt_servers", "doh_servers", "odoh_servers",
                "require_dnssec", "require_nolog", "require_nofilter", "force_tcp", "dnscrypt_ephemeral_keys",
                "tls_disable_session_tickets", "block_ipv6", "cache"):
        general[key] = onoff(ref[key])
    for key in ("max_clients", "timeout", "keepalive", "cert_refresh_delay"):
        general[key] = str(int(ref[key]))
    if ref.get("proxy_present"):
        sys.stderr.write("reference uses a proxy, which the test VM cannot reproduce\n")
        return 1
    json.dump({"general": general}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
