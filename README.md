# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板。  
QQ 机器人交互登录由 QL-Bot 通过 `bot_plugins/xht.py` 插件统一管理。

## 功能

- 每日签到（自动获取积分）
- 积分信息查询（连续签到天数、总积分、今日积分、任务进度）
- 模拟浏览文章
- 多账号支持（Token 通过青龙面板环境变量 `XHT_TOKEN` 读取）
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）
- 三种登录方式：Token 直绑、短信验证码 + 浏览器自动过滑块、短信验证码 + 第三方打码平台

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
├── xht_login_helper.py         # 登录辅助模块（Token/短信）
├── .env                        # 项目自身配置（青龙 Open API 等）
├── bot_plugins/
│   └── xht.py                  # QQ 机器人插件（被 QL-Bot 自动加载）
└── README.md
```

- **QL-XHT/bot_plugins/xht.py**：QQ 交互登录插件，被 QL-Bot 自动扫描加载
- **QL-XHT/xht_login_helper.py**：独立登录模块，支持 Token 直绑与短信登录
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

# 徐汇通配置一般保持默认即可
XHT_BASE_URL="https://app.xuhuimedia.cn/media-basic-port"
XHT_SITE_ID="310104"
```

### 3. 青龙面板拉库

青龙面板 -> 订阅管理 -> 新建订阅：

| 字段 | 值 |
|------|-----|
| 名称 | `QL_XHT` |
| 链接 | `https://github.com/Hayfan-wu/QL-XHT.git` |
| 定时规则 | `30 8 * * *` |
| 白名单 | `xht.py` |
| 文件后缀 | `py` |

### 4. 安装依赖

青龙面板 -> 依赖管理 -> Python3 -> 新建：

```
requests
```

如需使用短信登录，还需额外安装：

```bash
# 进入青龙容器或项目目录
pip install playwright opencv-python-headless
playwright install chromium
```

### 5. 配置青龙 Open API 应用

青龙面板 -> 系统设置 -> 应用设置 -> 创建应用：

- 名称：`QL_XHT`
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

#### 方式一：Token 直绑（推荐）

徐汇通 APP 登录后会在请求头中携带 JWT token。推荐通过抓包获取后直绑：

1. 在手机上打开徐汇通 APP 并登录
2. 使用 HttpCanary、Stream 等抓包工具抓取任意接口的请求头
3. 复制请求头中的 `token` 字段（JWT 格式，很长一串）
4. 在 QQ 群里 @机器人 或私聊：

```
XHT登录 token eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9...
```

机器人会校验 token 并保存到青龙面板 `XHT_TOKEN`。

#### 方式二：短信验证码登录（实验性）

短信登录需要先过阿里云拼图/滑块验证。本脚本提供两种求解器：

**A. 浏览器 + OpenCV 自动识别（免费，成功率有限）**

在 `.env` 中：

```bash
XHT_CAPTCHA_SOLVER="auto"
```

QQ 命令：

```
XHT登录 13800138000
```

机器人自动打开浏览器、识别缺口、发短信，然后等待你回复验证码。

**B. 第三方打码平台（付费，更稳定）**

以云码（jfbym）为例，在 `.env` 中：

```bash
XHT_CAPTCHA_SOLVER="jfbym"
XHT_CAPTCHA_API_KEY="你的云码_Token"
```

或使用 2Captcha：

```bash
XHT_CAPTCHA_SOLVER="2captcha"
XHT_CAPTCHA_API_KEY="你的2Captcha_API_Key"
```

或使用超级鹰：

```bash
XHT_CAPTCHA_SOLVER="chaojiying"
XHT_CAPTCHA_API_KEY="用户名:密码"
```

QQ 命令同上。

> 推荐：针对阿里云的**拼图滑块**，云码 `type=20226`（滑块_AL）接口最合适，返回的是目标拖动距离（像素），直接拖动即可。若识别失败，可在 `.env` 中切换 `XHT_CAPTCHA_TYPE`：
>
> ```bash
> XHT_CAPTCHA_TYPE="20226"  # 滑块_AL（推荐）
> XHT_CAPTCHA_TYPE="20111"  # 双图滑块
> XHT_CAPTCHA_TYPE="22222"  # 单图滑块优化
> ```

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
| `XHT登录 [手机号]` | 短信验证码登录（需配置滑块求解器） |
| `XHT登录 token [JWT]` | 直接提交抓包获取的 token（推荐） |
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
| `XHT_BASE_URL` | 否 | `https://app.xuhuimedia.cn/media-basic-port` | 徐汇通 API 地址 |
| `XHT_DEVICE_ID` | 否 | 自动生成 | 32位设备标识 |
| `XHT_SITE_ID` | 否 | `310104` | 站点 ID |
| `XHT_CAPTCHA_SOLVER` | 否 | 空 | 短信登录滑块求解器：auto / jfbym / 2captcha / chaojiying |
| `XHT_CAPTCHA_API_KEY` | 否 | 空 | 第三方打码平台 API Key（jfbym 填云码 token） |
| `XHT_NOTIFY` | 否 | 青龙内置 | 通知渠道 |
| `XHT_TIMEOUT` | 否 | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | 否 | `3` | 失败重试次数 |
| `XHT_BROWSE_ARTICLE` | 否 | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | 否 | `5` | 浏览文章数量 |

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
├── xht_login_helper.py   # 登录辅助模块
├── bot_plugins/
│   └── xht.py            # QQ 机器人交互插件
├── requirements.txt      # Python 依赖
├── .gitignore
└── README.md
```

## 已知限制

1. **阿里云滑块/拼图验证码**：徐汇通在发送短信前要求完成阿里云验证。纯后端环境无法自动完成，因此提供浏览器自动化和第三方打码两种可选方案。
2. **浏览器自动识别成功率**：OpenCV 识别拼图缺口受图片复杂度影响，成功率有限；如需稳定自动发短信，建议使用第三方打码平台。
3. **阅读积分**：当前抓包未捕获到明确的文章阅读上报接口，脚本通过调用新闻列表接口模拟浏览。

## 接口来源

本项目接口基于真实 APP 抓包分析：

- 业务域名：`https://app.xuhuimedia.cn/media-basic-port`
- 登录短信/滑块域名：`https://xhweb.shmedia.tech/media-basic-port`
- 认证方式：HTTP Header `token`（JWT）
