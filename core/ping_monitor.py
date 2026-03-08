"""
Ping 监控模块
持续 ping 目标地址并收集延迟、丢包、抖动等统计数据
"""

import platform
import subprocess
import re
import threading
import time
import statistics
from collections import deque


class PingResult:
    """单次 Ping 的结果"""
    __slots__ = ('target', 'latency', 'success', 'error', 'timestamp')

    def __init__(self, target, latency=None, success=False, error=None):
        self.target = target
        self.latency = latency   # ms, None if failed
        self.success = success
        self.error = error
        self.timestamp = time.time()


class PingMonitor:
    """
    持续 Ping 目标地址并收集统计数据。

    在后台线程里以固定间隔执行 ping，
    并将结果保存在一个固定长度的环形缓冲区中。
    """

    def __init__(self, target, history_size=120, interval=1.0):
        self.target = target
        self.interval = interval
        self.history = deque(maxlen=history_size)
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Windows 专用：隐藏控制台窗口
        self._creation_flags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            self._creation_flags = subprocess.CREATE_NO_WINDOW
        self._platform = platform.system().lower()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self.history.clear()
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._thread.start()

    def stop(self, join=True):
        self._running = False
        self._stop_event.set()
        if join and self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    @property
    def is_running(self):
        return self._running

    # ------------------------------------------------------------------
    # 内部循环
    # ------------------------------------------------------------------
    def _ping_loop(self):
        while self._running:
            t0 = time.time()
            result = self._do_ping()
            with self._lock:
                self.history.append(result)
            elapsed = time.time() - t0
            sleep_time = max(0.0, self.interval - elapsed)
            if sleep_time > 0 and self._running:
                self._stop_event.wait(sleep_time)

    def _do_ping(self):
        """执行一次 ping 并解析结果（兼容 Windows / macOS）。"""
        try:
            cmd = self._build_ping_command()
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=self._creation_flags,
            )
            output = '\n'.join(x for x in (proc.stdout, proc.stderr) if x)

            latency = self._parse_latency(output)
            if latency is not None:
                return PingResult(self.target, latency=latency, success=True)

            # 备用判断：有 TTL 或命令返回成功通常表示收到了回复
            if proc.returncode == 0 and re.search(r'TTL\s*=|ttl=', output, re.IGNORECASE):
                return PingResult(self.target, latency=1, success=True)

            if proc.returncode == 0:
                return PingResult(self.target, latency=1, success=True)

            return PingResult(self.target, success=False, error="请求超时")

        except subprocess.TimeoutExpired:
            return PingResult(self.target, success=False, error="执行超时")
        except Exception as e:
            return PingResult(self.target, success=False, error=str(e))

    def _build_ping_command(self):
        if self._platform == 'windows':
            return ['ping', '-n', '1', '-w', '2000', self.target]
        return ['ping', '-c', '1', self.target]

    @staticmethod
    def _parse_latency(output: str):
        m = re.search(r'(?:time|时间)\s*[=<]?\s*(\d+(?:\.\d+)?)\s*ms', output, re.IGNORECASE)
        if not m:
            return None
        return max(1, int(round(float(m.group(1)))))

    # ------------------------------------------------------------------
    # 统计数据
    # ------------------------------------------------------------------
    def get_stats(self):
        """
        返回当前统计数据字典，若无数据返回 None。

        Keys:
            total, success, loss, loss_rate,
            avg_latency, max_latency, min_latency, jitter,
            graph_data   — 最近 60 个数据点 (>=0 正常延迟, -1 丢包)
        """
        with self._lock:
            if not self.history:
                return None
            results = list(self.history)

        total = len(results)
        successes = [r for r in results if r.success]
        loss_count = total - len(successes)
        loss_rate = (loss_count / total * 100) if total > 0 else 0.0

        latencies = [r.latency for r in successes if r.latency is not None]

        if latencies:
            avg_latency = statistics.mean(latencies)
            max_latency = max(latencies)
            min_latency = min(latencies)
            jitter = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        else:
            avg_latency = max_latency = min_latency = jitter = 0.0

        # 图表数据：-1 表示丢包
        graph_data = []
        for r in results[-60:]:
            if r.success and r.latency is not None:
                graph_data.append(r.latency)
            else:
                graph_data.append(-1)

        return {
            'total': total,
            'success': len(successes),
            'loss': loss_count,
            'loss_rate': loss_rate,
            'avg_latency': avg_latency,
            'max_latency': max_latency,
            'min_latency': min_latency,
            'jitter': jitter,
            'graph_data': graph_data,
        }
