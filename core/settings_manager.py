"""应用设置管理（读取/保存）。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
import sys


@dataclass
class AppSettings:
    font_scale: float = 1.3
    layout_mode: str = "平衡"
    monitor_external: bool = True
    ping_interval: float = 1.0
    graph_max_points: int = 60
    always_on_top: bool = False
    opacity: float = 1.0
    auto_start_monitor: bool = False
    external_target_index: int = 0


SETTINGS_FILE = "settings.json"


def _default_project_root() -> str:
    """获取项目根目录，兼容 PyInstaller 打包后的路径。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def settings_path(project_root: str | None = None) -> str:
    if project_root is None:
        project_root = _default_project_root()
    return os.path.join(project_root, SETTINGS_FILE)


def load_settings(project_root: str | None = None) -> AppSettings:
    path = settings_path(project_root)
    if not os.path.exists(path):
        return AppSettings()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults = AppSettings()
        return AppSettings(
            font_scale=float(data.get("font_scale", defaults.font_scale)),
            layout_mode=str(data.get("layout_mode", defaults.layout_mode)),
            monitor_external=bool(data.get("monitor_external", defaults.monitor_external)),
            ping_interval=float(data.get("ping_interval", defaults.ping_interval)),
            graph_max_points=int(data.get("graph_max_points", defaults.graph_max_points)),
            always_on_top=bool(data.get("always_on_top", defaults.always_on_top)),
            opacity=float(data.get("opacity", defaults.opacity)),
            auto_start_monitor=bool(data.get("auto_start_monitor", defaults.auto_start_monitor)),
            external_target_index=int(data.get("external_target_index", defaults.external_target_index)),
        )
    except Exception:
        return AppSettings()


def save_settings(project_root: str | None = None, settings: AppSettings | None = None) -> bool:
    """保存设置到 JSON 文件。成功返回 True。"""
    if settings is None:
        return False
    path = settings_path(project_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
