# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板。

## 功能

- 每日签到（自动获取积分）
- 签到信息查询（连续签到天数、总积分）
- 模拟浏览文章
- 模拟分享
- 多账号支持
- 多渠道推送通知（青龙内置、PushPlus、Server酱、Bark、Telegram）

## 快速开始

### 1. 获取 Token

使用抓包工具（Charles / Fiddler / Stream 等）：

1. 手机配置代理连接抓包工具
2. 打开「徐汇通」APP 并登录
3. 在抓包记录中找到任意 API 请求
4. 复制请求头中 `Authori-zation` 字段的值（注意字段名中间有个横杠）

### 2. 配置

编辑项目目录下的 `.env` 文件：

```bash
# 必填
XHT_TOKEN="你的token"
XHT_BASE_URL="https://shrmtxh.shmedia.tech"

# 多账号用 & 分隔
# XHT_TOKEN="token1&token2&token3"
```

### 3. 青龙面板部署

**方式一：订阅仓库**

青龙面板 -> 订阅管理 -> 新建订阅：

- 名称：`QL-XHT`
- 链接：你的仓库地址
- 定时规则：`30 8 * * *`（每天 8:30 执行）
- 白名单：`xht.py`

然后在青龙面板环境变量中添加 `XHT_TOKEN`。

**方式二：手动添加**

1. 将 `xht.py` 上传到青龙面板脚本目录
2. 在项目目录的 `.env` 文件中配置 `XHT_TOKEN`
3. 添加定时任务：`python3 /path/to/QL-XHT/xht.py`
4. 定时规则：`30 8 * * *`

### 4. 安装依赖

青龙面板 -> 依赖管理 -> Python3 -> 新建依赖：

```
requests
```

或通过 requirements.txt 安装：

```bash
pip install -r requirements.txt
```

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `XHT_TOKEN` | 是 | - | 用户 Token，多账号用 `&` 分隔 |
| `XHT_BASE_URL` | 否 | `https://shrmtxh.shmedia.tech` | API 基础地址 |
| `XHT_NOTIFY` | 否 | 青龙内置 | 通知渠道：`notify`/`pushplus`/`serverchan`/`bark`/`telegram`/`none` |
| `XHT_TIMEOUT` | 否 | `15` | 请求超时（秒） |
| `XHT_RETRY_COUNT` | 否 | `3` | 失败重试次数 |
| `XHT_BROWSE_ARTICLE` | 否 | `true` | 是否浏览文章 |
| `XHT_BROWSE_COUNT` | 否 | `5` | 浏览文章数量 |
| `XHT_SHARE` | 否 | `true` | 是否执行分享 |
| `XHT_SHARE_COUNT` | 否 | `1` | 分享次数 |

## 注意事项

1. **所有配置均存储在项目自身的 `.env` 文件中**，不会修改 qq-bot 或青龙面板的任何文件
2. 如果 `XHT_BASE_URL` 不正确，请在 APP 抓包确认实际 API 域名后修改
3. Token 有效期较长，但如果脚本提示"Token已失效"，请重新抓包获取
4. 建议定时在每天早上 8:00 - 9:00 之间执行

## 目录结构

```
QL-XHT/
├── .env              # 配置文件（需自行填写 Token）
├── .env.example      # 配置示例
├── xht.py            # 主脚本
├── requirements.txt  # Python 依赖
└── README.md         # 说明文档
```