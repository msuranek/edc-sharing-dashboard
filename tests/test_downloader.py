import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from edc_portal.downloader import _is_no_data_csv, _use_daily_export


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 15, 12, 0, tzinfo=tz)


class DownloaderHelperTests(unittest.TestCase):
    def test_daily_export_is_used_for_current_and_previous_month(self) -> None:
        with patch("edc_portal.downloader.datetime", FixedDateTime):
            self.assertTrue(_use_daily_export(7, 2026))
            self.assertTrue(_use_daily_export(6, 2026))
            self.assertFalse(_use_daily_export(5, 2026))
            self.assertFalse(_use_daily_export(8, 2026))

    def test_no_data_csv_is_detected_from_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            no_data = Path(directory) / "no-data.csv"
            no_data.write_text("Datum;Cas od;Cas do\n", encoding="utf-8-sig")
            report = Path(directory) / "report.csv"
            report.write_text(
                "Datum;Cas od;Cas do;IN-100-D;OUT-100-D\n",
                encoding="utf-8",
            )

            self.assertTrue(_is_no_data_csv(no_data))
            self.assertFalse(_is_no_data_csv(report))
            self.assertFalse(_is_no_data_csv(Path(directory) / "missing.csv"))


if __name__ == "__main__":
    unittest.main()
