# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板，纯手动部署。

## 功能

- 每日签到（自动获取积分）
- 积分信息查询（连续签到天数、总积分、今日积分、任务进度）
- 模拟浏览文章
- 多账号支持（通过环境变量 `XHT_TOKEN` 读取，`&` 分隔）
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）

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
| `XHT_BROWSE_ARTICLE` | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | `5` | 浏览文章数量 |
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
├── bot_plugins/          # （已废弃，保留兼容）
├── .env.example          # 配置示例
├── requirements.txt      # Python 依赖
└── README.md
```

## 接口来源

本项目接口基于真实 APP 抓包分析：

- 业务域名：`https://app.xuhuimedia.cn/media-basic-port`
- 认证方式：HTTP Header `token`（JWT）