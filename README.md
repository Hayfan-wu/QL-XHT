# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板。
通过 QQ 机器人交互式手机号验证码登录，Token 自动持久化。

## 功能

- QQ 机器人交互登录（手机号 + 验证码，支持 WebSocket / HTTP）
- Token 自动持久化到 `data/tokens.json`
- 每日签到（自动获取积分）
- 签到信息查询（连续签到天数、总积分）
- 模拟浏览文章
- 模拟分享
- 多账号支持
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram、QQ）

## 工作原理

```
┌─────────────┐     私聊指令      ┌──────────────┐     API 请求     ┌─────────────┐
│   管理员 QQ  │ ──────────────▶ │  QQ 机器人    │ ──────────────▶ │  徐汇通 API  │
│             │ ◀────────────── │  (本项目)     │ ◀────────────── │             │
│  发送手机号  │     返回结果      │              │     返回数据     │             │
│  回复验证码  │                  │  WebSocket   │                  │  发短信验证码 │
└─────────────┘                  │  + HTTP API  │                  │  手机号登录  │
                                 └──────┬───────┘                  └─────────────┘
                                        │
                                        ▼
                                ┌──────────────┐
                                │ data/        │
                                │ tokens.json  │
                                │ (Token 持久化) │
                                └──────────────┘
```

## 快速开始

### 1. 准备 QQ 机器人

需要一个实现 OneBot v11 协议的 QQ 框架，例如：

- [NapCat](https://github.com/NapNeko/NapCatQQ)
- [Lagrange](https://github.com/LagrangeDev/Lagrange.Core)
- [LLOneBot](https://github.com/LLOneBot/LLOneBot)
- [go-cqhttp](https://github.com/Mrs4s/go-cqhttp)

确保开启 **正向 WebSocket** 和 **HTTP POST API**。

### 2. 配置

编辑项目目录下的 `.env` 文件：

```bash
# 必填 - QQ 机器人
QQ_WS_URL="ws://127.0.0.1:8080"       # 机器人 WebSocket 地址
QQ_HTTP_URL="http://127.0.0.1:3000"    # 机器人 HTTP API 地址
QQ_ADMIN_QQ="你的QQ号"                  # 管理员 QQ 号

# 徐汇通
XHT_BASE_URL="https://shrmtxh.shmedia.tech"
```

### 3. 启动 QQ 机器人服务

```bash
python3 xht.py --bot
```

此命令会持续运行，监听 QQ 私聊消息。

### 4. 在 QQ 中登录账号

向机器人发送私聊消息：

```
登录 13800138000
```

机器人会自动：
1. 向该手机号发送验证码
2. 等待你回复验证码
3. 使用验证码登录徐汇通
4. 保存 Token 到 `data/tokens.json`

支持回复「取消」取消登录。

### 5. 配置青龙面板定时任务

添加定时任务执行每日签到：

```
python3 /path/to/QL-XHT/xht.py
```

定时规则：`30 8 * * *`（每天 8:30）

### 6. 安装依赖

```
pip install -r requirements.txt
```

## QQ 命令

| 命令 | 说明 |
|------|------|
| `登录 13800138000` | 登录新账号（发送验证码） |
| `登录` | 交互式登录（下一步输入手机号） |
| `账号列表` 或 `列表` | 查看已登录账号及状态 |
| `删除 13800138000` | 删除指定账号 |
| `帮助` 或 `help` | 显示命令帮助 |

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `QQ_WS_URL` | 是 | - | QQ 机器人 WebSocket 地址 |
| `QQ_HTTP_URL` | 是 | - | QQ 机器人 HTTP API 地址 |
| `QQ_ADMIN_QQ` | 是 | - | 管理员 QQ 号 |
| `XHT_BASE_URL` | 否 | `https://shrmtxh.shmedia.tech` | 徐汇通 API 地址 |
| `XHT_NOTIFY` | 否 | 青龙内置 | 通知渠道 |
| `XHT_TIMEOUT` | 否 | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | 否 | `3` | 失败重试次数 |
| `XHT_BROWSE_ARTICLE` | 否 | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | 否 | `5` | 浏览文章数量 |
| `XHT_SHARE` | 否 | `true` | 是否执行分享 |
| `XHT_SHARE_COUNT` | 否 | `1` | 分享次数 |

## 注意事项

1. **所有配置均存储在项目自身的 `.env` 文件中**，不会修改 qq-bot 或青龙面板的任何文件
2. Token 自动保存在 `data/tokens.json`，定时任务自动读取
3. Token 过期后脚本会提示，通过 QQ 机器人重新登录即可
4. 仅 `QQ_ADMIN_QQ` 指定的 QQ 号可以操作机器人

## 目录结构

```
QL-XHT/
├── .env                # 配置文件（需填写 QQ 机器人信息）
├── .env.example        # 配置示例
├── xht.py              # 主脚本
├── requirements.txt    # Python 依赖
├── .gitignore
├── README.md
└── data/
    └── tokens.json     # Token 持久化存储（自动生成）
```