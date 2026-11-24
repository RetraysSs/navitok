"""Smoke tests: the plugin skeleton is well-formed and consistent."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
SKILL_MD = ROOT / "skills" / "navitok" / "SKILL.md"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def frontmatter(text):
    """Return simple `key: value` pairs from a leading --- block."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


class PluginManifestTest(unittest.TestCase):
    def test_plugin_json(self):
        data = load_json(PLUGIN_JSON)
        self.assertEqual(data["name"], "navitok")
        self.assertRegex(data["name"], KEBAB)
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(data["license"], "MIT")
        self.assertTrue(data["author"]["name"])
        self.assertTrue(data["description"])

    def test_marketplace_json(self):
        plugin = load_json(PLUGIN_JSON)
        market = load_json(MARKETPLACE_JSON)
        self.assertTrue(market["name"])
        self.assertTrue(market["owner"]["name"])
        self.assertEqual(len(market["plugins"]), 1)
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertIn(entry["source"], ("./", "."))
        self.assertEqual(entry["version"], plugin["version"])


class SkillTest(unittest.TestCase):
    def test_skill_frontmatter(self):
        fields = frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        self.assertIsNotNone(fields, "SKILL.md has no frontmatter")
        self.assertEqual(fields.get("name"), "navitok")
        self.assertTrue(fields.get("description"))


class DogfoodLedgerTest(unittest.TestCase):
    def test_ledger_lines_are_json(self):
        ledger = ROOT / "docs" / "dogfood" / "ledger.jsonl"
        self.assertTrue(ledger.exists())
        for n, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                record = json.loads(line)
                self.assertIn(record["schema"], (1, 2), f"line {n}")


if __name__ == "__main__":
    unittest.main()
