#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
徐汇通 抓包辅助工具

用于帮助用户通过抓包获取阅读/视频任务的 API 端点。

使用方法：
  1. 在手机上安装抓包工具（如 HttpCanary、Stream、Thor 等）
  2. 打开抓包工具，开始捕获 HTTPS 流量
  3. 打开徐汇通 APP，浏览几篇文章和视频
  4. 停止抓包，导出抓包数据为 HAR 格式
  5. 运行此脚本分析 HAR 文件：
     python3 xht_capture.py --har capture.har

或者使用 mitmproxy：
  1. 在电脑上安装 mitmproxy：pip install mitmproxy
  2. 设置手机代理到电脑 IP:8080
  3. 安装 mitmproxy CA 证书到手机
  4. 运行：mitmdump -w xht_traffic.flow
  5. 在手机上使用徐汇通 APP 浏览文章和视频
  6. 停止 mitmdump，运行：python3 xht_capture.py --flow xht_traffic.flow
"""

import os
import sys
import json
import argparse
import logging
import requests
from urllib.parse import urlparse, parse_qs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("XHT_CAPTURE")


def analyze_har(har_file: str):
    """分析 HAR 格式的抓包文件"""
    with open(har_file, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    logger.info(f"HAR 文件包含 {len(entries)} 个请求")

    api_calls = []
    for entry in entries:
        request = entry.get("request", {})
        url = request.get("url", "")
        method = request.get("method", "")

        # 过滤出 API 请求
        if any(kw in url for kw in [
            "api", "score", "read", "view", "watch", "track",
            "action", "event", "task", "job", "point", "credit",
            "content", "news", "video", "personal", "media-basic-port",
            "shmedia.tech", "xuhuimedia.cn", "ewdcloud.com",
        ]):
            post_data = request.get("postData", {})
            if isinstance(post_data, dict):
                post_text = post_data.get("text", "")
            else:
                post_text = str(post_data) if post_data else ""

            api_calls.append({
                "url": url,
                "method": method,
                "post_data": post_text[:500],
                "status": entry.get("response", {}).get("status", 0),
            })

    # 去重并分类
    unique_urls = {}
    for call in api_calls:
        url = call["url"]
        # 去掉查询参数
        base_url = url.split("?")[0]
        if base_url not in unique_urls:
            unique_urls[base_url] = call

    logger.info(f"\n找到 {len(unique_urls)} 个唯一 API 端点:")
    logger.info("=" * 60)

    for url, call in sorted(unique_urls.items()):
        method = call["method"]
        status = call["status"]
        post_data = call["post_data"]

        # 标记可能的阅读/视频追踪 API
        tags = []
        if any(kw in url.lower() for kw in ["read", "阅读"]):
            tags.append("🔍 阅读相关")
        if any(kw in url.lower() for kw in ["video", "watch", "play", "视频"]):
            tags.append("📹 视频相关")
        if any(kw in url.lower() for kw in ["score", "point", "credit", "积分"]):
            tags.append("💰 积分相关")
        if any(kw in url.lower() for kw in ["track", "log", "stat", "event", "action"]):
            tags.append("📊 追踪/统计")

        tag_str = " | ".join(tags) if tags else ""

        logger.info(f"\n{method} {url}")
        if tag_str:
            logger.info(f"  {tag_str}")
        logger.info(f"  Status: {status}")
        if post_data:
            logger.info(f"  Body: {post_data}")

    logger.info("\n" + "=" * 60)
    logger.info("分析完成！请关注标记为 '🔍 阅读相关' 或 '📹 视频相关' 的端点。")
    logger.info("这些就是阅读/视频任务的 API 端点，可集成到 xht.py 中。")

    return unique_urls


def analyze_flow(flow_file: str):
    """分析 mitmproxy flow 文件"""
    try:
        from mitmproxy.io import FlowReader
    except ImportError:
        logger.error("需要安装 mitmproxy: pip install mitmproxy")
        sys.exit(1)

    api_calls = []
    with open(flow_file, "rb") as f:
        reader = FlowReader(f)
        for flow in reader.stream():
            request = flow.request
            url = request.pretty_url if hasattr(request, 'pretty_url') else request.url
            method = request.method

            if any(kw in url for kw in [
                "api", "score", "read", "view", "watch", "track",
                "action", "event", "task", "job", "point", "credit",
                "shmedia.tech", "xuhuimedia.cn", "ewdcloud.com",
            ]):
                post_data = request.get_text() if request.content else ""
                api_calls.append({
                    "url": url,
                    "method": method,
                    "post_data": post_data[:500] if post_data else "",
                    "status": flow.response.status_code if flow.response else 0,
                })

    unique_urls = {}
    for call in api_calls:
        base_url = call["url"].split("?")[0]
        if base_url not in unique_urls:
            unique_urls[base_url] = call

    logger.info(f"找到 {len(unique_urls)} 个唯一 API 端点:")
    for url, call in sorted(unique_urls.items()):
        logger.info(f"  {call['method']} {url} -> {call['status']}")
        if call['post_data']:
            logger.info(f"    body: {call['post_data']}")

    return unique_urls


def capture_instructions():
    """打印抓包指引"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║          徐汇通 阅读/视频 API 抓包指引                      ║
╠══════════════════════════════════════════════════════════════╣
║                                                            ║
║  背景：阅读文章和观看视频的 API 端点由原生 APP 处理，      ║
║  无法通过静态分析获取。需要通过抓包来捕获这些 API。        ║
║                                                            ║
║  方法一：手机抓包工具（推荐）                              ║
║  ─────────────────────────────────────                     ║
║  1. 在手机上安装抓包工具：                                 ║
║     - Android: HttpCanary, Packet Capture                  ║
║     - iOS: Stream, Thor, Quantumult X                      ║
║  2. 安装抓包工具的 CA 证书（用于解密 HTTPS）               ║
║  3. 开始抓包                                               ║
║  4. 打开徐汇通 APP，浏览 2-3 篇文章（滚动到底部）          ║
║  5. 观看 2-3 个视频（播放完整视频）                        ║
║  6. 停止抓包，导出为 HAR 格式                              ║
║  7. 运行: python3 xht_capture.py --har capture.har          ║
║                                                            ║
║  方法二：mitmproxy（电脑端）                               ║
║  ─────────────────────────────                             ║
║  1. pip install mitmproxy                                  ║
║  2. 手机设置 WiFi 代理 -> 电脑 IP:8080                     ║
║  3. 手机浏览器访问 mitm.it 安装 CA 证书                    ║
║  4. 运行: mitmdump -w xht_traffic.flow                     ║
║  5. 在手机上使用徐汇通 APP 浏览文章和视频                  ║
║  6. 按 Ctrl+C 停止 mitmdump                                ║
║  7. 运行: python3 xht_capture.py --flow xht_traffic.flow    ║
║                                                            ║
║  找到 API 后：                                             ║
║  ────────────                                              ║
║  将 API 端点信息提交到 GitHub Issues 或在 xht.py 中       ║
║  添加阅读/视频任务的 API 调用。                            ║
║                                                            ║
╚══════════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(description="徐汇通抓包分析工具")
    parser.add_argument("--har", help="HAR 抓包文件路径")
    parser.add_argument("--flow", help="mitmproxy flow 文件路径")
    parser.add_argument("--guide", action="store_true", help="显示抓包指引")
    args = parser.parse_args()

    if args.guide:
        capture_instructions()
        return

    if args.har:
        analyze_har(args.har)
    elif args.flow:
        analyze_flow(args.flow)
    else:
        capture_instructions()


if __name__ == "__main__":
    main()