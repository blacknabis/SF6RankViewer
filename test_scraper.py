import json
import tempfile
import unittest
from pathlib import Path

from scraper import auth_state_has_session, class_contains


class ScraperHelperTests(unittest.TestCase):
    def test_empty_storage_state_is_not_authenticated(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

            self.assertFalse(auth_state_has_session(auth_path))

    def test_cookie_storage_state_is_authenticated(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps({"cookies": [{"name": "sid", "value": "x"}], "origins": []}),
                encoding="utf-8",
            )

            self.assertTrue(auth_state_has_session(auth_path))

    def test_class_selector_matches_css_module_prefix(self):
        self.assertEqual(class_contains("battle_data_player2"), "[class*='battle_data_player2']")


if __name__ == "__main__":
    unittest.main()
