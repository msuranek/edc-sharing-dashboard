from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from .model import EanMeasurement, Interval, ParsedReport


class NoDataExportError(ValueError):
    """Raised when EDC returns a valid export with no EAN data columns."""


def parse_kwh(value: str) -> float:
    cleaned = value.strip().replace("\xa0", "").replace(" ", "")
    if cleaned == "":
        return 0.0
    return float(cleaned.replace(",", "."))


def parse_date(date_value: str, time_value: str) -> datetime:
    raw = f"{date_value.strip()} {time_value.strip()}"
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported EDC date/time format: {raw}")


def classify_columns(header: list[str]) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    producers: list[tuple[str, int]] = []
    consumers: list[tuple[str, int]] = []

    if header == ["Datum", "Cas od", "Cas do"]:
        raise NoDataExportError("EDC export does not contain any EAN IN/OUT columns for the selected group and period")

    if len(header) < 5 or (len(header) - 3) % 2 != 0:
        raise ValueError("EDC CSV header must contain Datum, Cas od, Cas do and IN/OUT column pairs")

    for index in range(3, len(header), 2):
        before = header[index].strip()
        after = header[index + 1].strip()
        if not before.startswith("IN-") or not after.startswith("OUT-"):
            raise ValueError(f"Expected IN/OUT column pair, got {before!r} and {after!r}")
        if before[2:] != after[3:]:
            raise ValueError(f"Mismatched IN/OUT column pair: {before!r} and {after!r}")

        ean = before[3:-2]
        if before.endswith("-D"):
            producers.append((ean, index))
        elif before.endswith("-O"):
            consumers.append((ean, index))
        else:
            raise ValueError(f"Unknown EAN column type: {before!r}")

    return producers, consumers


def parse_edc_csv(path: str | Path) -> ParsedReport:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))

    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("CSV file is empty")

    header = [cell.strip() for cell in rows[0]]
    if header[:3] != ["Datum", "Cas od", "Cas do"]:
        raise ValueError(f"Unexpected EDC CSV header: {header[:3]}")

    producer_columns, consumer_columns = classify_columns(header)
    intervals: list[Interval] = []

    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) > len(header) and row[-1] == "":
            row = row[:-1]
        if len(row) != len(header):
            raise ValueError(f"Line {line_number}: expected {len(header)} columns, got {len(row)}")

        start = parse_date(row[0], row[1])
        end = parse_date(row[0], row[2])
        if end <= start:
            end += timedelta(days=1)
        errors: list[str] = []

        producers = []
        for ean, index in producer_columns:
            before = parse_kwh(row[index])
            after = parse_kwh(row[index + 1]) if row[index + 1].strip() else before
            if after > before:
                errors.append(f"Producer {ean}: OUT is greater than IN; sharing set to zero for this interval")
                after = before
            producers.append(EanMeasurement(ean=ean, before_kwh=max(0.0, before), after_kwh=max(0.0, after)))

        consumers = []
        for ean, index in consumer_columns:
            before = -parse_kwh(row[index])
            after = -parse_kwh(row[index + 1]) if row[index + 1].strip() else before
            if after > before:
                errors.append(f"Consumer {ean}: OUT consumption is greater than IN; sharing set to zero for this interval")
                after = before
            consumers.append(EanMeasurement(ean=ean, before_kwh=max(0.0, before), after_kwh=max(0.0, after)))

        interval = Interval(start=start, end=end, producers=producers, consumers=consumers, errors=errors)
        missed = interval.missed_kwh
        if missed > 0:
            production_after = interval.production_after_kwh
            consumption_after = interval.consumption_after_kwh
            for producer in producers:
                producer.missed_kwh = missed * producer.after_kwh / production_after if production_after else 0.0
            for consumer in consumers:
                consumer.missed_kwh = missed * consumer.after_kwh / consumption_after if consumption_after else 0.0
        intervals.append(interval)

    return ParsedReport(
        source_file=str(csv_path),
        producers=[ean for ean, _ in producer_columns],
        consumers=[ean for ean, _ in consumer_columns],
        intervals=intervals,
    )
