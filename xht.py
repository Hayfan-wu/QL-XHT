#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 自动签到 & 日常任务脚本
适用于青龙面板，配置均从项目 .env 文件读取
登录方式：由 QL-Bot 统一管理，Token 通过青龙 Open API 写入

基于真实抓包接口重写：
  - 业务域名：https://app.xuhuimedia.cn/media-basic-port
  - 认证方式：HTTP Header token (JWT)
  - 登录接口返回 token 在响应头 token 字段

功能：
  1. 每日签到
  2. 积分信息查询
  3. 用户信息查询
  4. 模拟浏览文章（新闻列表）
  5. 多账号支持（从青龙面板环境变量读取 XHT_TOKEN）
  6. 多种推送通知
"""

import os
import sys
import time
import random
import logging
import requests
import uuid
from datetime import datetime

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("XHT")

# ============================================================
# 从项目 .env 文件加载配置
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_SCRIPT_DIR, ".env")


def _load_env():
    """从项目目录下的 .env 文件加载环境变量"""
    if not os.path.isfile(_ENV_FILE):
        logger.warning(f"未找到配置文件: {_ENV_FILE}")
        return
    with open(_ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env()


# ============================================================
# 配置读取
# ============================================================
def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# --- 项目自身配置 ---
XHT_PROJECT_DIR = get_env("XHT_PROJECT_DIR", _SCRIPT_DIR)
XHT_SCRIPT_PATH = get_env("XHT_SCRIPT_PATH", os.path.join(_SCRIPT_DIR, "xht.py"))
XHT_BASE_URL = get_env("XHT_BASE_URL", "https://app.xuhuimedia.cn/media-basic-port").rstrip("/")
XHT_TIMEOUT = int(get_env("XHT_TIMEOUT", "15"))
XHT_RETRY_COUNT = int(get_env("XHT_RETRY_COUNT", "3"))
XHT_BROWSE_ARTICLE = get_env("XHT_BROWSE_ARTICLE", "true").lower() == "true"
XHT_BROWSE_COUNT = int(get_env("XHT_BROWSE_COUNT", "5"))

# 设备标识：固定或随机生成
XHT_DEVICE_ID = get_env("XHT_DEVICE_ID", "")
if not XHT_DEVICE_ID or len(XHT_DEVICE_ID) != 32:
    # 生成一个稳定的伪设备 ID（基于项目路径避免每次变化）
    base = os.path.basename(_SCRIPT_DIR) + "_xht_device"
    XHT_DEVICE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, base).hex.replace("-", "")[:32]

XHT_SITE_ID = get_env("XHT_SITE_ID", "310104")

# --- 青龙 Open API（用于读取 Token）---
QL_URL = get_env("QL_URL", "").rstrip("/")
QL_CLIENT_ID = get_env("QL_CLIENT_ID", "")
QL_CLIENT_SECRET = get_env("QL_CLIENT_SECRET", "")

# --- Token（优先从青龙面板读取，也可直接设置）---
_raw_tokens = get_env("XHT_TOKEN", "")
XHT_TOKENS = [t.strip() for t in _raw_tokens.split("&") if t.strip()]

# --- 通知配置 ---
XHT_NOTIFY = get_env("XHT_NOTIFY", "").lower()
XHT_PUSHPLUS_TOKEN = get_env("XHT_PUSHPLUS_TOKEN", "")
XHT_SERVERCHAN_KEY = get_env("XHT_SERVERCHAN_KEY", "")
XHT_BARK_URL = get_env("XHT_BARK_URL", "")
XHT_TG_BOT_TOKEN = get_env("XHT_TG_BOT_TOKEN", "")
XHT_TG_CHAT_ID = get_env("XHT_TG_CHAT_ID", "")
XHT_TG_API_PROXY = get_env("XHT_TG_API_PROXY", "")

# 默认 User-Agent（与抓包一致）
DEFAULT_UA = "xu hui tong/2.5.0 (iPhone; iOS 26.5; Scale/3.00)"


# ============================================================
# 青龙 Open API - 读取 Token
# ============================================================
def get_tokens_from_qinglong() -> list:
    """从青龙面板环境变量中读取 XHT_TOKEN"""
    if not QL_URL or not QL_CLIENT_ID or not QL_CLIENT_SECRET:
        return []
    try:
        # 1. 获取系统 token
        auth_url = f"{QL_URL}/open/auth/token"
        auth_resp = requests.get(auth_url, params={
            "client_id": QL_CLIENT_ID,
            "client_secret": QL_CLIENT_SECRET,
        }, timeout=10)
        if auth_resp.status_code != 200:
            logger.warning(f"青龙认证失败: HTTP {auth_resp.status_code}")
            return []
        auth_data = auth_resp.json()
        ql_token = auth_data.get("data", {}).get("token", "")
        if not ql_token:
            logger.warning("青龙认证未返回 token")
            return []

        # 2. 获取环境变量（尝试多种认证方式）
        env_url = f"{QL_URL}/open/envs"
        env_data = None
        auth_methods = [
            # 方式1: Bearer token
            lambda: requests.get(env_url, headers={"Authorization": f"Bearer {ql_token}"}, params={"searchValue": "XHT_TOKEN"}, timeout=10),
            # 方式2: query param token
            lambda: requests.get(env_url, params={"token": ql_token, "searchValue": "XHT_TOKEN"}, timeout=10),
        ]
        for i, fn in enumerate(auth_methods):
            env_resp = fn()
            if env_resp.status_code == 200:
                env_data = env_resp.json()
                if env_data.get("code") == 200:
                    if i > 0:
                        logger.info(f"青龙 API 认证方式 {i+1} 成功")
                    break
                logger.warning(f"青龙 API 认证方式 {i+1} 失败: code={env_data.get('code')}, msg={env_data.get('message', '')}")
            else:
                logger.warning(f"青龙 API 认证方式 {i+1} HTTP {env_resp.status_code}")

        if not env_data or env_data.get("code") != 200:
            logger.warning("所有青龙 API 认证方式均失败")
            return []

        envs = env_data.get("data", [])
        for env_item in envs:
            if env_item.get("name") == "XHT_TOKEN":
                value = env_item.get("value", "")
                if value:
                    tokens = [t.strip() for t in value.split("&") if t.strip()]
                    logger.info(f"从青龙面板读取到 {len(tokens)} 个 Token")
                    return tokens
        return []
    except Exception as e:
        logger.warning(f"从青龙面板读取 Token 失败: {e}")
        return []


def get_tokens_from_local() -> list:
    """从本地 .tokens 文件读取（兜底方案），检查多个可能路径"""
    import os
    candidates = []

    # 1. 环境变量显式指定
    ql_dir = os.environ.get("QL_SCRIPT_DIR", "")
    if ql_dir and os.path.isdir(ql_dir):
        candidates.append(os.path.join(ql_dir, ".tokens"))

    # 2. QL 容器内标准路径
    if os.path.isdir("/ql/data/scripts"):
        candidates.append("/ql/data/scripts/.tokens")

    # 3. xht.py 所在目录及上级
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tokens"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".tokens"))

    for local_file in candidates:
        try:
            if not os.path.exists(local_file):
                continue
            with open(local_file, "r", encoding="utf-8") as f:
                raw = f.read().strip()
                if not raw:
                    continue
                tokens = [t.strip() for t in raw.split("&") if t.strip()]
                if tokens:
                    logger.info(f"从本地文件读取到 {len(tokens)} 个 Token（路径: {local_file}）")
                    return tokens
        except Exception as e:
            logger.warning(f"从本地文件读取 Token 失败 ({local_file}): {e}")
    return []


# ============================================================
# 通知模块
# ============================================================
class Notify:
    """多渠道消息推送"""

    @staticmethod
    def send(title: str, content: str):
        if XHT_NOTIFY == "none":
            return
        if not XHT_NOTIFY:
            Notify._send_qinglong(title, content)
            return

        dispatch = {
            "pushplus": Notify._send_pushplus,
            "serverchan": Notify._send_serverchan,
            "bark": Notify._send_bark,
            "telegram": Notify._send_telegram,
        }
        fn = dispatch.get(XHT_NOTIFY)
        if fn:
            try:
                fn(title, content)
            except Exception as e:
                logger.error(f"通知发送失败 [{XHT_NOTIFY}]: {e}")

    @staticmethod
    def _send_qinglong(title: str, content: str):
        try:
            import notify
            notify.send(title, content)
        except ImportError:
            logger.info("未检测到青龙通知模块，跳过通知")
        except Exception as e:
            logger.error(f"青龙通知发送失败: {e}")

    @staticmethod
    def _send_pushplus(title: str, content: str):
        url = "http://www.pushplus.plus/send"
        data = {
            "token": XHT_PUSHPLUS_TOKEN,
            "title": title,
            "content": content.replace("\n", "<br>"),
            "template": "txt",
        }
        resp = requests.post(url, json=data, timeout=10)
        logger.info(f"PushPlus 推送结果: {resp.text}")

    @staticmethod
    def _send_serverchan(title: str, content: str):
        url = f"https://sctapi.ftqq.com/{XHT_SERVERCHAN_KEY}.send"
        data = {"title": title, "desp": content}
        resp = requests.post(url, data=data, timeout=10)
        logger.info(f"Server酱 推送结果: {resp.text}")

    @staticmethod
    def _send_bark(title: str, content: str):
        url = f"{XHT_BARK_URL}/{title}/{content}"
        resp = requests.get(url, timeout=10)
        logger.info(f"Bark 推送结果: {resp.text}")

    @staticmethod
    def _send_telegram(title: str, content: str):
        api_url = "https://api.telegram.org"
        if XHT_TG_API_PROXY:
            api_url = XHT_TG_API_PROXY
        url = f"{api_url}/bot{XHT_TG_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": XHT_TG_CHAT_ID,
            "text": f"**{title}**\n\n{content}",
            "parse_mode": "Markdown",
        }
        resp = requests.post(url, json=data, timeout=10)
        logger.info(f"Telegram 推送结果: {resp.text}")


# ============================================================
# 徐汇通 API 客户端
# ============================================================
class XHTClient:
    """徐汇通 API 交互客户端（基于真实抓包）"""

    def __init__(self, token: str, index: int = 0):
        self.token = token
        self.index = index
        self.base_url = XHT_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
            "Accept-Language": "zh-Hans-CN;q=1, zh-Hant-HK;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "deviceId": XHT_DEVICE_ID,
            "siteId": XHT_SITE_ID,
            "token": token,
        })
        self.nickname = f"账号{index + 1}"
        self.results = []

    def _log(self, msg: str):
        logger.info(f"[账号{self.index + 1}] {msg}")
        self.results.append(msg)

    def _request(self, method: str, path: str, json_body=None, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", XHT_TIMEOUT)
        if json_body is not None:
            kwargs["json"] = json_body
        else:
            kwargs.setdefault("json", {})

        for attempt in range(1, XHT_RETRY_COUNT + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        return {"code": -1, "msg": f"响应非JSON: {resp.text[:200]}"}
                    # 业务成功 code == 0
                    if data.get("code") == 0:
                        return data
                    # 已签到等场景可能 msg 中包含，交给调用方判断
                    return data
                elif resp.status_code == 401:
                    self._log("Token 已失效，请通过 QQ 机器人重新登录！")
                    return {"code": -1, "msg": "Token已失效"}
                else:
                    self._log(f"请求失败 [{method}] {path} -> HTTP {resp.status_code}")
                    if attempt < XHT_RETRY_COUNT:
                        time.sleep(2)
            except requests.exceptions.RequestException as e:
                self._log(f"请求异常 [{method}] {path} -> {e}")
                if attempt < XHT_RETRY_COUNT:
                    time.sleep(3)
        return {"code": -1, "msg": "请求超时或网络异常"}

    def get_user_info(self) -> bool:
        data = self._request("POST", "/api/app/personal/get")
        if data.get("code") == 0:
            user = data.get("data", {})
            self.nickname = user.get("nickname") or user.get("mobile") or self.nickname
            score = user.get("score", 0)
            mobile = user.get("mobile", "")
            self._log(f"用户: {self.nickname} | 手机号: {mobile} | 当前积分: {score}")
            return True
        else:
            self._log(f"获取用户信息失败: {data.get('msg', '未知错误')}")
            return False

    def get_score_info(self):
        """查询积分、签到天数、任务进度"""
        data = self._request("POST", "/api/app/personal/score/info")
        if data.get("code") == 0:
            info = data.get("data", {})
            sign_title = info.get("signTitle", "")
            total_score = info.get("totalScore", 0)
            today_point = info.get("todayPoint", 0)
            self._log(f"{sign_title} | 总积分: {total_score} | 今日积分: {today_point}")

            jobs = info.get("jobs", [])
            for job in jobs:
                title = job.get("title", "")
                status = job.get("status", "0")
                progress = job.get("progress", 0)
                total = job.get("totalProgress", 0)
                status_text = "已完成" if status == "1" else "未完成"
                self._log(f"任务: {title} ({status_text} {progress}/{total})")
            return info
        else:
            self._log(f"获取积分信息失败: {data.get('msg', '未知错误')}")
        return None

    def get_score_total(self):
        """查询积分汇总"""
        data = self._request("POST", "/api/app/personal/score/total")
        if data.get("code") == 0:
            d = data.get("data", {})
            score = d.get("score", 0)
            increase = d.get("increaseScore", 0)
            reduce = d.get("reduceScore", 0)
            self._log(f"积分汇总: 可用{score} | 累计获得{increase} | 累计消耗{reduce}")
            return d
        return None

    def sign_in(self) -> bool:
        self._log("开始每日签到...")
        data = self._request("POST", "/api/app/personal/score/sign")
        if data.get("code") == 0:
            d = data.get("data", {})
            title = d.get("title", "")
            status = d.get("status", "")
            if status == "signed" or "已签到" in title:
                self._log(f"签到状态: {title}")
                return True
            increase = d.get("increaseScore", "未知")
            self._log(f"签到成功！获得积分: {increase}")
            return True
        else:
            msg = data.get("msg", "未知错误")
            if "已签到" in msg or "已经签到" in msg:
                self._log("今日已签到")
                return True
            self._log(f"签到失败: {msg}")
            return False

    def get_article_list(self, page: int = 1, page_size: int = 10, channel_id: str = "4b63be60cfea4ec3aa1c6d9147745c49") -> list:
        """获取新闻列表（用于阅读任务）"""
        body = {
            "orderBy": "release_desc",
            "channel": {"id": channel_id},
            "pageSize": str(page_size),
            "pageNo": page,
        }
        data = self._request("POST", "/api/app/news/content/list", json_body=body)
        if data.get("code") == 0:
            return data.get("data", {}).get("records", [])
        return []

    def browse_article(self, article: dict) -> bool:
        """模拟浏览文章（目前仅调用新闻列表，因为抓包未捕获阅读上报接口）"""
        title = article.get("title", "")
        content_id = article.get("contentId", "")
        article_id = article.get("id", "")
        self._log(f"浏览文章: {title[:30]}... (ID:{article_id})")
        # 随机停留，模拟阅读时长
        stay = random.randint(3, 8)
        time.sleep(min(stay, 3))
        return True

    def do_browse_articles(self):
        if not XHT_BROWSE_ARTICLE:
            self._log("浏览文章任务已关闭")
            return
        self._log(f"开始浏览文章任务 (目标: {XHT_BROWSE_COUNT}篇)...")
        browsed = 0
        page = 1
        while browsed < XHT_BROWSE_COUNT and page <= 5:
            articles = self.get_article_list(page=page, page_size=10)
            if not articles:
                self._log("未获取到文章列表，停止浏览")
                break
            for article in articles:
                if browsed >= XHT_BROWSE_COUNT:
                    break
                if self.browse_article(article):
                    browsed += 1
                time.sleep(random.uniform(1, 3))
            page += 1
        self._log(f"浏览文章完成，共浏览 {browsed} 篇")

    def run(self):
        self._log("=" * 40)
        self._log("徐汇通自动任务开始")
        self._log("=" * 40)

        if not self.get_user_info():
            self._log("用户校验失败，跳过本次任务")
            return self.results

        self.get_score_total()
        self.get_score_info()
        self.sign_in()
        self.do_browse_articles()

        self._log("=" * 40)
        self._log("徐汇通自动任务完成")
        self._log("=" * 40)

        return self.results


# ============================================================
# 主函数
# ============================================================
def main():
    # 优先使用 .env 中的 XHT_TOKEN，其次从青龙面板，最后从本地文件读取
    tokens = XHT_TOKENS
    if not tokens:
        tokens = get_tokens_from_qinglong()
    if not tokens:
        tokens = get_tokens_from_local()

    if not tokens:
        logger.warning(
            "没有有效的 Token！\n"
            "请通过 QQ 机器人交互登录后，Token 会自动写入本地文件。\n"
            "也可手动在青龙面板环境变量中添加 XHT_TOKEN。"
        )
        sys.exit(0)

    logger.info(f"共检测到 {len(tokens)} 个有效账号")
    all_results = []

    for i, token in enumerate(tokens):
        client = XHTClient(token=token, index=i)
        try:
            results = client.run()
            all_results.append((client.nickname, results))
        except Exception as e:
            logger.error(f"[账号{i + 1}] 执行异常: {e}", exc_info=True)
            all_results.append((f"账号{i + 1}", [f"执行异常: {e}"]))

    # 汇总通知
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "徐汇通自动化任务报告"
    lines = [f"执行时间: {now}", f"账号数量: {len(tokens)}", ""]
    for nickname, results in all_results:
        lines.append(f"【{nickname}】")
        for r in results:
            lines.append(f"  {r}")
        lines.append("")

    content = "\n".join(lines)
    logger.info("\n" + "=" * 50)
    logger.info("任务报告汇总")
    logger.info("=" * 50)
    logger.info(content)

    Notify.send(title, content)


if __name__ == "__main__":
    main()
