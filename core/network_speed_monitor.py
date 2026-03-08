"""
实时网速监控模块（Windows）
通过 `netstat -e` 获取累计收发字节，按时间差计算实时网速。
"""

import re
import subprocess
import threading
import time


class NetworkSpeedInfo:
    def __init__(self):
        self.download_bps: float = 0.0
        self.upload_bps: float = 0.0
        self.error: str | None = None


class NetworkSpeedMonitor:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._info = NetworkSpeedInfo()

        self._prev_recv: int | None = None
        self._prev_sent: int | None = None
        self._prev_ts: float | None = None

        self._creation_flags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            self._creation_flags = subprocess.CREATE_NO_WINDOW

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._prev_recv = None
        self._prev_sent = None
        self._prev_ts = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, join=True):
        self._running = False
        self._stop_event.set()
        if join and self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def get_info(self) -> NetworkSpeedInfo:
        with self._lock:
            return self._info

    def _loop(self):
        while self._running:
            info = self._query()
            with self._lock:
                self._info = info
            self._stop_event.wait(self.interval)

    def _query(self) -> NetworkSpeedInfo:
        info = NetworkSpeedInfo()
        try:
            recv, sent = self._read_total_bytes()
            now = time.time()
            if self._prev_recv is not None and self._prev_sent is not None and self._prev_ts is not None:
                dt = max(0.001, now - self._prev_ts)
                info.download_bps = max(0.0, (recv - self._prev_recv) / dt)
                info.upload_bps = max(0.0, (sent - self._prev_sent) / dt)

            self._prev_recv = recv
            self._prev_sent = sent
            self._prev_ts = now
            return info

        except Exception as e:
            info.error = str(e)
            return info

    def _read_total_bytes(self) -> tuple[int, int]:
        proc = subprocess.run(
            ['netstat', '-e'],
            capture_output=True,
            timeout=8,
            creationflags=self._creation_flags,
        )
        out = _decode_output(proc.stdout)
        if not out.strip():
            raise RuntimeError('netstat 输出为空')

        # 优先匹配包含“Bytes/字节”的行
        for line in out.splitlines():
            if re.search(r'Bytes|字节', line, re.I):
                nums = _extract_numbers(line)
                if len(nums) >= 2:
                    return nums[0], nums[1]

        # 兜底：找第一行含 2 个以上数字且数值较大（排除包计数行的低值干扰）
        candidates = []
        for line in out.splitlines():
            nums = _extract_numbers(line)
            if len(nums) >= 2:
                candidates.append((line, nums[0], nums[1]))
        for _line, a, b in candidates:
            if a > 1024 or b > 1024:
                return a, b

        raise RuntimeError('无法从 netstat 输出解析字节统计')


def _extract_numbers(line: str) -> list[int]:
    nums = re.findall(r'[0-9][0-9,]*', line)
    out = []
    for n in nums:
        out.append(int(n.replace(',', '')))
    return out


def _decode_output(raw) -> str:
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    for enc in ('utf-8', 'gbk', 'cp936', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')
