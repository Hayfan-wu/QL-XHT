#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 自动签到 & 日常任务脚本
适用于青龙面板，配置均从项目 .env 文件读取
登录方式：由 QL-Bot 统一管理，Token 通过青龙 Open API 写入

功能：
  1. 每日签到
  2. 签到信息查询
  3. 模拟浏览文章
  4. 模拟分享
  5. 多账号支持（从青龙面板环境变量读取 XHT_TOKEN）
  6. 多种推送通知
"""

import os
import sys
import time
import random
import logging
import requests
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
XHT_BASE_URL = get_env("XHT_BASE_URL", "https://shrmtxh.shmedia.tech").rstrip("/")
XHT_TIMEOUT = int(get_env("XHT_TIMEOUT", "15"))
XHT_RETRY_COUNT = int(get_env("XHT_RETRY_COUNT", "3"))
XHT_BROWSE_ARTICLE = get_env("XHT_BROWSE_ARTICLE", "true").lower() == "true"
XHT_BROWSE_COUNT = int(get_env("XHT_BROWSE_COUNT", "5"))
XHT_SHARE = get_env("XHT_SHARE", "true").lower() == "true"
XHT_SHARE_COUNT = int(get_env("XHT_SHARE_COUNT", "1"))

# --- 青龙 Open API（用于读取 Token）---
QL_URL = get_env("QL_URL", "").rstrip("/")
QL_CLIENT_ID = get_env("QL_CLIENT_ID", "")
QL_CLIENT_SECRET = get_env("QL_CLIENT_SECRET", "")

# --- Token（优先从青龙面板读取，也可直接设置）---
# 由 QL-Bot 交互登录后自动写入青龙面板，脚本运行时读取
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

# 默认 User-Agent
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/131.0.6778.200 Mobile Safari/537.36"
)


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

        # 2. 获取环境变量
        env_url = f"{QL_URL}/open/envs"
        env_resp = requests.get(env_url, params={
            "token": ql_token,
            "searchValue": "XHT_TOKEN",
        }, timeout=10)
        if env_resp.status_code != 200:
            logger.warning(f"获取青龙环境变量失败: HTTP {env_resp.status_code}")
            return []
        env_data = env_resp.json()
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
    """徐汇通 API 交互客户端"""

    def __init__(self, token: str, index: int = 0):
        self.token = token
        self.index = index
        self.base_url = XHT_BASE_URL
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/plain, */*",
                "Authori-zation": token,
                "Authorization": token,
            }
        )
        self.nickname = f"账号{index + 1}"
        self.results = []

    def _log(self, msg: str):
        logger.info(f"[账号{self.index + 1}] {msg}")
        self.results.append(msg)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", XHT_TIMEOUT)
        for attempt in range(1, XHT_RETRY_COUNT + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return {"status": -1, "msg": f"响应非JSON: {resp.text[:200]}"}
                elif resp.status_code == 401:
                    self._log("Token 已失效，请通过 QQ 机器人重新登录！")
                    return {"status": -1, "msg": "Token已失效"}
                else:
                    self._log(f"请求失败 [{method}] {path} -> HTTP {resp.status_code}")
                    if attempt < XHT_RETRY_COUNT:
                        time.sleep(2)
            except requests.exceptions.RequestException as e:
                self._log(f"请求异常 [{method}] {path} -> {e}")
                if attempt < XHT_RETRY_COUNT:
                    time.sleep(3)
        return {"status": -1, "msg": "请求超时或网络异常"}

    def get_user_info(self) -> bool:
        data = self._request("POST", "/api/user")
        if data.get("status") == 200:
            user = data.get("data", {})
            self.nickname = user.get("nickname", self.nickname)
            integral = user.get("integral", 0)
            self._log(f"用户: {self.nickname} | 当前积分: {integral}")
            return True
        else:
            self._log(f"获取用户信息失败: {data.get('msg', '未知错误')}")
            return False

    def sign_in(self) -> bool:
        self._log("开始每日签到...")
        data = self._request("POST", "/sign/integral")
        if data.get("status") == 200:
            integral = data.get("data", {}).get("integral", "未知")
            self._log(f"签到成功！获得积分: {integral}")
            return True
        else:
            msg = data.get("msg", "未知错误")
            if "已签到" in msg or "已经签到" in msg:
                self._log("今日已签到")
                return True
            self._log(f"签到失败: {msg}")
            return False

    def get_sign_info(self):
        data = self._request(
            "POST", "/sign/user",
            json={"sign": "1", "integral": "1", "all": "1"},
            headers={"Content-Type": "application/json"},
        )
        if data.get("status") == 200:
            info = data.get("data", {})
            sign_num = info.get("sign_num", 0)
            integral = info.get("integral", 0)
            self._log(f"连续签到: {sign_num} 天 | 总积分: {integral}")
            return info
        return None

    def get_sign_config(self):
        data = self._request("GET", "/sign/config")
        if data.get("status") == 200:
            config = data.get("data", [])
            if config:
                self._log("签到积分规则:")
                for item in config:
                    day = item.get("day", "")
                    num = item.get("sign_num", "")
                    self._log(f"  第{day}天: +{num}积分")
            return config
        return None

    def get_article_list(self, page: int = 1, limit: int = 10) -> list:
        data = self._request("GET", f"/api/article/category/list/{page}/{limit}")
        articles = []
        if data.get("status") == 200:
            articles = data.get("data", {}).get("list", [])
        if not articles:
            data = self._request("GET", f"/api/article/list/{page}/{limit}")
            if data.get("status") == 200:
                articles = data.get("data", {}).get("list", [])
        return articles

    def browse_article(self, article_id: int, title: str = "") -> bool:
        data = self._request("GET", f"/api/article/details/{article_id}")
        if data.get("status") == 200:
            self._log(f"浏览文章成功: {title or f'ID:{article_id}'}")
            stay = random.randint(5, 15)
            time.sleep(min(stay, 3))
            self._request(
                "POST", "/api/user/set_visit",
                data={"url": f"/pages/news/detail/index?id={article_id}", "stay_time": str(stay)},
            )
            return True
        return False

    def do_browse_articles(self):
        if not XHT_BROWSE_ARTICLE:
            self._log("浏览文章任务已关闭")
            return
        self._log(f"开始浏览文章任务 (目标: {XHT_BROWSE_COUNT}篇)...")
        browsed = 0
        for page in range(1, 5):
            if browsed >= XHT_BROWSE_COUNT:
                break
            articles = self.get_article_list(page=page, limit=10)
            if not articles:
                continue
            for article in articles:
                if browsed >= XHT_BROWSE_COUNT:
                    break
                aid = article.get("id", 0)
                title = article.get("title", "")
                if aid and self.browse_article(aid, title):
                    browsed += 1
                time.sleep(random.uniform(1, 3))
        self._log(f"浏览文章完成，共浏览 {browsed} 篇")

    def do_share(self):
        if not XHT_SHARE:
            self._log("分享任务已关闭")
            return
        self._log(f"开始分享任务 (目标: {XHT_SHARE_COUNT}次)...")
        for i in range(XHT_SHARE_COUNT):
            data = self._request("POST", "/api/user/share")
            if data.get("status") == 200:
                self._log(f"分享成功 ({i + 1}/{XHT_SHARE_COUNT})")
            else:
                self._log(f"分享结果: {data.get('msg', '未知')}")
            time.sleep(random.uniform(1, 2))
        self._log("分享任务完成")

    def run(self):
        self._log("=" * 40)
        self._log("徐汇通自动任务开始")
        self._log("=" * 40)

        self.get_user_info()
        self.sign_in()
        self.get_sign_info()
        self.get_sign_config()
        self.do_browse_articles()
        self.do_share()

        self._log("=" * 40)
        self._log("徐汇通自动任务完成")
        self._log("=" * 40)

        return self.results


# ============================================================
# 主函数
# ============================================================
def main():
    # 优先使用 .env 中的 XHT_TOKEN，其次从青龙面板读取
    tokens = XHT_TOKENS
    if not tokens:
        tokens = get_tokens_from_qinglong()

    if not tokens:
        logger.warning(
            "没有有效的 Token！\n"
            "请通过 QQ 机器人交互登录后，Token 会自动写入青龙面板。\n"
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