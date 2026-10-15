import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugin/dns/dnscrypt-routes/src/opnsense/scripts/dnscrypt_routes/catalog.py"
FIXTURES = ROOT / "tests/fixtures/catalog"

spec = importlib.util.spec_from_file_location("catalog", SCRIPT)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

PRESET_RESOLVERS = ["scaleway-ams", "cs-de", "nwps.fi", "dorriere-fr", "dnscry.pt-nuremberg-ipv4"]
PRESET_RELAYS = ["anon-cs-de", "anon-cs-fr", "anon-scaleway-ams", "anon-scaleway"]


def by_name(items):
    return {i["name"]: i for i in items}


def test_operator_guess_vectors():
    vectors = {
        "cs-de": "cryptostorm", "anon-cs-fr": "cryptostorm",
        "scaleway-ams": "scaleway", "anon-scaleway-ams": "scaleway", "anon-scaleway": "scaleway",
        "nwps.fi": "nwps", "dorriere-fr": "dorriere", "dnscry.pt-nuremberg-ipv4": "dnscry.pt",
    }
    for name, expected in vectors.items():
        assert catalog.operator_guess(name) == expected, name


def test_location_suffix():
    assert catalog.location("cs-de") == "de"
    assert catalog.location("scaleway-ams") == "ams"
    assert catalog.location("nwps.fi") == "fi"
    assert catalog.location("anon-cs-fr") == "fr"
    assert catalog.location("cs-de6") == "de"
    assert catalog.location("cloudflare") == ""
    assert catalog.location("anon-scaleway") == ""
    assert catalog.location("dnscry.pt-nuremberg-ipv4") == ""


def test_fixture_catalog():
    cat = catalog.build(str(FIXTURES))
    assert cat["available"] is True
    assert cat["source_dir"] == str(FIXTURES)
    res, rel = by_name(cat["resolvers"]), by_name(cat["relays"])
    for n in PRESET_RESOLVERS:
        assert n in res
    for n in PRESET_RELAYS:
        assert n in rel
    assert len(res) == 7 and len(rel) == 5  # 9 preset names + 3 distractors
    assert res["cs-de"]["description"].startswith("CryptoStorm Frankfurt")
    assert res["cs-de"]["operator_guess"] == "cryptostorm"
    assert rel["anon-scaleway"]["operator_guess"] == "scaleway"
    assert set(cat["resolvers"][0]) == {"name", "location", "description", "operator_guess", "proto", "ipv6"}
    assert set(cat["relays"][0]) == {"name", "location", "description", "operator_guess", "ipv6"}


def test_proto_decoding():
    res = by_name(catalog.build(str(FIXTURES))["resolvers"])
    for n in PRESET_RESOLVERS:
        assert res[n]["proto"] == "dnscrypt", n
    assert res["cloudflare"]["proto"] == "doh"  # first of several DoH stamps
    assert res["cloudflare"]["ipv6"] is False


def test_stamps_direct():
    assert catalog.decode_stamp("sdns://AQcAAAAAAAAADTUxLjE1LjEyMi4yNTAg6Q3ZfapcbHgiHKLF7QFoli0Ty1Vsz3RXs1RUbxUrwZAcMi5kbnNjcnlwdC1jZXJ0LnNjYWxld2F5LWFtcw") == ("dnscrypt", False)
    assert catalog.decode_stamp("sdns://AgcAAAAAAAAABzEuMC4wLjEAEmRucy5jbG91ZGZsYXJlLmNvbQovZG5zLXF1ZXJ5") == ("doh", False)
    assert catalog.decode_stamp("sdns://gQ8xNDYuNzAuODIuMzo0NDM") == ("other", False)  # relay
    assert catalog.decode_stamp("sdns://gRhbMmEwZDo1NjAwOjFkOjk6OjUzXTo0NDM") == ("other", True)
    assert catalog.decode_stamp("sdns://!!!") == ("other", False)


def test_ipv6_flag():
    cat = catalog.build(str(FIXTURES))
    res, rel = by_name(cat["resolvers"]), by_name(cat["relays"])
    assert res["cs-de6"]["ipv6"] is True and res["cs-de6"]["proto"] == "dnscrypt"
    assert res["cs-de"]["ipv6"] is False
    assert rel["anon-cs-de6"]["ipv6"] is True
    assert rel["anon-cs-de"]["ipv6"] is False


def test_missing_dir_unavailable(tmp_path):
    cat = catalog.build(str(tmp_path / "nope"))
    assert cat == {"available": False, "source_dir": str(tmp_path / "nope"), "resolvers": [], "relays": []}


def test_one_list_missing_unavailable(tmp_path):
    (tmp_path / "relays.md").write_text((FIXTURES / "relays.md").read_text())
    assert catalog.build(str(tmp_path))["available"] is False


def test_cli(tmp_path):
    ok = subprocess.run([sys.executable, str(SCRIPT), "--dir", str(FIXTURES)], capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout)["available"] is True
    missing = subprocess.run([sys.executable, str(SCRIPT), "--dir", str(tmp_path / "x")], capture_output=True, text=True)
    assert missing.returncode == 0 and json.loads(missing.stdout)["available"] is False
