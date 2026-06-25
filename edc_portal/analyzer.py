from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .model import Interval, ParsedReport
from .names import load_names


def ean_name(ean: str, names: dict[str, str]) -> str:
    return names.get(ean, ean)


def round_kwh(value: float) -> float:
    return round(value + 0.0, 4)


def interval_to_dict(interval: Interval, names: dict[str, str]) -> dict[str, Any]:
    return {
        "start": interval.start.isoformat(),
        "end": interval.end.isoformat(),
        "production_before_kwh": round_kwh(interval.production_before_kwh),
        "production_after_kwh": round_kwh(interval.production_after_kwh),
        "consumption_before_kwh": round_kwh(interval.consumption_before_kwh),
        "consumption_after_kwh": round_kwh(interval.consumption_after_kwh),
        "shared_kwh": round_kwh(interval.shared_kwh),
        "missed_kwh": round_kwh(interval.missed_kwh),
        "producers": [measurement_dict(item, names) for item in interval.producers],
        "consumers": [measurement_dict(item, names) for item in interval.consumers],
        "errors": interval.errors,
    }


def measurement_dict(item: Any, names: dict[str, str]) -> dict[str, Any]:
    return {
        "ean": item.ean,
        "name": ean_name(item.ean, names),
        "before_kwh": round_kwh(item.before_kwh),
        "after_kwh": round_kwh(item.after_kwh),
        "shared_kwh": round_kwh(item.shared_kwh),
        "missed_kwh": round_kwh(item.missed_kwh),
    }


def summarize_eans(report: ParsedReport, names: dict[str, str]) -> dict[str, Any]:
    producers = {ean: empty_totals(ean, "producer", names) for ean in report.producers}
    consumers = {ean: empty_totals(ean, "consumer", names) for ean in report.consumers}

    for interval in report.intervals:
        for item in interval.producers:
            add_measurement(producers[item.ean], item)
        for item in interval.consumers:
            add_measurement(consumers[item.ean], item)

    return {
        "producers": list(producers.values()),
        "consumers": list(consumers.values()),
    }


def empty_totals(ean: str, kind: str, names: dict[str, str]) -> dict[str, Any]:
    return {
        "ean": ean,
        "name": ean_name(ean, names),
        "kind": kind,
        "before_kwh": 0.0,
        "after_kwh": 0.0,
        "shared_kwh": 0.0,
        "missed_kwh": 0.0,
    }


def add_measurement(total: dict[str, Any], item: Any) -> None:
    total["before_kwh"] += item.before_kwh
    total["after_kwh"] += item.after_kwh
    total["shared_kwh"] += item.shared_kwh
    total["missed_kwh"] += item.missed_kwh


def simulate_allocations(report: ParsedReport, allocations: list[int], rounds: int = 5) -> dict[str, Any]:
    shared_per_consumer = [0.0 for _ in report.consumers]
    total_shared = 0.0
    total_leftover_production = 0.0
    total_leftover_consumption = 0.0

    for interval in report.intervals:
        available = int(round(interval.production_before_kwh * 100))
        demand = [int(round(item.before_kwh * 100)) for item in interval.consumers]

        for _ in range(rounds):
            if available <= 0 or sum(demand) <= 0:
                break
            round_energy = available
            for index, allocation in enumerate(allocations):
                if available <= 0:
                    break
                candidate = int(round_energy * allocation / 100)
                shared = min(demand[index], candidate, available)
                demand[index] -= shared
                available -= shared
                shared_per_consumer[index] += shared / 100
                total_shared += shared / 100

        total_leftover_production += available / 100
        total_leftover_consumption += sum(demand) / 100

    return {
        "allocations": allocations,
        "shared_kwh": round_kwh(total_shared),
        "leftover_production_kwh": round_kwh(total_leftover_production),
        "leftover_consumption_kwh": round_kwh(total_leftover_consumption),
        "consumer_shared_kwh": [round_kwh(value) for value in shared_per_consumer],
    }


def recommend_allocations(report: ParsedReport) -> dict[str, Any]:
    consumer_count = len(report.consumers)
    if consumer_count == 0:
        return {"strategy": "none", "reason": "No consumer EANs found"}

    if consumer_count == 1:
        best = simulate_allocations(report, [100])
        return {"strategy": "single-consumer", "recommended": best, "alternatives": []}

    if consumer_count == 2:
        alternatives = [simulate_allocations(report, [first, 100 - first]) for first in range(0, 101)]
        alternatives.sort(key=lambda item: item["shared_kwh"], reverse=True)
        return {
            "strategy": "grid-search-1-percent",
            "recommended": alternatives[0],
            "alternatives": alternatives[:10],
        }

    demand = [0.0 for _ in report.consumers]
    for interval in report.intervals:
        if interval.production_before_kwh <= 0:
            continue
        for index, consumer in enumerate(interval.consumers):
            demand[index] += consumer.before_kwh

    total = sum(demand)
    if total <= 0:
        allocations = [0 for _ in report.consumers]
    else:
        allocations = [int(round(value / total * 100)) for value in demand]
        while sum(allocations) > 100:
            allocations[allocations.index(max(allocations))] -= 1
        while sum(allocations) < 100:
            allocations[allocations.index(max(allocations))] += 1

    return {
        "strategy": "demand-weighted-heuristic",
        "recommended": simulate_allocations(report, allocations),
        "alternatives": [],
    }


def analyze_report(report: ParsedReport) -> dict[str, Any]:
    names = load_names()
    intervals = [interval_to_dict(interval, names) for interval in report.intervals]
    totals = {
        "production_kwh": round_kwh(sum(interval.production_before_kwh for interval in report.intervals)),
        "consumption_kwh": round_kwh(sum(interval.consumption_before_kwh for interval in report.intervals)),
        "shared_kwh": round_kwh(sum(interval.shared_kwh for interval in report.intervals)),
        "missed_kwh": round_kwh(sum(interval.missed_kwh for interval in report.intervals)),
        "sold_to_network_kwh": round_kwh(sum(interval.production_after_kwh for interval in report.intervals)),
        "purchased_from_network_kwh": round_kwh(sum(interval.consumption_after_kwh for interval in report.intervals)),
    }
    efficiency = totals["shared_kwh"] / totals["production_kwh"] * 100 if totals["production_kwh"] else 0.0

    eans = summarize_eans(report, names)
    for collection in (eans["producers"], eans["consumers"]):
        for item in collection:
            for key in ("before_kwh", "after_kwh", "shared_kwh", "missed_kwh"):
                item[key] = round_kwh(item[key])

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": report.source_file,
        "producers": report.producers,
        "consumers": report.consumers,
        "om_names": {ean: ean_name(ean, names) for ean in report.producers + report.consumers},
        "interval_count": len(report.intervals),
        "date_from": report.intervals[0].start.isoformat() if report.intervals else None,
        "date_to": report.intervals[-1].end.isoformat() if report.intervals else None,
        "totals": totals | {"sharing_efficiency_percent": round(efficiency, 2)},
        "eans": eans,
        "recommendation": recommend_allocations(report),
        "intervals": intervals,
    }


def write_analysis(analysis: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = path.parent / "latest.json"
    latest.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
