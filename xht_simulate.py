#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 阅读/视频任务 - Playwright 模拟脚本

⚠️ 重要说明：
  阅读文章和观看视频任务由原生 APP 的 native 层直接处理，
  浏览器模拟无法触发阅读进度更新。此脚本仅用于：
  1. 帮助理解 APP 内部行为
  2. 捕获网络请求以供分析
  3. 未来如果发现 API 端点，可作为基础框架

运行方式：
  pip install playwright --break-system-packages
  playwright install chromium
  python3 xht_simulate.py

前置条件：
  需要在环境变量中设置 XHT_TOKEN 或传入 --token 参数
"""

import os
import sys
import time
import json
import asyncio
import argparse
import logging
from urllib.parse import unquote

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("XHT_SIM")

# ============================================================
# 配置
# ============================================================
TOKEN = os.environ.get("XHT_TOKEN", "")
BASE = "https://app.xuhuimedia.cn/media-basic-port"
DEVICE_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
SITE_ID = "310104"

API_H = {
    "User-Agent": "xu hui tong/2.5.0 (iPhone; iOS 26.5; Scale/3.00)",
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "*/*",
    "token": TOKEN,
    "deviceId": DEVICE_ID,
    "siteId": SITE_ID,
}

import requests


def api(path, body=None):
    """调用徐汇通 API"""
    r = requests.post(f"{BASE}{path}", headers=API_H, json=body or {}, timeout=10)
    if r.status_code == 200:
        return r.json()
    return None


def get_articles(count=25):
    """获取文章列表"""
    data = api("/api/app/news/content/list", {
        "orderBy": "release_desc",
        "channel": {"id": "4b63be60cfea4ec3aa1c6d9147745c49"},
        "pageSize": str(count), "pageNo": 1,
    })
    return data.get("data", {}).get("records", []) if data else []


def check_progress():
    """检查阅读/视频进度"""
    data = api("/api/app/personal/score/info")
    if data and data.get("code") == 0:
        for job in data["data"].get("jobs", []):
            if "阅读" in job.get("title", "") or "视频" in job.get("title", ""):
                logger.info(f"  {job['title']}: {job.get('progress', 0)}/{job.get('totalProgress', 'N/A')}")


async def simulate_reading(articles, max_articles=5):
    """
    使用 Playwright 模拟阅读文章
    注意：由于阅读追踪由原生 APP 处理，此方法不会增加阅读进度
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("需要安装 playwright: pip install playwright && playwright install chromium")
        sys.exit(1)

    captured_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                       "Rmt/XuHui; Version/2.5.0",
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )

        page = await context.new_page()

        # 拦截所有请求
        def on_request(request):
            captured_requests.append({
                "url": request.url,
                "method": request.method,
                "post_data": request.post_data,
            })

        def on_response(response):
            url = response.url
            if any(kw in url for kw in ['api', 'score', 'read', 'view', 'track',
                                          'action', 'stat', 'log', 'event', 'report']):
                try:
                    body = response.text()
                    if len(body) < 1000:
                        logger.info(f"  RESP {url} -> {body[:300]}")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        # 注入 Token 和 rmt 覆盖
        token_js = f"""
        window._rmt_token = '{TOKEN}';
        if (window.rmt) {{
            const origCallHandler = window.rmt.callHandler.bind(window.rmt);
            window.rmt.callHandler = function(name, data, cb) {{
                console.log('[SIM] callHandler:', name, JSON.stringify(data||{{}}).substring(0,200));
                if (name === 'getToken') {{
                    setTimeout(() => cb && cb(JSON.stringify({{type:'success',data:{{token:window._rmt_token}}}})), 50);
                }} else {{
                    setTimeout(() => cb && cb(JSON.stringify({{type:'success',data:{{}}}})), 50);
                }}
            }};
            if (window.rmt._eventHandler && window.rmt._eventHandler.ready) {{
                window.rmt._eventHandler.ready();
            }}
        }}
        """

        logger.info(f"模拟阅读 {min(max_articles, len(articles))} 篇文章...")
        for i, a in enumerate(articles[:max_articles]):
            aid = a.get("id", "")
            title = a.get("title", "")[:30]
            action_url = a.get("actionUrl", "")
            share_url = a.get("shareUrl", "")

            # 方案A: 打开文章详情页
            if "target=" in action_url:
                target = unquote(action_url).split("target=")[-1].split("&")[0]
                logger.info(f"  [{i+1}] {title}")
                logger.info(f"       URL: {target}")

                try:
                    await page.goto(target, wait_until="networkidle", timeout=15000)
                    await page.evaluate(token_js)
                    await asyncio.sleep(1)

                    # 模拟滚动阅读
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
                    await asyncio.sleep(0.5)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                    await asyncio.sleep(0.5)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    logger.info(f"      阅读完成")
                except Exception as e:
                    logger.error(f"      失败: {e}")

            # 方案B: 打开 shareUrl
            if share_url:
                logger.info(f"      shareUrl: {share_url[:60]}...")
                try:
                    await page.goto(share_url, wait_until="networkidle", timeout=15000)
                    await page.evaluate(token_js)
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.error(f"      shareUrl 失败: {e}")

            await asyncio.sleep(1)

        await browser.close()

    # 打印捕获的 API 请求
    api_calls = [c for c in captured_requests if
                 any(kw in c['url'] for kw in
                     ['api', 'score', 'read', 'view', 'track', 'action', 'stat', 'log'])]
    logger.info(f"\n捕获到 {len(api_calls)} 个 API 请求:")
    for c in api_calls:
        logger.info(f"  {c['method']} {c['url']}")
        if c['post_data']:
            logger.info(f"    body: {c['post_data'][:200]}")


async def main_async():
    parser = argparse.ArgumentParser(description="徐汇通阅读/视频模拟脚本")
    parser.add_argument("--token", help="JWT Token")
    parser.add_argument("--count", type=int, default=5, help="模拟阅读文章数")
    args = parser.parse_args()

    global TOKEN, API_H
    if args.token:
        TOKEN = args.token
        API_H["token"] = TOKEN

    if not TOKEN:
        logger.error("请设置 XHT_TOKEN 环境变量或使用 --token 参数")
        sys.exit(1)

    # 获取文章列表
    logger.info("获取文章列表...")
    articles = get_articles(count=25)
    logger.info(f"获取到 {len(articles)} 篇文章")

    # 当前进度
    logger.info("当前进度:")
    check_progress()

    # 模拟阅读
    await simulate_reading(articles, max_articles=args.count)

    # 模拟后进度
    logger.info("\n模拟后进度:")
    check_progress()

    logger.info("\n注意：阅读进度未增加是正常的，因为阅读追踪由原生 APP 处理，")
    logger.info("无法通过 HTTP API 或浏览器模拟完成。")
    logger.info("请参考 README.md 中的「抓包获取阅读API」章节获取帮助。")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()