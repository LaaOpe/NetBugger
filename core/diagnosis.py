"""
网络诊断引擎
综合分析网关 Ping、外网 Ping、WiFi 信号数据，
判断网络卡顿 / 丢包的根因是无线网卡还是路由器。
"""


class DiagnosisResult:
    """诊断结果"""

    # 严重程度等级
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

    def __init__(self, severity: str, title: str,
                 details: list[str], suggestions: list[str]):
        self.severity = severity
        self.title = title
        self.details = details          # 数据摘要
        self.suggestions = suggestions  # 建议列表


class DiagnosisEngine:
    """
    诊断引擎：根据一系列阈值和规则给出诊断结论。

    判断逻辑概述
    ─────────────────────────────────────────
    网关丢包高 + 信号弱       → 无线信号 / 距离问题
    网关丢包高 + 信号正常     → 网卡驱动 / 路由器 WiFi 模块
    网关正常   + 外网丢包高   → 路由器 WAN 口 / 运营商线路
    网关抖动大                → 无线干扰
    全部正常                  → 网络健康
    """

    # ── 阈值 ──────────────────────────────
    GW_LOSS_WARN   = 3.0     # 网关丢包警告阈值 (%)
    GW_LOSS_CRIT   = 10.0    # 网关丢包严重阈值 (%)
    EXT_LOSS_WARN  = 5.0     # 外网丢包警告阈值 (%)
    EXT_LOSS_CRIT  = 15.0    # 外网丢包严重阈值 (%)
    GW_LAT_WARN    = 15      # 网关延迟警告 (ms)
    GW_LAT_CRIT    = 50      # 网关延迟严重 (ms)
    GW_JITTER_WARN = 5       # 网关抖动警告 (ms)
    GW_JITTER_CRIT = 20      # 网关抖动严重 (ms)
    SIG_LOW        = 40      # 信号弱 (%)
    SIG_MED        = 60      # 信号中等 (%)
    MIN_SAMPLES    = 10      # 最少采样数

    # ------------------------------------------------------------------
    def diagnose(self, gateway_stats, external_stats, wifi_info):
        """
        执行综合诊断。

        Parameters
        ----------
        gateway_stats : dict | None
            ``PingMonitor.get_stats()`` 网关
        external_stats : dict | None
            ``PingMonitor.get_stats()`` 外网
        wifi_info : WifiInfo | None

        Returns
        -------
        DiagnosisResult
        """

        # ── 数据不足 ────────────────────────
        if not gateway_stats or not external_stats:
            return DiagnosisResult(
                DiagnosisResult.UNKNOWN,
                "⏳ 数据收集中…",
                ["正在收集网络数据，请稍候"],
                ["请等待至少 10 秒以获得准确诊断"],
            )

        if gateway_stats['total'] < self.MIN_SAMPLES:
            return DiagnosisResult(
                DiagnosisResult.UNKNOWN,
                "⏳ 数据收集中…",
                [f"已收集 {gateway_stats['total']}/{self.MIN_SAMPLES} 个样本"],
                ["请等待数据收集完成"],
            )

        # ── 提取指标 ────────────────────────
        gw_loss    = gateway_stats['loss_rate']
        gw_lat     = gateway_stats['avg_latency']
        gw_jitter  = gateway_stats['jitter']
        ext_loss   = external_stats['loss_rate']
        ext_lat    = external_stats['avg_latency']

        wifi_ok     = wifi_info is not None and wifi_info.connected
        wifi_signal = wifi_info.signal_percent if wifi_ok else 0

        # ── 汇总行 ─────────────────────────
        details = [
            f"网关丢包率: {gw_loss:.1f}%",
            f"网关平均延迟: {gw_lat:.1f} ms  |  抖动: {gw_jitter:.1f} ms",
            f"外网丢包率: {ext_loss:.1f}%",
            f"外网平均延迟: {ext_lat:.1f} ms",
        ]
        if wifi_ok:
            details.append(f"WiFi 信号强度: {wifi_signal}%")

        # ── 规则链 ──────────────────────────

        # 1) WiFi 未连接
        if wifi_info is not None and not wifi_ok:
            return DiagnosisResult(
                DiagnosisResult.CRITICAL,
                "❌ WiFi 未连接",
                details + ["WiFi 适配器未连接到任何无线网络"],
                [
                    "检查 WiFi 开关是否已开启",
                    "尝试重新连接 WiFi",
                    "检查路由器是否正常工作",
                    "在设备管理器中检查网卡驱动",
                ],
            )

        # 2) 网关严重丢包
        if gw_loss >= self.GW_LOSS_CRIT:
            if wifi_signal < self.SIG_LOW:
                return DiagnosisResult(
                    DiagnosisResult.CRITICAL,
                    "⚠ 无线信号差导致严重丢包",
                    details,
                    [
                        "靠近路由器以增强信号",
                        "检查是否有墙壁 / 障碍物遮挡",
                        "尝试切换到 5 GHz 频段",
                        "排查附近干扰源（微波炉、蓝牙设备等）",
                        "考虑添加 WiFi 信号放大器",
                    ],
                )
            if wifi_signal < self.SIG_MED:
                return DiagnosisResult(
                    DiagnosisResult.CRITICAL,
                    "⚠ 信号偏弱，无线连接不稳定",
                    details,
                    [
                        "尝试靠近路由器",
                        "更换 WiFi 频道减少干扰",
                        "更新无线网卡驱动",
                        "检查路由器 WiFi 模块状态",
                    ],
                )
            # 信号好但丢包高
            return DiagnosisResult(
                DiagnosisResult.CRITICAL,
                "⚠ 信号良好但丢包严重 — 网卡或路由器故障",
                details,
                [
                    "更新 / 重装无线网卡驱动",
                    "在设备管理器中禁用再启用无线网卡",
                    "检查路由器是否过热或负载过高",
                    "重启路由器",
                    "用其他设备连同一 WiFi 对比",
                    "仍有问题则考虑更换网卡",
                ],
            )

        # 3) 网关轻微丢包
        if gw_loss >= self.GW_LOSS_WARN:
            if wifi_signal < self.SIG_MED:
                return DiagnosisResult(
                    DiagnosisResult.WARNING,
                    "⚡ 信号偏弱，偶尔丢包",
                    details,
                    [
                        "靠近路由器或减少障碍物",
                        "减少同频段设备数量",
                        "更换 WiFi 频道",
                    ],
                )
            return DiagnosisResult(
                DiagnosisResult.WARNING,
                "⚡ 局域网偶有丢包",
                details,
                [
                    "检查是否有设备大量占用带宽",
                    "更新网卡驱动",
                    "查看路由器已连设备数",
                ],
            )

        # 4) 网关高抖动
        if gw_jitter >= self.GW_JITTER_CRIT:
            return DiagnosisResult(
                DiagnosisResult.WARNING,
                "⚡ 无线延迟波动较大",
                details,
                [
                    "可能存在无线干扰",
                    "尝试更换 WiFi 频道",
                    "切换至 5 GHz 频段",
                    "远离干扰源",
                ],
            )

        # 5) 外网严重丢包（网关正常）
        if ext_loss >= self.EXT_LOSS_CRIT:
            return DiagnosisResult(
                DiagnosisResult.CRITICAL,
                "⚠ 本地正常，外网严重丢包 — 路由器或运营商问题",
                details,
                [
                    "重启路由器",
                    "检查路由器 WAN 口网线",
                    "登录路由器后台查看 WAN 状态",
                    "联系运营商检查线路",
                    "查看是否有设备大量占带宽",
                ],
            )

        if ext_loss >= self.EXT_LOSS_WARN:
            return DiagnosisResult(
                DiagnosisResult.WARNING,
                "⚡ 本地正常，外网轻微丢包",
                details,
                [
                    "可能是运营商线路波动",
                    "检查路由器连接状态",
                    "持续观察是否自行恢复",
                ],
            )

        # 6) 网关延迟偏高
        if gw_lat >= self.GW_LAT_CRIT:
            return DiagnosisResult(
                DiagnosisResult.WARNING,
                "⚡ 到路由器延迟偏高",
                details,
                [
                    "检查无线信号质量",
                    "减少路由器连接设备数",
                    "重启无线网卡",
                ],
            )

        # 7) 轻微抖动
        if gw_jitter >= self.GW_JITTER_WARN:
            return DiagnosisResult(
                DiagnosisResult.WARNING,
                "⚡ 无线连接有轻微抖动",
                details,
                [
                    "轻微抖动通常不影响使用",
                    "如有卡顿可尝试更换频道",
                ],
            )

        # 8) 一切正常
        return DiagnosisResult(
            DiagnosisResult.GOOD,
            "✅ 网络连接状况良好",
            details,
            ["当前网络稳定，无需操作"],
        )
