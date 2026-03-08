"""
NetBugger 主窗口
基于 tkinter 的深色主题 UI，实时展示 ping 图表、WiFi 信息与诊断结果。
"""

import tkinter as tk
from tkinter import ttk
import time
import sys
import os
import csv
import threading
from datetime import datetime
from collections import deque

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.ping_monitor import PingMonitor
from core.wifi_monitor import WifiMonitor, WifiInfo, detect_gateway
from core.diagnosis import DiagnosisEngine, DiagnosisResult
from core.network_speed_monitor import NetworkSpeedMonitor
from core.self_diagnosis import SelfDiagnosisEngine
from core.settings_manager import AppSettings, load_settings, save_settings

# ======================================================================
# 颜色常量（深色主题）
# ======================================================================
BG_DARK   = '#1e1e1e'
BG_PANEL  = '#252526'
BG_GRAPH  = '#1b1b1b'
FG_MAIN   = '#cccccc'
FG_DIM    = '#888888'
FG_TITLE  = '#ffffff'
BORDER    = '#3c3c3c'
GREEN     = '#4ec9b0'
YELLOW    = '#dcdcaa'
ORANGE    = '#ce9178'
RED       = '#f44747'
BLUE      = '#569cd6'

FONT_FAMILY = 'Microsoft YaHei UI'
FONT_SCALE = 1.3


def sf(size: int) -> int:
    return max(8, int(round(size * FONT_SCALE)))


def _add_hover(btn, hover_bg):
    """给按钮添加鼠标悬停变色效果。"""
    normal_bg = btn.cget('bg')
    btn.bind('<Enter>', lambda e, b=btn, c=hover_bg: b.config(bg=c))
    btn.bind('<Leave>', lambda e, b=btn, c=normal_bg: b.config(bg=c))


# ======================================================================
# 自定义组件
# ======================================================================

class PingGraph(tk.Canvas):
    """实时 Ping 延迟折线图（Canvas 绘制）"""

    def __init__(self, parent, title="", max_points=60, **kw):
        kw.setdefault('bg', BG_GRAPH)
        kw.setdefault('highlightthickness', 0)
        super().__init__(parent, **kw)
        self.title = title
        self._data: list[int] = []
        self._max_points = max_points
        self.bind('<Configure>', lambda _: self._redraw())

    def update_data(self, data: list[int]):
        self._data = data
        self._redraw()

    # ------------------------------------------------------------------
    def _redraw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return

        pad_t, pad_b, pad_l, pad_r = 22, 18, 42, 8
        gw = w - pad_l - pad_r
        gh = h - pad_t - pad_b
        if gw < 10 or gh < 10:
            return

        # 标题
        self.create_text(w // 2, 11, text=self.title, fill=FG_MAIN,
                 font=(FONT_FAMILY, sf(9), 'bold'))

        # 绘图区底色
        self.create_rectangle(pad_l, pad_t, w - pad_r, h - pad_b,
                              fill=BG_PANEL, outline=BORDER)

        if not self._data:
            self.create_text(w // 2, h // 2, text="等待数据…",
                             fill=FG_DIM, font=(FONT_FAMILY, sf(9)))
            return

        plot_data = self._data[-self._max_points:]

        # 纵轴量程
        valid = [d for d in plot_data if d >= 0]
        max_val = max(max(valid) * 1.15, 8) if valid else 80

        # 网格
        for i in range(5):
            y = pad_t + gh * i / 4
            v = max_val * (1 - i / 4)
            self.create_line(pad_l, y, w - pad_r, y, fill='#333333', dash=(2, 4))
            self.create_text(pad_l - 4, y, text=f"{v:.0f}", anchor='e',
                             fill=FG_DIM, font=('Consolas', sf(7)))
        self.create_text(pad_l - 4, pad_t - 9, text="ms", anchor='e',
                         fill=FG_DIM, font=('Consolas', sf(7)))

        # 数据点
        n = len(plot_data)
        step = gw / max(n - 1, 1)
        pts = []
        for i, v in enumerate(plot_data):
            x = pad_l + i * step
            if v >= 0:
                y = pad_t + gh * (1 - v / max_val)
                y = max(pad_t, min(h - pad_b, y))
                pts.append((x, y, v))
            else:
                # 丢包标记
                y = h - pad_b - 3
                self.create_oval(x - 3, y - 3, x + 3, y + 3, fill=RED, outline='')
                pts.append(None)

        # 折线
        for i in range(1, len(pts)):
            if pts[i] and pts[i - 1]:
                color = _latency_color(pts[i][2])
                self.create_line(pts[i - 1][0], pts[i - 1][1],
                                 pts[i][0], pts[i][1],
                                 fill=color, width=1.5)
        # 点
        for p in pts:
            if p:
                c = _latency_color(p[2])
                self.create_oval(p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2,
                                 fill=c, outline='')


class SignalBar(tk.Canvas):
    """WiFi 信号强度条"""

    def __init__(self, parent, **kw):
        kw.setdefault('bg', BG_PANEL)
        kw.setdefault('highlightthickness', 0)
        kw.setdefault('height', 18)
        super().__init__(parent, **kw)
        self._pct = 0
        self.bind('<Configure>', lambda _: self._draw())

    def set_value(self, pct: int):
        self._pct = max(0, min(100, pct))
        self._draw()

    def _draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        bar_w = w - 50
        self.create_rectangle(0, 2, bar_w, h - 2, fill='#333333', outline='')
        filled = int(bar_w * self._pct / 100)
        color = GREEN if self._pct >= 60 else (YELLOW if self._pct >= 40 else RED)
        if filled > 0:
            self.create_rectangle(0, 2, filled, h - 2, fill=color, outline='')
        self.create_text(bar_w + 6, h // 2, text=f"{self._pct}%", anchor='w',
                         fill=color, font=('Consolas', sf(9), 'bold'))


class StatsBar(tk.Frame):
    """一行统计指标"""

    def __init__(self, parent, items: list[tuple[str, str]], **kw):
        super().__init__(parent, bg=BG_DARK, **kw)
        self._labels: dict[str, tk.Label] = {}
        for i, (key, label_text) in enumerate(items):
            f = tk.Frame(self, bg=BG_DARK)
            f.grid(row=0, column=i, padx=(0, 16), sticky='w')
            tk.Label(f, text=f"{label_text}: ", fg=FG_DIM, bg=BG_DARK,
                   font=(FONT_FAMILY, sf(8))).pack(side='left')
            lbl = tk.Label(f, text="--", fg=FG_MAIN, bg=BG_DARK,
                       font=('Consolas', sf(9), 'bold'))
            lbl.pack(side='left')
            self._labels[key] = lbl

    def set(self, key: str, text: str, fg: str = FG_MAIN):
        lbl = self._labels.get(key)
        if lbl:
            lbl.config(text=text, fg=fg)


class RecordViewer(tk.Toplevel):
    METRICS = [
        ('网关延迟 (ms)', 'gw_avg_latency'),
        ('外网延迟 (ms)', 'ext_avg_latency'),
        ('网关丢包 (%)', 'gw_loss_rate'),
        ('外网丢包 (%)', 'ext_loss_rate'),
        ('下载速率 (KB/s)', 'download_kbps'),
        ('上传速率 (KB/s)', 'upload_kbps'),
        ('WiFi 信号 (%)', 'wifi_signal'),
    ]

    def __init__(self, parent, csv_path: str):
        super().__init__(parent)
        self.title('录制回放 - 网络变化图')
        self.geometry('980x560')
        self.minsize(820, 460)
        self.configure(bg=BG_DARK)

        self._csv_path = csv_path
        self._rows = self._load_rows(csv_path)

        top = tk.Frame(self, bg=BG_DARK, padx=10, pady=8)
        top.pack(fill='x')
        tk.Label(top, text='指标:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).pack(side='left')
        self._metric_var = tk.StringVar(value=self.METRICS[0][0])
        self._metric_combo = ttk.Combobox(
            top, textvariable=self._metric_var, width=22,
            values=[m[0] for m in self.METRICS], state='readonly',
            font=(FONT_FAMILY, sf(9)),
        )
        self._metric_combo.pack(side='left', padx=(6, 16))
        self._metric_combo.bind('<<ComboboxSelected>>', lambda _e: self._draw())

        tk.Button(
            top, text='打开 CSV 文件',
            command=self._open_csv_file,
            font=(FONT_FAMILY, sf(9), 'bold'),
            bg='#0e639c', fg='#ffffff', relief='flat', padx=12, pady=2,
            cursor='hand2'
        ).pack(side='left')

        self._summary_lbl = tk.Label(
            top,
            text=f'样本数: {len(self._rows)}    文件: {os.path.basename(csv_path)}',
            fg=FG_DIM, bg=BG_DARK, font=(FONT_FAMILY, sf(8)),
        )
        self._summary_lbl.pack(side='right')

        self._canvas = tk.Canvas(self, bg=BG_GRAPH, highlightthickness=0)
        self._canvas.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self._canvas.bind('<Configure>', lambda _e: self._draw())
        self._draw()

    def _load_rows(self, path: str) -> list[dict]:
        rows = []
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except Exception:
            return []
        return rows

    def _open_csv_file(self):
        try:
            os.startfile(self._csv_path)
        except Exception:
            pass

    def _draw(self):
        c = self._canvas
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        if w < 40 or h < 40:
            return

        pad_t, pad_b, pad_l, pad_r = 24, 34, 56, 14
        gw, gh = w - pad_l - pad_r, h - pad_t - pad_b
        if gw < 20 or gh < 20:
            return

        c.create_rectangle(pad_l, pad_t, w - pad_r, h - pad_b, outline=BORDER, fill=BG_PANEL)
        c.create_text(pad_l, 10, anchor='w', fill=FG_MAIN,
                      font=(FONT_FAMILY, sf(9), 'bold'),
                      text=f'文件: {self._csv_path}')

        if not self._rows:
            c.create_text(w // 2, h // 2, text='录制文件为空或读取失败',
                          fill=FG_DIM, font=(FONT_FAMILY, sf(10)))
            return

        metric_name = self._metric_var.get()
        metric_key = self.METRICS[0][1]
        for name, key in self.METRICS:
            if name == metric_name:
                metric_key = key
                break

        vals = []
        for row in self._rows:
            try:
                vals.append(float(row.get(metric_key, '0') or 0))
            except ValueError:
                vals.append(0.0)

        if not vals:
            c.create_text(w // 2, h // 2, text='无可绘制数据',
                          fill=FG_DIM, font=(FONT_FAMILY, sf(10)))
            return

        max_val = max(max(vals) * 1.1, 1.0)
        min_val = 0.0

        for i in range(5):
            y = pad_t + gh * i / 4
            v = max_val * (1 - i / 4)
            c.create_line(pad_l, y, w - pad_r, y, fill='#333333', dash=(2, 4))
            c.create_text(pad_l - 6, y, anchor='e', fill=FG_DIM,
                          font=('Consolas', sf(7)), text=f'{v:.1f}')

        n = len(vals)
        step = gw / max(1, n - 1)
        points = []
        for i, v in enumerate(vals):
            x = pad_l + i * step
            y = pad_t + gh * (1 - (v - min_val) / max(1e-9, (max_val - min_val)))
            y = max(pad_t, min(h - pad_b, y))
            points.extend([x, y])

        if len(points) >= 4:
            c.create_line(*points, fill=BLUE, width=2)
        for i in range(0, len(points), 2):
            c.create_oval(points[i] - 2, points[i + 1] - 2,
                          points[i] + 2, points[i + 1] + 2,
                          fill=GREEN, outline='')

        c.create_text(w // 2, h - 14, text=f'{metric_name}  ({n} 个采样点)',
                      fill=FG_MAIN, font=(FONT_FAMILY, sf(9), 'bold'))


class SettingsDialog(tk.Toplevel):
    FONT_OPTIONS = [
        ('100%', 1.0),
        ('115%', 1.15),
        ('130%', 1.3),
        ('145%', 1.45),
    ]
    LAYOUT_OPTIONS = ['平衡', '图表优先', '文本优先']
    PING_INTERVAL_OPTIONS = [
        ('0.5 秒', 0.5),
        ('1.0 秒', 1.0),
        ('2.0 秒', 2.0),
        ('3.0 秒', 3.0),
    ]
    GRAPH_POINTS_OPTIONS = [
        ('30 点', 30),
        ('60 点', 60),
        ('90 点', 90),
        ('120 点', 120),
    ]

    def __init__(self, parent, settings: AppSettings, on_apply):
        super().__init__(parent)
        self.title('⚙ NetBugger 设置')
        self.resizable(False, False)
        self.configure(bg=BG_DARK)

        self._on_apply = on_apply
        self._settings = settings
        self._parent_win = parent

        self._build_body()
        self.transient(parent)
        self.grab_set()

        # 居中于父窗口
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        dw = self.winfo_reqwidth()
        dh = self.winfo_reqheight()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_body(self):
        body = tk.Frame(self, bg=BG_DARK, padx=20, pady=16)
        body.pack(fill='both', expand=True)

        row = 0

        # ── 监控设置 ──
        tk.Label(body, text='📡 监控设置', fg=BLUE, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(10), 'bold')
                 ).grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 6))
        row += 1

        tk.Label(body, text='Ping 间隔:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).grid(row=row, column=0, sticky='e', pady=4)
        self._ping_var = tk.StringVar(value=self._ping_label(self._settings.ping_interval))
        ttk.Combobox(body, textvariable=self._ping_var,
                     values=[x[0] for x in self.PING_INTERVAL_OPTIONS],
                     state='readonly', width=14, font=(FONT_FAMILY, sf(9)),
                     ).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1

        tk.Label(body, text='图表数据点:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).grid(row=row, column=0, sticky='e', pady=4)
        self._points_var = tk.StringVar(value=self._points_label(self._settings.graph_max_points))
        ttk.Combobox(body, textvariable=self._points_var,
                     values=[x[0] for x in self.GRAPH_POINTS_OPTIONS],
                     state='readonly', width=14, font=(FONT_FAMILY, sf(9)),
                     ).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1

        self._ext_var = tk.BooleanVar(value=self._settings.monitor_external)
        tk.Checkbutton(body, text='监测外网 Ping', variable=self._ext_var,
                       fg=FG_MAIN, bg=BG_DARK, activebackground=BG_DARK,
                       activeforeground=FG_MAIN, selectcolor=BG_PANEL,
                       font=(FONT_FAMILY, sf(9)),
                       ).grid(row=row, column=0, columnspan=2, sticky='w', pady=4)
        row += 1

        self._auto_start_var = tk.BooleanVar(value=self._settings.auto_start_monitor)
        tk.Checkbutton(body, text='启动时自动开始监测', variable=self._auto_start_var,
                       fg=FG_MAIN, bg=BG_DARK, activebackground=BG_DARK,
                       activeforeground=FG_MAIN, selectcolor=BG_PANEL,
                       font=(FONT_FAMILY, sf(9)),
                       ).grid(row=row, column=0, columnspan=2, sticky='w', pady=4)
        row += 1

        # ── 分隔线 ──
        tk.Frame(body, bg=BORDER, height=1).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1

        # ── 界面设置 ──
        tk.Label(body, text='🎨 界面设置', fg=BLUE, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(10), 'bold')
                 ).grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 6))
        row += 1

        tk.Label(body, text='字号缩放:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).grid(row=row, column=0, sticky='e', pady=4)
        self._font_var = tk.StringVar(value=self._font_label_from_scale(self._settings.font_scale))
        ttk.Combobox(body, textvariable=self._font_var,
                     values=[x[0] for x in self.FONT_OPTIONS],
                     state='readonly', width=14, font=(FONT_FAMILY, sf(9)),
                     ).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1

        tk.Label(body, text='整体布局:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).grid(row=row, column=0, sticky='e', pady=4)
        self._layout_var = tk.StringVar(value=self._settings.layout_mode)
        ttk.Combobox(body, textvariable=self._layout_var,
                     values=self.LAYOUT_OPTIONS,
                     state='readonly', width=14, font=(FONT_FAMILY, sf(9)),
                     ).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1

        tk.Label(body, text='窗口透明度:', fg=FG_MAIN, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(9))).grid(row=row, column=0, sticky='e', pady=4)
        opacity_frame = tk.Frame(body, bg=BG_DARK)
        opacity_frame.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        self._opacity_var = tk.DoubleVar(value=self._settings.opacity)
        tk.Scale(opacity_frame, from_=0.3, to=1.0, resolution=0.05,
                 orient='horizontal', variable=self._opacity_var,
                 bg=BG_DARK, fg=FG_MAIN, troughcolor=BG_PANEL,
                 highlightthickness=0, length=140, font=(FONT_FAMILY, sf(7)),
                 command=self._preview_opacity,
                 ).pack(side='left')
        row += 1

        self._top_var = tk.BooleanVar(value=self._settings.always_on_top)
        tk.Checkbutton(body, text='窗口始终置顶', variable=self._top_var,
                       fg=FG_MAIN, bg=BG_DARK, activebackground=BG_DARK,
                       activeforeground=FG_MAIN, selectcolor=BG_PANEL,
                       font=(FONT_FAMILY, sf(9)),
                       ).grid(row=row, column=0, columnspan=2, sticky='w', pady=4)
        row += 1

        # ── 分隔线 ──
        tk.Frame(body, bg=BORDER, height=1).grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1

        # ── 提示 & 按钮 ──
        tk.Label(body, text='提示：布局/字号变动会刷新界面但不中断监测。',
                 fg=FG_DIM, bg=BG_DARK, font=(FONT_FAMILY, sf(8)),
                 anchor='w').grid(row=row, column=0, columnspan=2, sticky='w', pady=(0, 8))
        row += 1

        btns = tk.Frame(body, bg=BG_DARK)
        btns.grid(row=row, column=0, columnspan=2, sticky='e', pady=(4, 0))

        cancel_btn = tk.Button(btns, text='取消', command=self._cancel,
                               font=(FONT_FAMILY, sf(9), 'bold'),
                               bg='#3c3c3c', fg='#ffffff', activebackground='#505050',
                               activeforeground='#ffffff', relief='flat',
                               padx=14, pady=3, cursor='hand2')
        cancel_btn.pack(side='right')
        _add_hover(cancel_btn, '#505050')

        apply_btn = tk.Button(btns, text='✓ 应用', command=self._apply,
                              font=(FONT_FAMILY, sf(9), 'bold'),
                              bg='#0e639c', fg='#ffffff', activebackground='#1177bb',
                              activeforeground='#ffffff', relief='flat',
                              padx=16, pady=3, cursor='hand2')
        apply_btn.pack(side='right', padx=(0, 8))
        _add_hover(apply_btn, '#1177bb')

        body.columnconfigure(1, weight=1)

    def _preview_opacity(self, _val):
        try:
            self._parent_win.attributes('-alpha', self._opacity_var.get())
        except Exception:
            pass

    def _cancel(self):
        # 取消时恢复原透明度
        try:
            self._parent_win.attributes('-alpha', self._settings.opacity)
        except Exception:
            pass
        self.destroy()

    def _font_label_from_scale(self, scale: float) -> str:
        nearest = min(self.FONT_OPTIONS, key=lambda x: abs(x[1] - scale))
        return nearest[0]

    def _scale_from_font_label(self, label: str) -> float:
        for l, s in self.FONT_OPTIONS:
            if l == label:
                return s
        return 1.3

    def _ping_label(self, val: float) -> str:
        nearest = min(self.PING_INTERVAL_OPTIONS, key=lambda x: abs(x[1] - val))
        return nearest[0]

    def _ping_value(self, label: str) -> float:
        for l, v in self.PING_INTERVAL_OPTIONS:
            if l == label:
                return v
        return 1.0

    def _points_label(self, val: int) -> str:
        nearest = min(self.GRAPH_POINTS_OPTIONS, key=lambda x: abs(x[1] - val))
        return nearest[0]

    def _points_value(self, label: str) -> int:
        for l, v in self.GRAPH_POINTS_OPTIONS:
            if l == label:
                return v
        return 60

    def _apply(self):
        new_settings = AppSettings(
            font_scale=self._scale_from_font_label(self._font_var.get()),
            layout_mode=self._layout_var.get() if self._layout_var.get() in self.LAYOUT_OPTIONS else '平衡',
            monitor_external=bool(self._ext_var.get()),
            ping_interval=self._ping_value(self._ping_var.get()),
            graph_max_points=self._points_value(self._points_var.get()),
            always_on_top=bool(self._top_var.get()),
            opacity=self._opacity_var.get(),
            auto_start_monitor=bool(self._auto_start_var.get()),
            external_target_index=self._settings.external_target_index,
        )
        self._on_apply(new_settings)
        self.destroy()


# ======================================================================
# 迷你悬浮窗
# ======================================================================

class MiniFloatWindow(tk.Toplevel):
    """小型悬浮监控窗口，始终置顶显示关键网络指标。"""

    WIDTH = 230
    HEIGHT = 138

    def __init__(self, master, on_restore, on_close):
        super().__init__(master)
        self.overrideredirect(True)          # 无边框
        self.attributes('-topmost', True)    # 始终置顶
        self.attributes('-alpha', 0.92)
        self.configure(bg='#1a1a2e')
        self._on_restore = on_restore
        self._on_close = on_close

        # 初始位置：屏幕右下角偏上
        sx = self.winfo_screenwidth()
        sy = self.winfo_screenheight()
        x = sx - self.WIDTH - 16
        y = sy - self.HEIGHT - 80
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        # 拖拽支持
        self._drag_x = 0
        self._drag_y = 0

        self._build_ui()

    def _build_ui(self):
        # 标题栏（可拖拽）
        title_bar = tk.Frame(self, bg='#16213e', height=24)
        title_bar.pack(fill='x')
        title_bar.pack_propagate(False)

        title_lbl = tk.Label(title_bar, text=' ⚡ NetBugger', fg='#e0e0e0',
                             bg='#16213e', font=(FONT_FAMILY, 9, 'bold'),
                             anchor='w')
        title_lbl.pack(side='left', padx=4, fill='x', expand=True)

        # 拖拽绑定到标题栏及标签
        for w in (title_bar, title_lbl):
            w.bind('<Button-1>', self._start_drag)
            w.bind('<B1-Motion>', self._on_drag)

        # 还原按钮
        restore_btn = tk.Label(title_bar, text='⬜', fg='#aaaaaa', bg='#16213e',
                               font=(FONT_FAMILY, 9), cursor='hand2')
        restore_btn.pack(side='right', padx=(0, 2))
        restore_btn.bind('<Button-1>', lambda e: self._on_restore())
        restore_btn.bind('<Enter>', lambda e: restore_btn.config(fg='#ffffff'))
        restore_btn.bind('<Leave>', lambda e: restore_btn.config(fg='#aaaaaa'))

        # 关闭按钮
        close_btn = tk.Label(title_bar, text='✕', fg='#aaaaaa', bg='#16213e',
                             font=(FONT_FAMILY, 9), cursor='hand2')
        close_btn.pack(side='right', padx=(0, 2))
        close_btn.bind('<Button-1>', lambda e: self._on_close())
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg=RED))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg='#aaaaaa'))

        # 内容区
        body = tk.Frame(self, bg='#1a1a2e', padx=8, pady=4)
        body.pack(fill='both', expand=True)

        # ── 第一行：Ping ──
        row0 = tk.Frame(body, bg='#1a1a2e')
        row0.pack(fill='x', pady=(0, 2))
        tk.Label(row0, text='Ping', fg='#888', bg='#1a1a2e',
                 font=(FONT_FAMILY, 8), width=5, anchor='w').pack(side='left')
        self._ping_lbl = tk.Label(row0, text='-- ms', fg=GREEN, bg='#1a1a2e',
                                  font=('Consolas', 10, 'bold'), anchor='w')
        self._ping_lbl.pack(side='left', padx=(4, 0))
        self._loss_lbl = tk.Label(row0, text='丢包 --%', fg=FG_DIM, bg='#1a1a2e',
                                  font=(FONT_FAMILY, 8), anchor='e')
        self._loss_lbl.pack(side='right')

        # ── 第二行：外网 Ping ──
        row1 = tk.Frame(body, bg='#1a1a2e')
        row1.pack(fill='x', pady=(0, 2))
        tk.Label(row1, text='外网', fg='#888', bg='#1a1a2e',
                 font=(FONT_FAMILY, 8), width=5, anchor='w').pack(side='left')
        self._ext_ping_lbl = tk.Label(row1, text='-- ms', fg=GREEN, bg='#1a1a2e',
                                      font=('Consolas', 10, 'bold'), anchor='w')
        self._ext_ping_lbl.pack(side='left', padx=(4, 0))
        self._ext_loss_lbl = tk.Label(row1, text='丢包 --%', fg=FG_DIM, bg='#1a1a2e',
                                      font=(FONT_FAMILY, 8), anchor='e')
        self._ext_loss_lbl.pack(side='right')

        # ── 分隔线 ──
        tk.Frame(body, bg='#333', height=1).pack(fill='x', pady=3)

        # ── 第三行：网速 ──
        row2 = tk.Frame(body, bg='#1a1a2e')
        row2.pack(fill='x', pady=(0, 1))
        self._dl_lbl = tk.Label(row2, text='↓ 0 KB/s', fg=GREEN, bg='#1a1a2e',
                                font=('Consolas', 9, 'bold'), anchor='w')
        self._dl_lbl.pack(side='left')
        self._ul_lbl = tk.Label(row2, text='↑ 0 KB/s', fg=BLUE, bg='#1a1a2e',
                                font=('Consolas', 9, 'bold'), anchor='e')
        self._ul_lbl.pack(side='right')

        # ── 第四行：WiFi 信号 ──
        row3 = tk.Frame(body, bg='#1a1a2e')
        row3.pack(fill='x')
        tk.Label(row3, text='WiFi', fg='#888', bg='#1a1a2e',
                 font=(FONT_FAMILY, 8), width=5, anchor='w').pack(side='left')
        self._wifi_lbl = tk.Label(row3, text='--%', fg=FG_DIM, bg='#1a1a2e',
                                  font=('Consolas', 9, 'bold'), anchor='w')
        self._wifi_lbl.pack(side='left', padx=(4, 0))

        # 底部圆角边框效果
        border = tk.Frame(self, bg='#0f3460', height=2)
        border.pack(fill='x', side='bottom')

    def update_stats(self, gw_stats, ext_stats, wifi_info, speed_info):
        """由主窗口定时调用，更新悬浮窗数据。"""
        # 网关 Ping
        if gw_stats and gw_stats.get('total', 0) > 0:
            avg = gw_stats['avg_latency']
            loss = gw_stats['loss_rate']
            self._ping_lbl.config(text=f"{avg:.0f} ms", fg=_latency_color(avg))
            self._loss_lbl.config(text=f"丢包 {loss:.1f}%", fg=_loss_color(loss))
        else:
            self._ping_lbl.config(text='-- ms', fg=FG_DIM)
            self._loss_lbl.config(text='丢包 --%', fg=FG_DIM)

        # 外网 Ping
        if ext_stats and ext_stats.get('total', 0) > 0 and ext_stats.get('graph_data'):
            avg = ext_stats['avg_latency']
            loss = ext_stats['loss_rate']
            self._ext_ping_lbl.config(text=f"{avg:.0f} ms", fg=_latency_color(avg))
            self._ext_loss_lbl.config(text=f"丢包 {loss:.1f}%", fg=_loss_color(loss))
        else:
            self._ext_ping_lbl.config(text='-- ms', fg=FG_DIM)
            self._ext_loss_lbl.config(text='丢包 --%', fg=FG_DIM)

        # 网速
        if speed_info:
            self._dl_lbl.config(text=f"↓ {_format_speed(speed_info.download_bps)}")
            self._ul_lbl.config(text=f"↑ {_format_speed(speed_info.upload_bps)}")

        # WiFi
        if wifi_info and wifi_info.connected:
            pct = wifi_info.signal_percent
            color = GREEN if pct >= 60 else (YELLOW if pct >= 40 else RED)
            self._wifi_lbl.config(text=f"{pct}%", fg=color)
        else:
            self._wifi_lbl.config(text='--%', fg=FG_DIM)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + event.x - self._drag_x
        y = self.winfo_y() + event.y - self._drag_y
        self.geometry(f"+{x}+{y}")


# ======================================================================
# 主窗口
# ======================================================================

class MainWindow(tk.Tk):

    EXTERNAL_TARGETS = [
        ('8.8.8.8',        'Google DNS'),
        ('114.114.114.114', '114 DNS'),
        ('223.5.5.5',      '阿里 DNS'),
        ('1.1.1.1',        'Cloudflare'),
        ('119.29.29.29',   '腾讯 DNS'),
    ]

    def __init__(self):
        super().__init__()
        self.title("NetBugger — 网络丢包卡顿诊断工具")
        self.geometry("1060x760")
        self.minsize(940, 680)
        self.configure(bg=BG_DARK)

        # 加载设置
        self._settings = load_settings(_PROJECT_ROOT)
        global FONT_SCALE
        FONT_SCALE = self._settings.font_scale

        # 尝试设置 DPI 感知
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # ── 监控对象 ────────────────────
        self._gateway_ip: str | None = None
        _idx = min(self._settings.external_target_index, len(self.EXTERNAL_TARGETS) - 1)
        self._ext_target: str = self.EXTERNAL_TARGETS[_idx][0]

        self._gw_monitor: PingMonitor | None = None
        self._ext_monitor: PingMonitor | None = None
        self._wifi_monitor = WifiMonitor(interval=3.0)
        self._speed_monitor = NetworkSpeedMonitor(interval=1.0)
        self._diag_engine = DiagnosisEngine()
        self._self_diag_engine = SelfDiagnosisEngine()

        self._monitoring = False
        self._start_time: float = 0.0
        self._update_job = None
        self._recording = False
        self._record_file_path: str | None = None
        self._record_fp = None
        self._record_writer = None
        self._record_points = 0
        self._manual_diag_override_until = 0.0

        # 自诊断采样缓存
        self._wifi_signal_series = deque(maxlen=180)
        self._gw_latency_series = deque(maxlen=180)

        # ── 悬浮窗 & 托盘 ──────────────
        self._mini_float: MiniFloatWindow | None = None
        self._tray_icon = None
        self._tray_thread = None

        # ── 构建 UI ─────────────────────
        self._build_ui()
        self._detect_gateway_async()

        # 应用窗口属性
        self.attributes('-topmost', self._settings.always_on_top)
        self.attributes('-alpha', self._settings.opacity)

        # 窗口关闭 / 最小化
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind('<Unmap>', self._on_minimize)

        # 初始化系统托盘
        self._init_tray_icon()

        # 自动开始监测
        if self._settings.auto_start_monitor:
            self.after(1500, self._auto_start_if_ready)

    def _open_settings(self):
        SettingsDialog(self, self._settings, self._apply_settings)

    def _apply_settings(self, new_settings: AppSettings):
        old = self._settings
        self._settings = new_settings
        save_settings(_PROJECT_ROOT, self._settings)

        global FONT_SCALE
        FONT_SCALE = self._settings.font_scale

        # 应用窗口属性
        self.attributes('-topmost', self._settings.always_on_top)
        self.attributes('-alpha', self._settings.opacity)

        # 判断是否需要重启监控（仅监控参数变化时重启）
        need_restart = (
            old.monitor_external != new_settings.monitor_external
            or old.ping_interval != new_settings.ping_interval
        )

        was_running = self._monitoring

        # 暂停 UI 刷新
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None

        if was_running and need_restart:
            self._stop_monitor(open_record_viewer=False)

        current_gateway = self._gw_var.get() if hasattr(self, '_gw_var') else ""
        self._rebuild_ui(restore_gateway=current_gateway)

        if was_running:
            if need_restart:
                self._start_monitor()
            else:
                # 仅 UI 变化，恢复监测状态而不重置数据
                self._btn_text.set("⏹  停止监测")
                self._btn.config(bg='#c72e2e', activebackground='#d94444')
                self._gw_entry.config(state='disabled')
                if self._gateway_ip:
                    self._gw_graph.title = f"网关 ({self._gateway_ip})"
                if self._settings.monitor_external:
                    self._ext_graph.title = f"外网 ({self._ext_target})"
                else:
                    self._ext_graph.title = "外网监测已关闭"
                self._status_lbl.config(text=" 设置已应用，监测继续中…")
                self._schedule_update()
        else:
            self._status_lbl.config(text=" 设置已应用")

    def _rebuild_ui(self, restore_gateway: str = ""):
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        if restore_gateway:
            self._gw_var.set(restore_gateway)

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self):
        layout_mode = self._settings.layout_mode
        if layout_mode == '图表优先':
            graph_height = 180
            mid_expand = True
            diag_weight = 2
        elif layout_mode == '文本优先':
            graph_height = 100
            mid_expand = False
            diag_weight = 3
        else:
            graph_height = 128
            mid_expand = False
            diag_weight = 2

        # ---------- 顶部控制栏 ----------
        ctrl = tk.Frame(self, bg='#2d2d2d', padx=10, pady=6)
        ctrl.pack(fill='x')

        tk.Label(ctrl, text="网关 IP:", fg=FG_MAIN, bg='#2d2d2d',
                 font=(FONT_FAMILY, sf(9))).pack(side='left')
        self._gw_var = tk.StringVar(value="检测中…")
        self._gw_entry = tk.Entry(ctrl, textvariable=self._gw_var, width=16,
                                  font=('Consolas', sf(10)),
                                  bg='#3c3c3c', fg=FG_MAIN,
                                  insertbackground=FG_MAIN,
                                  relief='flat', bd=2)
        self._gw_entry.pack(side='left', padx=(4, 16))

        tk.Label(ctrl, text="外网目标:", fg=FG_MAIN, bg='#2d2d2d',
                 font=(FONT_FAMILY, sf(9))).pack(side='left')
        self._ext_var = tk.StringVar(value=self.EXTERNAL_TARGETS[0][0])
        ext_combo = ttk.Combobox(ctrl, textvariable=self._ext_var, width=18,
                                 values=[f"{ip}  ({desc})"
                                         for ip, desc in self.EXTERNAL_TARGETS],
                                 state='readonly', font=('Consolas', sf(9)))
        ext_combo.current(min(self._settings.external_target_index, len(self.EXTERNAL_TARGETS) - 1))
        ext_combo.pack(side='left', padx=(4, 16))
        ext_combo.bind('<<ComboboxSelected>>', self._on_ext_changed)

        self._settings_btn = tk.Button(
            ctrl,
            text='⚙ 设置',
            command=self._open_settings,
            font=(FONT_FAMILY, sf(10), 'bold'),
            bg='#4a4a4a',
            fg='#ffffff',
            activebackground='#5a5a5a',
            activeforeground='#ffffff',
            relief='flat',
            padx=14,
            pady=2,
            cursor='hand2',
        )
        self._settings_btn.pack(side='right', padx=(8, 0))
        _add_hover(self._settings_btn, '#5a5a5a')

        # 缩到托盘按钮
        tray_btn = tk.Button(
            ctrl, text='⏷ 托盘',
            command=self._hide_to_tray,
            font=(FONT_FAMILY, sf(10), 'bold'),
            bg='#3a3a5c', fg='#ffffff', activebackground='#4a4a6c',
            activeforeground='#ffffff', relief='flat',
            padx=10, pady=2, cursor='hand2',
        )
        tray_btn.pack(side='right', padx=(8, 0))
        _add_hover(tray_btn, '#4a4a6c')

        # 悬浮窗按钮
        float_btn = tk.Button(
            ctrl, text='📌 悬浮窗',
            command=self._switch_to_float,
            font=(FONT_FAMILY, sf(10), 'bold'),
            bg='#2e5c4f', fg='#ffffff', activebackground='#3a7060',
            activeforeground='#ffffff', relief='flat',
            padx=10, pady=2, cursor='hand2',
        )
        float_btn.pack(side='right', padx=(8, 0))
        _add_hover(float_btn, '#3a7060')

        self._record_btn_text = tk.StringVar(value="●  录制")
        self._record_btn = tk.Button(
            ctrl, textvariable=self._record_btn_text,
            command=self._toggle_recording,
            font=(FONT_FAMILY, sf(10), 'bold'),
            bg='#6a4f00', fg='#ffffff', activebackground='#866200',
            activeforeground='#ffffff',
            relief='flat', padx=14, pady=2, cursor='hand2'
        )
        self._record_btn.pack(side='right', padx=(8, 0))

        self._self_diag_btn = tk.Button(
            ctrl, text='🧠  自我诊断',
            command=self._run_self_diagnosis,
            font=(FONT_FAMILY, sf(10), 'bold'),
            bg='#455a64', fg='#ffffff', activebackground='#556b76',
            activeforeground='#ffffff', relief='flat', padx=14, pady=2,
            cursor='hand2'
        )
        self._self_diag_btn.pack(side='right', padx=(8, 0))
        _add_hover(self._self_diag_btn, '#556b76')

        self._btn_text = tk.StringVar(value="▶  开始监测")
        self._btn = tk.Button(ctrl, textvariable=self._btn_text,
                              command=self._toggle_monitor,
                              font=(FONT_FAMILY, sf(10), 'bold'),
                              bg='#0e639c', fg='#ffffff',
                              activebackground='#1177bb',
                              activeforeground='#ffffff',
                              relief='flat', padx=16, pady=2,
                              cursor='hand2')
        self._btn.pack(side='right')

        speed_row = tk.Frame(self, bg='#252526', padx=10, pady=4)
        speed_row.pack(fill='x')
        tk.Label(speed_row, text='实时网速:', fg=FG_MAIN, bg='#252526',
                 font=(FONT_FAMILY, sf(9), 'bold')).pack(side='left')
        self._speed_down_lbl = tk.Label(speed_row, text='↓ 0 KB/s', fg=GREEN, bg='#252526',
                                        font=('Consolas', sf(10), 'bold'))
        self._speed_down_lbl.pack(side='left', padx=(10, 16))
        self._speed_up_lbl = tk.Label(speed_row, text='↑ 0 KB/s', fg=BLUE, bg='#252526',
                                      font=('Consolas', sf(10), 'bold'))
        self._speed_up_lbl.pack(side='left')
        self._record_hint_lbl = tk.Label(speed_row, text='未录制', fg=FG_DIM, bg='#252526',
                                         font=(FONT_FAMILY, sf(8)))
        self._record_hint_lbl.pack(side='right')

        # ---------- 中部：Ping 图表 ----------
        mid = tk.Frame(self, bg=BG_DARK)
        mid.pack(fill='both' if mid_expand else 'x', expand=mid_expand, padx=8, pady=(6, 0))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # 网关 Ping 面板
        gw_frame = tk.LabelFrame(mid, text=" 网关 Ping ", fg=BLUE,
                                 bg=BG_DARK, font=(FONT_FAMILY, sf(9), 'bold'),
                                 bd=1, relief='groove',
                                 labelanchor='nw')
        gw_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 4))

        self._gw_graph = PingGraph(gw_frame, title="", max_points=self._settings.graph_max_points, height=graph_height)
        self._gw_graph.pack(fill='x', expand=False, padx=4, pady=(2, 0))

        self._gw_stats = StatsBar(gw_frame, [
            ('avg', '延迟'), ('loss', '丢包'), ('jitter', '抖动'),
            ('max', '最大'), ('min', '最小'), ('cnt', '计数'),
        ])
        self._gw_stats.pack(fill='x', padx=4, pady=4)

        # 外网 Ping 面板
        ext_frame = tk.LabelFrame(mid, text=" 外网 Ping ", fg=BLUE,
                                  bg=BG_DARK, font=(FONT_FAMILY, sf(9), 'bold'),
                                  bd=1, relief='groove',
                                  labelanchor='nw')
        ext_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 0))

        self._ext_graph = PingGraph(ext_frame, title="", max_points=self._settings.graph_max_points, height=graph_height)
        self._ext_graph.pack(fill='x', expand=False, padx=4, pady=(2, 0))

        self._ext_stats = StatsBar(ext_frame, [
            ('avg', '延迟'), ('loss', '丢包'), ('jitter', '抖动'),
            ('max', '最大'), ('min', '最小'), ('cnt', '计数'),
        ])
        self._ext_stats.pack(fill='x', padx=4, pady=4)

        # ---------- 下部：WiFi + 诊断 ----------
        bot = tk.Frame(self, bg=BG_DARK)
        bot.pack(fill='both', expand=True, padx=8, pady=(4, 0))
        bot.columnconfigure(0, weight=1)
        bot.columnconfigure(1, weight=diag_weight)
        bot.rowconfigure(0, weight=1)

        # WiFi 面板
        wifi_frame = tk.LabelFrame(bot, text=" WiFi 信息 ", fg=BLUE,
                                   bg=BG_DARK, font=(FONT_FAMILY, sf(9), 'bold'),
                                   bd=1, relief='groove')
        wifi_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 4), pady=0)

        wifi_inner = tk.Frame(wifi_frame, bg=BG_DARK)
        wifi_inner.pack(fill='both', expand=True, padx=8, pady=4)

        self._wifi_labels: dict[str, tk.Label] = {}
        wifi_items = [
            ('ssid',    'SSID'),
            ('desc',    '网卡'),
            ('radio',   '频段'),
            ('channel', '频道'),
            ('rx',      '接收速率'),
            ('tx',      '发送速率'),
            ('dl',      '下载速率'),
            ('ul',      '上传速率'),
        ]
        for i, (key, text) in enumerate(wifi_items):
            tk.Label(wifi_inner, text=f"{text}:", fg=FG_DIM, bg=BG_DARK,
                     font=(FONT_FAMILY, sf(8)), anchor='e', width=8
                     ).grid(row=i, column=0, sticky='e', pady=1)
            lbl = tk.Label(wifi_inner, text="--", fg=FG_MAIN, bg=BG_DARK,
                           font=(FONT_FAMILY, sf(8)), anchor='w')
            lbl.grid(row=i, column=1, sticky='w', padx=(4, 0), pady=1)
            self._wifi_labels[key] = lbl

        # 信号条
        r = len(wifi_items)
        tk.Label(wifi_inner, text="信号:", fg=FG_DIM, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(8)), anchor='e', width=8
                 ).grid(row=r, column=0, sticky='e', pady=1)
        self._signal_bar = SignalBar(wifi_inner, width=160)
        self._signal_bar.grid(row=r, column=1, sticky='ew', padx=(4, 0), pady=1)
        wifi_inner.columnconfigure(1, weight=1)

        # 诊断面板
        diag_frame = tk.LabelFrame(bot, text=" 📊 诊断结果 ", fg=BLUE,
                                   bg=BG_DARK, font=(FONT_FAMILY, sf(9), 'bold'),
                                   bd=1, relief='groove')
        diag_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 0), pady=0)

        diag_inner = tk.Frame(diag_frame, bg=BG_DARK)
        diag_inner.pack(fill='both', expand=True, padx=10, pady=6)

        self._diag_title = tk.Label(
            diag_inner, text="点击「开始监测」启动诊断",
            fg=FG_DIM, bg=BG_DARK,
            font=(FONT_FAMILY, sf(12), 'bold'), anchor='w', wraplength=620,
        )
        self._diag_title.pack(fill='x', anchor='w')

        sep1 = tk.Frame(diag_inner, bg=BORDER, height=1)
        sep1.pack(fill='x', pady=4)

        self._diag_details = tk.Label(
            diag_inner, text="", fg=FG_DIM, bg=BG_DARK,
            font=(FONT_FAMILY, sf(8)), anchor='nw', justify='left', wraplength=620,
        )
        self._diag_details.pack(fill='x', anchor='w')

        tk.Label(diag_inner, text="建议:", fg=BLUE, bg=BG_DARK,
                 font=(FONT_FAMILY, sf(8), 'bold'), anchor='w').pack(fill='x', pady=(6, 0))

        self._diag_suggest = tk.Label(
            diag_inner, text="", fg=FG_MAIN, bg=BG_DARK,
            font=(FONT_FAMILY, sf(8)), anchor='nw', justify='left', wraplength=620,
        )
        self._diag_suggest.pack(fill='x', anchor='w')

        # ---------- 状态栏 ----------
        status = tk.Frame(self, bg='#007acc', height=22)
        status.pack(fill='x', side='bottom')
        self._status_lbl = tk.Label(status, text=" 就绪", fg='#ffffff',
                                    bg='#007acc', font=(FONT_FAMILY, sf(8)),
                                    anchor='w')
        self._status_lbl.pack(side='left', padx=6)
        self._timer_lbl = tk.Label(status, text="", fg='#ffffff',
                                   bg='#007acc', font=('Consolas', sf(8)),
                                   anchor='e')
        self._timer_lbl.pack(side='right', padx=6)

    # ==================================================================
    # 事件处理
    # ==================================================================
    def _detect_gateway_async(self):
        """在后台检测默认网关"""
        import threading

        def _do():
            gw = detect_gateway()
            self.after(0, lambda: self._gw_var.set(gw or "192.168.1.1"))

        threading.Thread(target=_do, daemon=True).start()

    def _auto_start_if_ready(self):
        """自动开始监测（等待网关检测完成）。"""
        gw = self._gw_var.get().strip()
        if gw and gw != "检测中…":
            self._start_monitor()
        else:
            self.after(500, self._auto_start_if_ready)

    def _on_ext_changed(self, _event=None):
        sel = self._ext_var.get()
        ip = sel.split()[0] if sel else self.EXTERNAL_TARGETS[0][0]
        self._ext_target = ip
        # 保存选择的外网目标
        for i, (target_ip, _) in enumerate(self.EXTERNAL_TARGETS):
            if target_ip == ip:
                self._settings.external_target_index = i
                save_settings(_PROJECT_ROOT, self._settings)
                break

    def _toggle_monitor(self):
        if self._monitoring:
            self._stop_monitor()
        else:
            self._start_monitor()

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording(open_viewer=True)
        else:
            self._start_recording()

    def _run_self_diagnosis(self):
        if not self._monitoring:
            self._status_lbl.config(text=' 请先开始监测，再执行自我诊断')
            return

        gw_stats = self._gw_monitor.get_stats() if self._gw_monitor else None
        ext_stats = self._ext_monitor.get_stats() if self._ext_monitor else None
        wifi_info = self._wifi_monitor.get_info()

        result = self._self_diag_engine.evaluate(
            gw_stats=gw_stats,
            ext_stats=ext_stats,
            wifi_signal_series=list(self._wifi_signal_series),
            gw_latency_series=list(self._gw_latency_series),
            wifi_connected=bool(wifi_info and wifi_info.connected),
        )

        self._diag_title.config(text=result.title, fg=BLUE)
        self._diag_details.config(text='\n'.join([
            f"网卡侧嫌疑: {result.adapter_score}%",
            f"路由器/上游侧嫌疑: {result.router_score}%",
            "",
            "证据:",
            *[f"- {x}" for x in result.evidence],
        ]))
        self._diag_suggest.config(text='\n'.join([f"• {s}" for s in result.suggestions]))
        self._status_lbl.config(text=' 已完成自我诊断评分（无额外设备）')
        self._manual_diag_override_until = time.time() + 20

    def _start_recording(self):
        if not self._monitoring:
            self._status_lbl.config(text=' 请先开始监测再录制')
            return
        if self._recording:
            return
        try:
            rec_dir = os.path.join(_PROJECT_ROOT, 'recordings')
            os.makedirs(rec_dir, exist_ok=True)
            name = datetime.now().strftime('record_%Y%m%d_%H%M%S.csv')
            path = os.path.join(rec_dir, name)
            fp = open(path, 'w', encoding='utf-8-sig', newline='')
            writer = csv.writer(fp)
            writer.writerow([
                'timestamp', 'elapsed_s',
                'gw_avg_latency', 'gw_loss_rate',
                'ext_avg_latency', 'ext_loss_rate',
                'wifi_signal',
                'download_kbps', 'upload_kbps',
            ])
            self._record_fp = fp
            self._record_writer = writer
            self._record_file_path = path
            self._record_points = 0
            self._recording = True
            self._record_btn_text.set('■  停止录制')
            self._record_btn.config(bg='#b54700', activebackground='#ca5b0f')
            self._record_hint_lbl.config(text=f'录制中: {os.path.basename(path)}', fg=YELLOW)
            self._status_lbl.config(text=' 正在录制网络变化…')
        except Exception as e:
            self._status_lbl.config(text=f' 录制启动失败: {e}')

    def _stop_recording(self, open_viewer: bool):
        if not self._recording:
            return
        self._recording = False
        self._record_btn_text.set('●  录制')
        self._record_btn.config(bg='#6a4f00', activebackground='#866200')

        path = self._record_file_path
        if self._record_fp:
            try:
                self._record_fp.flush()
                self._record_fp.close()
            except Exception:
                pass
        self._record_fp = None
        self._record_writer = None
        self._record_hint_lbl.config(text='未录制', fg=FG_DIM)
        self._status_lbl.config(text=f' 录制结束: {self._record_points} 个点')

        if open_viewer and path and os.path.exists(path):
            RecordViewer(self, path)

    def _start_monitor(self):
        gw = self._gw_var.get().strip()
        if not gw or gw == "检测中…":
            gw = "192.168.1.1"
            self._gw_var.set(gw)
        self._gateway_ip = gw

        ext = self._ext_target
        self._gw_monitor = PingMonitor(gw, history_size=120, interval=self._settings.ping_interval)
        self._ext_monitor = PingMonitor(ext, history_size=120, interval=self._settings.ping_interval) if self._settings.monitor_external else None

        self._gw_monitor.start()
        if self._ext_monitor:
            self._ext_monitor.start()
        self._wifi_monitor.start()
        self._speed_monitor.start()

        self._wifi_signal_series.clear()
        self._gw_latency_series.clear()

        self._monitoring = True
        self._start_time = time.time()
        self._btn_text.set("⏹  停止监测")
        self._btn.config(bg='#c72e2e', activebackground='#d94444')
        self._gw_entry.config(state='disabled')
        self._status_lbl.config(text=" 监测中…")

        # 更新图表标题
        self._gw_graph.title = f"网关 ({gw})"
        if self._settings.monitor_external:
            self._ext_graph.title = f"外网 ({ext})"
        else:
            self._ext_graph.title = "外网监测已关闭（可在设置中开启）"
            self._update_ping_panel(self._ext_graph, self._ext_stats, None)

        self._schedule_update()

    def _stop_monitor(self, open_record_viewer=True):
        self._monitoring = False
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None

        if self._recording:
            self._stop_recording(open_viewer=open_record_viewer)

        if self._gw_monitor:
            self._gw_monitor.stop()
        if self._ext_monitor:
            self._ext_monitor.stop()
        self._wifi_monitor.stop()
        self._speed_monitor.stop()

        self._btn_text.set("▶  开始监测")
        self._btn.config(bg='#0e639c', activebackground='#1177bb')
        self._gw_entry.config(state='normal')
        self._status_lbl.config(text=" 已停止")

    # ==================================================================
    # 定时刷新
    # ==================================================================
    def _schedule_update(self):
        if not self._monitoring:
            return
        self._refresh_ui()
        self._update_job = self.after(800, self._schedule_update)

    def _refresh_ui(self):
        gw_stats = self._gw_monitor.get_stats() if self._gw_monitor else None
        if self._settings.monitor_external and self._ext_monitor:
            ext_stats = self._ext_monitor.get_stats()
        else:
            ext_stats = self._ext_fallback_stats(gw_stats)
        wifi_info = self._wifi_monitor.get_info()
        speed_info = self._speed_monitor.get_info()

        # ── Ping 图表 & 统计 ──
        self._update_ping_panel(self._gw_graph, self._gw_stats, gw_stats)
        self._update_ping_panel(self._ext_graph, self._ext_stats, ext_stats)

        # ── WiFi 信息 ──
        self._update_wifi(wifi_info, speed_info)

        # ── 实时网速 ──
        self._update_speed(speed_info)

        # ── 诊断 ──
        if time.time() > self._manual_diag_override_until:
            diag = self._diag_engine.diagnose(gw_stats, ext_stats, wifi_info)
            self._update_diagnosis(diag)

        # ── 自诊断采样缓存 ──
        self._cache_self_diag_samples(gw_stats, wifi_info)

        if self._recording:
            self._record_snapshot(gw_stats, ext_stats, wifi_info, speed_info)

        # ── 计时器 ──
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        self._timer_lbl.config(text=f"运行时间 {h:02d}:{m:02d}:{s:02d}")

        # ── 更新悬浮窗 ──
        if self._mini_float:
            try:
                self._mini_float.update_stats(gw_stats, ext_stats, wifi_info, speed_info)
            except Exception:
                pass

    def _cache_self_diag_samples(self, gw_stats, wifi_info: WifiInfo):
        if wifi_info and wifi_info.connected:
            self._wifi_signal_series.append(float(wifi_info.signal_percent))
        else:
            self._wifi_signal_series.append(0.0)

        latency = -1.0
        if gw_stats:
            graph_data = gw_stats.get('graph_data', [])
            for v in reversed(graph_data):
                if v >= 0:
                    latency = float(v)
                    break
        self._gw_latency_series.append(latency)

    # ------------------------------------------------------------------
    @staticmethod
    def _update_ping_panel(graph: PingGraph, bar: StatsBar, stats):
        if not stats:
            graph.update_data([])
            bar.set('avg', '--')
            bar.set('loss', '--')
            bar.set('jitter', '--')
            bar.set('max', '--')
            bar.set('min', '--')
            bar.set('cnt', '--')
            return
        graph.update_data(stats['graph_data'])
        bar.set('avg', f"{stats['avg_latency']:.1f} ms",
                _latency_color(stats['avg_latency']))
        bar.set('loss', f"{stats['loss_rate']:.1f}%",
                _loss_color(stats['loss_rate']))
        bar.set('jitter', f"{stats['jitter']:.1f} ms")
        bar.set('max', f"{stats['max_latency']:.0f} ms")
        bar.set('min', f"{stats['min_latency']:.0f} ms")
        bar.set('cnt', f"{stats['total']}")

    def _update_wifi(self, info: WifiInfo, speed_info):
        if info.connected:
            self._wifi_labels['ssid'].config(text=info.ssid or "--", fg=FG_MAIN)
            self._wifi_labels['desc'].config(text=info.description or "--", fg=FG_MAIN)
            self._wifi_labels['radio'].config(text=info.radio_type or "--", fg=FG_MAIN)
            self._wifi_labels['channel'].config(text=info.channel or "--", fg=FG_MAIN)
            self._wifi_labels['rx'].config(text=info.receive_rate or "--", fg=FG_MAIN)
            self._wifi_labels['tx'].config(text=info.transmit_rate or "--", fg=FG_MAIN)
            self._wifi_labels['dl'].config(text=f"{_format_speed(speed_info.download_bps)}", fg=GREEN)
            self._wifi_labels['ul'].config(text=f"{_format_speed(speed_info.upload_bps)}", fg=BLUE)
            self._signal_bar.set_value(info.signal_percent)
        else:
            for lbl in self._wifi_labels.values():
                lbl.config(text="--", fg=FG_MAIN)
            self._signal_bar.set_value(0)
            if info.error:
                self._wifi_labels['ssid'].config(text=info.error, fg=ORANGE)
            if info.description:
                self._wifi_labels['desc'].config(text=info.description, fg=FG_MAIN)

    def _update_speed(self, speed_info):
        self._speed_down_lbl.config(text=f"↓ {_format_speed(speed_info.download_bps)}")
        self._speed_up_lbl.config(text=f"↑ {_format_speed(speed_info.upload_bps)}")

    def _record_snapshot(self, gw_stats, ext_stats, wifi_info: WifiInfo, speed_info):
        if not self._record_writer:
            return
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elapsed = time.time() - self._start_time
        gw_avg = (gw_stats or {}).get('avg_latency', 0)
        gw_loss = (gw_stats or {}).get('loss_rate', 0)
        ext_avg = (ext_stats or {}).get('avg_latency', 0)
        ext_loss = (ext_stats or {}).get('loss_rate', 0)
        wifi_signal = wifi_info.signal_percent if wifi_info and wifi_info.connected else 0
        dl_kbps = speed_info.download_bps / 1024.0
        ul_kbps = speed_info.upload_bps / 1024.0
        self._record_writer.writerow([
            ts,
            f'{elapsed:.2f}',
            f'{gw_avg:.2f}',
            f'{gw_loss:.2f}',
            f'{ext_avg:.2f}',
            f'{ext_loss:.2f}',
            f'{wifi_signal:.0f}',
            f'{dl_kbps:.2f}',
            f'{ul_kbps:.2f}',
        ])
        self._record_points += 1

    @staticmethod
    def _ext_fallback_stats(gw_stats):
        # 关闭外网监测时提供占位，保证下游诊断与录制流程可运行
        base_total = (gw_stats or {}).get('total', 0)
        return {
            'total': base_total,
            'success': base_total,
            'loss': 0,
            'loss_rate': 0.0,
            'avg_latency': 0.0,
            'max_latency': 0.0,
            'min_latency': 0.0,
            'jitter': 0.0,
            'graph_data': [],
        }

    def _update_diagnosis(self, diag: DiagnosisResult):
        color_map = {
            DiagnosisResult.GOOD:     GREEN,
            DiagnosisResult.WARNING:  YELLOW,
            DiagnosisResult.CRITICAL: RED,
            DiagnosisResult.UNKNOWN:  FG_DIM,
        }
        c = color_map.get(diag.severity, FG_DIM)
        self._diag_title.config(text=diag.title, fg=c)
        self._diag_details.config(text="\n".join(diag.details))
        self._diag_suggest.config(
            text="\n".join(f"• {s}" for s in diag.suggestions))

    # ==================================================================
    # 关闭
    # ==================================================================
    def _on_close(self):
        """完全退出程序。"""
        # 取消 UI 刷新
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None
        self._monitoring = False

        # 关闭悬浮窗
        if self._mini_float:
            try:
                self._mini_float.destroy()
            except Exception:
                pass
            self._mini_float = None

        # 关闭托盘图标
        self._destroy_tray()

        # 刷新录制文件
        if self._recording:
            self._stop_recording(open_viewer=False)

        # 快速通知所有监控线程停止（守护线程会随进程退出）
        for mon in [self._gw_monitor, self._ext_monitor, self._wifi_monitor, self._speed_monitor]:
            if mon:
                mon.stop(join=False)

        self.destroy()

    def _on_minimize(self, event):
        """窗口最小化时缩到托盘。"""
        if event.widget is not self:
            return
        # 仅当真正最小化（iconic）时
        if self.state() == 'iconic':
            self.after(10, self._hide_to_tray)

    # ==================================================================
    # 系统托盘
    # ==================================================================
    def _create_tray_image(self) -> 'Image.Image':
        """生成托盘图标图像（一个深色圆底 + 闪电符号）。"""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 背景圆
        draw.ellipse([2, 2, size - 3, size - 3], fill='#0f3460', outline='#4ec9b0', width=2)
        # 闪电
        try:
            font = ImageFont.truetype('segoeui.ttf', 36)
        except Exception:
            font = ImageFont.load_default()
        draw.text((size // 2, size // 2), '⚡', fill='#4ec9b0', font=font, anchor='mm')
        return img

    def _init_tray_icon(self):
        """在后台线程中启动系统托盘图标。"""
        if not _HAS_TRAY:
            return

        def _on_show(icon, item):
            self.after(0, self._restore_from_tray)

        def _on_float(icon, item):
            self.after(0, self._toggle_mini_float)

        def _on_quit(icon, item):
            self.after(0, self._on_close)

        menu = pystray.Menu(
            pystray.MenuItem('显示主窗口', _on_show, default=True),
            pystray.MenuItem('迷你悬浮窗', _on_float),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', _on_quit),
        )

        image = self._create_tray_image()
        self._tray_icon = pystray.Icon('NetBugger', image, 'NetBugger', menu)
        self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        self._tray_thread.start()

    def _destroy_tray(self):
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

    def _hide_to_tray(self):
        """隐藏主窗口到系统托盘。"""
        self.withdraw()

    def _restore_from_tray(self):
        """从托盘恢复主窗口。"""
        self.deiconify()
        self.state('normal')
        self.lift()
        self.focus_force()

    # ==================================================================
    # 迷你悬浮窗
    # ==================================================================
    def _toggle_mini_float(self):
        """切换迷你悬浮窗的显示/隐藏。"""
        if self._mini_float:
            self._close_mini_float()
        else:
            self._open_mini_float()

    def _open_mini_float(self):
        if self._mini_float:
            return
        self._mini_float = MiniFloatWindow(
            self,
            on_restore=self._float_restore,
            on_close=self._close_mini_float,
        )

    def _close_mini_float(self):
        if self._mini_float:
            try:
                self._mini_float.destroy()
            except Exception:
                pass
            self._mini_float = None

    def _float_restore(self):
        """从悬浮窗还原主窗口。"""
        self._close_mini_float()
        self._restore_from_tray()

    def _switch_to_float(self):
        """缩小主窗口到悬浮窗模式。"""
        self._open_mini_float()
        self.withdraw()


# ======================================================================
# 工具函数
# ======================================================================

def _latency_color(ms: float) -> str:
    if ms < 10:
        return GREEN
    if ms < 50:
        return YELLOW
    if ms < 100:
        return ORANGE
    return RED


def _loss_color(pct: float) -> str:
    if pct < 1:
        return GREEN
    if pct < 5:
        return YELLOW
    if pct < 10:
        return ORANGE
    return RED


def _format_speed(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    kb = bps / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB/s"
    mb = kb / 1024.0
    return f"{mb:.2f} MB/s"
