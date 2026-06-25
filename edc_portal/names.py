from __future__ import annotations

import json
from pathlib import Path


DEFAULT_NAMES_PATH = Path("config/om_names.json")


def load_names(path: str | Path = DEFAULT_NAMES_PATH) -> dict[str, str]:
    names_path = Path(path)
    if not names_path.exists():
        return {}
    data = json.loads(names_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{names_path} must be a JSON object mapping EAN to name")
    return {str(ean): str(name) for ean, name in data.items()}


def save_names(names: dict[str, str], path: str | Path = DEFAULT_NAMES_PATH) -> Path:
    names_path = Path(path)
    names_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_names = dict(sorted(names.items()))
    names_path.write_text(json.dumps(sorted_names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return names_path


def set_name(ean: str, name: str, path: str | Path = DEFAULT_NAMES_PATH) -> Path:
    names = load_names(path)
    names[ean] = name
    return save_names(names, path)


def remove_name(ean: str, path: str | Path = DEFAULT_NAMES_PATH) -> Path:
    names = load_names(path)
    names.pop(ean, None)
    return save_names(names, path)
