# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板。
QQ 机器人交互登录由 QL-Bot 通过 `bot_plugins/xht.py` 插件统一管理。

## 功能

- 每日签到（自动获取积分）
- 签到信息查询（连续签到天数、总积分）
- 模拟浏览文章
- 模拟分享
- 多账号支持（Token 通过青龙面板环境变量 `XHT_TOKEN` 读取）
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）

## 架构

```
QL-Bot/                         # QQ 机器人框架
├── main.py
├── bot/
│   ├── core.py                 # 插件加载、消息分发
│   ├── project_loader.py       # 自动扫描 /opt/*/bot_plugins/
│   └── ...
└── .env                        # 只放机器人核心配置

/opt/QL-XHT/                    # 本项目
├── xht.py                      # 青龙定时任务脚本
├── .env                        # 项目自身配置（青龙 Open API 等）
├── bot_plugins/
│   └── xht.py                  # QQ 机器人插件（被 QL-Bot 自动加载）
└── README.md
```

- **QL-XHT/bot_plugins/xht.py**：QQ 交互登录插件，被 QL-Bot 自动扫描加载
- **QL-XHT/xht.py**：青龙定时签到脚本，只负责签到和日常任务

## 快速部署

### 1. 克隆仓库

```bash
cd /opt
git clone https://github.com/Hayfan-wu/QL-XHT.git
```

### 2. 配置项目 .env

```bash
cd /opt/QL-XHT
cp .env.example .env
nano .env
```

填写青龙 Open API 凭据：

```bash
QL_URL="http://127.0.0.1:5700"
QL_CLIENT_ID="你的client_id"
QL_CLIENT_SECRET="你的client_secret"
XHT_BASE_URL="https://shrmtxh.shmedia.tech"
```

### 3. 青龙面板拉库

青龙面板 -> 订阅管理 -> 新建订阅：

| 字段 | 值 |
|------|-----|
| 名称 | `QL-XHT` |
| 链接 | `https://github.com/Hayfan-wu/QL-XHT.git` |
| 定时规则 | `30 8 * * *` |
| 白名单 | `xht.py` |
| 文件后缀 | `py` |

### 4. 安装依赖

青龙面板 -> 依赖管理 -> Python3 -> 新建：

```
requests
```

### 5. 配置青龙 Open API 应用

青龙面板 -> 系统设置 -> 应用设置 -> 创建应用：

- 名称：`QL-XHT`
- 权限：环境变量（读取、修改）

创建后得到 `Client ID` 和 `Client Secret`，填入 `/opt/QL-XHT/.env`。

### 6. 重启 QL-Bot 加载插件

```bash
cd /opt/QL-Bot
pkill -f "python3 main.py"
export $(cat .env | grep -v '^#' | xargs)
nohup python3 main.py > main.log 2>&1 &
```

QL-Bot 启动时会自动扫描 `/opt/QL-XHT/bot_plugins/` 并加载 `xht.py`。

### 7. QQ 交互登录

在 QQ 群里 @机器人 或私聊：

```
XHT登录 13800138000
```

机器人会发送验证码，回复验证码后即可登录，Token 自动写入青龙面板 `XHT_TOKEN`。

### 8. 创建青龙定时任务

青龙面板 -> 定时任务 -> 新建：

| 字段 | 值 |
|------|-----|
| 名称 | `QL-XHT签到` |
| 命令 | `task Hayfan-wu_QL-XHT/xht.py` |
| 定时规则 | `30 8 * * *` |

保存后手动运行一次验证。

## QQ 命令

| 命令 | 说明 |
|------|------|
| `XHT登录 13800138000` | 手机号验证码登录 |
| `XHT查询` | 查询已登录账号状态 |
| `XHT执行` | 立即执行签到脚本 |
| `XHT管理` | 查看已登录账号 |
| `XHT管理 删除 1` | 删除第 1 个账号 |
| `XHT帮助` | 显示命令帮助 |

## 环境变量说明

### QL-XHT 项目 .env

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `QL_URL` | 是 | `http://127.0.0.1:5700` | 青龙面板地址 |
| `QL_CLIENT_ID` | 是 | - | 青龙 Open API Client ID |
| `QL_CLIENT_SECRET` | 是 | - | 青龙 Open API Client Secret |
| `XHT_BASE_URL` | 否 | `https://shrmtxh.shmedia.tech` | 徐汇通 API 地址 |
| `XHT_NOTIFY` | 否 | 青龙内置 | 通知渠道 |
| `XHT_TIMEOUT` | 否 | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | 否 | `3` | 失败重试次数 |
| `XHT_BROWSE_ARTICLE` | 否 | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | 否 | `5` | 浏览文章数量 |
| `XHT_SHARE` | 否 | `true` | 是否执行分享 |
| `XHT_SHARE_COUNT` | 否 | `1` | 分享次数 |

### 青龙面板环境变量

| 名称 | 说明 |
|------|------|
| `XHT_TOKEN` | 由 QQ 机器人登录后自动写入，多账号用 `&` 分隔 |

## 目录结构

```
QL-XHT/
├── .env                  # 项目自身配置
├── .env.example          # 配置示例
├── xht.py                # 青龙定时签到脚本
├── bot_plugins/
│   └── xht.py            # QQ 机器人交互插件
├── requirements.txt      # Python 依赖
├── .gitignore
└── README.md
```