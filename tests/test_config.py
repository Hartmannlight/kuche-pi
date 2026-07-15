import importlib.util
import unittest
from unittest.mock import patch
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
        physical_order = ("KEY_F14", "KEY_F16", "KEY_F18", "KEY_F20", "KEY_F13", "KEY_F15", "KEY_F17", "KEY_F19")
        expected = (
            {"action": "stop"},
            {"action": "play", "source": "tagesschau"},
            {"action": "play", "source": "dlf_kultur"},
            {"action": "labels"},
            {"action": "play", "source": "swr1"},
            {"action": "play", "source": "querfunk"},
            {"action": "play", "source": "rock_antenne"},
            {"action": "play", "source": "dlf"},
        )
        self.assertEqual(tuple(daemon.KEY_ACTIONS[key] for key in physical_order), expected)

    def test_label_job_contains_date_and_background(self):
        result = labels.render(b"~DGR:OPENLBL.GRF,1,1,AA\n", b"^XA^FD{{DATUM}}^FS^XZ\n", "10.07")
        self.assertEqual(result, b"~DGR:OPENLBL.GRF,1,1,AA\r\n^XA^FD10.07^FS^XZ\n")

    def test_label_job_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            labels.render(b"background", b"{{DATUM}}", "10.07.2026")

    def test_label_printer_name_cannot_escape_api_path(self):
        labels.validate_printer_name("ente")
        with self.assertRaises(ValueError):
            labels.validate_printer_name("../not-a-printer")

    def test_label_waits_for_graphic_before_submitting_print(self):
        events = []

        def submit(_agent_url, _printer, _payload, description):
            events.append(("submit", description))
            return description.lower()

        def wait(_agent_url, _job_id, description, _timeout):
            events.append(("wait", description))

        with (
            patch.object(labels, "submit_job", side_effect=submit),
            patch.object(labels, "wait_for_transport", side_effect=wait),
            patch.object(
                labels.time,
                "sleep",
                side_effect=lambda seconds: events.append(("sleep", seconds)),
            ),
        ):
            labels.send_to_printer("http://127.0.0.1:8080", "ente", b"graphic", b"label")

        self.assertEqual(
            events,
            [
                ("submit", "Grafik-Upload"),
                ("wait", "Grafik-Upload"),
                ("sleep", labels.GRAPHIC_SETTLE_SECONDS),
                ("submit", "Tagesetikett"),
                ("wait", "Tagesetikett"),
            ],
        )

    def test_shipped_zpl_assets_render_a_complete_job(self):
        root = Path(__file__).parents[1] / "assets" / "labels"
        result = labels.render(
            (root / "opened_am_bg_203.zpl").read_bytes(),
            (root / "opened_am_print_template_203.zpl").read_bytes(),
            "10.07",
        )
        self.assertTrue(result.startswith(b"~DGR:OPENLBL.GRF,9600,40,"))
        self.assertIn(b"^PW320", result)
        self.assertIn(b"^LL240", result)
        self.assertIn(b"^FD10.07^FS", result)


if __name__ == "__main__":
    unittest.main()
