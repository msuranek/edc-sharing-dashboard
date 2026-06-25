from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path


def read_env_file(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def project_code() -> str:
    value = os.getenv("EDC_PROJECT_CODE") or read_env_file().get("EDC_PROJECT_CODE", "")
    return slugify(value)


def default_group() -> str:
    env = read_env_file()
    return os.getenv("EDC_GROUP") or os.getenv("EDC_DEFAULT_GROUP") or env.get("EDC_GROUP", "") or env.get("EDC_DEFAULT_GROUP", "")


def group_slug(group_name: str | None = None) -> str:
    return slugify(group_name or default_group())


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", ascii_value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)


def data_dir(group_name: str | None = None) -> Path:
    code = project_code()
    group = group_slug(group_name)
    path = Path("data")
    if code:
        path /= code
    if group:
        path /= group
    return path


def raw_dir(group_name: str | None = None) -> Path:
    return data_dir(group_name) / "raw"


def processed_dir(group_name: str | None = None) -> Path:
    return data_dir(group_name) / "processed"


def downloads_dir(group_name: str | None = None) -> Path:
    code = project_code()
    group = group_slug(group_name)
    path = Path("downloads")
    if code:
        path /= code
    if group:
        path /= group
    return path


def project_downloads_dir() -> Path:
    code = project_code()
    path = Path("downloads")
    if code:
        path /= code
    return path
