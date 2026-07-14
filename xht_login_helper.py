#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 (XHT) 登录辅助模块

支持三种登录方式：
  1. JWT Token 直绑（最稳定，推荐）
  2. 短信验证码登录 + 浏览器自动过滑块（实验性）
  3. 短信验证码登录 + 第三方打码平台过滑块（实验性，需 API Key）

可被 bot_plugins/xht.py 调用，也可作为独立脚本运行：
  python3 xht_login_helper.py --token <JWT>
  python3 xht_login_helper.py --sms <手机号>
  python3 xht_login_helper.py --sms <手机号> --solver 2captcha
"""

import os
import sys
import re
import json
import time
import random
import base64
import argparse
import logging
import requests

# 加载项目 .env
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_SCRIPT_DIR, ".env")

def _load_env():
    if not os.path.isfile(_ENV_FILE):
        return
    with open(_ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("XHT_LOGIN")

# 可选依赖：OpenCV（仅在 auto solver 时需要）
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    _CV2_AVAILABLE = False

# 配置
XHT_BASE_URL = os.environ.get("XHT_BASE_URL", "https://app.xuhuimedia.cn/media-basic-port").rstrip("/")
XHT_CAPTCHA_WEB = "https://xhweb.shmedia.tech/media-basic-port"
XHT_CAPTCHA_PAGE = "https://xhweb.shmedia.tech/h5/xh/aliCaptchaVerify/?siteId=310104"
XHT_SITE_ID = os.environ.get("XHT_SITE_ID", "310104")
XHT_DEVICE_ID = os.environ.get("XHT_DEVICE_ID", "")

QL_URL = os.environ.get("QL_URL", "http://127.0.0.1:5700").rstrip("/")
QL_CLIENT_ID = os.environ.get("QL_CLIENT_ID", "")
QL_CLIENT_SECRET = os.environ.get("QL_CLIENT_SECRET", "")

# 第三方打码配置
CAPTCHA_SOLVER = os.environ.get("XHT_CAPTCHA_SOLVER", "").lower()  # "auto" / "2captcha" / "chaojiying" / "jfbym"
CAPTCHA_API_KEY = os.environ.get("XHT_CAPTCHA_API_KEY", "")

UA_APP = "xu hui tong/2.5.0 (iPhone; iOS 26.5; Scale/3.00)"
UA_WEB = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148Rmt/XuHui; Version/2.5.0"


# ============================================================
# 青龙环境变量操作
# ============================================================
class QingLongEnv:
    def __init__(self):
        self.token = self._get_token()

    def _get_token(self):
        if not all([QL_URL, QL_CLIENT_ID, QL_CLIENT_SECRET]):
            raise RuntimeError("缺少青龙 Open API 配置（QL_URL/QL_CLIENT_ID/QL_CLIENT_SECRET）")
        r = requests.get(f"{QL_URL}/open/auth/token", params={
            "client_id": QL_CLIENT_ID,
            "client_secret": QL_CLIENT_SECRET,
        }, timeout=15)
        data = r.json()
        if data.get("code") != 200:
            raise RuntimeError(f"青龙认证失败: {data}")
        return data["data"]["token"]

    def list_envs(self, search_value=""):
        params = {"token": self.token}
        if search_value:
            params["searchValue"] = search_value
        r = requests.get(f"{QL_URL}/open/envs", params=params, timeout=15)
        data = r.json()
        if data.get("code") != 200:
            raise RuntimeError(f"获取环境变量失败: {data}")
        return data.get("data", [])

    def create_env(self, name, value, remarks=""):
        body = {"name": name, "value": value, "remarks": remarks}
        r = requests.post(f"{QL_URL}/open/envs", headers={"Authorization": f"Bearer {self.token}"}, json=body, timeout=15)
        data = r.json()
        if data.get("code") != 200:
            raise RuntimeError(f"创建环境变量失败: {data}")
        return data["data"]

    def update_env(self, env_id, name, value, remarks=""):
        body = {"id": env_id, "name": name, "value": value, "remarks": remarks}
        r = requests.put(f"{QL_URL}/open/envs", headers={"Authorization": f"Bearer {self.token}"}, json=body, timeout=15)
        data = r.json()
        if data.get("code") != 200:
            raise RuntimeError(f"更新环境变量失败: {data}")
        return data["data"]

    def append_token(self, token, remarks=""):
        envs = self.list_envs(search_value="XHT_TOKEN")
        existing = None
        for env in envs:
            if env.get("name") == "XHT_TOKEN":
                existing = env
                break

        tokens = []
        if existing:
            tokens = [t.strip() for t in existing.get("value", "").split("&") if t.strip()]
        if token in tokens:
            return False, "该 Token 已存在"

        tokens.append(token)
        value = "&".join(tokens)
        if existing:
            self.update_env(existing["id"], "XHT_TOKEN", value, remarks=remarks)
        else:
            self.create_env("XHT_TOKEN", value, remarks=remarks)
        return True, f"已保存 Token，当前共 {len(tokens)} 个账号"


# ============================================================
# 徐汇通 API
# ============================================================
class XHTAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA_APP,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
            "deviceId": XHT_DEVICE_ID,
            "siteId": XHT_SITE_ID,
        })

    def query_user(self, token):
        url = f"{XHT_BASE_URL}/api/app/personal/get"
        r = self.session.post(url, json={}, headers={"token": token}, timeout=15)
        data = r.json()
        if data.get("code") == 0:
            user = data.get("data", {})
            return True, {
                "nickname": user.get("nickname", ""),
                "mobile": user.get("mobile", ""),
                "score": user.get("score", 0),
            }
        return False, data.get("msg", "查询失败")

    def send_sms(self, phone, captcha_param):
        url = f"{XHT_CAPTCHA_WEB}/api/app/auth/captcha/validate/send_sms_code"
        headers = {
            "User-Agent": UA_WEB,
            "Content-Type": "application/json",
            "Origin": "https://xhweb.shmedia.tech",
            "Referer": XHT_CAPTCHA_PAGE,
            "deviceId": XHT_DEVICE_ID,
            "siteId": XHT_SITE_ID,
        }
        body = {
            "mobile": phone,
            "sceneType": "app",
            "captchaVerifyParam": captcha_param if isinstance(captcha_param, str) else json.dumps(captcha_param),
        }
        r = requests.post(url, json=body, headers=headers, timeout=15)
        try:
            data = r.json()
        except Exception:
            return False, f"响应非JSON: {r.text[:200]}", ""
        if data.get("code") == 0:
            return True, "验证码已发送", data.get("data", {}).get("formToken", "")
        return False, data.get("msg", "发送失败"), ""

    def login(self, phone, code, form_token):
        url = f"{XHT_BASE_URL}/api/app/auth/validate_code_login"
        body = {"formToken": form_token, "mobile": phone, "validateCode": code}
        r = self.session.post(url, json=body, timeout=15)
        try:
            data = r.json()
        except Exception:
            return False, f"响应非JSON: {r.text[:200]}", ""
        if data.get("code") == 0:
            token = r.headers.get("token", "")
            account = data.get("data", {}).get("account", {})
            return True, token, account.get("nickname", "")
        return False, data.get("msg", "登录失败"), ""


# ============================================================
# 滑块求解器（可选依赖）
# ============================================================
class CaptchaSolver:
    """统一滑块求解接口"""

    def solve(self, page):
        """返回 captchaVerifyParam 字符串，失败返回 None"""
        raise NotImplementedError

    def _human_drag(self, page, selector, distance, duration=1.0):
        """模拟人类拖动滑块"""
        box = page.locator(selector).first.bounding_box()
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        steps = int(duration * 80)
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        for i in range(steps + 1):
            t = i / steps
            t2 = 2 * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 2) / 2
            page.mouse.move(
                start_x + distance * t2 + random.uniform(-1, 1),
                start_y + random.uniform(-2, 2) * (1 - t)
            )
            time.sleep(duration / steps)
        page.mouse.up()

    def _wait_for_captcha(self, page, timeout=10):
        """等待滑块验证完成并返回 captchaVerifyParam"""
        for _ in range(int(timeout * 2)):
            if page.evaluate("window._xht_captcha_done"):
                return page.evaluate("window._xht_captcha_param")
            time.sleep(0.5)
        return None


class BrowserAutoSolver(CaptchaSolver):
    """浏览器内自动识别拼图缺口并拖动（实验性）"""

    def solve(self, page):
        if not _CV2_AVAILABLE:
            raise RuntimeError(
                "使用浏览器自动识别需要安装 opencv-python-headless:\n"
                "  pip install opencv-python-headless"
            )

        page.wait_for_selector("#aliyunCaptcha-img", timeout=15000)
        time.sleep(2)

        bg_url = page.eval_on_selector("#aliyunCaptcha-img", "el => el.src")
        puzzle_url = page.eval_on_selector("#aliyunCaptcha-puzzle", "el => el.src")

        bg = self._img_from_url(bg_url)
        puzzle = self._img_from_url(puzzle_url)
        gap_x = self._find_gap(bg, puzzle)

        # 页面显示宽度 300px
        scale = 300 / bg.shape[1]
        drag_distance = max(0, min(gap_x * scale, 250))
        self._human_drag(page, "#aliyunCaptcha-sliding-slider", drag_distance)

        return self._wait_for_captcha(page)

    def _img_from_url(self, url):
        if url.startswith("data:image"):
            data = base64.b64decode(url.split(",", 1)[1])
            return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        r = requests.get(url, headers={"User-Agent": UA_WEB}, timeout=15)
        return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)

    def _find_gap(self, bg, puzzle):
        bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
        puzzle_gray = cv2.cvtColor(puzzle, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(puzzle_gray, 200, 255, cv2.THRESH_BINARY)
        mask = mask // 255

        edges = cv2.Canny(bg_gray, 50, 150)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        edges = edges.astype(np.float32) / 255.0

        h, w = mask.shape
        best_x, max_score = 0, -1
        for x in range(0, edges.shape[1] - w):
            score = np.sum(edges[:, x:x + w] * mask)
            if score > max_score:
                max_score = score
                best_x = x
        return best_x


class ThirdPartySolver(CaptchaSolver):
    """第三方打码平台（2Captcha / 超级鹰 / 云码 jfbym）"""

    def solve(self, page):
        if not CAPTCHA_API_KEY:
            raise RuntimeError("未配置 XHT_CAPTCHA_API_KEY")

        if CAPTCHA_SOLVER == "jfbym":
            distance = self._solve_jfbym(page)
        elif CAPTCHA_SOLVER == "2captcha":
            distance = self._solve_2captcha(page)
        elif CAPTCHA_SOLVER == "chaojiying":
            distance = self._solve_chaojiying(page)
        else:
            raise RuntimeError(f"不支持的 solver: {CAPTCHA_SOLVER}")

        # 拿到识别距离后统一拖动并等待 captcha 回调
        self._human_drag(page, "#aliyunCaptcha-sliding-slider", distance)
        return self._wait_for_captcha(page)

    def _img_b64_from_page(self, page, selector):
        """从页面元素 src 获取 base64，支持 data URI 或 URL"""
        src = page.eval_on_selector(selector, "el => el.src")
        if src.startswith("data:image"):
            return src.split(",", 1)[1]
        r = requests.get(src, headers={"User-Agent": UA_WEB}, timeout=15)
        return base64.b64encode(r.content).decode()

    def _solve_jfbym(self, page):
        """
        云码（jfbym）双图滑块识别
        接口：http://api.jfbym.com/api/YmServer/customApi
        类型：20111（双图滑块，返回像素距离）
        """
        url = "http://api.jfbym.com/api/YmServer/customApi"
        bg_b64 = self._img_b64_from_page(page, "#aliyunCaptcha-img")
        slide_b64 = self._img_b64_from_page(page, "#aliyunCaptcha-puzzle")

        payload = {
            "token": CAPTCHA_API_KEY,
            "type": "20111",
            "slide_image": slide_b64,
            "background_image": bg_b64,
        }
        headers = {"Content-Type": "application/json"}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        try:
            resp = r.json()
        except Exception as e:
            raise RuntimeError(f"云码返回非JSON: {r.text[:200]}")

        logger.info(f"云码响应: {resp}")
        if resp.get("code") != 0 and resp.get("code") != "0":
            raise RuntimeError(f"云码识别失败: {resp}")

        # 返回的是像素距离 px（以背景图最左侧为 0）
        distance = resp.get("data", {}).get("data", "")
        try:
            distance = float(distance)
        except (ValueError, TypeError):
            raise RuntimeError(f"云码返回距离异常: {distance}")

        # 云码返回的是图片像素距离，需要按页面显示宽度缩放
        box = page.locator("#aliyunCaptcha-img").first.bounding_box()
        scale = box["width"] / 300 if box else 1.0
        return distance * scale

    def _solve_2captcha(self, page):
        element = page.locator(".aliyunCaptcha-body").first
        if element.count() == 0:
            element = page.locator("#aliyunCaptcha-img").first
        screenshot = element.screenshot()
        b64 = base64.b64encode(screenshot).decode()

        url = "http://2captcha.com/in.php"
        data = {
            "key": CAPTCHA_API_KEY,
            "method": "base64",
            "body": b64,
            "textinstructions": "Click the center of the empty puzzle slot",
            "json": 1,
        }
        r = requests.post(url, data=data, timeout=30).json()
        if r.get("status") != 1:
            raise RuntimeError(f"2Captcha 提交失败: {r}")
        cid = r["request"]
        for _ in range(30):
            time.sleep(5)
            res = requests.get(
                f"http://2captcha.com/res.php?key={CAPTCHA_API_KEY}&action=get&id={cid}&json=1",
                timeout=30
            ).json()
            if res.get("status") == 1:
                coords = res.get("request", [])
                if coords:
                    gap_x = coords[0].get("x", 0)
                    box = element.bounding_box()
                    scale = box["width"] / 300
                    return gap_x * scale
            elif res.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2Captcha 错误: {res}")
        raise RuntimeError("2Captcha 超时")

    def _solve_chaojiying(self, page):
        element = page.locator(".aliyunCaptcha-body").first
        if element.count() == 0:
            element = page.locator("#aliyunCaptcha-img").first
        screenshot = element.screenshot()
        b64 = base64.b64encode(screenshot).decode()

        url = "http://upload.chaojiying.net/Upload/Processing.php"
        files = {"userfile": ("captcha.png", base64.b64decode(b64), "image/png")}
        data = {
            "user": CAPTCHA_API_KEY.split(":")[0],
            "pass": CAPTCHA_API_KEY.split(":")[1],
            "codetype": "9004",  # 坐标点击
            "softid": "96001",
        }
        r = requests.post(url, files=files, data=data, timeout=30).json()
        if r.get("err_str") == "OK":
            pic_str = r.get("pic_str", "")
            gap_x = int(pic_str.split(",")[0])
            box = element.bounding_box()
            scale = box["width"] / 300
            return gap_x * scale
        raise RuntimeError(f"超级鹰识别失败: {r}")


# ============================================================
# 登录流程封装
# ============================================================
class XHTLoginFlow:
    def __init__(self):
        self.api = XHTAPI()
        self.qinglong = None
        try:
            self.qinglong = QingLongEnv()
        except Exception as e:
            logger.warning(f"青龙环境未配置: {e}")

    def save_token(self, token, remarks=""):
        if not self.qinglong:
            return False, "青龙未配置，无法保存 Token"
        return self.qinglong.append_token(token, remarks=remarks)

    def login_by_token(self, token):
        ok, info = self.api.query_user(token)
        if not ok:
            return False, f"Token 校验失败: {info}", None
        save_ok, save_msg = self.save_token(token, remarks=f"手机号 {info.get('mobile', '')}")
        return save_ok, save_msg, info

    def login_by_sms(self, phone, solver_type="auto"):
        """
        短信登录完整流程：
          1. 浏览器加载滑块页
          2. 使用 solver 过滑块拿到 captchaVerifyParam
          3. 发送短信
          4. 等待用户输入验证码
          5. 调用登录接口
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False, "短信登录需要安装 Playwright: pip install playwright && playwright install chromium", None

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=414,896",
                ]
            )
            context = browser.new_context(
                user_agent=UA_WEB,
                viewport={"width": 414, "height": 896},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                window.chrome = { runtime: {} };
                window._xht_captcha_param = null;
                window._xht_captcha_done = false;
                const originalInit = window.initAliyunCaptcha;
                window.initAliyunCaptcha = function(config) {
                    const cb = config.captchaVerifyCallback;
                    config.captchaVerifyCallback = function(captchaVerifyParam, bizResult) {
                        window._xht_captcha_param = captchaVerifyParam;
                        window._xht_captcha_done = true;
                        if (cb) return cb(captchaVerifyParam, bizResult);
                        return { captchaResult: true, bizResult: true };
                    };
                    if (originalInit) return originalInit(config);
                };
            """)

            logger.info("加载验证码页面...")
            page.goto(XHT_CAPTCHA_PAGE, wait_until="networkidle", timeout=60000)
            time.sleep(2)

            # 选择求解器
            if solver_type in ("2captcha", "chaojiying", "jfbym"):
                solver = ThirdPartySolver()
            else:
                solver = BrowserAutoSolver()

            logger.info(f"使用求解器: {solver.__class__.__name__}")
            param = solver.solve(page)
            browser.close()

            if not param:
                return False, "未能获取 captchaVerifyParam，滑块验证失败", None

            logger.info("滑块验证通过，准备发送短信...")
            ok, msg, form_token = self.api.send_sms(phone, param)
            if not ok:
                return False, f"发送短信失败: {msg}", None

            return True, f"短信已发送，formToken={form_token}", form_token


# ============================================================
# 命令行入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="徐汇通登录辅助")
    parser.add_argument("--token", help="直接绑定 JWT Token")
    parser.add_argument("--sms", help="手机号，使用短信验证码登录")
    parser.add_argument("--solver", default="auto", choices=["auto", "2captcha", "chaojiying", "jfbym"], help="滑块求解器")
    parser.add_argument("--code", help="短信验证码（可选，如不提供则只发送短信）")
    parser.add_argument("--form-token", help="短信登录的 formToken（可选）")
    args = parser.parse_args()

    flow = XHTLoginFlow()

    if args.token:
        ok, msg, info = flow.login_by_token(args.token)
        print(f"\n{'成功' if ok else '失败'}: {msg}")
        if info:
            print(f"用户: {info.get('nickname')}, 手机号: {info.get('mobile')}, 积分: {info.get('score')}")
        return

    if args.sms:
        if args.code and args.form_token:
            # 已有验证码和 formToken，直接登录
            ok, token, nickname = flow.api.login(args.sms, args.code, args.form_token)
            if ok:
                save_ok, save_msg = flow.save_token(token, remarks=f"手机号 {args.sms}")
                print(f"\n登录成功！{save_msg}\nToken: {token[:20]}...")
            else:
                print(f"\n登录失败: {token}")
        else:
            # 发送短信，返回 formToken
            ok, msg, form_token = flow.login_by_sms(args.sms, solver_type=args.solver)
            print(f"\n{'成功' if ok else '失败'}: {msg}")
            if form_token:
                print(f"formToken: {form_token}")
                print(f"下一步: python3 xht_login_helper.py --sms {args.sms} --code <验证码> --form-token {form_token}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
