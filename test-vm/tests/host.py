"""Host-side JSON helpers for `vm test` (lib/cmd-test.sh). Reads JSON on stdin; run with python3 -I.

  uuid <relay|resolver> <name>          uuid of the row named <name> in a settings/get response
  model                                 settings/get response -> {general, relays, resolvers} (names, sorted)
  preset <preset.json>                  settings/get equals preset.json plus the C-01 defaults (exit 1 + diff)
  owned <effective-settings.json> [any-via-order]
                                        probe.py toml output: routing keys equal the reference, no ECS
  failed <path regex>                   C-03 failure format with a validation path matching the regex
  saved                                 C-03 success format; prints the warning paths
  same <keys> <before>                  probe.py snap on stdin: the listed keys equal those of <before>
  isolated <before>                     probe.py snap on stdin: F3 isolation and cleanup against <before>
On a failed check the reason is printed and the exit status is 1.
"""
import json
import re
import sys

C01_DEFAULTS = {"enabled": "0", "lbStrategy": "wp2", "skipIncompatible": "1", "directCertFallback": "1",
                "ecsEnabled": "0", "ecsSubnet": "146.70.82.0/24"}


def selected(value):
    """OptionField / ModelRelationField data from settings/get: the selected keys; plain values unchanged."""
    if isinstance(value, dict):
        return [key for key, opt in value.items() if isinstance(opt, dict) and str(opt.get("selected")) == "1"]
    return value


def model(data):
    root = data["dnscryptroutes"]
    general = {}
    for key, value in root["general"].items():
        sel = selected(value)
        general[key] = sel[0] if isinstance(sel, list) and len(sel) == 1 else sel
    relays = {uuid: row for uuid, row in (root["relays"]["relay"] or {}).items()}
    names = {uuid: row["name"] for uuid, row in relays.items()}
    out_relays = sorted(({"name": r["name"], "operator": r["operator"]} for r in relays.values()),
                        key=lambda r: r["name"])
    out_resolvers = []
    for row in (root["resolvers"]["resolver"] or {}).values():
        out_resolvers.append({"name": row["name"], "operator": row["operator"], "enabled": int(row["enabled"]),
                              "relays": sorted(names.get(u, u) for u in selected(row["relays"]))})
    out_resolvers.sort(key=lambda r: r["name"])
    return {"general": general, "relays": out_relays, "resolvers": out_resolvers}


def main(argv):
    data = json.load(sys.stdin)
    cmd = argv[1]
    if cmd == "uuid":
        kind, name = argv[2], argv[3]
        rows = data["dnscryptroutes"][kind + "s"][kind] or {}
        found = [uuid for uuid, row in rows.items() if row["name"] == name]
        if len(found) != 1:
            sys.exit("no single %s named %s" % (kind, name))
        print(found[0])
        return 0
    if cmd == "model":
        print(json.dumps(model(data), sort_keys=True))
        return 0
    if cmd == "preset":
        with open(argv[2], encoding="utf-8") as fh:
            preset = json.load(fh)
        want = {"general": C01_DEFAULTS,
                "relays": sorted(preset["relays"], key=lambda r: r["name"]),
                "resolvers": sorted(({"name": r["name"], "operator": r["operator"], "enabled": int(r["enabled"]),
                                      "relays": sorted(r["relays"])} for r in preset["resolvers"]),
                                    key=lambda r: r["name"])}
        got = model(data)
        if got != want:
            print("want %s\ngot  %s" % (json.dumps(want, sort_keys=True), json.dumps(got, sort_keys=True)))
            return 1
        return 0
    if cmd == "owned":
        with open(argv[2], encoding="utf-8") as fh:
            ref = json.load(fh)
        anon = ref["anonymized_dns"]
        want = {"server_names": ref["server_names"], "lb_strategy": ref["lb_strategy"],
                "routes": anon["routes"], "skip_incompatible": anon["skip_incompatible"],
                "direct_cert_fallback": anon["direct_cert_fallback"], "edns_client_subnet": None,
                "dnscrypt_servers": True, "doh_servers": False, "odoh_servers": False,
                "first_line": "# dnscrypt-routes: managed"}
        got = {key: data.get(key) for key in want}
        if argv[3:] == ["any-via-order"]:
            for routes in (want["routes"], got["routes"] or []):
                for route in routes:
                    route["via"] = sorted(route["via"])
        if got != want:
            print("want %s\ngot  %s" % (json.dumps(want, sort_keys=True), json.dumps(got, sort_keys=True)))
            return 1
        return 0
    if cmd == "failed":
        # C-03 failure format: {"result": "failed", "validations": {path: msg}}, a path matching the regex
        val = data.get("validations")
        problems = []
        if data.get("result") != "failed":
            problems.append("result is not failed")
        if not isinstance(val, dict) or not val:
            problems.append("no validations")
        elif not all(k.startswith("dnscryptroutes.") for k in val):
            problems.append("a path without the dnscryptroutes. prefix")
        elif not any(re.fullmatch(argv[2], k) for k in val):
            problems.append("no path matches %s" % argv[2])
        if problems:
            print("%s: %s" % ("; ".join(problems), json.dumps(data)))
            return 1
        return 0
    if cmd == "saved":
        # C-03 success: result saved, validations {}; prints the warning paths, one per line
        if data.get("result") != "saved" or data.get("validations") != {} or not isinstance(data.get("warnings"), list):
            print("not saved as C-03 specifies: %s" % json.dumps(data))
            return 1
        for w in data["warnings"]:
            print(w["path"])
        return 0
    if cmd == "same":
        # same <keys,...> <before snap>: the listed probe.py snap keys are unchanged
        # "log": same inode and not shorter (dnscrypt-proxy truncates its log when it starts)
        before = json.loads(argv[3])
        diff = []
        for k in argv[2].split(","):
            if k == "log":
                if not data["log"] or data["log"]["inode"] != before["log"]["inode"] or data["log"]["size"] < before["log"]["size"]:
                    diff.append("live log truncated or replaced (a restart): %s -> %s" % (before["log"], data["log"]))
            elif before.get(k) != data.get(k):
                diff.append("%s %s -> %s" % (k, before.get(k), data.get(k)))
        if diff:
            print("; ".join(diff))
            return 1
        return 0
    if cmd == "isolated":
        # isolated <before snap>: F3 isolation plus the cleanup checks (R-13, R-16)
        before = json.loads(argv[2])
        diff = ["%s %s -> %s" % (k, before.get(k), data.get(k)) for k in ("pid", "toml", "l5353", "catalog")
                if before.get(k) != data.get(k)]
        if not data["log"] or data["log"]["inode"] != before["log"]["inode"] or data["log"]["size"] < before["log"]["size"]:
            diff.append("live log truncated or rotated: %s -> %s" % (before["log"], data["log"]))
        if data["l5354"]:
            diff.append("still listening on 5354: %s" % data["l5354"])
        if data["procs"] != [data["pid"]]:
            diff.append("dnscrypt-proxy processes %s, service pid %s" % (data["procs"], data["pid"]))
        if data["sandbox"]:
            diff.append("sandbox still present")
        if diff:
            print("; ".join(diff))
            return 1
        return 0
    sys.exit("unknown command %s" % cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
