"""
WiFi 监控模块
通过 netsh 采集无线网卡信息（信号强度、SSID、频段等），
并自动检测默认网关。
"""

import subprocess
import re
import threading
import time


def _decode_output(raw) -> str:
    """安全解码子进程输出，兼容中文 Windows (GBK/CP936)"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    # raw 是 bytes，尝试多种编码
    for enc in ('utf-8', 'gbk', 'cp936', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def detect_gateway():
    """
    自动检测默认网关 IP 地址。

    优先使用 ipconfig 解析，兼容中英文 Windows。
    """
    flags = 0
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        flags = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.run(
            ['ipconfig'],
            capture_output=True, timeout=10,
            creationflags=flags,
        )
        stdout = _decode_output(proc.stdout)

        # 按适配器段落拆分，优先匹配 WLAN / Wi-Fi / Wireless 适配器的网关
        sections = re.split(r'\r?\n(?=\S)', stdout)
        wlan_gw = None
        fallback_gw = None
        ipv4_re = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')
        for sec in sections:
            # 找到 "默认网关" 行及其后续的续行，提取所有 IPv4 地址
            gw_block = re.search(
                r'(?:Default Gateway|默认网关)[\s.]*(:.+(?:\r?\n\s+.+)*)',
                sec, re.I,
            )
            if not gw_block:
                continue
            gw_ips = ipv4_re.findall(gw_block.group(1))
            gw = None
            for ip in gw_ips:
                if ip != '0.0.0.0':
                    gw = ip
                    break
            if not gw:
                continue
            # 判断是否为无线适配器段落
            if re.search(r'WLAN|Wi-?Fi|Wireless|无线', sec, re.I):
                wlan_gw = gw
                break
            if fallback_gw is None:
                fallback_gw = gw
        if wlan_gw:
            return wlan_gw
        if fallback_gw:
            return fallback_gw
    except Exception:
        pass

    # 兜底：尝试 route print
    try:
        proc = subprocess.run(
            ['route', 'print', '0.0.0.0'],
            capture_output=True, timeout=10,
            creationflags=flags,
        )
        stdout = _decode_output(proc.stdout)
        m = re.search(
            r'0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})',
            stdout,
        )
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


class WifiInfo:
    """WiFi 连接信息数据类"""

    def __init__(self):
        self.connected: bool = False
        self.ssid: str = ""
        self.signal_percent: int = 0
        self.description: str = ""       # 网卡名称
        self.radio_type: str = ""        # 802.11ax / ac …
        self.channel: str = ""
        self.receive_rate: str = ""      # Mbps
        self.transmit_rate: str = ""     # Mbps
        self.bssid: str = ""
        self.auth: str = ""
        self.error: str | None = None


class WifiMonitor:
    """
    周期性采集 WiFi 状态信息。

    在后台线程中调用 ``netsh wlan show interfaces`` 并解析输出。
    """

    def __init__(self, interval=3.0):
        self.interval = interval
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._info = WifiInfo()

        self._creation_flags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            self._creation_flags = subprocess.CREATE_NO_WINDOW

    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, join=True):
        self._running = False
        self._stop_event.set()
        if join and self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def get_info(self) -> WifiInfo:
        with self._lock:
            return self._info

    # ------------------------------------------------------------------
    def _loop(self):
        while self._running:
            info = self._query()
            with self._lock:
                self._info = info
            self._stop_event.wait(self.interval)

    def _query(self) -> WifiInfo:
        info = WifiInfo()
        try:
            proc = subprocess.run(
                ['netsh', 'wlan', 'show', 'interfaces'],
                capture_output=True, timeout=10,
                creationflags=self._creation_flags,
            )
            out = _decode_output(proc.stdout)
            if not out.strip():
                info.error = "未检测到无线网卡或 WiFi 服务未运行"
                return info

            # 连接状态
            m = re.search(r'(?:State|状态)\s*:\s*(.+)', out, re.I)
            if m:
                state = m.group(1).strip().lower()
                info.connected = state in ('connected', '已连接')

            if not info.connected:
                info.error = "WiFi 未连接（可能使用有线网络）"
                # 仍然解析网卡名称
                m = re.search(r'(?:Description|描述|说明)\s*:\s*(.+)', out, re.I)
                if m:
                    info.description = m.group(1).strip()
                return info

            # 逐项解析（兼容中英文 Windows 所有字段名变体）
            patterns = {
                'ssid':          r'(?:^|\b)SSID\s*:\s*(.+)',
                'signal_percent': r'(?:Signal|信号)\s*:\s*(\d+)\s*%',
                'description':   r'(?:Description|描述|说明)\s*:\s*(.+)',
                'radio_type':    r'(?:Radio type|无线电类型)\s*:\s*(.+)',
                'channel':       r'(?:Channel|频道|通道)\s*:\s*(\S+)',
                'receive_rate':  r'(?:Receive rate|接收速率)[^:]*:\s*(.+)',
                'transmit_rate': r'(?:Transmit rate|传输速率)[^:]*:\s*(.+)',
                'bssid':         r'(?:AP\s*)?BSSID\s*:\s*(.+)',
                'auth':          r'(?:Authentication|身份验证)\s*:\s*(.+)',
            }

            for attr, pat in patterns.items():
                m = re.search(pat, out, re.I)
                if m:
                    val = m.group(1).strip()
                    if attr == 'signal_percent':
                        setattr(info, attr, int(val))
                    else:
                        setattr(info, attr, val)

            return info

        except Exception as e:
            info.error = f"查询 WiFi 信息失败: {e}"
            return info
