"""
无额外设备的单机自我诊断评分引擎
输出网卡侧 / 路由器侧嫌疑分数与证据。
"""

from dataclasses import dataclass
import statistics


@dataclass
class SelfDiagnosisResult:
    adapter_score: int
    router_score: int
    title: str
    evidence: list[str]
    suggestions: list[str]


class SelfDiagnosisEngine:
    """基于本机采样数据进行概率型归因（非绝对定责）。"""

    def evaluate(
        self,
        gw_stats: dict | None,
        ext_stats: dict | None,
        wifi_signal_series: list[float],
        gw_latency_series: list[float],
        wifi_connected: bool,
    ) -> SelfDiagnosisResult:
        if not gw_stats or not ext_stats:
            return SelfDiagnosisResult(
                adapter_score=50,
                router_score=50,
                title="数据不足，无法形成可信自诊断",
                evidence=["请先连续监测至少 2 分钟"],
                suggestions=["保持监测运行，采集更多样本后再执行自诊断"],
            )

        if gw_stats.get('total', 0) < 50:
            return SelfDiagnosisResult(
                adapter_score=50,
                router_score=50,
                title="样本偏少，自诊断可信度较低",
                evidence=[f"当前样本数: {gw_stats.get('total', 0)}，建议 >= 50"],
                suggestions=["继续运行 1-2 分钟后重试"],
            )

        adapter = 0.0
        router = 0.0
        evidence: list[str] = []
        suggestions: list[str] = []

        gw_loss = float(gw_stats.get('loss_rate', 0.0))
        ext_loss = float(ext_stats.get('loss_rate', 0.0))
        gw_jitter = float(gw_stats.get('jitter', 0.0))
        gw_avg = float(gw_stats.get('avg_latency', 0.0))
        ext_avg = float(ext_stats.get('avg_latency', 0.0))

        if not wifi_connected:
            adapter += 35
            evidence.append("WiFi 非连接态，问题更偏本机无线链路")

        if gw_loss >= 8:
            adapter += 24
            router += 18
            evidence.append(f"网关丢包较高 ({gw_loss:.1f}%)，本地链路存在明显异常")
        elif gw_loss >= 3:
            adapter += 12
            router += 8
            evidence.append(f"网关有轻度丢包 ({gw_loss:.1f}%)")

        if ext_loss >= 8 and gw_loss < 2:
            router += 30
            evidence.append(f"网关基本正常但外网丢包高 ({ext_loss:.1f}%)，偏路由器WAN/上游")
        elif ext_loss >= 5 and gw_loss < 3:
            router += 18
            evidence.append("外网丢包高于网关，路由器或上游链路嫌疑增加")

        if gw_jitter >= 15:
            adapter += 18
            evidence.append(f"网关抖动偏高 ({gw_jitter:.1f}ms)，更像无线干扰/网卡状态波动")
        elif gw_jitter >= 7:
            adapter += 10
            evidence.append("网关抖动中等偏高")

        if gw_avg >= 30:
            adapter += 8
            router += 6
            evidence.append(f"到网关平均时延偏高 ({gw_avg:.1f}ms)")

        # 信号与延迟相关性（强相关偏网卡/无线环境）
        corr = self._correlation(wifi_signal_series, gw_latency_series)
        if corr <= -0.45:
            adapter += 22
            evidence.append(f"信号与延迟呈明显负相关 (r={corr:.2f})，偏无线链路问题")
        elif corr <= -0.25:
            adapter += 12
            evidence.append(f"信号与延迟有一定负相关 (r={corr:.2f})")
        elif abs(corr) < 0.1:
            router += 6
            evidence.append("信号与延迟相关性弱，偏路由器转发/上游因素")

        # 若外网时延明显高而网关稳定，偏路由器/上游
        if ext_avg > gw_avg * 3 and gw_loss < 2:
            router += 14
            evidence.append("外网时延显著高于网关且网关稳定，偏路由器WAN/运营商")

        adapter = max(1.0, adapter)
        router = max(1.0, router)
        total = adapter + router
        adapter_score = int(round(adapter / total * 100))
        router_score = 100 - adapter_score

        if adapter_score >= router_score:
            title = f"自诊断结论：更偏无线网卡侧（{adapter_score}%）"
            suggestions.extend([
                "更新/回退无线网卡驱动后复测",
                "设备管理器关闭网卡节能选项",
                "尽量切换到 5GHz 并固定信道",
            ])
        else:
            title = f"自诊断结论：更偏路由器/上游侧（{router_score}%）"
            suggestions.extend([
                "重启路由器并检查 WAN 口状态",
                "检查路由器 CPU/连接数与 QoS 设置",
                "高峰时段持续异常可联系运营商排查线路",
            ])

        if not evidence:
            evidence.append("当前指标均较温和，未检测到明显单侧异常特征")

        suggestions.append("该结果为概率诊断，建议在不同时间段各测一次并对比")

        return SelfDiagnosisResult(
            adapter_score=adapter_score,
            router_score=router_score,
            title=title,
            evidence=evidence,
            suggestions=suggestions,
        )

    @staticmethod
    def _correlation(xs: list[float], ys: list[float]) -> float:
        n = min(len(xs), len(ys))
        if n < 8:
            return 0.0
        x = xs[-n:]
        y = ys[-n:]

        # 去掉缺失与非法值
        pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None and b >= 0]
        if len(pairs) < 8:
            return 0.0

        xvals = [p[0] for p in pairs]
        yvals = [p[1] for p in pairs]

        if statistics.pstdev(xvals) == 0 or statistics.pstdev(yvals) == 0:
            return 0.0

        mx = statistics.mean(xvals)
        my = statistics.mean(yvals)
        num = sum((a - mx) * (b - my) for a, b in pairs)
        den_x = sum((a - mx) ** 2 for a in xvals)
        den_y = sum((b - my) ** 2 for b in yvals)
        den = (den_x * den_y) ** 0.5
        if den == 0:
            return 0.0
        return num / den
