# -*- coding: utf-8 -*-
"""徐汇通 (XHT) QQ 机器人控制插件

由 QL-Bot 自动扫描 /opt/QL-XHT/bot_plugins/ 加载。
负责交互登录、Token 管理、查询状态、触发执行。
"""

import os
import re
import sys
import time
import requests

# 兼容 QL-Bot 的导入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.plugins.base import Plugin
from bot.project_env import ProjectEnv
from bot.ql_api import QingLongAPI
from bot.session import sessions


class XHTAPI:
    """徐汇通登录相关 API"""

    def __init__(self, base_url="https://shrmtxh.shmedia.tech"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                    "Chrome/131.0.6778.200 Mobile Safari/537.36"
                ),
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
            }
        )

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", 15)
        try:
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return {"status": -1, "msg": f"响应非JSON: {resp.text[:200]}"}
            return {"status": -1, "msg": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": -1, "msg": str(e)}

    def send_sms(self, phone: str):
        """发送短信验证码"""
        # 先获取 verify_code key
        key_resp = self._request("GET", "/api/verify_code")
        if key_resp.get("status") != 200:
            return False, key_resp.get("msg", "获取验证码 key 失败")

        sms_resp = self._request(
            "POST",
            "/api/register/verify",
            json={"phone": phone, "type": "login"},
        )
        if sms_resp.get("status") == 200:
            return True, "验证码已发送"
        return False, sms_resp.get("msg", "发送验证码失败")

    def login(self, phone: str, captcha: str):
        """手机号 + 验证码登录"""
        resp = self._request(
            "POST",
            "/api/login/mobile",
            json={"phone": phone, "captcha": captcha, "spread": "0"},
        )
        if resp.get("status") == 200:
            data = resp.get("data", {})
            token = data.get("token", "")
            if token:
                return True, token, data.get("expires_time", 0)
            return False, "登录成功但未获取到 Token", 0
        return False, resp.get("msg", "登录失败"), 0

    def query_user(self, token: str):
        """查询用户信息"""
        headers = {
            "Authori-zation": token,
            "Authorization": token,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = self._request("POST", "/api/user", headers=headers)
        if resp.get("status") == 200:
            data = resp.get("data", {})
            return True, {
                "nickname": data.get("nickname", ""),
                "integral": data.get("integral", 0),
            }
        return False, resp.get("msg", "查询失败")


class XHTPlugin(Plugin):
    name = "xht"
    commands = [
        re.compile(r"^XHT\s*登录", re.IGNORECASE),
        re.compile(r"^XHT\s*查询", re.IGNORECASE),
        re.compile(r"^XHT\s*执行", re.IGNORECASE),
        re.compile(r"^XHT\s*管理", re.IGNORECASE),
        re.compile(r"^XHT\s*帮助", re.IGNORECASE),
        "xht帮助",
    ]

    def __init__(self):
        self.env = None
        self.ql = None
        self.api = None

    def _init(self):
        """初始化项目环境"""
        if self.env is None:
            self.env = ProjectEnv(self.project_dir)
        if self.ql is None:
            self.ql = QingLongAPI(
                base_url=self.env.get("QL_URL", "http://127.0.0.1:5700"),
                client_id=self.env.get("QL_CLIENT_ID", ""),
                client_secret=self.env.get("QL_CLIENT_SECRET", ""),
            )
        if self.api is None:
            self.api = XHTAPI(base_url=self.env.get("XHT_BASE_URL", "https://shrmtxh.shmedia.tech"))

    def _get_tokens(self):
        """从青龙面板读取 XHT_TOKEN"""
        self._init()
        envs = self.ql.list_envs(search_value="XHT_TOKEN")
        for env in envs:
            if env.get("name") == "XHT_TOKEN":
                value = env.get("value", "")
                return [t.strip() for t in value.split("&") if t.strip()], env
        return [], None

    def _set_token(self, token: str, remarks=""):
        """保存 Token 到青龙面板（追加到已有账号）"""
        self._init()
        tokens, env = self._get_tokens()
        if token in tokens:
            return True, "该账号已存在"

        new_tokens = tokens + [token]
        new_value = "&".join(new_tokens)

        try:
            if env:
                self.ql.update_env(env["id"], "XHT_TOKEN", new_value, remarks=remarks)
            else:
                self.ql.create_env("XHT_TOKEN", new_value, remarks=remarks)
            return True, "Token 已保存"
        except Exception as e:
            return False, f"保存 Token 失败: {e}"

    def _remove_token(self, token: str):
        """移除指定 Token"""
        self._init()
        tokens, env = self._get_tokens()
        if token not in tokens:
            return False, "未找到该账号"
        new_tokens = [t for t in tokens if t != token]
        new_value = "&".join(new_tokens)
        try:
            if new_value:
                self.ql.update_env(env["id"], "XHT_TOKEN", new_value, remarks=env.get("remarks", ""))
            else:
                self.ql.delete_env(env["id"])
            return True, "账号已删除"
        except Exception as e:
            return False, f"删除失败: {e}"

    def handle(self, text, sender_id, group_id=None):
        self._init()

        # XHT帮助
        if re.search(r"^XHT\s*帮助", text, re.IGNORECASE) or text.lower() == "xht帮助":
            return (
                "=== 徐汇通 (XHT) 命令 ===\n"
                "XHT登录 [手机号] - 手机号验证码登录\n"
                "XHT查询 - 查询已登录账号状态\n"
                "XHT执行 - 立即执行签到脚本\n"
                "XHT管理 - 查看/删除已登录账号\n"
                "XHT帮助 - 显示本帮助"
            )

        # XHT登录
        match = re.search(r"^XHT\s*登录\s*(\d{11})?", text, re.IGNORECASE)
        if match:
            phone = match.group(1)
            if not phone:
                return "请发送：XHT登录 13800138000"
            ok, msg = self.api.send_sms(phone)
            if ok:
                sessions.set(sender_id, group_id, "xht", {"phone": phone, "step": "captcha"})
                return f"验证码已发送至 {phone}，请回复验证码（4-6位数字）"
            return f"发送验证码失败：{msg}"

        # XHT查询
        if re.search(r"^XHT\s*查询", text, re.IGNORECASE):
            tokens, _ = self._get_tokens()
            if not tokens:
                return "暂无已登录的徐汇通账号"
            lines = ["=== 徐汇通账号状态 ==="]
            for i, token in enumerate(tokens, 1):
                ok, info = self.api.query_user(token)
                if ok:
                    lines.append(f"{i}. {info['nickname']} | 积分：{info['integral']}")
                else:
                    lines.append(f"{i}. 查询失败：{info}")
            return "\n".join(lines)

        # XHT执行
        if re.search(r"^XHT\s*执行", text, re.IGNORECASE):
            return self._run_script()

        # XHT管理
        if re.search(r"^XHT\s*管理", text, re.IGNORECASE):
            tokens, env = self._get_tokens()
            if not tokens:
                return "暂无已登录账号"
            lines = ["=== 已登录账号 ===", f"共 {len(tokens)} 个账号"]
            for i, token in enumerate(tokens, 1):
                masked = token[:8] + "****" + token[-4:] if len(token) > 12 else token
                lines.append(f"{i}. {masked}")
            lines.append("\n发送「XHT管理 删除 序号」可删除指定账号")
            return "\n".join(lines)

        # XHT管理 删除 序号
        match = re.search(r"^XHT\s*管理\s*删除\s*(\d+)", text, re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            tokens, _ = self._get_tokens()
            if idx < 0 or idx >= len(tokens):
                return "序号无效"
            ok, msg = self._remove_token(tokens[idx])
            return msg

        return None

    def _run_script(self):
        """调用青龙定时任务执行 xht.py"""
        self._init()
        script_path = self.env.get("XHT_SCRIPT_PATH", os.path.join(self.project_dir, "xht.py"))
        try:
            # 优先尝试通过青龙 API 运行定时任务
            task_name = os.path.basename(os.path.dirname(script_path))
            tasks = self._get_ql_tasks()
            for task in tasks:
                if task_name in task.get("command", ""):
                    self._run_ql_task(task["id"])
                    return f"已触发执行：{task.get('name', task_name)}"
            # 退化为本地执行
            os.system(f"cd {self.project_dir} && python3 {script_path}")
            return "已触发本地执行 xht.py"
        except Exception as e:
            return f"执行失败：{e}"

    def _get_ql_tasks(self):
        """获取青龙定时任务列表"""
        try:
            url = f"{self.ql.base_url}/open/crons"
            r = requests.get(url, headers=self.ql._headers(), params={"searchValue": "XHT"}, timeout=10)
            data = r.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("data", [])
        except Exception:
            pass
        return []

    def _run_ql_task(self, task_id):
        """运行指定青龙任务"""
        url = f"{self.ql.base_url}/open/crons/run"
        requests.put(url, headers=self.ql._headers(), json=[task_id], timeout=10)


def register_session_handlers(handlers):
    """注册多轮会话处理器，用于验证码输入"""

    def xht_session_handler(text, sender_id, group_id, session_data):
        step = session_data.get("step", "")
        phone = session_data.get("phone", "")
        plugin = XHTPlugin()
        plugin.project_dir = session_data.get("project_dir", "")
        plugin._init()

        if step != "captcha" or not phone:
            return None

        text = text.strip()
        if text.lower() in ("cancel", "取消"):
            sessions.clear(sender_id, group_id)
            return "已取消登录"

        if not text.isdigit() or not (4 <= len(text) <= 8):
            return "请输入正确的验证码（4-6位数字），或回复「取消」"

        ok, token, _ = plugin.api.login(phone, text)
        if ok:
            save_ok, save_msg = plugin._set_token(token, remarks=f"手机号 {phone}")
            sessions.clear(sender_id, group_id)
            return f"登录成功！\n手机号：{phone}\n{save_msg}"
        else:
            sessions.clear(sender_id, group_id)
            return f"登录失败：{token}"

    handlers["xht"] = xht_session_handler