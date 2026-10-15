import tempfile
import unittest
from pathlib import Path

from edc_portal.parser import NoDataExportError, classify_columns, parse_edc_csv, parse_kwh


class ParserTests(unittest.TestCase):
    def test_parse_kwh_accepts_czech_decimal_format(self) -> None:
        self.assertEqual(parse_kwh(" 1 234,56 "), 1234.56)
        self.assertEqual(parse_kwh(""), 0.0)

    def test_classify_columns_rejects_no_data_export(self) -> None:
        with self.assertRaises(NoDataExportError):
            classify_columns(["Datum", "Cas od", "Cas do"])

    def test_parse_report_handles_sharing_and_midnight(self) -> None:
        csv_text = (
            "Datum;Cas od;Cas do;IN-100-D;OUT-100-D;IN-200-O;OUT-200-O\n"
            "30.06.2026;23:45;00:00;10,0;4,0;-8,0;-2,0\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edc-2026-06.csv"
            path.write_text(csv_text, encoding="utf-8")
            report = parse_edc_csv(path)

        self.assertEqual(report.producers, ["100"])
        self.assertEqual(report.consumers, ["200"])
        self.assertEqual(len(report.intervals), 1)
        interval = report.intervals[0]
        self.assertEqual(interval.end.date().isoformat(), "2026-07-01")
        self.assertEqual(interval.shared_kwh, 6.0)
        self.assertEqual(interval.missed_kwh, 2.0)


if __name__ == "__main__":
    unittest.main()
