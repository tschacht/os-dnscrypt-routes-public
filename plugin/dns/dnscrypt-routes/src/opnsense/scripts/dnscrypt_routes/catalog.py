#!/usr/bin/env python3
"""Parse dnscrypt-proxy's cached public-resolvers.md / relays.md into the C-05 JSON."""
import argparse
import base64
import json
import os
import re
import sys

DEFAULT_DIR = "/usr/local/etc/dnscrypt-proxy"
ALIASES = {"cs": "cryptostorm", "nwps.fi": "nwps"}
PROTO_BY_BYTE = {0x01: "dnscrypt", 0x02: "doh", 0x05: "odoh"}


def operator_guess(name):
    n = name.lower()
    if n.startswith("anon-"):
        n = n[len("anon-"):]
    n = n.split("-", 1)[0]
    return ALIASES.get(n, n).lower()


def location(name):
    """Best effort from a 2-3 letter name suffix (-de, -ams, .fi); empty otherwise."""
    n = name.lower()
    if n.startswith("anon-"):
        n = n[len("anon-"):]
    tokens = [t for t in re.split(r"[-.]", n) if t]
    while tokens and tokens[-1] in ("ipv4", "ipv6"):
        tokens.pop()
    if len(tokens) < 2:
        return ""
    last = re.sub(r"6$", "", tokens[-1])  # cs-de6 is the IPv6 twin of cs-de
    return last if re.fullmatch(r"[a-z]{2,3}", last) else ""


def decode_stamp(stamp):
    """Return (proto, ipv6) for an sdns:// stamp; ("other", False) if undecodable."""
    try:
        raw = stamp[len("sdns://"):].strip()
        data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        kind = data[0]
        pos = 1 if kind == 0x81 else 9  # DNSCrypt relays carry no props
        length = data[pos]
        addr = data[pos + 1:pos + 1 + length].decode("ascii")
    except (ValueError, IndexError, UnicodeDecodeError):
        return "other", False
    ipv6 = addr.startswith("[") or addr.count(":") > 1
    return PROTO_BY_BYTE.get(kind, "other"), ipv6


def parse_list(text):
    """Yield (name, description, first stamp or None) per '## name' entry."""
    entries = []
    for block in re.split(r"(?m)^(?=## )", text):
        if not block.startswith("## "):
            continue
        head, _, body = block.partition("\n")
        desc, stamp = [], None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("sdns://"):
                stamp = stamp or line
            elif line:
                desc.append(line)
        entries.append((head[3:].strip(), " ".join(desc), stamp))
    return entries


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def build(directory):
    out = {"available": False, "source_dir": directory, "resolvers": [], "relays": []}
    try:
        res_text = _read(os.path.join(directory, "public-resolvers.md"))
        rel_text = _read(os.path.join(directory, "relays.md"))
    except (OSError, UnicodeDecodeError):
        return out  # both lists are required; fail closed (R-06)
    for name, desc, stamp in parse_list(res_text):
        proto, ipv6 = decode_stamp(stamp) if stamp else ("other", False)
        out["resolvers"].append({
            "name": name, "location": location(name), "description": desc,
            "operator_guess": operator_guess(name), "proto": proto, "ipv6": ipv6})
    for name, desc, stamp in parse_list(rel_text):
        ipv6 = decode_stamp(stamp)[1] if stamp else False
        out["relays"].append({
            "name": name, "location": location(name), "description": desc,
            "operator_guess": operator_guess(name), "ipv6": ipv6})
    out["available"] = True
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    json.dump(build(args.dir), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
