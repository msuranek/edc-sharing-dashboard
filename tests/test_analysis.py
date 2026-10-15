import unittest
from datetime import datetime, timedelta

from edc_portal.analyzer import recommend_allocations, simulate_allocations
from edc_portal.model import EanMeasurement, Interval, ParsedReport


def sample_report(consumers: list[EanMeasurement]) -> ParsedReport:
    start = datetime(2026, 6, 1, 12, 0)
    return ParsedReport(
        source_file="synthetic.csv",
        producers=["producer"],
        consumers=[item.ean for item in consumers],
        intervals=[
            Interval(
                start=start,
                end=start + timedelta(minutes=15),
                producers=[EanMeasurement("producer", before_kwh=10.0, after_kwh=0.0)],
                consumers=consumers,
            )
        ],
    )


class AnalysisTests(unittest.TestCase):
    def test_single_consumer_recommendation_uses_full_allocation(self) -> None:
        report = sample_report([EanMeasurement("consumer", before_kwh=8.0, after_kwh=0.0)])

        result = recommend_allocations(report)

        self.assertEqual(result["strategy"], "single-consumer")
        self.assertEqual(result["recommended"]["allocations"], [100])
        self.assertEqual(result["recommended"]["shared_kwh"], 8.0)

    def test_simulation_preserves_energy_balance(self) -> None:
        report = sample_report([
            EanMeasurement("consumer-a", before_kwh=6.0, after_kwh=0.0),
            EanMeasurement("consumer-b", before_kwh=4.0, after_kwh=0.0),
        ])

        result = simulate_allocations(report, [60, 40])

        self.assertEqual(result["shared_kwh"], 10.0)
        self.assertEqual(result["leftover_production_kwh"], 0.0)
        self.assertEqual(result["leftover_consumption_kwh"], 0.0)
        self.assertEqual(result["consumer_shared_kwh"], [6.0, 4.0])


if __name__ == "__main__":
    unittest.main()
