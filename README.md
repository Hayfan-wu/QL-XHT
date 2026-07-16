# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板，纯手动部署。

## 功能

- 每日签到（自动获取积分）
- 积分信息查询（连续签到天数、总积分、今日积分）
- 多账号支持（通过环境变量 `XHT_TOKEN` 读取，`&` 分隔）
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）

> 注意：阅读文章和观看视频任务无法通过 HTTP API 完成。经过 200+ 个 API 路径探测、APK 逆向分析、H5 页面 JS 分析和浏览器模拟，确认阅读/视频进度追踪由原生 APP 的 native 层处理（`rmt://` 桥协议），HTTP 层无对应端点。详见下方「阅读/视频任务」章节。

## 快速部署

### 1. 青龙面板拉库

青龙面板 -> 订阅管理 -> 新建订阅：

| 字段 | 值 |
|------|-----|
| 名称 | `QL_XHT` |
| 链接 | `https://github.com/Hayfan-wu/QL-XHT.git` |
| 定时规则 | `30 8 * * *` |
| 白名单 | `xht.py` |
| 文件后缀 | `py` |

### 2. 安装依赖

青龙面板 -> 依赖管理 -> Python3 -> 新建：

```
requests
```

### 3. 添加 Token 环境变量

青龙面板 -> 环境变量 -> 新建：

| 字段 | 值 |
|------|-----|
| 名称 | `XHT_TOKEN` |
| 值 | 你的 JWT Token（多账号用 `&` 分隔） |

#### 如何获取 Token

1. 手机上打开徐汇通 APP 并登录
2. 使用抓包工具（HttpCanary、Stream 等）抓取任意接口的请求头
3. 复制请求头中的 `token` 字段（JWT 格式，以 `eyJ` 开头的一长串）

### 4. 创建定时任务

青龙面板 -> 定时任务 -> 新建：

| 字段 | 值 |
|------|-----|
| 名称 | `徐汇通签到` |
| 命令 | `task Hayfan-wu_QL-XHT/xht.py` |
| 定时规则 | `30 8 * * *` |

## 环境变量说明

### 青龙面板环境变量（必填）

| 名称 | 必填 | 说明 |
|------|------|------|
| `XHT_TOKEN` | 是 | JWT Token，多账号用 `&` 分隔，如 `token1&token2&token3` |

### 青龙面板环境变量（可选）

| 名称 | 默认值 | 说明 |
|------|--------|------|
| `XHT_BASE_URL` | `https://app.xuhuimedia.cn/media-basic-port` | 徐汇通 API 地址 |
| `XHT_SITE_ID` | `310104` | 站点 ID |
| `XHT_TIMEOUT` | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | `3` | 失败重试次数 |
| `XHT_NOTIFY` | 青龙内置 | 通知渠道：pushplus / serverchan / bark / telegram |
| `XHT_PUSHPLUS_TOKEN` | - | PushPlus Token |
| `XHT_SERVERCHAN_KEY` | - | Server酱 SendKey |
| `XHT_BARK_URL` | - | Bark 推送 URL |
| `XHT_TG_BOT_TOKEN` | - | Telegram Bot Token |
| `XHT_TG_CHAT_ID` | - | Telegram Chat ID |
| `XHT_TG_API_PROXY` | - | Telegram API 代理 |
| `XHT_DEVICE_ID` | 自动生成 | 32位设备标识 |

## 目录结构

```
QL-XHT/
├── xht.py                # 青龙定时签到脚本
├── xht_simulate.py       # Playwright 浏览器模拟脚本
├── xht_capture.py        # 抓包分析辅助工具
├── bot_plugins/          # （已废弃，保留兼容）
├── .env.example          # 配置示例
├── requirements.txt      # Python 依赖
└── README.md
```

## 阅读/视频任务

### 现状

阅读文章（20篇/天）和观看视频（20个/天）的任务进度由原生 APP 的 native 层直接处理，无法通过 HTTP API 完成。经过以下全面分析：

| 分析方向 | 方法 | 结果 |
|---------|------|------|
| API 路径探测 | 测试 200+ 个可能路径 | 全部返回 404 |
| Gateway 域名 | `xuhui-gateway.shmedia.tech` | SSL 错误，不可访问 |
| H5 页面 JS 分析 | `bridge-1.0.js`, `rmt-2.0.0.js` | 无阅读追踪代码 |
| 浏览器模拟 | 集成浏览器加载文章页面 | 无追踪 API 调用 |
| APK 逆向 | 下载并解包 APK | 360加固保护，无法解密 |
| Native .so 库 | 搜索 lib 目录 | 均为第三方库，无 API URL |

### 解决方案

**方案一：抓包获取 API（推荐）**

使用手机抓包工具捕获徐汇通 APP 的网络请求，找到阅读/视频追踪的 API 端点：

```bash
# 查看详细抓包指引
python3 xht_capture.py --guide

# 分析 HAR 抓包文件
python3 xht_capture.py --har capture.har

# 分析 mitmproxy flow 文件
python3 xht_capture.py --flow xht_traffic.flow
```

**方案二：Playwright 浏览器模拟**

使用 `xht_simulate.py` 在浏览器中模拟 APP 行为，捕获网络请求：

```bash
pip install playwright --break-system-packages
playwright install chromium
python3 xht_simulate.py --token YOUR_TOKEN --count 5
```

> 注意：浏览器模拟无法触发阅读进度更新（因为追踪由原生 APP 处理），
> 但可以帮助捕获网络请求用于分析。

**方案三：手动完成**

每天在手机上打开徐汇通 APP，手动浏览 20 篇文章和 20 个视频即可完成任务。

### 如何贡献

如果你成功抓包获取到了阅读/视频追踪的 API 端点，请提交 Issue 或 PR 到本仓库，帮助完善脚本功能。

## 接口来源

本项目接口基于真实 APP 抓包分析：

- 业务域名：`https://app.xuhuimedia.cn/media-basic-port`
- 认证方式：HTTP Header `token`（JWT）