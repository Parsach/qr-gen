from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence


@dataclass
class AppPaths:
    """Centralizes the small set of persistent files written by the app."""

    config: str = "qr_generator_config.json"
    history: str = "qr_generator_history.json"
    templates: str = "custom_templates.json"
    presets: str = "qr_presets.json"


class ConfigManager:
    """Small helper around JSON files so UI code focuses on state, not IO."""

    def __init__(self, base_dir: str, paths: AppPaths | None = None) -> None:
        self.base_dir = base_dir
        self.paths = paths or AppPaths()

    def _resolve(self, path: str) -> str:
        return os.path.join(self.base_dir, path)

    def _ensure_dir(self, path: str) -> None:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

    def _load_json(self, path: str, default: Any) -> Any:
        full_path = self._resolve(path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as exc:
            print(f"Failed to decode {path}: {exc}")
            return default

    def _save_json(self, path: str, payload: Any) -> None:
        full_path = self._resolve(path)
        self._ensure_dir(full_path)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

    # Config -----------------------------------------------------------------
    def load_config(self) -> Dict[str, Any]:
        return self._load_json(self.paths.config, {})

    def save_config(self, payload: Dict[str, Any]) -> None:
        self._save_json(self.paths.config, payload)

    # History ----------------------------------------------------------------
    def load_history(self) -> List[Dict[str, Any]]:
        return self._load_json(self.paths.history, [])

    def save_history(self, history: Sequence[Dict[str, Any]]) -> None:
        self._save_json(self.paths.history, list(history))

    # Templates --------------------------------------------------------------
    def load_custom_templates(self) -> List[Dict[str, Any]]:
        return self._load_json(self.paths.templates, [])

    def save_custom_templates(self, templates: Sequence[Dict[str, Any]]) -> None:
        self._save_json(self.paths.templates, list(templates))

    # Presets ----------------------------------------------------------------
    def load_presets(self) -> List[Dict[str, Any]]:
        return self._load_json(self.paths.presets, [])

    def save_presets(self, presets: Sequence[Dict[str, Any]]) -> None:
        self._save_json(self.paths.presets, list(presets))


def resolve_base_dir() -> str:
    """Helps running the app from anywhere while keeping files next to code."""

    return os.path.dirname(os.path.abspath(__file__))
