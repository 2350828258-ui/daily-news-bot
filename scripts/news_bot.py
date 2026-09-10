"""
每日科技新闻推送机器人（大壮一号版本 - 飞书文档+按月归档版）

通过公开 RSS 按自定义主题拉取资讯，创建飞书文档并按月归档，推送到群。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import logging
import os
import re
import sys
import time
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as e:
        logger.warning("读取 .env 失败: %s", e)


_load_dotenv()

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "").strip().lstrip("\ufeff")
FEISHU_SECRET = os.getenv("FEISHU_SECRET", "").strip().lstrip("\ufeff")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "").strip()
FEISHU_ARCHIVE_FOLDER_TOKEN = os.getenv("FEISHU_ARCHIVE_FOLDER_TOKEN", "").strip()

KEYWORDS = ["大壮一号", "每日资讯"]

DEFAULT_TOPICS = (
    "大模型与基础技术",
    "AIGC工具与多模态",
    "AI智能体与行业落地",
    "行业动态与商业政策",
    "优秀AI视频案例与创作者生态"
)
MIN_TOPICS = 1
MAX_TOPICS = 5

DEFAULT_PUSH_HOUR = 7
DEFAULT_PUSH_MINUTE = 30

RSS_COUNT = 5
REQUEST_TIMEOUT = 15
FETCH_RETRIES = 2
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# 综合科技媒体（主要供前四个板块使用）
FALLBACK_FEEDS = (
    "https://www.ithome.com/rss/",
    "https://36kr.com/feed",
    "https://www.solidot.org/index.rss",
    "https://www.jiqizhixin.com/rss",
    "https://www.qbitai.com/feed",
    "https://www.infoq.cn/feed",
    "https://www.leiphone.com/feed",
    "https://www.pingwest.com/feed",
    "https://rss.huxiu.com/",
    "https://www.tmtpost.com/feed",
    "https://www.geekpark.net/rss",
)

# 全球高质量创作者社区（第五个板块专属）
CREATOR_FEEDS = (
    "https://www.reddit.com/r/aivideo/.rss",
    "https://www.reddit.com/r/comfyui/.rss",
    "https://www.reddit.com/r/Midjourney/.rss",
    "https://www.reddit.com/r/StableDiffusion/.rss",
    "https://www.reddit.com/r/aiArt/.rss",
)

TOPIC_PRIMARY_FEEDS: dict[str, tuple[str, ...]] = {
    "行业动态与商业政策": (
        "https://rss.huxiu.com/",
        "https://36kr.com/feed",
    ),
    "优秀AI视频案例与创作者生态": CREATOR_FEEDS,
}

TOPIC_SEARCH_QUERIES: dict[str, str] = {
    "大模型与基础技术": "AI大模型 OR OpenAI OR Google OR Anthropic OR DeepSeek OR 大模型",
    "AIGC工具与多模态": "AIGC OR Sora OR 可灵 OR Midjourney OR Stable Diffusion OR AI视频 OR AI绘画",
    "AI智能体与行业落地": "AI Agent OR 智能体 OR 具身智能 OR 人形机器人 OR 自动化工作流",
    "行业动态与商业政策": "AI 融资 OR AI 政策 OR AI 监管 OR 科技行业动态 OR AI芯片",
    "优秀AI视频案例与创作者生态": "AI短片 获奖 OR AI电影节 OR AI绘画 作品 OR Midjourney 艺术 OR Stable Diffusion 插画 OR 创作者 分享",
}

TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = {
    "大模型与基础技术": (
        "大模型", "AI大模型", "OpenAI", "Google", "Anthropic", "DeepSeek", "开源", "Llama", "Claude", "Gemini"
    ),
    "AIGC工具与多模态": (
        "AIGC", "Sora", "可灵", "即梦", "Midjourney", "Flux", "Stable Diffusion", "视频生成", "图像生成", "多模态"
    ),
    "AI智能体与行业落地": (
        "AI Agent", "智能体", "具身智能", "人形机器人", "自动化工作流", "落地", "应用", "宇树", "Figure"
    ),
    "行业动态与商业政策": (
        "融资", "并购", "IPO", "财报", "政策", "监管", "法规", "商业动态", "合作", "市场"
    ),
    "优秀AI视频案例与创作者生态": (
        "AI短片", "获奖", "电影节", "AI绘画", "插画", "艺术作品", "Midjourney", "Stable Diffusion", "创作者", "ComfyUI", "Runway", "Sora"
    ),
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 非法，使用默认 %d", name, raw, default)
        return default


PUSH_HOUR = _env_int("PUSH_HOUR", DEFAULT_PUSH_HOUR)
PUSH_MINUTE = _env_int("PUSH_MINUTE", DEFAULT_PUSH_MINUTE)


def validate_config() -> None:
    missing = []
    if not FEISHU_WEBHOOK_URL:
        missing.append("FEISHU_WEBHOOK_URL")
    if not FEISHU_SECRET:
        missing.append("FEISHU_SECRET")
    if not FEISHU_APP_ID:
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if missing:
        logger.error("缺少必要环境变量: %s", ", ".join(missing))
        sys.exit(1)
    if not FEISHU_ARCHIVE_FOLDER_TOKEN:
        logger.warning("未配置 FEISHU_ARCHIVE_FOLDER_TOKEN，文档将创建在云空间根目录")


def parse_topics(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        env_topics = os.getenv("TOPICS", "").strip()
        if env_topics:
            raw = env_topics
        else:
            return list(DEFAULT_TOPICS)

    topics: list[str] = []
    seen: set[str] = set()
    for part in str(raw).split(","):
        topic = part.strip()
        if not topic:
            continue
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic)

    if not (MIN_TOPICS <= len(topics) <= MAX_TOPICS):
        logger.error("主题数量须为 %d–%d 个，当前解析到 %d 个", MIN_TOPICS, MAX_TOPICS, len(topics))
        sys.exit(1)
    return topics


def topic_keywords(topic: str) -> tuple[str, ...]:
    parts = re.split(r"[\s/|]+|(?:\s+OR\s+)", topic, flags=re.IGNORECASE)
    keywords = [p.strip() for p in parts if p and p.strip()]
    if topic not in keywords:
        keywords.insert(0, topic)
    keywords.extend(TOPIC_SYNONYMS.get(topic, ()))
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(kw)
    return tuple(unique)


def google_news_rss_url(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_feed(url: str, retries: int = FETCH_RETRIES) -> Any | None:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if getattr(feed, "bozo", False) and not feed.entries:
                return None
            return feed
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
    logger.warning("拉取 RSS 失败 [%s]: %s", url, last_error)
    return None


def _entry_to_item(entry: Any, default_source: str = "") -> dict[str, str]:
    title = strip_html(getattr(entry, "title", "") or "无标题")
    source = default_source
    if hasattr(entry, "source") and getattr(entry.source, "title", None):
        source = entry.source.title
    elif getattr(entry, "author", None):
        source = str(entry.author)
    snippet = strip_html(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
    return {
        "title": title,
        "source": source or "未知来源",
        "url": getattr(entry, "link", "") or "",
        "snippet": snippet[:80],
    }


def _match_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


_fallback_feed_cache: dict[str, Any | None] = {}
# 黑名单：彻底封杀短视频营销号、广告、培训、引流
_TITLE_BLOCKLIST = (
    "个人中心", "的个人主页", "登录", "注册", "甘肃日报", "兰州晚报", "新甘肃",
    "广告", "抽奖", "免费领取", "点击购买", "优惠", "招商", "代理", "兼职",
    "月入", "震惊", "速看", "删前", "福利", "下载", "安装", "扫码", "加群",
    "培训", "变现", "副业", "带你", "零基础", "小白", "干货", "速成", "引流",
)


def _is_junk_item(item: dict[str, str]) -> bool:
    blob = f"{item.get('title', '')} {item.get('source', '')} {item.get('url', '')}"
    return any(bad in blob for bad in _TITLE_BLOCKLIST)


def _load_feeds(urls: tuple[str, ...]) -> list[tuple[str, Any]]:
    loaded: list[tuple[str, Any]] = []
    for feed_url in urls:
        if feed_url not in _fallback_feed_cache:
            _fallback_feed_cache[feed_url] = _fetch_feed(feed_url)
        feed = _fallback_feed_cache[feed_url]
        if feed and feed.entries:
            loaded.append((feed_url, feed))
    return loaded


def _collect_from_feeds(feed_pairs, *, keywords, count, seen_titles):
    results: list[dict[str, str]] = []
    for feed_url, feed in feed_pairs:
        feed_title = getattr(feed.feed, "title", "") or feed_url
        for entry in feed.entries:
            item = _entry_to_item(entry, default_source=str(feed_title))
            if _is_junk_item(item):
                continue
            if keywords is not None:
                blob = f"{item['title']} {item['snippet']}"
                if not _match_keywords(blob, keywords):
                    continue
            title_key = item["title"].strip().lower()
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            results.append(item)
            if len(results) >= count:
                return results
    return results


def search_news_by_topic(topic: str, count: int = RSS_COUNT) -> list[dict[str, str]]:
    keywords = topic_keywords(topic)
    seen_titles: set[str] = set()
    results: list[dict[str, str]] = []

    # 1) 第五板块专属：只从创作者社区抓取，绝不碰国内综合科技媒体
    if topic == "优秀AI视频案例与创作者生态":
        creator_items = _collect_from_feeds(
            _load_feeds(CREATOR_FEEDS), keywords=keywords, count=count, seen_titles=seen_titles
        )
        return creator_items[:count]

    # 2) 其他板块：按原逻辑（优先源 -> Google News -> 国内综合媒体）
    primary_urls = TOPIC_PRIMARY_FEEDS.get(topic)
    if primary_urls:
        primary_items = _collect_from_feeds(
            _load_feeds(primary_urls), keywords=None, count=count, seen_titles=seen_titles
        )
        results.extend(primary_items)
        if len(results) >= count:
            return results[:count]

    query = TOPIC_SEARCH_QUERIES.get(topic, topic)
    google_url = google_news_rss_url(query)
    feed = _fetch_feed(google_url, retries=1)
    if feed and feed.entries:
        for entry in feed.entries:
            item = _entry_to_item(entry)
            if _is_junk_item(item):
                continue
            title_key = item["title"].strip().lower()
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            results.append(item)
            if len(results) >= count:
                break
        if len(results) >= count:
            return results[:count]

    more = _collect_from_feeds(
        _load_feeds(FALLBACK_FEEDS),
        keywords=keywords,
        count=count - len(results),
        seen_titles=seen_titles,
    )
    results.extend(more)
    return results[:count]


def generate_sign(secret: str, timestamp: str) -> str:
    key = f"{timestamp}\n{secret}"
    return base64.b64encode(hmac.new(key.encode(), b"", hashlib.sha256).digest()).decode("utf-8")


def send_with_sign(content: str) -> dict[str, Any]:
    try:
        timestamp = str(int(time.time()))
        sign = generate_sign(FEISHU_SECRET, timestamp)
        payload = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "text",
            "content": {"text": content},
        }
        response = requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=REQUEST_TIMEOUT)
        result = response.json()
        logger.info("飞书响应: %s", result)
        return result
    except Exception as e:
        logger.error("发送失败: %s", e)
        return {"code": -1, "msg": str(e)}


def _get_tenant_access_token() -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
    return token


def _get_or_create_monthly_folder(token: str, headers: dict) -> str:
    if not FEISHU_ARCHIVE_FOLDER_TOKEN:
        return ""

    current_month = datetime.now().strftime("%Y-%m")
    logger.info("检查归档文件夹: %s", current_month)

    try:
        list_url = "https://open.feishu.cn/open-apis/drive/v1/files"
        params = {"folder_token": FEISHU_ARCHIVE_FOLDER_TOKEN, "page_size": 200}
        resp = requests.get(list_url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        files = resp.json().get("data", {}).get("files", [])

        for f in files:
            if f.get("type") == "folder" and f.get("name") == current_month:
                folder_token = f.get("token")
                logger.info("✅ 已找到当月归档文件夹: %s (token: %s)", current_month, folder_token)
                return folder_token

        create_folder_url = "https://open.feishu.cn/open-apis/drive/v1/files/create_folder"
        payload = {"name": current_month, "folder_token": FEISHU_ARCHIVE_FOLDER_TOKEN}
        resp = requests.post(create_folder_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        new_token = resp.json().get("data", {}).get("token")
        logger.info("✅ 已创建当月归档文件夹: %s (token: %s)", current_month, new_token)
        return new_token or ""

    except Exception as e:
        logger.warning("获取/创建归档文件夹失败，文档将创建在根目录: %s", e)
        return ""


def _build_doc_blocks(sections: list[tuple[str, list[dict[str, str]]]]) -> list[dict]:
    today = datetime.now().strftime("%Y年%m月%d日")
    blocks = []

    blocks.append(_text_block("大壮家族的朋友们，集合啦！我是你们的老朋友——大壮一号！"))
    blocks.append(_text_block(f"今天是{today}，别人都在愁没方向，大壮一号给你们把AI最前沿的情报都端上来啦！"))

    for topic, news in sections:
        blocks.append(_text_block(f"📌 {topic}", bold=True))
        if news:
            for i, item in enumerate(news, start=1):
                title = item["title"].replace("【", "").replace("】", "").strip()
                url = (item.get("url") or "").strip()
                line = f"{i}）{title}"
                if url:
                    line += f" 🔗 {url}"
                blocks.append(_text_block(line))
        else:
            blocks.append(_text_block("今天这板块兄弟们没整出啥大动静，让大壮一号再去打探打探～"))

    blocks.append(_text_block("好啦，今天的吹牛就到这里！大壮一号祝各位大壮家族的朋友们，新的一天吃嘛嘛香，做视频不卡顿！😎✨"))
    return blocks


def _text_block(text: str, bold: bool = False) -> dict:
    return {
        "block_type": 2,
        "text": {
            "elements": [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {"bold": bold}
                    }
                }
            ],
            "style": {}
        }
    }


def create_feishu_document(title: str, sections: list[tuple[str, list[dict[str, str]]]]) -> str:
    token = _get_tenant_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    monthly_folder_token = _get_or_create_monthly_folder(token, headers)

    create_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
    payload = {"title": title}
    if monthly_folder_token:
        payload["folder_token"] = monthly_folder_token

    resp = requests.post(create_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    doc_data = resp.json().get("data", {})
    document_id = doc_data.get("document", {}).get("document_id")
    if not document_id:
        raise RuntimeError(f"创建文档失败: {resp.text}")

    doc_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}"
    resp = requests.get(doc_url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    root_block_id = resp.json().get("data", {}).get("document", {}).get("document_id")

    blocks = _build_doc_blocks(sections)
    write_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{root_block_id}/children"
    write_payload = {"children": blocks, "index": 0}
    resp = requests.post(write_url, headers=headers, json=write_payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    try:
        perm_url = f"https://open.feishu.cn/open-apis/drive/v1/permissions/{document_id}/public?type=docx"
        perm_payload = {"link_share_entity": "tenant_readable"}
        resp = requests.patch(perm_url, headers=headers, json=perm_payload, timeout=REQUEST_TIMEOUT)
        logger.info("修改文档权限响应: %s", resp.text)
    except Exception as e:
        logger.warning("修改文档权限失败（不影响文档创建）: %s", e)

    return f"https://feishu.cn/docx/{document_id}"


def job_news_push(topics: list[str]) -> int:
    _fallback_feed_cache.clear()
    logger.info("=" * 50)
    logger.info("开始执行新闻推送任务...")
    logger.info("主题: %s", ", ".join(topics))

    sections: list[tuple[str, list[dict[str, str]]]] = []
    any_news = False
    for topic in topics:
        logger.info("正在搜索「%s」新闻...", topic)
        news = search_news_by_topic(topic, count=RSS_COUNT)
        if news:
            any_news = True
        sections.append((topic, news))

    if not any_news:
        logger.error("未获取到任何新闻，任务终止")
        return 1

    today_str = datetime.now().strftime("%Y-%m-%d")
    doc_title = f"大壮一号AI日报 | {today_str}"
    try:
        doc_url = create_feishu_document(doc_title, sections)
        logger.info("✅ 文档创建成功: %s", doc_url)
    except Exception as e:
        logger.error("创建飞书文档失败: %s", e)
        return 1

    message = f"🔔 大壮一号播报\n大壮家族的朋友们，今日AI日报已生成，请查收：\n{doc_url}"
    result = send_with_sign(message)

    if result.get("code") == 0:
        logger.info("✅ 文档链接推送成功！")
        return 0
    else:
        logger.error("❌ 文档链接推送失败: %s", result.get("msg"))
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日科技新闻推送机器人")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="推送一次后退出")
    mode.add_argument("--schedule", action="store_true", help="长驻定时")
    parser.add_argument("--topics", type=str, default=None, help="推送主题")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_config()
    topics = parse_topics(args.topics)

    if args.schedule:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
        scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(job_news_push, CronTrigger(hour=PUSH_HOUR, minute=PUSH_MINUTE, timezone="Asia/Shanghai"), args=[topics])
        scheduler.start()
        return

    exit_code = job_news_push(topics)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
