# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板。
QQ 机器人交互登录由 QL-Bot 统一管理，本项目只负责签到和日常任务。

## 功能

- 每日签到（自动获取积分）
- 签到信息查询（连续签到天数、总积分）
- 模拟浏览文章
- 模拟分享
- 多账号支持（Token 通过青龙面板环境变量 `XHT_TOKEN` 读取）
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）

## 架构

```
QL-Bot (QQ机器人)  --交互登录-->  徐汇通 API  --获取Token-->  青龙面板环境变量 (XHT_TOKEN)
                                                                      |
QL-XHT (本脚本)  <----青龙定时任务----  青龙面板  <---读取Token---  XHT_TOKEN
```

- **QL-Bot**：负责 QQ 交互登录，获取 Token 后写入青龙面板
- **QL-XHT**：只负责定时签到和日常任务，从青龙面板读取 Token

## 快速部署

### 1. 青龙面板订阅

青龙面板 -> 订阅管理 -> 新建订阅：

| 字段 | 值 |
|------|-----|
| 名称 | `QL-XHT` |
| 链接 | `https://github.com/Hayfan-wu/QL-XHT.git` |
| 定时规则 | `30 8 * * *` |
| 白名单 | `xht.py` |
| 文件后缀 | `py` |

### 2. 安装依赖

青龙面板 -> 依赖管理 -> Python3 -> 新建：

```
requests
```

### 3. 配置 .env

编辑项目目录下的 `.env`，填入青龙 Open API 凭据（和 QL-WPS 等项目一致）：

```bash
QL_URL="http://127.0.0.1:5700"
QL_CLIENT_ID="你的client_id"
QL_CLIENT_SECRET="你的client_secret"
XHT_BASE_URL="https://shrmtxh.shmedia.tech"
```

### 4. 青龙面板添加环境变量

青龙面板 -> 环境变量 -> 新建：

| 名称 | 值 |
|------|-----|
| `XHT_TOKEN` | 由 QL-Bot 交互登录后自动写入，或手动填入 Token（多账号用 `&` 分隔） |

### 5. 运行

青龙面板 -> 定时任务 -> 手动运行 QL-XHT 验证。

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `XHT_TOKEN` | 是 | - | 用户 Token（由 QL-Bot 写入或手动配置），多账号用 `&` 分隔 |
| `XHT_BASE_URL` | 否 | `https://shrmtxh.shmedia.tech` | API 基础地址 |
| `QL_URL` | 否 | `http://127.0.0.1:5700` | 青龙面板地址 |
| `QL_CLIENT_ID` | 否 | - | 青龙 Open API Client ID |
| `QL_CLIENT_SECRET` | 否 | - | 青龙 Open API Client Secret |
| `XHT_NOTIFY` | 否 | 青龙内置 | 通知渠道：`pushplus`/`serverchan`/`bark`/`telegram`/`none` |
| `XHT_TIMEOUT` | 否 | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | 否 | `3` | 失败重试次数 |
| `XHT_BROWSE_ARTICLE` | 否 | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | 否 | `5` | 浏览文章数量 |
| `XHT_SHARE` | 否 | `true` | 是否执行分享 |
| `XHT_SHARE_COUNT` | 否 | `1` | 分享次数 |

## 目录结构

```
QL-XHT/
├── .env              # 配置文件（项目自身参数，无 QQ 机器人参数）
├── .env.example      # 配置示例
├── xht.py            # 主脚本
├── requirements.txt  # Python 依赖
├── .gitignore
└── README.md
```