from __future__ import annotations

from pathlib import Path
from typing import Any

from .analyzer import analyze_report, write_analysis
from .downloader import download_months
from .parser import NoDataExportError, parse_edc_csv
from .paths import processed_dir


def sync_months(months: list[tuple[int, int]], group_name: str | None = None) -> list[dict[str, Any]]:
    downloads = download_months([(month, year, None) for month, year in months], group_name=group_name)
    results = []
    for csv_path in downloads:
        analysis_path = analysis_output_path(csv_path, group_name)
        year, month = month_from_csv_path(csv_path)
        try:
            report = parse_edc_csv(csv_path)
        except NoDataExportError as exc:
            results.append({
                "csv": str(csv_path),
                "analysis": None,
                "year": year,
                "month": month,
                "shared_kwh": 0.0,
                "missed_kwh": 0.0,
                "no_data": True,
                "message": str(exc),
            })
            continue
        analysis = analyze_report(report)
        written_path = write_analysis(analysis, analysis_path)
        results.append({
            "csv": str(csv_path),
            "analysis": str(written_path),
            "year": year,
            "month": month,
            "shared_kwh": analysis["totals"]["shared_kwh"],
            "missed_kwh": analysis["totals"]["missed_kwh"],
            "no_data": False,
        })
    return results


def month_from_csv_path(csv_path: str | Path) -> tuple[int, int]:
    parts = Path(csv_path).stem.split("-")
    if len(parts) < 3:
        raise ValueError(f"Unable to read month from CSV filename: {csv_path}")
    return int(parts[1]), int(parts[2])


def analysis_output_path(csv_path: str | Path, group_name: str | None = None) -> Path:
    path = Path(csv_path)
    stem = path.stem
    return processed_dir(group_name) / f"{stem}-analysis.json"
