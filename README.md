# QL-XHT

徐汇通 APP 自动签到 & 日常任务脚本，适用于青龙面板，纯手动部署。

## 功能

- 每日签到（自动获取积分）
- **阅读文章任务**（20篇/天，自动完成）
- **观看视频任务**（20个/天，自动完成）
- 积分信息查询（连续签到天数、总积分、今日积分）
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

### API 端点

| 任务 | API 端点 | 方法 | 说明 |
|------|---------|------|------|
| 阅读文章 | `/api/app/points/read/add` | POST | 每次调用 +1 阅读进度，最多 20 次 |
| 观看视频 | `/api/app/points/video/add` | POST | 每次调用 +1 视频进度，最多 20 次 |
| 登录积分 | `/api/app/points/login/add` | POST | 每日首次登录获取积分 |


## 接口来源

本项目接口基于真实 APP 抓包分析：

- 业务域名：`https://app.xuhuimedia.cn/media-basic-port`
- 认证方式：HTTP Header `token`（JWT）
