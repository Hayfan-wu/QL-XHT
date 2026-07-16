#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 自动签到脚本
适用于青龙面板，纯手动部署

基于真实抓包接口重写：
  - 业务域名：https://app.xuhuimedia.cn/media-basic-port
  - 认证方式：HTTP Header token (JWT)

部署方式：
  1. 在青龙面板「环境变量」中添加 XHT_TOKEN（多账号用 & 分隔）
  2. 或在本脚本同目录下创建 .env 文件，写入 XHT_TOKEN=你的token
  3. 在青龙面板创建定时任务执行 python3 xht.py

功能：
  1. 每日签到
  2. 积分信息查询
  3. 多账号支持（从环境变量 XHT_TOKEN 读取）
  4. 多种推送通知

注意：阅读文章和观看视频任务无法通过 HTTP API 完成，
      这些任务需要原生 APP 内操作（rmt:// 桥协议）。
      详见 xht_simulate.py（模拟）和 xht_capture.py（抓包分析）。
"""

import os
import sys
import time
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
# 从项目 .env 文件加载配置（可选）
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_SCRIPT_DIR, ".env")


def _load_env():
    """从 .env 文件加载环境变量（不覆盖已存在的）"""
    if not os.path.isfile(_ENV_FILE):
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


# --- 业务配置 ---
XHT_BASE_URL = get_env("XHT_BASE_URL", "https://app.xuhuimedia.cn/media-basic-port").rstrip("/")
XHT_TIMEOUT = int(get_env("XHT_TIMEOUT", "15"))
XHT_RETRY_COUNT = int(get_env("XHT_RETRY_COUNT", "3"))
XHT_SITE_ID = get_env("XHT_SITE_ID", "310104")

# 设备标识
XHT_DEVICE_ID = get_env("XHT_DEVICE_ID", "")
if not XHT_DEVICE_ID or len(XHT_DEVICE_ID) != 32:
    base = os.path.basename(_SCRIPT_DIR) + "_xht_device"
    XHT_DEVICE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, base).hex.replace("-", "")[:32]

# ════════════════════════════════════════════════════════════
# ✅ Token 环境变量名：XHT_TOKEN
# 多账号用 & 分隔，例如：token1&token2&token3
# 在青龙面板「环境变量」中添加：
#   名称：XHT_TOKEN
#   值：  eyJ0eXAiOiJKV1QiLCJh...
# ════════════════════════════════════════════════════════════
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
DEFAULT_UA = "xu hui tong/2.5.0 (iPhone; iOS 26.5; Scale/3.00)"


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
            pass
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

    def _log(self, msg: str):
        logger.info(f"[账号{self.index + 1}] {msg}")

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
                    if data.get("code") == 0:
                        return data
                    return data
                elif resp.status_code == 401:
                    self._log("Token 已失效，请重新获取 Token 后更新 XHT_TOKEN 环境变量")
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
            self._log(f"用户: {self.nickname} | 手机号: {mobile} | 积分: {score}")
            return True
        else:
            self._log(f"获取用户信息失败: {data.get('msg', '未知错误')}")
            return False

    def get_score_info(self):
        data = self._request("POST", "/api/app/personal/score/info")
        if data.get("code") == 0:
            info = data.get("data", {})
            sign_title = info.get("signTitle", "")
            total_score = info.get("totalScore", 0)
            today_point = info.get("todayPoint", 0)
            self._log(f"{sign_title} | 总积分: {total_score} | 今日积分: {today_point}")
            return info
        else:
            self._log(f"获取积分信息失败: {data.get('msg', '未知错误')}")
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

    def run(self):
        self.stats = {"sign": False, "score": 0, "today": 0}

        if not self.get_user_info():
            self._log("用户校验失败，跳过本次任务")
            return self.stats

        info = self.get_score_info()
        if info:
            self.stats["score"] = info.get("totalScore", 0)
            self.stats["today"] = info.get("todayPoint", 0)

        self.stats["sign"] = self.sign_in()

        # 签到后重新获取最新积分
        time.sleep(1)
        final_info = self.get_score_info()
        if final_info:
            self.stats["score"] = final_info.get("totalScore", 0)
            self.stats["today"] = final_info.get("todayPoint", 0)

        self._log("=" * 40)
        self._log("徐汇通签到完成")
        self._log("=" * 40)

        return self.stats


# ============================================================
# 主函数
# ============================================================
def main():
    tokens = XHT_TOKENS

    if not tokens:
        logger.error("")
        logger.error("╔══════════════════════════════════════════════════════════════╗")
        logger.error("║  ❌ 没有有效的 Token！                                      ║")
        logger.error("║                                                            ║")
        logger.error("║  请在青龙面板「环境变量」中添加：                           ║")
        logger.error("║    名称：XHT_TOKEN                                         ║")
        logger.error("║    值：  你的JWT Token（多账号用 & 分隔）                   ║")
        logger.error("║                                                            ║")
        logger.error("║  或在本脚本同目录创建 .env 文件，写入：                     ║")
        logger.error("║    XHT_TOKEN=你的token                                      ║")
        logger.error("╚══════════════════════════════════════════════════════════════╝")
        logger.error("")
        sys.exit(0)

    logger.info(f"共检测到 {len(tokens)} 个账号")
    all_stats = []

    for i, token in enumerate(tokens):
        client = XHTClient(token=token, index=i)
        try:
            stats = client.run()
            all_stats.append((client.nickname, stats))
        except Exception as e:
            logger.error(f"[账号{i + 1}] 执行异常: {e}", exc_info=True)
            all_stats.append((f"账号{i + 1}", {"sign": False, "score": 0, "today": 0, "error": str(e)}))

    # 汇总通知（精简格式）
    now = datetime.now().strftime("%m-%d %H:%M")
    lines = [f"徐汇通日报  {now}", ""]
    for nickname, s in all_stats:
        if s.get("error"):
            lines.append(f"{nickname}  ❌ {s['error']}")
        else:
            sign = "✓" if s.get("sign") else "✗"
            score = s.get("score", 0)
            today = s.get("today", 0)
            lines.append(f"{nickname}")
            lines.append(f"积分 {score}  +{today}  签到{sign}")
        lines.append("")

    content = "\n".join(lines)
    logger.info(content)
    Notify.send("徐汇通日报", content)


if __name__ == "__main__":
    main()