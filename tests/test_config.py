import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "bin" / "audio-buttons-daemon.py"
SPEC = importlib.util.spec_from_file_location("audio_buttons_daemon", MODULE_PATH)
daemon = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daemon)

LABEL_MODULE_PATH = Path(__file__).parents[1] / "bin" / "print-ente-label.py"
LABEL_SPEC = importlib.util.spec_from_file_location("print_ente_label", LABEL_MODULE_PATH)
labels = importlib.util.module_from_spec(LABEL_SPEC)
assert LABEL_SPEC.loader is not None
LABEL_SPEC.loader.exec_module(labels)


class ConfigTests(unittest.TestCase):
    def test_example_configuration_is_valid(self):
        config_path = Path(__file__).parents[1] / "config" / "audio-buttons.json"
        config = daemon.load_config(config_path)
        self.assertEqual(config["streams"]["dlf"]["kind"], "radio")

    def test_missing_required_key_is_rejected(self):
        config_path = Path(__file__).parents[1] / "config" / "invalid-missing-required.json"
        with self.assertRaises(daemon.ConfigurationError):
            daemon.load_config(config_path)

    def test_key_layout_matches_requested_keys(self):
        self.assertEqual(daemon.KEY_ACTIONS["KEY_F13"], {"action": "stop"})
        self.assertEqual(daemon.KEY_ACTIONS["KEY_F20"]["source"], "dlf")

    def test_label_job_contains_date_and_background(self):
        result = labels.render(b"~DGR:OPENLBL.GRF,1,1,AA\n", b"^XA^FD{{DATUM}}^FS^XZ\n", "10.07.2026")
        self.assertEqual(result, b"~DGR:OPENLBL.GRF,1,1,AA\r\n^XA^FD10.07.2026^FS^XZ\n")

    def test_label_job_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            labels.render(b"background", b"{{DATUM}}", "2026-07-10")

    def test_shipped_zpl_assets_render_a_complete_job(self):
        root = Path(__file__).parents[1] / "assets" / "labels"
        result = labels.render(
            (root / "opened_am_bg_203.zpl").read_bytes(),
            (root / "opened_am_print_template_203.zpl").read_bytes(),
            "10.07.2026",
        )
        self.assertTrue(result.startswith(b"~DGR:OPENLBL.GRF,12000,50,"))
        self.assertIn(b"^FD10.07.2026^FS", result)


if __name__ == "__main__":
    unittest.main()
