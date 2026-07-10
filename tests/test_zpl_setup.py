import unittest
from pathlib import Path


class ZplSetupScriptTests(unittest.TestCase):
    def test_arrays_are_initialized_for_nounset_mode(self):
        script = (Path(__file__).parents[1] / "scripts" / "setup-zpl-usb-parallel.sh").read_text(
            encoding="utf-8"
        )
        for name in ("DEV", "USB", "VID", "PID", "SERIAL", "MFR", "PRODUCT"):
            self.assertIn(f"{name}=()", script)


if __name__ == "__main__":
    unittest.main()
