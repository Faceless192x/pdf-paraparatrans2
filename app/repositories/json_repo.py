import json
import os
import tempfile
from typing import Any


def load_json(json_path: str) -> Any:
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"{json_path} not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(json_path: str, data: Any, *, indent: int = 2) -> None:
    dir_path = os.path.dirname(json_path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, ensure_ascii=False, indent=indent)
    os.replace(tmp_path, json_path)
