#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 自动签到 & 日常任务脚本
适用于青龙面板，配置均从项目 .env 文件读取
登录方式：QQ 机器人交互登录（手机号 + 验证码）

功能：
  1. QQ 机器人交互式手机号验证码登录（WebSocket / HTTP）
  2. Token 自动持久化与刷新
  3. 每日签到
  4. 签到信息查询
  5. 模拟浏览文章
  6. 模拟分享
  7. 多账号支持
  8. 多种推送通知
"""

import os
import sys
import json
import time
import random
import logging
import threading
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
# 路径常量
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_SCRIPT_DIR, ".env")
_DATA_DIR = os.path.join(_SCRIPT_DIR, "data")
_TOKENS_FILE = os.path.join(_DATA_DIR, "tokens.json")

# 确保 data 目录存在
os.makedirs(_DATA_DIR, exist_ok=True)


# ============================================================
# 从项目 .env 文件加载配置
# ============================================================
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


XHT_BASE_URL = get_env("XHT_BASE_URL", "https://shrmtxh.shmedia.tech").rstrip("/")
TIMEOUT = int(get_env("XHT_TIMEOUT", "15"))
RETRY_COUNT = int(get_env("XHT_RETRY_COUNT", "3"))
BROWSE_ARTICLE = get_env("XHT_BROWSE_ARTICLE", "true").lower() == "true"
BROWSE_COUNT = int(get_env("XHT_BROWSE_COUNT", "5"))
ENABLE_SHARE = get_env("XHT_SHARE", "true").lower() == "true"
SHARE_COUNT = int(get_env("XHT_SHARE_COUNT", "1"))

# QQ 机器人配置
QQ_WS_URL = get_env("QQ_WS_URL", "")
QQ_HTTP_URL = get_env("QQ_HTTP_URL", "")
QQ_ADMIN_QQ = get_env("QQ_ADMIN_QQ", "")

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
# Token 持久化管理
# ============================================================
class TokenStore:
    """Token 持久化存储，支持多账号"""

    @staticmethod
    def load() -> list:
        """加载所有已保存的 token 记录"""
        if not os.path.isfile(_TOKENS_FILE):
            return []
        try:
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    @staticmethod
    def save(accounts: list):
        """保存 token 记录到文件"""
        with open(_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)

    @staticmethod
    def get_valid_tokens() -> list:
        """获取所有有效的 token（未过期）"""
        accounts = TokenStore.load()
        now = time.time()
        valid = []
        for acc in accounts:
            token = acc.get("token", "")
            if not token:
                continue
            expire = acc.get("expires_time", 0)
            # 如果没有过期时间或未过期
            if not expire or expire > now:
                valid.append(token)
            else:
                logger.info(f"账号 {acc.get('phone', '未知')} Token 已过期")
        return valid

    @staticmethod
    def add_or_update(phone: str, token: str, expires_time: float = 0, nickname: str = ""):
        """添加或更新账号 token"""
        accounts = TokenStore.load()
        found = False
        for acc in accounts:
            if acc.get("phone") == phone:
                acc["token"] = token
                acc["expires_time"] = expires_time
                acc["nickname"] = nickname
                acc["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                found = True
                break
        if not found:
            accounts.append({
                "phone": phone,
                "token": token,
                "expires_time": expires_time,
                "nickname": nickname,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        TokenStore.save(accounts)

    @staticmethod
    def remove(phone: str):
        """移除指定手机号的账号"""
        accounts = TokenStore.load()
        accounts = [a for a in accounts if a.get("phone") != phone]
        TokenStore.save(accounts)


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
            "qq": Notify._send_qq,
        }
        fn = dispatch.get(NOTIFY_TYPE)
        if fn:
            try:
                fn(title, content)
            except Exception as e:
                logger.error(f"通知发送失败 [{NOTIFY_TYPE}]: {e}")

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

    @staticmethod
    def _send_qq(title: str, content: str):
        """通过 QQ 机器人 HTTP API 发送私聊通知"""
        if not QQ_HTTP_URL or not QQ_ADMIN_QQ:
            return
        msg = f"【{title}】\n{content}"
        QQBot.http_send_private_msg(QQ_ADMIN_QQ, msg)


# ============================================================
# QQ 机器人通信模块 (OneBot v11)
# ============================================================
class QQBot:
    """QQ 机器人通信，支持 WebSocket 和 HTTP 两种模式

    - WebSocket 模式：通过 ws:// 连接接收消息并发送回复（推荐）
    - HTTP 模式：通过 HTTP API 发送消息（仅发送，无交互）
    """

    def __init__(self):
        self.ws_url = QQ_WS_URL
        self.http_url = QQ_HTTP_URL.rstrip("/") if QQ_HTTP_URL else ""
        self.admin_qq = QQ_ADMIN_QQ
        self._ws = None
        self._ws_connected = False
        self._pending_captcha = {}  # phone -> {"key": str, "event": threading.Event, "code": str}
        self._pending_phone = {}    # session -> phone (等待验证码的手机号)
        self._lock = threading.Lock()

    # ---------- HTTP API ----------

    @staticmethod
    def _http_api(http_url: str, endpoint: str, params: dict = None) -> dict:
        """调用 OneBot HTTP API"""
        url = f"{http_url}/{endpoint}"
        try:
            resp = requests.post(url, json=params or {}, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"QQ HTTP API 调用失败: {e}")
            return {"status": "failed", "retcode": -1}

    def http_send_private_msg(self, user_id: str, message: str) -> dict:
        """通过 HTTP API 发送私聊消息"""
        if not self.http_url:
            logger.warning("QQ_HTTP_URL 未配置，无法发送消息")
            return {"status": "failed"}
        return self._http_api(self.http_url, "send_private_msg", {
            "user_id": int(user_id),
            "message": message,
        })

    def http_send_group_msg(self, group_id: str, message: str) -> dict:
        """通过 HTTP API 发送群消息"""
        if not self.http_url:
            return {"status": "failed"}
        return self._http_api(self.http_url, "send_group_msg", {
            "group_id": int(group_id),
            "message": message,
        })

    # ---------- WebSocket 连接 ----------

    def _ws_send(self, data: dict):
        """通过 WebSocket 发送数据"""
        if self._ws and self._ws_connected:
            try:
                self._ws.send(json.dumps(data))
            except Exception as e:
                logger.error(f"WebSocket 发送失败: {e}")
                self._ws_connected = False

    def _ws_send_private(self, user_id: str, message: str):
        """通过 WebSocket 发送私聊消息"""
        self._ws_send({
            "action": "send_private_msg",
            "params": {
                "user_id": int(user_id),
                "message": message,
            },
            "echo": f"send_pm_{int(time.time())}",
        })

    def _send_to_admin(self, message: str):
        """向管理员 QQ 发送消息"""
        if not self.admin_qq:
            logger.warning("QQ_ADMIN_QQ 未配置")
            return
        if self._ws_connected:
            self._ws_send_private(self.admin_qq, message)
        else:
            self.http_send_private_msg(self.admin_qq, message)

    def _handle_message(self, event: dict):
        """处理收到的 QQ 消息"""
        # 仅处理私聊消息
        post_type = event.get("post_type", "")
        message_type = event.get("message_type", "")
        if post_type != "message" or message_type != "private":
            return

        user_id = str(event.get("user_id", ""))
        raw_msg = event.get("message", "")
        # 提取纯文本（兼容 CQ 码和数组格式）
        if isinstance(raw_msg, list):
            text = "".join(
                seg.get("data", {}).get("text", "")
                for seg in raw_msg
                if seg.get("type") == "text"
            ).strip()
        else:
            text = str(raw_msg).strip()

        # 权限检查：仅管理员可操作
        if user_id != self.admin_qq:
            return

        logger.info(f"收到 QQ 消息 [{user_id}]: {text}")

        # 检查是否在等待验证码
        with self._lock:
            for phone, info in list(self._pending_captcha.items()):
                if info["event"].is_set():
                    continue
                # 用户发送的是验证码（纯数字，通常 4-6 位）
                if text.isdigit() and 4 <= len(text) <= 8:
                    info["code"] = text
                    info["event"].set()
                    self._ws_send_private(user_id, f"验证码已收到，正在登录...")
                    return
                elif text.lower() == "cancel" or text == "取消":
                    info["code"] = "__CANCEL__"
                    info["event"].set()
                    self._ws_send_private(user_id, "已取消登录")
                    return

        # 指令处理
        if text.startswith("登录") or text.startswith("添加"):
            # 解析手机号：支持 "登录 13800138000" 或 "登录" 后通过多轮对话获取
            parts = text.split()
            phone = ""
            if len(parts) >= 2:
                phone = parts[1].strip()
            if phone and len(phone) == 11 and phone.isdigit():
                self._start_login(user_id, phone)
            else:
                self._ws_send_private(user_id, "请输入手机号（11位）：")
                with self._lock:
                    self._pending_phone[user_id] = time.time()

        elif text.isdigit() and len(text) == 11:
            # 可能是单独发送的手机号
            with self._lock:
                if user_id in self._pending_phone:
                    del self._pending_phone[user_id]
            self._start_login(user_id, text)

        elif text == "账号列表" or text == "列表":
            self._show_accounts(user_id)

        elif text.startswith("删除") or text.startswith("移除"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 11:
                self._remove_account(user_id, parts[1])
            else:
                self._ws_send_private(user_id, "请输入要删除的手机号，例如：删除 13800138000")

        elif text == "帮助" or text == "help":
            self._ws_send_private(user_id, (
                "=== 徐汇通机器人命令 ===\n"
                "登录/添加 [手机号] - 登录新账号\n"
                "  例如：登录 13800138000\n"
                "  或直接发送：登录\n"
                "账号列表/列表 - 查看已登录账号\n"
                "删除/移除 [手机号] - 删除账号\n"
                "帮助/help - 显示帮助"
            ))

    def _start_login(self, user_id: str, phone: str):
        """发起登录流程：发送验证码"""
        self._ws_send_private(user_id, f"正在为 {phone} 发送验证码，请稍候...")

        # 1. 获取验证码 key
        key_resp = self._xht_request("GET", "/api/verify_code")
        if key_resp.get("status") != 200:
            msg = key_resp.get("msg", "获取验证码失败")
            self._ws_send_private(user_id, f"获取验证码失败：{msg}\n请稍后重试。")
            return

        key = key_resp.get("data", {}).get("key", "")
        if not key:
            self._ws_send_private(user_id, "获取验证码 key 失败，请稍后重试。")
            return

        # 2. 发送短信验证码
        sms_resp = self._xht_request("POST", "/api/register/verify", json={
            "phone": phone,
            "type": "login",
        }, headers={"Content-Type": "application/json"})

        if sms_resp.get("status") != 200:
            msg = sms_resp.get("msg", "发送验证码失败")
            self._ws_send_private(user_id, f"发送验证码失败：{msg}\n请检查手机号是否正确。")
            return

        # 3. 等待用户输入验证码
        event = threading.Event()
        with self._lock:
            self._pending_captcha[phone] = {
                "key": key,
                "event": event,
                "code": "",
            }

        self._ws_send_private(user_id, (
            f"验证码已发送到 {phone}\n"
            f"请回复验证码（4-6位数字）\n"
            f"回复「取消」可取消本次登录"
        ))

        # 等待用户输入（最长 5 分钟）
        event.wait(timeout=300)

        with self._lock:
            info = self._pending_captcha.pop(phone, None)

        if not info or not info["code"]:
            self._ws_send_private(user_id, "等待验证码超时，请重新发起登录。")
            return

        if info["code"] == "__CANCEL__":
            return

        # 4. 使用验证码登录
        login_resp = self._xht_request("POST", "/api/login/mobile", json={
            "phone": phone,
            "captcha": info["code"],
            "spread": "0",
        }, headers={"Content-Type": "application/json"})

        if login_resp.get("status") == 200:
            token = login_resp.get("data", {}).get("token", "")
            expires = login_resp.get("data", {}).get("expires_time", 0)
            if token:
                # 转换过期时间
                if isinstance(expires, (int, float)) and expires > 0:
                    if expires < 1e12:
                        expires = time.time() + expires
                else:
                    expires = 0

                TokenStore.add_or_update(phone, token, expires)
                self._ws_send_private(user_id, (
                    f"登录成功！\n"
                    f"手机号：{phone}\n"
                    f"Token 已保存，将自动执行每日签到任务。"
                ))
                logger.info(f"QQ 交互登录成功: {phone}")
            else:
                self._ws_send_private(user_id, "登录成功但未获取到 Token，请重试。")
        else:
            msg = login_resp.get("msg", "登录失败")
            self._ws_send_private(user_id, f"登录失败：{msg}\n请检查验证码是否正确。")

    def _show_accounts(self, user_id: str):
        """显示已登录的账号列表"""
        accounts = TokenStore.load()
        if not accounts:
            self._ws_send_private(user_id, "当前没有任何已登录的账号。")
            return

        lines = ["=== 已登录账号 ==="]
        for i, acc in enumerate(accounts, 1):
            phone = acc.get("phone", "未知")
            nickname = acc.get("nickname", "")
            updated = acc.get("updated_at", "")
            token = acc.get("token", "")
            expire = acc.get("expires_time", 0)
            # 状态判断
            status = "有效"
            if expire and expire < time.time():
                status = "已过期"
            lines.append(f"{i}. {phone} {nickname} [{status}] 更新: {updated}")

        self._ws_send_private(user_id, "\n".join(lines))

    def _remove_account(self, user_id: str, phone: str):
        """删除指定账号"""
        TokenStore.remove(phone)
        self._ws_send_private(user_id, f"已删除账号：{phone}")

    @staticmethod
    def _xht_request(method: str, path: str, **kwargs) -> dict:
        """徐汇通 API 请求（无鉴权）"""
        url = f"{XHT_BASE_URL}{path}"
        kwargs.setdefault("timeout", TIMEOUT)
        kwargs.setdefault("headers", {})
        kwargs["headers"].setdefault("User-Agent", DEFAULT_UA)
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return {"status": -1, "msg": f"响应非JSON: {resp.text[:200]}"}
            return {"status": -1, "msg": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": -1, "msg": str(e)}

    def start_ws(self):
        """启动 WebSocket 连接监听"""
        if not self.ws_url:
            logger.info("QQ_WS_URL 未配置，WebSocket 模式未启用")
            return

        try:
            import websocket
        except ImportError:
            logger.error("需要安装 websocket-client：pip install websocket-client")
            return

        def on_message(ws, message):
            try:
                data = json.loads(message)
                self._handle_message(data)
            except json.JSONDecodeError:
                pass

        def on_error(ws, error):
            logger.error(f"WebSocket 错误: {error}")

        def on_close(ws, *args):
            self._ws_connected = False
            logger.warning("WebSocket 连接已断开，30秒后重连...")
            time.sleep(30)
            self.start_ws()

        def on_open(ws):
            self._ws_connected = True
            self._ws = ws
            logger.info(f"QQ 机器人 WebSocket 已连接: {self.ws_url}")
            if self.admin_qq:
                self._ws_send_private(self.admin_qq, "徐汇通机器人已上线\n发送「帮助」查看可用命令")

        logger.info(f"正在连接 QQ 机器人 WebSocket: {self.ws_url}")
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        # 在后台线程运行
        wst = threading.Thread(target=ws.run_forever, daemon=True)
        wst.start()


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
                    self._log("Token 已失效，请通过 QQ 机器人重新登录！")
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
                self._log("今日已签到")
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
            data = self._request("GET", f"/api/article/list/{page}/{limit}")
            if data.get("status") == 200:
                articles = data.get("data", {}).get("list", [])
        return articles

    def browse_article(self, article_id: int, title: str = "") -> bool:
        """模拟浏览文章"""
        data = self._request("GET", f"/api/article/details/{article_id}")
        if data.get("status") == 200:
            self._log(f"浏览文章成功: {title or f'ID:{article_id}'}")
            stay = random.randint(5, 15)
            time.sleep(min(stay, 3))
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
        self._log("分享任务完成")

    def run(self):
        """执行所有任务"""
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
# QQ 机器人登录服务（独立运行模式）
# ============================================================
def run_bot_service():
    """以 QQ 机器人模式运行，持续监听消息"""
    logger.info("=" * 50)
    logger.info("启动 QQ 机器人交互登录服务")
    logger.info("=" * 50)

    if not QQ_WS_URL and not QQ_HTTP_URL:
        logger.error("请先配置 QQ_WS_URL 或 QQ_HTTP_URL")
        sys.exit(1)
    if not QQ_ADMIN_QQ:
        logger.error("请先配置 QQ_ADMIN_QQ（管理员 QQ 号）")
        sys.exit(1)

    bot = QQBot()

    # 启动 WebSocket 监听
    if QQ_WS_URL:
        bot.start_ws()

    # 保持主线程运行
    logger.info("QQ 机器人服务已启动，等待指令...")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("服务已停止")


# ============================================================
# 主函数（定时任务模式）
# ============================================================
def main():
    # 检查是否有已保存的 token
    tokens = TokenStore.get_valid_tokens()

    if not tokens:
        logger.warning(
            "没有有效的 Token！\n"
            "请通过以下方式登录获取 Token：\n"
            "  1. 配置 QQ 机器人相关变量后运行: python3 xht.py --bot\n"
            "  2. 在 QQ 中向机器人发送: 登录 13800138000\n"
            f"  3. Token 将自动保存到: {_TOKENS_FILE}"
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
    # 参数解析
    if len(sys.argv) > 1:
        if sys.argv[1] in ("--bot", "-b"):
            # QQ 机器人交互登录模式
            run_bot_service()
        elif sys.argv[1] in ("--help", "-h"):
            print("用法:")
            print("  python3 xht.py          # 执行定时任务（签到等）")
            print("  python3 xht.py --bot    # 启动 QQ 机器人交互登录服务")
            print("  python3 xht.py --help   # 显示帮助")
        else:
            logger.error(f"未知参数: {sys.argv[1]}，使用 --help 查看帮助")
            sys.exit(1)
    else:
        # 默认：执行定时任务
        main()