# -*- coding: utf-8 -*-
"""徐汇通 (XHT) QQ 机器人控制插件

由 QL-Bot 自动扫描 /opt/QL-XHT/bot_plugins/ 加载。
负责交互登录、Token 管理、查询状态、触发执行。

登录流程说明：
  1. 徐汇通发送短信前需要先通过阿里云滑块验证（/api/app/json/captcha 返回 open_flag=true）。
  2. 滑块验证在 QQ 机器人环境无法自动完成，因此本插件提供两种登录方式：
     a) XHT登录 token [jwt_token]   # 推荐：用户手动抓包获取 token 后直接提交
     b) XHT登录 [手机号]            # 尝试自动发短信，若服务端要求滑块则提示用户
"""

import os
import re
import sys
import time
import uuid
import requests

# 兼容 QL-Bot 的导入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.plugins.base import Plugin
from bot.project_env import ProjectEnv
from bot.ql_api import QingLongAPI
from bot.session import sessions


class XHTAPI:
    """徐汇通登录相关 API（基于真实抓包）"""

    # 业务域名（用户信息、签到、登录）
    BASE_APP_URL = "https://app.xuhuimedia.cn/media-basic-port"
    # 滑块验证 / 短信发送域名（H5 页面）
    BASE_WEB_URL = "https://xhweb.shmedia.tech/media-basic-port"

    def __init__(self, device_id: str = "", site_id: str = "310104"):
        self.site_id = site_id
        self.device_id = device_id or self._generate_device_id()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "xu hui tong/2.5.0 (iPhone; iOS 26.5; Scale/3.00)",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
            "Accept-Language": "zh-Hans-CN;q=1, zh-Hant-HK;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "deviceId": self.device_id,
            "siteId": self.site_id,
        })

    @staticmethod
    def _generate_device_id() -> str:
        return uuid.uuid4().hex.replace("-", "")[:32]

    def _request(self, method, url, json_body=None, headers=None, timeout=15):
        h = dict(self.session.headers)
        if headers:
            h.update(headers)
        try:
            kwargs = {"headers": h, "timeout": timeout}
            if json_body is not None:
                kwargs["json"] = json_body
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 200:
                try:
                    return resp.json(), dict(resp.headers)
                except ValueError:
                    return {"code": -1, "msg": f"响应非JSON: {resp.text[:200]}"}, dict(resp.headers)
            return {"code": -1, "msg": f"HTTP {resp.status_code}"}, dict(resp.headers)
        except Exception as e:
            return {"code": -1, "msg": str(e)}, {}

    def check_captcha_open(self) -> bool:
        """检查是否开启滑块验证"""
        url = f"{self.BASE_APP_URL}/api/app/json/captcha"
        data, _ = self._request("POST", url, json_body={})
        if data.get("code") == 0:
            return data.get("data", {}).get("open_flag", False)
        return True  # 默认认为开启，避免误发

    def send_sms(self, phone: str, captcha_verify_param: str = ""):
        """
        发送短信验证码。
        由于需要阿里云滑块参数，QQ 机器人通常无法自动完成。
        """
        url = f"{self.BASE_WEB_URL}/api/app/auth/captcha/validate/send_sms_code"
        # 不带滑块参数时尝试调用，服务端会返回具体错误
        body = {"sceneType": "app", "mobile": phone}
        if captcha_verify_param:
            body["captchaVerifyParam"] = captcha_verify_param

        headers = {
            # H5 页面使用的 UA
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148Rmt/XuHui; Version/2.5.0"
            ),
            "Content-Type": "application/json",
            "Origin": "https://xhweb.shmedia.tech",
            "Referer": f"https://xhweb.shmedia.tech/h5/xh/aliCaptchaVerify/?siteId={self.site_id}",
        }
        data, _ = self._request("POST", url, json_body=body, headers=headers)
        if data.get("code") == 0:
            form_token = data.get("data", {}).get("formToken", "")
            return True, "验证码已发送", form_token
        return False, data.get("msg", "发送验证码失败"), ""

    def login(self, phone: str, validate_code: str, form_token: str):
        """手机号 + 短信验证码 + formToken 登录"""
        url = f"{self.BASE_APP_URL}/api/app/auth/validate_code_login"
        body = {
            "formToken": form_token,
            "mobile": phone,
            "validateCode": validate_code,
        }
        data, resp_headers = self._request("POST", url, json_body=body)
        if data.get("code") == 0:
            token = resp_headers.get("token", "")
            account = data.get("data", {}).get("account", {})
            nickname = account.get("nickname", "")
            if token:
                return True, token, nickname
            return False, "登录成功但未获取到 Token", ""
        return False, data.get("msg", "登录失败"), ""

    def query_user(self, token: str):
        """查询用户信息，用于校验 Token 有效性"""
        url = f"{self.BASE_APP_URL}/api/app/personal/get"
        headers = {"token": token}
        data, _ = self._request("POST", url, json_body={}, headers=headers)
        if data.get("code") == 0:
            user = data.get("data", {})
            return True, {
                "nickname": user.get("nickname", ""),
                "mobile": user.get("mobile", ""),
                "score": user.get("score", 0),
            }
        return False, data.get("msg", "查询失败")


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
            device_id = self.env.get("XHT_DEVICE_ID", "")
            site_id = self.env.get("XHT_SITE_ID", "310104")
            self.api = XHTAPI(device_id=device_id, site_id=site_id)

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
                "XHT登录 [手机号] - 尝试手机号验证码登录（受滑块验证限制）\n"
                "XHT登录 token [JWT Token] - 直接提交抓包获取的 Token（推荐）\n"
                "XHT查询 - 查询已登录账号状态\n"
                "XHT执行 - 立即执行签到脚本\n"
                "XHT管理 - 查看/删除已登录账号\n"
                "XHT帮助 - 显示本帮助\n\n"
                "说明：因徐汇通发送短信需要阿里云滑块验证，机器人无法自动完成。\n"
                "推荐在 APP 中登录后使用 HttpCanary/Stream 等工具抓取 token，\n"
                "然后发送「XHT登录 token [你的token]」完成绑定。"
            )

        # XHT登录 token [jwt]
        match = re.search(r"^XHT\s*登录\s+token\s+(\S+)", text, re.IGNORECASE)
        if match:
            token = match.group(1).strip()
            ok, info = self.api.query_user(token)
            if not ok:
                return f"Token 校验失败：{info}\n请确认 token 是否正确且未过期。"
            save_ok, save_msg = self._set_token(token, remarks=f"手机号 {info.get('mobile', '')}")
            if save_ok:
                return (
                    f"Token 绑定成功！\n"
                    f"用户：{info.get('nickname', '-')}\n"
                    f"手机号：{info.get('mobile', '-')}\n"
                    f"当前积分：{info.get('score', 0)}\n"
                    f"{save_msg}"
                )
            return f"保存失败：{save_msg}"

        # XHT登录 [手机号]
        match = re.search(r"^XHT\s*登录\s*(\d{11})\s*$", text, re.IGNORECASE)
        if match:
            phone = match.group(1)
            # 先检查滑块开关
            if self.api.check_captcha_open():
                return (
                    "当前服务端开启了滑块验证，机器人无法自动完成。\n"
                    "请使用以下方式登录：\n"
                    "1. 在 APP 中手动完成登录\n"
                    "2. 使用抓包工具获取请求头中的 token（JWT 字符串）\n"
                    f"3. 发送：XHT登录 token [你的token]"
                )
            ok, msg, form_token = self.api.send_sms(phone)
            if ok and form_token:
                sessions.set(sender_id, group_id, "xht", {
                    "phone": phone,
                    "form_token": form_token,
                    "step": "captcha",
                    "project_dir": self.project_dir,
                })
                return f"验证码已发送至 {phone}，请回复验证码（4-6位数字）"
            return f"发送验证码失败：{msg}\n建议直接使用「XHT登录 token [你的token]」"

        # XHT查询
        if re.search(r"^XHT\s*查询", text, re.IGNORECASE):
            tokens, _ = self._get_tokens()
            if not tokens:
                return "暂无已登录的徐汇通账号"
            lines = ["=== 徐汇通账号状态 ==="]
            for i, token in enumerate(tokens, 1):
                ok, info = self.api.query_user(token)
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

        if not text.isdigit() or not (4 <= len(text) <= 8):
            return "请输入正确的验证码（4-6位数字），或回复「取消」"

        ok, token, nickname = plugin.api.login(phone, text, form_token)
        if ok:
            save_ok, save_msg = plugin._set_token(token, remarks=f"手机号 {phone}")
            sessions.clear(sender_id, group_id)
            return (
                f"登录成功！\n"
                f"手机号：{phone}\n"
                f"用户：{nickname or '-'}\n"
                f"{save_msg}"
            )
        else:
            sessions.clear(sender_id, group_id)
            return (
                f"登录失败：{token}\n"
                "建议直接使用「XHT登录 token [你的token]」绑定。"
            )

    handlers["xht"] = xht_session_handler
