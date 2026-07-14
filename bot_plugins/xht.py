# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) QQ 机器人控制插件

由 QL-Bot 自动扫描 /opt/QL-XHT/bot_plugins/ 加载。
负责交互登录、Token 管理、查询状态、触发执行。

登录方式：
  1. JWT Token 直绑（推荐，最稳定）
  2. 短信验证码登录（依赖浏览器自动过滑块或第三方打码平台，实验性）

短信登录说明：
  徐汇通发送短信前需要阿里云拼图/滑块验证。QQ 机器人纯后端环境无法自动完成，
  因此提供两种短信登录实现：
  - auto: 浏览器 + OpenCV 自动识别缺口（成功率有限，免费）
  - 2captcha / chaojiying: 第三方打码平台识别（付费，更稳定）
"""

import os
import re
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.plugins.base import Plugin
from bot.project_env import ProjectEnv
from bot.ql_api import QingLongAPI
from bot.session import sessions

# 导入项目内登录辅助模块
from xht_login_helper import XHTLoginFlow


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
        self.flow = None

    def _init(self):
        if self.env is None:
            self.env = ProjectEnv(self.project_dir)
        if self.ql is None:
            self.ql = QingLongAPI(
                base_url=self.env.get("QL_URL", "http://127.0.0.1:5700"),
                client_id=self.env.get("QL_CLIENT_ID", ""),
                client_secret=self.env.get("QL_CLIENT_SECRET", ""),
            )
        if self.flow is None:
            self.flow = XHTLoginFlow()

    def _get_tokens(self):
        """从青龙面板读取 XHT_TOKEN"""
        self._init()
        envs = self.ql.list_envs(search_value="XHT_TOKEN")
        for env in envs:
            if env.get("name") == "XHT_TOKEN":
                value = env.get("value", "")
                return [t.strip() for t in value.split("&") if t.strip()], env
        return [], None

    def _remove_token_by_index(self, idx: int):
        """移除指定序号的 Token"""
        self._init()
        tokens, env = self._get_tokens()
        if idx < 0 or idx >= len(tokens):
            return False, "序号无效"
        removed = tokens.pop(idx)
        new_value = "&".join(tokens)
        try:
            if new_value:
                self.ql.update_env(env["id"], "XHT_TOKEN", new_value, remarks=env.get("remarks", ""))
            else:
                self.ql.delete_env(env["id"])
            masked = removed[:8] + "****" + removed[-4:] if len(removed) > 12 else removed
            return True, f"已删除账号: {masked}"
        except Exception as e:
            return False, f"删除失败: {e}"

    def handle(self, text, sender_id, group_id=None):
        self._init()

        # XHT帮助
        if re.search(r"^XHT\s*帮助", text, re.IGNORECASE) or text.lower() == "xht帮助":
            return (
                "=== 徐汇通 (XHT) 命令 ===\n"
                "XHT登录 token [JWT] - 直接提交抓包 Token（推荐）\n"
                "XHT登录 [手机号] - 短信验证码登录（实验性，需配置滑块求解器）\n"
                "XHT查询 - 查询已登录账号状态\n"
                "XHT执行 - 立即执行签到脚本\n"
                "XHT管理 - 查看/删除已登录账号\n"
                "XHT帮助 - 显示本帮助\n\n"
                "说明：\n"
                "1. Token 直绑最稳定，APP 抓包后发送「XHT登录 token eyJ...」即可。\n"
                "2. 短信登录需在 .env 配置 XHT_CAPTCHA_SOLVER（auto/2captcha/chaojiying），\n"
                "   并安装对应依赖（详见 README）。"
            )

        # XHT登录 token [jwt]
        match = re.search(r"^XHT\s*登录\s+token\s+(\S+)", text, re.IGNORECASE)
        if match:
            token = match.group(1).strip()
            ok, msg, info = self.flow.login_by_token(token)
            if ok:
                return (
                    f"Token 绑定成功！\n"
                    f"用户：{info.get('nickname', '-')}\n"
                    f"手机号：{info.get('mobile', '-')}\n"
                    f"当前积分：{info.get('score', 0)}\n"
                    f"{msg}"
                )
            return f"绑定失败：{msg}"

        # XHT登录 [手机号]
        match = re.search(r"^XHT\s*登录\s*(\d{11})\s*$", text, re.IGNORECASE)
        if match:
            phone = match.group(1)
            solver = self.env.get("XHT_CAPTCHA_SOLVER", "auto").lower() or "auto"
            if solver not in ("auto", "2captcha", "chaojiying", "jfbym"):
                return (
                    "未配置有效的滑块求解器。请在 /opt/QL-XHT/.env 中设置：\n"
                    "XHT_CAPTCHA_SOLVER=auto       # 浏览器+OpenCV（免费，成功率有限）\n"
                    "XHT_CAPTCHA_SOLVER=jfbym      # 云码双图滑块识别（付费，推荐）\n"
                    "XHT_CAPTCHA_SOLVER=2captcha   # 2Captcha 第三方打码\n"
                    "或直接使用：XHT登录 token [你的JWT]"
                )

            # 短信登录需要 Playwright，在独立线程中运行以避免与 asyncio 冲突
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.flow.login_by_sms, phone, solver)
                    try:
                        ok, msg, form_token = future.result(timeout=90)
                    except FuturesTimeoutError:
                        return "验证码发送超时（90秒），请稍后重试"
            except Exception as e:
                err_msg = str(e)
                hint = (
                    f"当前 solver: {solver}\n"
                    f"异常：{err_msg}\n\n"
                )
                if solver == "auto":
                    hint += (
                        "提示：auto 模式需要安装 OpenCV。\n"
                        "  pip install opencv-python-headless\n\n"
                        "推荐改用云码（jfbym）：在 /opt/QL-XHT/.env 中添加\n"
                        "  XHT_CAPTCHA_SOLVER=jfbym\n"
                        "  XHT_CAPTCHA_API_KEY=你的云码token\n\n"
                    )
                elif solver == "jfbym":
                    hint += (
                        "提示：请检查 /opt/QL-XHT/.env 中 XHT_CAPTCHA_API_KEY 是否正确配置。\n"
                        "或直接使用：XHT登录 token [你的JWT]"
                    )
                else:
                    hint += "建议改用「XHT登录 token [你的JWT]」"
                return hint

            if ok and form_token:
                sessions.set(sender_id, group_id, "xht", {
                    "phone": phone,
                    "form_token": form_token,
                    "step": "captcha",
                    "project_dir": self.project_dir,
                })
                return f"验证码已发送至 {phone}，请回复 6 位验证码。\n（如需取消请回复「取消」）"
            return f"发送验证码失败：{msg}\n建议改用「XHT登录 token [你的JWT]」"

        # XHT查询
        if re.search(r"^XHT\s*查询", text, re.IGNORECASE):
            tokens, _ = self._get_tokens()
            if not tokens:
                return "暂无已登录的徐汇通账号"
            lines = ["=== 徐汇通账号状态 ==="]
            for i, token in enumerate(tokens, 1):
                ok, info = self.flow.api.query_user(token)
                if ok:
                    lines.append(
                        f"{i}. {info['nickname']} | 手机号：{info['mobile']} | 积分：{info['score']}"
                    )
                else:
                    lines.append(f"{i}. 查询失败：{info}")
            return "\n".join(lines)

        # XHT执行
        if re.search(r"^XHT\s*执行", text, re.IGNORECASE):
            return self._run_script()

        # XHT管理 删除 序号
        match = re.search(r"^XHT\s*管理\s*删除\s*(\d+)", text, re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            ok, msg = self._remove_token_by_index(idx)
            return msg

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

        return None

    def _run_script(self):
        """调用青龙定时任务执行 xht.py"""
        self._init()
        script_path = self.env.get("XHT_SCRIPT_PATH", os.path.join(self.project_dir, "xht.py"))
        try:
            task_name = os.path.basename(os.path.dirname(script_path))
            tasks = self._get_ql_tasks()
            for task in tasks:
                if task_name in task.get("command", ""):
                    self._run_ql_task(task["id"])
                    return f"已触发执行：{task.get('name', task_name)}"
            os.system(f"cd {self.project_dir} && python3 {script_path}")
            return "已触发本地执行 xht.py"
        except Exception as e:
            return f"执行失败：{e}"

    def _get_ql_tasks(self):
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
        url = f"{self.ql.base_url}/open/crons/run"
        requests.put(url, headers=self.ql._headers(), json=[task_id], timeout=10)


def register_session_handlers(handlers):
    """注册多轮会话处理器，用于验证码输入"""

    def xht_session_handler(text, sender_id, group_id, session_data):
        step = session_data.get("step", "")
        phone = session_data.get("phone", "")
        form_token = session_data.get("form_token", "")
        project_dir = session_data.get("project_dir", "")

        if step != "captcha" or not phone or not form_token:
            return None

        plugin = XHTPlugin()
        plugin.project_dir = project_dir
        plugin._init()

        text = text.strip()
        if text.lower() in ("cancel", "取消"):
            sessions.clear(sender_id, group_id)
            return "已取消登录"

        if not text.isdigit() or len(text) != 6:
            return "请输入 6 位数字验证码，或回复「取消」"

        ok, token, nickname = plugin.flow.api.login(phone, text, form_token)
        if ok:
            save_ok, save_msg = plugin.flow.save_token(token, remarks=f"手机号 {phone}")
            sessions.clear(sender_id, group_id)
            return (
                f"登录成功！\n"
                f"手机号：{phone}\n"
                f"用户：{nickname or '-'}\n"
                f"{save_msg}"
            )
        else:
            sessions.clear(sender_id, group_id)
            return f"登录失败：{token}"

    handlers["xht"] = xht_session_handler
