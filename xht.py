#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 自动签到 & 日常任务脚本
适用于青龙面板，配置均从项目 .env 文件读取

功能：
  1. 每日签到
  2. 签到信息查询
  3. 模拟浏览文章
  4. 模拟分享
  5. 多账号支持
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
            # 仅在当前进程未设置该环境变量时覆盖
            if key and key not in os.environ:
                os.environ[key] = value


_load_env()


# ============================================================
# 配置读取
# ============================================================
def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


XHT_TOKENS = [t.strip() for t in get_env("XHT_TOKEN").split("&") if t.strip()]
XHT_BASE_URL = get_env("XHT_BASE_URL", "https://shrmtxh.shmedia.tech").rstrip("/")
TIMEOUT = int(get_env("XHT_TIMEOUT", "15"))
RETRY_COUNT = int(get_env("XHT_RETRY_COUNT", "3"))
BROWSE_ARTICLE = get_env("XHT_BROWSE_ARTICLE", "true").lower() == "true"
BROWSE_COUNT = int(get_env("XHT_BROWSE_COUNT", "5"))
ENABLE_SHARE = get_env("XHT_SHARE", "true").lower() == "true"
SHARE_COUNT = int(get_env("XHT_SHARE_COUNT", "1"))

# 通知配置
NOTIFY_TYPE = get_env("XHT_NOTIFY", "").lower()
PUSHPLUS_TOKEN = get_env("XHT_PUSHPLUS_TOKEN", "")
SERVERCHAN_KEY = get_env("XHT_SERVERCHAN_KEY", "")
BARK_URL = get_env("XHT_BARK_URL", "")
TG_BOT_TOKEN = get_env("XHT_TG_BOT_TOKEN", "")
TG_CHAT_ID = get_env("XHT_TG_CHAT_ID", "")
TG_API_PROXY = get_env("XHT_TG_API_PROXY", "")

# 默认 User-Agent
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/131.0.6778.200 Mobile Safari/537.36"
)


# ============================================================
# 通知模块
# ============================================================
class Notify:
    """多渠道消息推送"""

    @staticmethod
    def send(title: str, content: str):
        """根据配置发送通知"""
        if NOTIFY_TYPE == "none":
            return
        if not NOTIFY_TYPE:
            Notify._send_qinglong(title, content)
            return

        dispatch = {
            "pushplus": Notify._send_pushplus,
            "serverchan": Notify._send_serverchan,
            "bark": Notify._send_bark,
            "telegram": Notify._send_telegram,
        }
        fn = dispatch.get(NOTIFY_TYPE)
        if fn:
            try:
                fn(title, content)
            except Exception as e:
                logger.error(f"通知发送失败 [{NOTIFY_TYPE}]: {e}")

    @staticmethod
    def _send_qinglong(title: str, content: str):
        """使用青龙面板内置通知"""
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
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content.replace("\n", "<br>"),
            "template": "txt",
        }
        resp = requests.post(url, json=data, timeout=10)
        logger.info(f"PushPlus 推送结果: {resp.text}")

    @staticmethod
    def _send_serverchan(title: str, content: str):
        url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
        data = {"title": title, "desp": content}
        resp = requests.post(url, data=data, timeout=10)
        logger.info(f"Server酱 推送结果: {resp.text}")

    @staticmethod
    def _send_bark(title: str, content: str):
        url = f"{BARK_URL}/{title}/{content}"
        resp = requests.get(url, timeout=10)
        logger.info(f"Bark 推送结果: {resp.text}")

    @staticmethod
    def _send_telegram(title: str, content: str):
        api_url = "https://api.telegram.org"
        if TG_API_PROXY:
            api_url = TG_API_PROXY
        url = f"{api_url}/bot{TG_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TG_CHAT_ID,
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
        """统一请求封装，带重试"""
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", TIMEOUT)
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return {"status": -1, "msg": f"响应非JSON: {resp.text[:200]}"}
                elif resp.status_code == 401:
                    self._log("Token 已失效，请重新获取！")
                    return {"status": -1, "msg": "Token已失效"}
                else:
                    self._log(
                        f"请求失败 [{method}] {path} -> HTTP {resp.status_code}"
                    )
                    if attempt < RETRY_COUNT:
                        time.sleep(2)
            except requests.exceptions.RequestException as e:
                self._log(f"请求异常 [{method}] {path} -> {e}")
                if attempt < RETRY_COUNT:
                    time.sleep(3)
        return {"status": -1, "msg": "请求超时或网络异常"}

    def get_user_info(self) -> bool:
        """获取用户信息"""
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
        """每日签到"""
        self._log("开始每日签到...")
        data = self._request("POST", "/sign/integral")
        if data.get("status") == 200:
            integral = data.get("data", {}).get("integral", "未知")
            self._log(f"签到成功！获得积分: {integral}")
            return True
        else:
            msg = data.get("msg", "未知错误")
            if "已签到" in msg or "已经签到" in msg:
                self._log(f"今日已签到")
                return True
            self._log(f"签到失败: {msg}")
            return False

    def get_sign_info(self):
        """获取签到信息（连续签到天数等）"""
        data = self._request(
            "POST",
            "/sign/user",
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
        """获取签到配置（每天签到可得积分）"""
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
        """获取文章列表"""
        data = self._request("GET", f"/api/article/category/list/{page}/{limit}")
        articles = []
        if data.get("status") == 200:
            articles = data.get("data", {}).get("list", [])
        if not articles:
            # 备用接口
            data = self._request("GET", f"/api/article/list/{page}/{limit}")
            if data.get("status") == 200:
                articles = data.get("data", {}).get("list", [])
        return articles

    def browse_article(self, article_id: int, title: str = "") -> bool:
        """模拟浏览文章"""
        data = self._request("GET", f"/api/article/details/{article_id}")
        if data.get("status") == 200:
            self._log(f"浏览文章成功: {title or f'ID:{article_id}'}")
            # 模拟停留时间
            stay = random.randint(5, 15)
            time.sleep(min(stay, 3))  # 脚本中缩短等待
            # 上报访问记录
            self._request(
                "POST",
                "/api/user/set_visit",
                data={"url": f"/pages/news/detail/index?id={article_id}", "stay_time": str(stay)},
            )
            return True
        return False

    def do_browse_articles(self):
        """执行浏览文章任务"""
        if not BROWSE_ARTICLE:
            self._log("浏览文章任务已关闭")
            return
        self._log(f"开始浏览文章任务 (目标: {BROWSE_COUNT}篇)...")
        browsed = 0
        for page in range(1, 5):
            if browsed >= BROWSE_COUNT:
                break
            articles = self.get_article_list(page=page, limit=10)
            if not articles:
                continue
            for article in articles:
                if browsed >= BROWSE_COUNT:
                    break
                aid = article.get("id", 0)
                title = article.get("title", "")
                if aid and self.browse_article(aid, title):
                    browsed += 1
                time.sleep(random.uniform(1, 3))
        self._log(f"浏览文章完成，共浏览 {browsed} 篇")

    def do_share(self):
        """执行分享任务"""
        if not ENABLE_SHARE:
            self._log("分享任务已关闭")
            return
        self._log(f"开始分享任务 (目标: {SHARE_COUNT}次)...")
        for i in range(SHARE_COUNT):
            data = self._request("POST", "/api/user/share")
            if data.get("status") == 200:
                self._log(f"分享成功 ({i + 1}/{SHARE_COUNT})")
            else:
                self._log(f"分享结果: {data.get('msg', '未知')}")
            time.sleep(random.uniform(1, 2))
        self._log(f"分享任务完成")

    def run(self):
        """执行所有任务"""
        self._log(f"{'='*40}")
        self._log(f"徐汇通自动任务开始")
        self._log(f"{'='*40}")

        # 1. 获取用户信息
        self.get_user_info()

        # 2. 每日签到
        self.sign_in()

        # 3. 签到信息
        self.get_sign_info()
        self.get_sign_config()

        # 4. 浏览文章
        self.do_browse_articles()

        # 5. 分享
        self.do_share()

        self._log(f"{'='*40}")
        self._log(f"徐汇通自动任务完成")
        self._log(f"{'='*40}")

        return self.results


# ============================================================
# 主函数
# ============================================================
def main():
    if not XHT_TOKENS:
        logger.error(
            "未配置 XHT_TOKEN！\n"
            f"请在 {_ENV_FILE} 文件中设置 XHT_TOKEN 变量。\n"
            "获取方式：使用抓包工具打开徐汇通APP，找到请求头中的 Authori-zation 字段值。"
        )
        sys.exit(1)

    logger.info(f"共检测到 {len(XHT_TOKENS)} 个账号")
    all_results = []

    for i, token in enumerate(XHT_TOKENS):
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
    lines = [f"执行时间: {now}", f"账号数量: {len(XHT_TOKENS)}", ""]
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

    # 发送通知
    Notify.send(title, content)


if __name__ == "__main__":
    main()