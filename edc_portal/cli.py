from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .analyzer import analyze_report, write_analysis
from .downloader import download_month, download_months, read_env_file
from .names import load_names, remove_name, save_names, set_name
from .parser import parse_edc_csv
from .paths import default_group, downloads_dir, group_slug, processed_dir, project_code
from .sync import sync_months


def main() -> None:
    parser = argparse.ArgumentParser(description="EDC sharing demo tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="Download a month from EDC portal")
    download.add_argument("--month", type=int, nargs="+", required=True)
    download.add_argument("--year", type=int, required=True)
    download.add_argument("--output-name", default=None, help="Downloaded CSV filename, only valid for one month")

    parse = subparsers.add_parser("parse", help="Parse EDC CSV and create analysis JSON")
    parse.add_argument("csv_file")
    parse.add_argument("--output", default=None)

    subparsers.add_parser("names", help="List configured metering point names")

    set_name_parser = subparsers.add_parser("set-name", help="Set readable name for an EAN")
    set_name_parser.add_argument("ean")
    set_name_parser.add_argument("name")
    set_name_parser.add_argument("--reparse", default=None, help="CSV file to reparse after saving the name")
    set_name_parser.add_argument("--output", default=None, help="Analysis JSON path used with --reparse")

    remove_name_parser = subparsers.add_parser("remove-name", help="Remove readable name for an EAN")
    remove_name_parser.add_argument("ean")
    remove_name_parser.add_argument("--reparse", default=None, help="CSV file to reparse after removing the name")
    remove_name_parser.add_argument("--output", default=None, help="Analysis JSON path used with --reparse")

    subparsers.add_parser("demo", help="Analyze bundled sample CSV")

    serve = subparsers.add_parser("serve", help="Serve the demo portal")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    export_static = subparsers.add_parser("export-static", help="Export a static read-only web app")
    export_static.add_argument("--output", required=True, help="Output directory, for example dist/energo")

    args = parser.parse_args()

    if args.command == "download":
        if args.output_name and len(args.month) != 1:
            parser.error("--output-name can only be used with exactly one --month value")
        if len(args.month) == 1:
            path = download_month(args.month[0], args.year, output_name=args.output_name)
            print(f"Downloaded: {path}")
        else:
            paths = download_months([(month, args.year, None) for month in args.month])
            for path in paths:
                print(f"Downloaded: {path}")
    elif args.command == "parse":
        output = args.output or default_output_path(args.csv_file)
        run_parse(args.csv_file, output)
    elif args.command == "names":
        run_names()
    elif args.command == "set-name":
        path = set_name(args.ean, args.name)
        print(f"Saved name in {path}: {args.ean} = {args.name}")
        if args.reparse:
            run_parse(args.reparse, args.output or default_output_path(args.reparse))
    elif args.command == "remove-name":
        path = remove_name(args.ean)
        print(f"Removed name in {path}: {args.ean}")
        if args.reparse:
            run_parse(args.reparse, args.output or default_output_path(args.reparse))
    elif args.command == "demo":
        run_parse("data/sample/demo-edc.csv", str(processed_dir() / "demo-analysis.json"))
    elif args.command == "serve":
        serve_portal(args.host, args.port)
    elif args.command == "export-static":
        export_static_site(Path(args.output))


def default_output_path(csv_file: str) -> str:
    stem = Path(csv_file).stem
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(processed_dir() / f"{stem}-{timestamp}.json")


def run_parse(csv_file: str, output: str) -> None:
    report = parse_edc_csv(csv_file)
    analysis = analyze_report(report)
    path = write_analysis(analysis, output)
    print(f"Parsed {csv_file}")
    print(f"Analysis: {path}")
    print(f"Latest: {path.parent / 'latest.json'}")
    print(f"Shared: {analysis['totals']['shared_kwh']} kWh")
    print(f"Missed: {analysis['totals']['missed_kwh']} kWh")
    recommendation = analysis["recommendation"].get("recommended")
    if recommendation:
        print(f"Recommended allocation: {recommendation['allocations']} %")


def run_names() -> None:
    names = load_names()
    if not names:
        print("No OM names configured yet.")
        return
    for ean, name in sorted(names.items()):
        print(f"{ean}: {name}")


def apply_names_to_group_analysis(group_name: str | None, names: dict[str, str]) -> int:
    directory = processed_dir(group_name)
    paths = sorted(directory.glob("edc-????-??-analysis.json"))
    latest = directory / "latest.json"
    if latest.exists():
        paths.append(latest)
    for path in paths:
        apply_names_to_analysis_file(path, names)
    return len(paths)


def apply_names_to_analysis_file(path: Path, names: dict[str, str]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    all_eans = list(data.get("producers", [])) + list(data.get("consumers", []))
    data["om_names"] = {ean: names.get(ean, ean) for ean in all_eans}

    def apply_item_name(item):
        ean = item.get("ean")
        if ean:
            item["name"] = names.get(ean, ean)

    for section in ("producers", "consumers"):
        for item in data.get("eans", {}).get(section, []):
            apply_item_name(item)
    for interval in data.get("intervals", []):
        for section in ("producers", "consumers"):
            for item in interval.get(section, []):
                apply_item_name(item)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_static_site(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in Path("web").iterdir():
        if path.name.startswith("."):
            continue
        target = output_dir / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)

    code = project_code()
    manifest = build_static_manifest()
    static_data_root = output_dir / "data"
    for group in manifest["groups"]:
        for month in group["months"]:
            source = Path(month["source"])
            target = output_dir / month["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        latest = group.get("latest_source")
        if latest:
            target = output_dir / group["latest_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(latest, target)

    for group in manifest["groups"]:
        for month in group["months"]:
            month.pop("source", None)
        group.pop("latest_source", None)

    static_data_root.mkdir(parents=True, exist_ok=True)
    (static_data_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "static-config.json").write_text(json.dumps({
        "static": True,
        "manifest": "data/manifest.json",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported static EDC app for {code or 'default project'} to {output_dir}")
    print(f"Open through a static web server, for example: python3 -m http.server --directory {output_dir} 8080")


def build_static_manifest() -> dict:
    code = project_code()
    names_by_slug = known_group_names_by_slug()
    groups = []
    data_root = Path("data") / code if code else Path("data")
    if data_root.exists():
        for group_dir in sorted(item for item in data_root.iterdir() if item.is_dir()):
            slug = group_dir.name
            if slug not in names_by_slug and not (group_dir / "processed").exists():
                continue
            groups.append(static_group_manifest(names_by_slug.get(slug, slug), slug, code))

    for slug, name in names_by_slug.items():
        if not any(group["slug"] == slug for group in groups):
            groups.append(static_group_manifest(name, slug, code))

    groups.sort(key=lambda item: (not item["has_data"], item["name"].lower()))
    default_name = default_group()
    return {
        "project_code": code,
        "default_group": default_name,
        "default_group_slug": group_slug(default_name),
        "om_names": load_names(),
        "groups": groups,
    }


def known_group_names_by_slug() -> dict[str, str]:
    names: dict[str, str] = {}

    def add(name: str) -> None:
        clean = name.strip()
        if clean:
            names.setdefault(group_slug(clean), clean)

    add(default_group())
    search_root = Path("downloads") / project_code() if project_code() else Path("downloads")
    for path in sorted(search_root.glob("**/available-groups.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            add(line)
    return names


def static_group_manifest(name: str, slug: str, code: str) -> dict:
    processed = (Path("data") / code / slug / "processed") if code else (Path("data") / slug / "processed")
    months = []
    if processed.exists():
        for path in sorted(processed.glob("edc-????-??-analysis.json")):
            parts = path.stem.split("-")
            if len(parts) < 4:
                continue
            try:
                year = int(parts[1])
                month = int(parts[2])
            except ValueError:
                continue
            months.append({
                "year": year,
                "month": month,
                "path": str(Path("data") / code / slug / "processed" / path.name) if code else str(Path("data") / slug / "processed" / path.name),
                "source": str(path),
            })
    latest = processed / "latest.json"
    latest_path = str(Path("data") / code / slug / "processed" / "latest.json") if code else str(Path("data") / slug / "processed" / "latest.json")
    return {
        "name": name,
        "slug": slug,
        "has_data": bool(months),
        "months": months,
        "latest_path": latest_path if latest.exists() else None,
        "latest_source": str(latest) if latest.exists() else None,
    }


def serve_portal(host: str, port: int) -> None:
    sync_lock = threading.Lock()
    sync_state = {
        "running": False,
        "job_id": None,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "traceback": None,
        "results": [],
        "requested_months": [],
    }

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(Path("web").resolve()), **kwargs)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/web", "/web/"):
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path == "/api/om-names":
                self.send_json(load_names())
                return
            if path == "/api/months":
                self.send_json(self.available_months(self.query_group()))
                return
            if path == "/api/config":
                self.send_json({
                    "project_code": project_code(),
                    "group": default_group(),
                    "group_slug": group_slug(),
                })
                return
            if path == "/api/groups":
                self.send_json({"groups": self.available_groups()})
                return
            if path == "/api/data/latest":
                self.send_json_file(processed_dir(self.query_group()) / "latest.json")
                return
            if path == "/api/data/month":
                try:
                    query = parse_qs(urlparse(self.path).query)
                    year = int(query.get("year", ["0"])[0])
                    month = int(query.get("month", ["0"])[0])
                    if month < 1 or month > 12:
                        raise ValueError("Měsíc musí být 1 až 12.")
                    self.send_json_file(processed_dir(self.query_group()) / f"edc-{year}-{month:02d}-analysis.json")
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            if path == "/api/sync-status":
                self.send_json(self.sync_status())
                return
            super().do_GET()

        def list_directory(self, path):
            self.send_error(404, "Directory listing disabled")
            return None

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/sync":
                self.handle_sync()
                return
            if path != "/api/om-names":
                self.send_error(404)
                return

            try:
                payload = self.read_json()
                ean = str(payload.get("ean", "")).strip()
                name = str(payload.get("name", "")).strip()
                if not ean:
                    raise ValueError("Missing EAN")

                names = load_names()
                if name:
                    names[ean] = name
                else:
                    names.pop(ean, None)
                save_names(names)
                self.patch_analysis_names(names)
                self.send_json({"ok": True, "om_names": names})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)

        def handle_sync(self) -> None:
            try:
                payload = self.read_json()
                if not self.authorized(payload):
                    self.send_json({"ok": False, "error": "Neplatný admin token."}, status=403)
                    return

                group_name = self.request_group(payload)
                months = self.sync_month_request(payload)
                if not months:
                    raise ValueError("Vyber alespoň jeden měsíc.")

                with sync_lock:
                    if sync_state["running"]:
                        self.send_json({"ok": False, "error": "Stahování už běží.", "status": sync_state}, status=409)
                        return

                    job_id = uuid.uuid4().hex[:12]
                    sync_state.update({
                        "running": True,
                        "job_id": job_id,
                        "started_at": datetime.now().isoformat(timespec="seconds"),
                        "finished_at": None,
                        "error": None,
                        "traceback": None,
                        "results": [],
                        "group": group_name,
                        "group_slug": group_slug(group_name),
                        "requested_months": [{"year": year, "month": month} for month, year in months],
                    })

                thread = threading.Thread(target=self.run_sync_job, args=(months, group_name), daemon=True)
                thread.start()
                self.send_json({"ok": True, "status": self.sync_status()}, status=202)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)

        def run_sync_job(self, months: list[tuple[int, int]], group_name: str) -> None:
            try:
                results = sync_months(months, group_name=group_name)
                with sync_lock:
                    sync_state.update({
                        "running": False,
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "error": None,
                        "traceback": None,
                        "results": results,
                    })
            except Exception as exc:
                with sync_lock:
                    sync_state.update({
                        "running": False,
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    })

        def sync_status(self) -> dict:
            with sync_lock:
                return dict(sync_state)

        def request_group(self, payload: dict) -> str:
            return str(payload.get("group") or self.query_group()).strip() or default_group()

        def query_group(self) -> str:
            query = parse_qs(urlparse(self.path).query)
            return query.get("group", [default_group()])[0] or default_group()

        def sync_month_request(self, payload: dict) -> list[tuple[int, int]]:
            if isinstance(payload.get("months"), list):
                months = []
                for item in payload["months"]:
                    month = int(item["month"])
                    year = int(item["year"])
                    self.validate_month(month, year)
                    months.append((month, year))
                return self.unique_months(months)

            if payload.get("from") and payload.get("to"):
                start_month = int(payload["from"]["month"])
                start_year = int(payload["from"]["year"])
                end_month = int(payload["to"]["month"])
                end_year = int(payload["to"]["year"])
                return self.month_range(start_month, start_year, end_month, end_year)

            month = int(payload.get("month", 0))
            year = int(payload.get("year", 0))
            self.validate_month(month, year)
            return [(month, year)]

        def month_range(self, start_month: int, start_year: int, end_month: int, end_year: int) -> list[tuple[int, int]]:
            self.validate_month(start_month, start_year)
            self.validate_month(end_month, end_year)
            start_index = start_year * 12 + start_month
            end_index = end_year * 12 + end_month
            if end_index < start_index:
                raise ValueError("Konec období musí být po začátku.")
            if end_index - start_index > 11:
                raise ValueError("Najednou lze stáhnout maximálně 12 měsíců.")
            return [
                (((index - 1) % 12) + 1, (index - 1) // 12)
                for index in range(start_index, end_index + 1)
            ]

        def unique_months(self, months: list[tuple[int, int]]) -> list[tuple[int, int]]:
            seen = set()
            unique = []
            for item in months:
                if item in seen:
                    continue
                seen.add(item)
                unique.append(item)
            return unique

        def validate_month(self, month: int, year: int) -> None:
            if month < 1 or month > 12:
                raise ValueError("Měsíc musí být 1 až 12.")
            if year < 2024 or year > 2100:
                raise ValueError("Rok je mimo očekávaný rozsah.")

        def authorized(self, payload: dict) -> bool:
            expected = self.admin_token()
            if not expected:
                return False
            parsed = urlparse(self.path)
            query_token = parse_qs(parsed.query).get("token", [""])[0]
            provided = (
                self.headers.get("X-EDC-Admin-Token", "")
                or str(payload.get("token", ""))
                or query_token
            )
            return provided == expected

        def admin_token(self) -> str:
            return os.getenv("EDC_ADMIN_TOKEN") or read_env_file().get("EDC_ADMIN_TOKEN", "")

        def read_json(self) -> dict:
            length = int(self.headers.get("content-length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def patch_analysis_names(self, names: dict[str, str]) -> None:
            apply_names_to_group_analysis(self.query_group(), names)

        def available_months(self, group_name: str | None = None) -> dict[str, list[dict[str, int]]]:
            months = []
            for path in sorted(processed_dir(group_name).glob("edc-????-??-analysis.json")):
                parts = path.stem.split("-")
                if len(parts) < 4:
                    continue
                try:
                    months.append({
                        "year": int(parts[1]),
                        "month": int(parts[2]),
                    })
                except ValueError:
                    continue
            return {"months": months}

        def available_groups(self) -> list[dict[str, str]]:
            groups = []
            seen = set()

            def add_group(name: str) -> None:
                clean = name.strip()
                if not clean or clean in seen:
                    return
                seen.add(clean)
                groups.append({
                    "name": clean,
                    "slug": group_slug(clean),
                    "has_data": bool(list(processed_dir(clean).glob("edc-????-??-analysis.json"))),
                })

            add_group(default_group())
            search_root = Path("downloads") / project_code() if project_code() else Path("downloads")
            for path in sorted(search_root.glob("**/available-groups.txt")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    add_group(line)

            return groups

        def send_json_file(self, path: Path) -> None:
            if not path.exists():
                self.send_json({"ok": False, "error": "Soubor s daty nebyl nalezen."}, status=404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving EDC portal at http://{host}:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
