from typing import Any, Dict

from modules.settings_sync import load_settings as _load_settings
from modules.settings_sync import save_settings as _save_settings


def load_settings(settings_path: str) -> Dict[str, Any]:
    return _load_settings(settings_path)


def save_settings(settings_path: str, settings: Dict[str, Any], *, indent: int = 4) -> None:
    _save_settings(settings_path, settings, indent=indent)
