# NetBugger — 网络丢包卡顿诊断工具

一款桌面网络诊断工具，用于实时诊断网络丢包卡顿的根因：
**究竟是电脑无线网卡有问题，还是路由器 / 运营商线路有问题。**

## 下载

- Windows v0.1.1: [NetBugger-windows-v0.1.1.zip](https://github.com/LaaOpe/NetBugger/releases/download/v0.1.1/NetBugger-windows-v0.1.1.zip)
- macOS v0.1.1: [NetBugger-macos-v0.1.1.zip](https://github.com/LaaOpe/NetBugger/releases/download/v0.1.1/NetBugger-macos-v0.1.1.zip)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 🏠 网关 Ping 监测 | 持续 Ping 路由器，检测本地无线链路质量 |
| 🌐 外网 Ping 监测 | 持续 Ping 公网 DNS，检测路由器到互联网的链路 |
| 📶 WiFi 信号采集 | 实时读取信号强度、网卡型号、频段、速率等 |
| 🚀 实时网速显示 | 每秒刷新下载/上传速率（KB/s、MB/s） |
| 🧠 自我诊断评分 | 无需额外设备，给出网卡侧/路由器侧嫌疑百分比与证据 |
| 🔍 智能诊断引擎 | 综合以上数据自动判断问题根因并给出建议 |
| 📈 实时折线图 | Canvas 绘制延迟 / 丢包趋势图 |
| 🎬 录制与回放 | 一键录制网络变化，停止后自动以坐标折线图回放 |

## 诊断逻辑

```
网关丢包高 + WiFi 信号弱      →  无线信号 / 距离问题
网关丢包高 + WiFi 信号正常    →  网卡驱动 / 路由器 WiFi 模块
网关正常   + 外网丢包高       →  路由器 WAN 口 / 运营商线路
网关延迟抖动大                →  无线干扰
全部正常                      →  网络健康 ✅
```

## 运行环境

- **操作系统**: Windows 10 / 11、macOS
- **Python**: 3.9+
- **源码运行依赖**: tkinter（随大多数桌面 Python 发行版提供）
- **可选依赖**: `Pillow`、`pystray`（用于托盘图标）

> 注：macOS 版本默认关闭系统托盘能力，以避免 Tk 与托盘框架的主线程冲突。

## 快速开始

```powershell
cd NetBugger
python main.py
```

## macOS 打包为 App

项目已提供打包脚本：

```bash
cd NetBugger
chmod +x build_macos_app.sh
./build_macos_app.sh
```

成功后会生成：

```text
dist/NetBugger.app
```

macOS 版本的设置与录制文件默认保存在：

```text
~/Library/Application Support/NetBugger/
```

## 项目结构

```
NetBugger/
├── main.py                  # 入口文件
├── core/
│   ├── __init__.py
│   ├── ping_monitor.py      # Ping 监控（后台线程）
│   ├── wifi_monitor.py      # WiFi 信息采集 + 网关检测
│   ├── network_speed_monitor.py  # 实时网速采样
│   └── diagnosis.py         # 诊断引擎
├── ui/
│   ├── __init__.py
│   └── main_window.py       # tkinter 主窗口 & 所有 UI 组件
└── README.md
```

## 使用方法

1. 启动后软件会**自动检测默认网关 IP**，也可手动修改
2. 从下拉框选择外网 Ping 目标（默认 Google DNS 8.8.8.8）
3. 点击 **▶ 开始监测**
4. 在顶部查看 **实时下载/上传速度**
5. 需要留痕时，点击 **● 录制**，按钮会变为 **■ 停止录制**
6. 点击 **■ 停止录制** 后会自动弹出回放窗口，可按指标浏览折线变化，并支持打开 CSV 原始文件
7. 点击 **🧠 自我诊断** 可生成“网卡侧 vs 路由器侧”嫌疑评分（建议先监测 1-2 分钟）
8. 诊断结果会在采集约 10 个样本后给出结论

## 许可

MIT License

## 下载

- **Windows 版（可下载）**: 请在 Releases 中上传构建产物后在此处添加下载链接。例如：

	- 最新安装包 / 可执行文件: https://github.com/your-username/your-repo/releases/latest

- **Mac 版（待构建）**: 尚未构建，待准备 macOS 构建产物后再在此处添加下载链接。

> 提示：将上面的 `https://github.com/your-username/your-repo/releases/latest` 替换为你真实的仓库 URL 或直接把构建产物上传到 GitHub Releases，然后把 Release 资产链接填入这里。
