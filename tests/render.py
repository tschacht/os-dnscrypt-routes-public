"""Offline reproduction of the OPNsense template render environment (R-20).

Copied in behavior from opnsense/core, repository state 8e6f3f34a90051ca6819e23c22e84a5afca856bf (master,
fetched 2026-10-12):
  src/opnsense/service/modules/template.py        Environment(trim_blocks=True, extensions do + loopcontrols),
                                                  filter regex_replace = re.sub(pattern, replacement, value),
                                                  helpers re-created per render, core's end-of-line rule on write
  src/opnsense/service/modules/addons/template_helpers.py   Helpers.exists / toList / getUUID (and friends)
  src/opnsense/service/modules/config.py          '__uuid__' / '__uuid_tags__' maps and '@uuid' attributes

Config data is a plain dict shaped like core's parsed config.xml (all leaf values are strings, empty leaves are
absent). Items that carry an '@uuid' key are registered in '__uuid__' / '__uuid_tags__' by `with_uuid_maps`.
"""
import copy
import re
import shutil
import tempfile
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_TEMPLATES = ROOT / "plugin/dns/dnscrypt-routes/src/opnsense/service/templates"
PLUGIN_TEMPLATE_NAME = "OPNsense/Dnscryptproxy/dnscrypt-proxy-routes.toml"
PLUGIN_TARGET_NAME = "OPNsense/Dnscryptproxy/+TARGETS.D/95-dnscrypt-routes.TARGET"
STOCK_TEMPLATE_NAME = "OPNsense/Dnscryptproxy/dnscrypt-proxy.toml"
MANUAL_TEMPLATE_NAME = "OPNsense/Dnscryptproxy/dnscrypt-proxy-eu.toml"
MANUAL_TARGET_NAME = "OPNsense/Dnscryptproxy/+TARGETS.D/90-eu.TARGET"
STOCK_REFERENCE = ROOT / "reference/stock-template.toml"
MANUAL_TEMPLATE_SRC = ROOT / "artifacts" / MANUAL_TEMPLATE_NAME
MANUAL_TARGET_SRC = ROOT / "artifacts" / MANUAL_TARGET_NAME


class Helpers:
    """The subset of core's template_helpers.Helpers that templates here use (same semantics)."""

    def __init__(self, template_in_data):
        self._template_in_data = template_in_data

    def getNodeByTag(self, tag):
        node = self._template_in_data
        for item in tag.split("."):
            if item in node:
                node = node[item]
            else:
                return None
        return node

    def exists(self, tag):
        return self.getNodeByTag(tag) is not None

    def empty(self, tag):
        node = self.getNodeByTag(tag)
        if node is None:
            return True
        elif len(node) == 0:
            return True
        elif hasattr(node, "strip") and node.strip() in ("", "0"):
            return True
        return False

    def toList(self, tag, sortBy=None, sortAs=None):
        result = self.getNodeByTag(tag)
        if result is None:
            return []
        if type(result) != list:
            result = [result]
        if sortBy is None:
            return result
        if sortAs == "int":
            return sorted(result, key=lambda d: int(d[sortBy]))
        return sorted(result, key=lambda d: d[sortBy])

    def getUUIDtag(self, uuid):
        return self._template_in_data["__uuid_tags__"].get(uuid, "__not_found__")

    def getUUID(self, uuid):
        return self._template_in_data["__uuid__"].get(uuid, {})


def with_uuid_maps(config):
    """Deep-copy `config` and add '__uuid__' / '__uuid_tags__' like core's config.py does.

    Every dict that has an '@uuid' key is registered under the key (tag) it is stored below.
    """
    data = copy.deepcopy(config)
    uuids, tags = {}, {}

    def walk(node):
        if isinstance(node, dict):
            for tag, child in node.items():
                for item in child if isinstance(child, list) else [child]:
                    if isinstance(item, dict) and "@uuid" in item:
                        uuids[item["@uuid"]] = item
                        tags[item["@uuid"]] = tag
                    walk(item)

    walk(data)
    data["__uuid__"] = uuids
    data["__uuid_tags__"] = tags
    return data


def make_environment(templates_dir):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
    )
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(pattern, replacement, value)
    return env


class TemplateTree:
    """A temporary templates tree like /usr/local/opnsense/service/templates."""

    def __init__(self, stock_text=None, manual_template=False, manual_target=False):
        self._tmp = tempfile.TemporaryDirectory(prefix="dnscrypt-routes-render-")
        self.root = Path(self._tmp.name)
        if stock_text is None:
            stock_text = STOCK_REFERENCE.read_text()
        self.write(STOCK_TEMPLATE_NAME, stock_text)
        self.copy_in(PLUGIN_TEMPLATES / PLUGIN_TEMPLATE_NAME, PLUGIN_TEMPLATE_NAME)
        self.copy_in(PLUGIN_TEMPLATES / PLUGIN_TARGET_NAME, PLUGIN_TARGET_NAME)
        if manual_template:
            self.copy_in(MANUAL_TEMPLATE_SRC, MANUAL_TEMPLATE_NAME)
        if manual_target:
            self.copy_in(MANUAL_TARGET_SRC, MANUAL_TARGET_NAME)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def copy_in(self, src, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)  # read-only use of the source

    def render(self, template_name, config):
        """Render one template the way core's Template._generate does, including its end-of-line rule."""
        env = make_environment(self.root)
        page = env.get_template(template_name)
        data = with_uuid_maps(config)
        env.globals["helpers"] = Helpers(data)
        content = page.render(data)
        # core: if the output lacks a final newline but the template source has one, add it
        if len(content) > 1 and content[-1] != "\n":
            if (self.root / template_name).read_bytes()[-1:] in (b"\n", b"\r"):
                content += "\n"
        return content

    def render_plugin(self, config):
        return self.render(PLUGIN_TEMPLATE_NAME, config)

    def close(self):
        self._tmp.cleanup()
