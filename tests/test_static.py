"""Checks a broken edit would otherwise slip through: catalogs, PlainText, argv-only processes."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class StaticTests(unittest.TestCase):
    def catalog(self, code):
        return json.loads(read(os.path.join("i18n", code + ".json")))

    def test_catalogs_have_same_keys(self):
        self.assertEqual(set(self.catalog("en")), set(self.catalog("fr")))

    def test_every_used_key_exists(self):
        src = read("Panel.qml") + read("SettingsPage.qml")
        used = {k for k in re.findall(r'strings\.tn?\("([^"]+)"', src) if not k.endswith(".")}
        self.assertFalse(used - set(self.catalog("en")))

    def test_all_text_is_plain(self):
        for name in ("Panel.qml", "SettingsPage.qml"):
            src = read(name)
            texts = len(re.findall(r"^\s*Text \{", src, re.M))
            self.assertGreaterEqual(src.count("textFormat: Text.PlainText"), texts, name)

    def test_processes_use_argv_only(self):
        src = read("Service.qml")
        self.assertIn('"omarchy-bar", "set"', src)
        self.assertNotIn('"sh"', src)
        self.assertNotIn('"bash"', src)

    def test_ics_link_goes_over_stdin(self):
        src = read("Service.qml")
        self.assertNotIn("helperPath, icsUrl", src)
        self.assertIn("stdinEnabled: true", src)


if __name__ == "__main__":
    unittest.main()
