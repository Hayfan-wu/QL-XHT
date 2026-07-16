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
        logger.info(f"青龙 token 获取: code={data.get('code')}, msg={data.get('message', '')}")
        if data.get("code") != 200:
            raise RuntimeError(f"青龙认证失败: {data}")
        token = data["data"]["token"]
        logger.info(f"青龙 token 获取成功: {token[:20]}...")
        return token

    def _ql_request(self, method, path, params=None, body=None):
        """统一的青龙 API 请求，尝试多种认证方式"""
        url = f"{QL_URL}{path}"
        auth_attempts = [
            # 方式1: Bearer token（新版本）
            lambda: requests.request(method, url, params=params, headers={"Authorization": f"Bearer {self.token}"}, json=body, timeout=15),
            # 方式2: query param token（旧版本）
            lambda: requests.request(method, url, params=dict(params or {}, token=self.token), json=body, timeout=15),
        ]
        for i, fn in enumerate(auth_attempts):
            r = fn()
            data = r.json()
            if data.get("code") == 200:
                if i > 0:
                    logger.info(f"青龙 API 认证方式 {i+1} 成功")
                return data
            logger.warning(f"青龙 API 认证方式 {i+1} 失败: code={data.get('code')}, msg={data.get('message', '')}")
        return data

    def list_envs(self, search_value=""):
        params = {"searchValue": search_value} if search_value else None
        data = self._ql_request("GET", "/open/envs", params=params)
        if data.get("code") != 200:
            raise RuntimeError(f"获取环境变量失败: {data}")
        return data.get("data", [])

    def create_env(self, name, value, remarks=""):
        body = {"name": name, "value": value, "remarks": remarks}
        data = self._ql_request("POST", "/open/envs", body=body)
        if data.get("code") != 200:
            raise RuntimeError(f"创建环境变量失败: {data}")
        return data["data"]

    def update_env(self, env_id, name, value, remarks=""):
        body = {"id": env_id, "name": name, "value": value, "remarks": remarks}
        data = self._ql_request("PUT", "/open/envs", body=body)
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
        logger.info(f"发送短信请求: mobile={phone}, captchaVerifyParam前100字符={str(captcha_param)[:100]}")
        r = requests.post(url, json=body, headers=headers, timeout=15)
        try:
            data = r.json()
        except Exception:
            return False, f"响应非JSON: {r.text[:200]}", ""
        logger.info(f"短信API响应: code={data.get('code')}, msg={data.get('msg')}, data={data.get('data')}")
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

    def _human_drag(self, page, selector, distance, duration=1.2):
        """模拟人类拖动滑块（带回弹和微调）"""
        box = page.locator(selector).first.bounding_box()
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        steps = int(duration * 80)
        page.mouse.move(start_x, start_y)
        time.sleep(random.uniform(0.1, 0.3))
        page.mouse.down()
        time.sleep(random.uniform(0.05, 0.15))

        # 主拖动：先快后慢的缓动曲线
        for i in range(1, steps + 1):
            t = i / steps
            # ease-out-quart: 起步快，末尾慢
            t2 = 1 - pow(1 - t, 4)
            x = start_x + distance * t2
            # Y 轴轻微抖动，越靠近终点越稳定
            y = start_y + random.uniform(-1.5, 1.5) * (1 - t * 0.8)
            page.mouse.move(x, y)
            time.sleep(duration / steps * (0.5 + 0.5 * (1 - t)))  # 末尾更慢

        # 到达后微小回弹（模拟人类过冲后修正）
        overshoot = random.uniform(1, 3)
        page.mouse.move(start_x + distance + overshoot, start_y + random.uniform(-0.5, 0.5))
        time.sleep(random.uniform(0.02, 0.06))
        page.mouse.move(start_x + distance - random.uniform(1, 3), start_y)
        time.sleep(random.uniform(0.02, 0.05))
        page.mouse.move(start_x + distance, start_y + random.uniform(-0.3, 0.3))
        time.sleep(random.uniform(0.05, 0.15))
        page.mouse.up()

    def _wait_for_captcha(self, page, timeout=15):
        """等待滑块验证完成并返回 captchaVerifyParam"""
        for i in range(int(timeout * 2)):
            try:
                done = page.evaluate("window._xht_captcha_done")
                if done:
                    param = page.evaluate("window._xht_captcha_param")
                    raw = page.evaluate("window._xht_captcha_raw || 'none'")
                    logger.info(f"第 {i} 次轮询获取到 captchaVerifyParam，长度={len(param) if param else 0}，raw前100={raw[:100]}")
                    if param:
                        return param
            except Exception:
                pass
            time.sleep(0.5)

        # 兜底：检查页面 DOM 是否有验证成功元素
        try:
            body_html = page.evaluate("document.body.innerHTML.slice(0,500)")
            if 'captchaVerifyParam' in body_html or 'success' in body_html.lower():
                logger.info("页面 DOM 中出现成功标志，尝试提取")
                param = page.evaluate("""
                    (() => {
                        if (window._xht_captcha_param) return window._xht_captcha_param;
                        var m = document.body.innerHTML.match(/captchaVerifyParam[=:"]+([^"&\\s]+)/);
                        return m ? m[1] : null;
                    })()
                """)
                if param:
                    return param
        except Exception:
            pass

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
        logger.info(f"识别距离: {distance:.1f}px, 准备拖动滑块")
        box = page.locator("#aliyunCaptcha-sliding-slider").first.bounding_box()
        logger.info(f"滑块位置: x={box['x']}, y={box['y']}, w={box['width']}, h={box['height']}")
        bg_box = page.locator("#aliyunCaptcha-img").first.bounding_box()
        logger.info(f"背景图位置: x={bg_box['x']}, y={bg_box['y']}, w={bg_box['width']}")

        # 拖动策略：鼠标从滑块中心开始，拖动距离 = 识别距离（缩放后）。
        # 云码 20226 返回的是截图上目标位置到最左侧的像素距离，
        # 对于底部滑块按钮，该距离即为其中心应移动的距离。
        drag_distance = distance

        # 限制拖动距离不超过滑轨范围
        max_drag = bg_box["width"] - box["width"]
        drag_distance = max(0, min(drag_distance, max_drag))
        logger.info(f"最终拖动距离: {drag_distance:.1f}px")

        self._human_drag(page, "#aliyunCaptcha-sliding-slider", drag_distance)
        logger.info("拖动完成，等待 captcha 回调...")
        result = self._wait_for_captcha(page)
        if result:
            logger.info(f"验证通过，captchaVerifyParam 长度: {len(result)}")
        else:
            # 截图保存用于调试
            try:
                page.screenshot(path="/tmp/xht_captcha_fail.png")
                logger.warning("滑块验证未通过，截图已保存到 /tmp/xht_captcha_fail.png")
            except Exception:
                pass
        return result

    def _img_b64_from_page(self, page, selector):
        """从页面元素 src 获取 base64，支持 data URI 或 URL"""
        src = page.eval_on_selector(selector, "el => el.src")
        if src.startswith("data:image"):
            return src.split(",", 1)[1]
        r = requests.get(src, headers={"User-Agent": UA_WEB}, timeout=15)
        return base64.b64encode(r.content).decode()

    def _solve_jfbym(self, page):
        """
        云码（jfbym）滑块识别
        接口：http://api.jfbym.com/api/YmServer/customApi
        类型可通过环境变量 XHT_CAPTCHA_TYPE 指定：
          20111 双图滑块（bg + slide）
          20226 滑块_AL 单图（推荐，需含滑轨）
          22222 单图滑块优化
        """
        import time as _time
        url = "http://api.jfbym.com/api/YmServer/customApi"
        jfbym_type = os.environ.get("XHT_CAPTCHA_TYPE", "20226").strip()

        if jfbym_type == "20111":
            # 双图滑块：分别传背景图和滑块图
            bg_b64 = self._img_b64_from_page(page, "#aliyunCaptcha-img")
            slide_b64 = self._img_b64_from_page(page, "#aliyunCaptcha-puzzle")
            payload = {
                "token": CAPTCHA_API_KEY,
                "type": "20111",
                "slide_image": slide_b64,
                "background_image": bg_b64,
            }
            scale = self._jfbym_scale_from_natural_width(page)
        else:
            # 单图接口：截取完整验证码区域（图片 + 滑轨）
            screenshot = self._screenshot_captcha_area(page)
            b64 = base64.b64encode(screenshot).decode()
            payload = {
                "token": CAPTCHA_API_KEY,
                "type": jfbym_type,
                "image": b64,
            }
            scale = self._jfbym_scale_from_screenshot(screenshot, page)

        headers = {"Content-Type": "application/json"}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        try:
            resp = r.json()
        except Exception as e:
            raise RuntimeError(f"云码返回非JSON: {r.text[:200]}")

        logger.info(f"云码响应 (type={jfbym_type}): {resp}")
        # 云码成功时外层 code=10000，内层 data.code=0
        outer_code = resp.get("code")
        if outer_code not in (0, "0", 10000, "10000"):
            raise RuntimeError(f"云码识别失败: {resp}")
        inner_data = resp.get("data", {})
        if isinstance(inner_data, dict) and inner_data.get("code") not in (0, "0"):
            raise RuntimeError(f"云码识别失败: {resp}")

        distance = inner_data.get("data", "") if isinstance(inner_data, dict) else ""
        try:
            distance = float(distance)
        except (ValueError, TypeError):
            raise RuntimeError(f"云码返回距离异常: {distance}")

        return distance * scale

    def _screenshot_captcha_area(self, page):
        """截取包含图片和滑轨的完整验证码区域"""
        body = page.locator(".aliyunCaptcha-body").first
        if body.count() == 0:
            body = page.locator("#aliyunCaptcha-img").first

        box = body.bounding_box()
        if not box:
            # 兜底：截取整个页面
            return page.screenshot()

        # 只向下扩展 140px 以包含滑轨，不加水平 padding
        clip = {
            "x": box["x"],
            "y": max(0, box["y"] - 10),
            "width": box["width"],
            "height": box["height"] + 140,
        }
        screenshot = page.screenshot(clip=clip)

        # 保存调试图方便核对
        import time as _time
        debug_path = f"/tmp/xht_jfbym_{int(_time.time())}.png"
        try:
            with open(debug_path, "wb") as f:
                f.write(screenshot)
            logger.info(f"调试图已保存: {debug_path}")
        except Exception as e:
            logger.warning(f"保存调试图失败: {e}")
        return screenshot

    def _jfbym_scale_from_natural_width(self, page):
        """20111：按背景图 naturalWidth 与显示宽度缩放"""
        bg_box = page.locator("#aliyunCaptcha-img").first.bounding_box()
        display_width = bg_box["width"] if bg_box else 300
        try:
            natural_width = page.eval_on_selector("#aliyunCaptcha-img", "el => el.naturalWidth")
            if natural_width and natural_width > 0:
                scale = display_width / natural_width
                logger.info(f"原图宽度: {natural_width}px, 显示宽度: {display_width}px, 缩放: {scale:.4f}")
                return scale
        except Exception as e:
            logger.warning(f"获取原图宽度失败: {e}")
        return 1.0

    def _jfbym_scale_from_screenshot(self, screenshot, page):
        """单图接口：按截图宽度与页面显示宽度缩放"""
        try:
            body = page.locator(".aliyunCaptcha-body").first
            if body.count() == 0:
                body = page.locator("#aliyunCaptcha-img").first
            box = body.bounding_box()
            display_width = box["width"] if box else 300

            if _CV2_AVAILABLE:
                img_arr = cv2.imdecode(np.frombuffer(screenshot, np.uint8), cv2.IMREAD_COLOR)
                original_width = img_arr.shape[1]
            else:
                import io
                from PIL import Image as PILImage
                img = PILImage.open(io.BytesIO(screenshot))
                original_width = img.width
            scale = display_width / original_width if original_width > 0 else 1.0
            logger.info(f"截图宽度: {original_width}px, 页面显示宽度: {display_width}px, 缩放: {scale:.4f}")
            return scale
        except Exception as e:
            logger.warning(f"获取截图宽度失败: {e}，使用缩放 1.0")
            return 1.0

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
        # 保存到青龙，失败不影响登录结果
        save_msg = ""
        try:
            save_ok, msg = self.save_token(token, remarks=f"手机号 {info.get('mobile', '')}")
            save_msg = f"（{msg}）" if save_ok else f"（保存失败: {msg}）"
        except Exception as e:
            save_msg = f"（保存异常: {e}）"
        return True, save_msg, info

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
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh'] });
                window.chrome = { runtime: {} };
                window._xht_captcha_param = null;
                window._xht_captcha_done = false;

                // 策略A：拦截 postMessage（阿里云验证码通过 iframe 通信）
                var _origAddEventListener = window.addEventListener;
                window.addEventListener = function(type, listener, options) {
                    if (type === 'message') {
                        var wrapped = function(e) {
                            try {
                                if (e.data && typeof e.data === 'string') {
                                    var data = JSON.parse(e.data);
                                    if (data.captchaVerifyParam) {
                                        window._xht_captcha_param = data.captchaVerifyParam;
                                        window._xht_captcha_done = true;
                                    }
                                }
                            } catch(ignored) {}
                            return listener.call(this, e);
                        };
                        return _origAddEventListener.call(this, type, wrapped, options);
                    }
                    return _origAddEventListener.call(this, type, listener, options);
                };

                // 策略B：拦截 fetch 请求体
                var _origFetch = window.fetch;
                window.fetch = function(url, opts) {
                    if (opts && opts.body && typeof opts.body === 'string') {
                        try {
                            var body = JSON.parse(opts.body);
                            if (body.captchaVerifyParam) {
                                window._xht_captcha_param = body.captchaVerifyParam;
                                window._xht_captcha_done = true;
                            }
                        } catch(ignored) {}
                    }
                    return _origFetch.apply(this, arguments);
                };

                // 策略C：拦截 XHR 请求体
                var _origXHRSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.send = function(body) {
                    if (body && typeof body === 'string') {
                        try {
                            var parsed = JSON.parse(body);
                            if (parsed.captchaVerifyParam) {
                                window._xht_captcha_param = parsed.captchaVerifyParam;
                                window._xht_captcha_done = true;
                            }
                        } catch(ignored) {}
                    }
                    return _origXHRSend.call(this, body);
                };

                // 策略D：轮询检查 initAliyunCaptcha 挂载回调
                (function _poll() {
                    if (window._xht_captcha_done) return;
                    if (window.initAliyunCaptcha && !window._xht_aliyun_hooked) {
                        window._xht_aliyun_hooked = true;
                        var _orig = window.initAliyunCaptcha;
                        window.initAliyunCaptcha = function(cfg) {
                            var cb = cfg.captchaVerifyCallback;
                            cfg.captchaVerifyCallback = function(result) {
                                // 阿里云回调可能返回字符串或对象，统一提取
                                if (typeof result === 'string') {
                                    window._xht_captcha_param = result;
                                } else if (result && typeof result === 'object') {
                                    window._xht_captcha_param = result.captchaVerifyParam || result.data || JSON.stringify(result);
                                }
                                window._xht_captcha_raw = JSON.stringify(result);
                                window._xht_captcha_done = true;
                                if (cb) return cb.apply(this, arguments);
                                return { captchaResult: true, bizResult: true };
                            };
                            return _orig(cfg);
                        };
                    }
                    setTimeout(_poll, 100);
                })();
            """)

            # 策略E：用 page.route 拦截 SMS 请求，捕获 captchaVerifyParam
            def _intercept_sms_request(route):
                request = route.request
                if request.post_data and 'captchaVerifyParam' in (request.post_data or ''):
                    try:
                        import json as _json
                        body = _json.loads(request.post_data)
                        if body.get('captchaVerifyParam'):
                            logger.info("page.route 拦截到 captchaVerifyParam")
                            page.evaluate("""
                                window._xht_captcha_param = arguments[0];
                                window._xht_captcha_done = true;
                            """, body['captchaVerifyParam'])
                    except Exception:
                        pass
                route.continue_()
            page.route("**/send_sms_code*", _intercept_sms_request)

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

            if not param:
                browser.close()
                return False, "未能获取 captchaVerifyParam，滑块验证失败", None

            logger.info("滑块验证通过，通过浏览器页面发送短信...")
            # 在浏览器页面内调用 SMS API，确保 session/cookies/deviceId
            sms = f"{XHT_CAPTCHA_WEB}/api/app/auth/captcha/validate/send_sms_code"
            sms_result = page.evaluate("""
                async ([url, phone, param, deviceId, siteId]) => {
                    try {
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'deviceId': deviceId,
                                'siteId': siteId,
                            },
                            body: JSON.stringify({
                                mobile: phone,
                                sceneType: 'app',
                                captchaVerifyParam: param,
                            }),
                        });
                        const data = await resp.json();
                        data;
                    } catch(e) {
                        {error: e.message};
                    }
                }
            """, [sms, phone, param, XHT_DEVICE_ID, XHT_SITE_ID])

            logger.info(f"页面内 SMS 响应: {sms_result}")
            browser.close()

            if sms_result.get("code") == 0:
                form_token = sms_result.get("data", {}).get("formToken", "")
                return True, f"短信已发送，formToken={form_token}", form_token
            return False, f"发送短信失败: {sms_result.get('msg', sms_result.get('error', '未知'))}", None


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
