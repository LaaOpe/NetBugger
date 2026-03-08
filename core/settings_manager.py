"""应用设置管理（读取/保存）。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
import sys


APP_NAME = "NetBugger"


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
    """获取项目根目录，兼容源码运行与 PyInstaller 打包后的路径。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_data_dir(project_root: str | None = None) -> str:
    """返回可写的应用数据目录。"""
    if sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    elif sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or _default_project_root()
    else:
        base = os.path.expanduser('~/.config')

    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_recordings_dir(project_root: str | None = None) -> str:
    """返回录制文件目录。"""
    path = os.path.join(get_app_data_dir(project_root), 'recordings')
    os.makedirs(path, exist_ok=True)
    return path


def settings_path(project_root: str | None = None) -> str:
    return os.path.join(get_app_data_dir(project_root), SETTINGS_FILE)


def load_settings(project_root: str | None = None) -> AppSettings:
    app_path = settings_path(project_root)
    bundled_root = project_root or _default_project_root()
    bundled_path = os.path.join(bundled_root, SETTINGS_FILE)

    path = None
    for candidate in (app_path, bundled_path):
        if os.path.exists(candidate):
            path = candidate
            break

    if path is None:
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
