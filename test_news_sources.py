# filename: test_news_sources.py
# Python 3.11+
#
# 用途：
# 1) 测试新闻站点首页/频道页可达性
# 2) 测试 RSS/Atom 是否可读
# 3) 从 RSS 或首页提取文章链接，测试正文抓取是否成功
# 4) 输出 JSON + Markdown 报告
#
# 安装依赖：
# pip install requests beautifulsoup4 trafilatura lxml
#
# 运行：
# python test_news_sources.py
#
# 可选环境变量：
# PROBE_TIMEOUT=20
# MAX_ARTICLES_PER_SOURCE=5

from __future__ import annotations

import json
import os
import re
import time
import traceback
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
import trafilatura


TIMEOUT = int(os.getenv("PROBE_TIMEOUT", "20"))
MAX_ARTICLES_PER_SOURCE = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "5"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass
class Source:
    name: str
    group: str  # domestic / international / extra
    base_url: str
    homepage: str
    section_urls: List[str]
    rss_urls: List[str]
    article_url_patterns: List[str]  # 正则，用于过滤疑似新闻详情页


@dataclass
class ProbeResult:
    name: str
    group: str
    homepage_ok: bool = False
    homepage_status: Optional[int] = None
    homepage_final_url: Optional[str] = None
    homepage_error: Optional[str] = None

    rss_ok: bool = False
    rss_working_url: Optional[str] = None
    rss_items_found: int = 0
    rss_error: Optional[str] = None

    article_candidates: int = 0
    article_probe_success: int = 0
    article_probe_total: int = 0
    article_sample_urls: List[str] = None
    extract_success_rate: float = 0.0

    verdict: str = "unknown"   # good / partial / blocked / failed
    notes: List[str] = None


SOURCES: List[Source] = [
    # ---------------- 国内 ----------------
    Source(
        name="新浪新闻",
        group="domestic",
        base_url="https://news.sina.com.cn",
        homepage="https://news.sina.com.cn/",
        section_urls=[
            "https://news.sina.com.cn/china/",
            "https://news.sina.com.cn/world/",
            "https://finance.sina.com.cn/",
        ],
        rss_urls=[],
        article_url_patterns=[r"sina\.com\.cn/.+/\d{4}-\d{2}-\d{2}/doc-"],
    ),
    Source(
        name="网易新闻",
        group="domestic",
        base_url="https://news.163.com",
        homepage="https://news.163.com/",
        section_urls=[
            "https://news.163.com/domestic/",
            "https://news.163.com/world/",
            "https://money.163.com/",
        ],
        rss_urls=[],
        article_url_patterns=[r"163\.com/.+article/.+\.html"],
    ),
    Source(
        name="腾讯新闻",
        group="domestic",
        base_url="https://news.qq.com",
        homepage="https://news.qq.com/",
        section_urls=[
            "https://news.qq.com/china_index.htm",
            "https://news.qq.com/world_index.htm",
            "https://new.qq.com/ch/finance/",
        ],
        rss_urls=[],
        article_url_patterns=[r"(qq\.com/rain/a/|new\.qq\.com/rain/a/)"],
    ),
    Source(
        name="新华网",
        group="domestic",
        base_url="http://www.news.cn",
        homepage="http://www.news.cn/",
        section_urls=[
            "http://www.news.cn/politics/",
            "http://www.news.cn/world/",
            "http://www.news.cn/fortune/",
        ],
        rss_urls=[],
        article_url_patterns=[r"news\.cn/.+/\d{8}/[a-zA-Z0-9_]+\.htm"],
    ),
    Source(
        name="人民网",
        group="domestic",
        base_url="http://www.people.com.cn",
        homepage="http://www.people.com.cn/",
        section_urls=[
            "http://politics.people.com.cn/",
            "http://world.people.com.cn/",
            "http://finance.people.com.cn/",
        ],
        rss_urls=[],
        article_url_patterns=[r"people\.com\.cn/.+/n\d{4}/\d{4}/c\d+-\d+\.html"],
    ),
    Source(
        name="央视网",
        group="domestic",
        base_url="https://news.cctv.com",
        homepage="https://news.cctv.com/",
        section_urls=[
            "https://news.cctv.com/china/",
            "https://news.cctv.com/world/",
            "https://finance.cctv.com/",
        ],
        rss_urls=[],
        article_url_patterns=[r"cctv\.com/.+/\d{2}/\d{2}/[A-Z0-9]+\.shtml"],
    ),
    Source(
        name="凤凰网",
        group="domestic",
        base_url="https://news.ifeng.com",
        homepage="https://news.ifeng.com/",
        section_urls=[
            "https://news.ifeng.com/c/",
            "https://news.ifeng.com/world/",
            "https://finance.ifeng.com/",
        ],
        rss_urls=[],
        article_url_patterns=[r"ifeng\.com/c/\d+[a-zA-Z0-9]*"],
    ),
    Source(
        name="环球网",
        group="domestic",
        base_url="https://www.huanqiu.com",
        homepage="https://www.huanqiu.com/",
        section_urls=[
            "https://world.huanqiu.com/",
            "https://china.huanqiu.com/",
            "https://finance.huanqiu.com/",
        ],
        rss_urls=[],
        article_url_patterns=[r"huanqiu\.com/article/"],
    ),
    Source(
        name="澎湃新闻",
        group="domestic",
        base_url="https://www.thepaper.cn",
        homepage="https://www.thepaper.cn/",
        section_urls=[
            "https://www.thepaper.cn/channel_25950",
            "https://www.thepaper.cn/channel_122908",
            "https://www.thepaper.cn/channel_25951",
        ],
        rss_urls=[],
        article_url_patterns=[r"thepaper\.cn/newsDetail_forward_\d+"],
    ),
    Source(
        name="界面新闻",
        group="domestic",
        base_url="https://www.jiemian.com",
        homepage="https://www.jiemian.com/",
        section_urls=[
            "https://www.jiemian.com/lists/4.html",
            "https://www.jiemian.com/lists/20.html",
            "https://www.jiemian.com/lists/5.html",
        ],
        rss_urls=[],
        article_url_patterns=[r"jiemian\.com/article/\d+\.html"],
    ),
    Source(
        name="财新网",
        group="domestic",
        base_url="https://www.caixin.com",
        homepage="https://www.caixin.com/",
        section_urls=[
            "https://china.caixin.com/",
            "https://international.caixin.com/",
            "https://economy.caixin.com/",
        ],
        rss_urls=[],
        article_url_patterns=[r"caixin\.com/\d{4}-\d{2}-\d{2}/\d+\.html"],
    ),
    Source(
        name="第一财经",
        group="domestic",
        base_url="https://www.yicai.com",
        homepage="https://www.yicai.com/",
        section_urls=[
            "https://www.yicai.com/news/",
            "https://www.yicai.com/world/",
            "https://www.yicai.com/finance/",
        ],
        rss_urls=[],
        article_url_patterns=[r"yicai\.com/news/\d+\.html"],
    ),
    Source(
        name="新闻晨报",
        group="domestic",
        base_url="https://www.jfdaily.com",
        homepage="https://www.jfdaily.com/",
        section_urls=[
            "https://www.jfdaily.com/channel_77",
            "https://www.jfdaily.com/channel_3",
            "https://www.jfdaily.com/channel_5",
        ],
        rss_urls=[],
        article_url_patterns=[r"jfdaily\.com/news/detail\?id=\d+"],
    ),

    # ---------------- 国际 ----------------
    Source(
        name="CNN",
        group="international",
        base_url="https://www.cnn.com",
        homepage="https://www.cnn.com/",
        section_urls=[
            "https://www.cnn.com/world",
            "https://www.cnn.com/business",
            "https://www.cnn.com/politics",
        ],
        rss_urls=[
            "https://rss.cnn.com/rss/edition.rss",
            "https://rss.cnn.com/rss/edition_world.rss",
            "https://rss.cnn.com/rss/money_latest.rss",
        ],
        article_url_patterns=[r"cnn\.com/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="卫报 The Guardian",
        group="international",
        base_url="https://www.theguardian.com",
        homepage="https://www.theguardian.com/international",
        section_urls=[
            "https://www.theguardian.com/world",
            "https://www.theguardian.com/business",
            "https://www.theguardian.com/technology",
        ],
        rss_urls=[
            "https://www.theguardian.com/world/rss",
            "https://www.theguardian.com/business/rss",
            "https://www.theguardian.com/uk/technology/rss",
        ],
        article_url_patterns=[r"theguardian\.com/.+/\d{4}/[a-z]{3}/\d{2}/"],
    ),
    Source(
        name="金融时报 FT",
        group="international",
        base_url="https://www.ft.com",
        homepage="https://www.ft.com/",
        section_urls=[
            "https://www.ft.com/world",
            "https://www.ft.com/companies",
            "https://www.ft.com/technology",
        ],
        rss_urls=[
            "https://www.ft.com/world?format=rss",
            "https://www.ft.com/technology?format=rss",
            "https://www.ft.com/companies?format=rss",
        ],
        article_url_patterns=[r"ft\.com/content/"],
    ),
    Source(
        name="华尔街日报 WSJ",
        group="international",
        base_url="https://www.wsj.com",
        homepage="https://www.wsj.com/",
        section_urls=[
            "https://www.wsj.com/world",
            "https://www.wsj.com/business",
            "https://www.wsj.com/tech",
        ],
        rss_urls=[
            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
            "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
            "https://feeds.a.dj.com/rss/RSSTech.xml",
        ],
        article_url_patterns=[r"wsj\.com/.+"],
    ),
    Source(
        name="泰晤士报 The Times",
        group="international",
        base_url="https://www.thetimes.com",
        homepage="https://www.thetimes.com/",
        section_urls=[
            "https://www.thetimes.com/world",
            "https://www.thetimes.com/business-money",
        ],
        rss_urls=[],
        article_url_patterns=[r"thetimes\.com/article/"],
    ),
    Source(
        name="经济学人 The Economist",
        group="international",
        base_url="https://www.economist.com",
        homepage="https://www.economist.com/",
        section_urls=[
            "https://www.economist.com/the-world-this-week",
            "https://www.economist.com/finance-and-economics",
            "https://www.economist.com/business",
            "https://www.economist.com/science-and-technology",
        ],
        rss_urls=[],
        article_url_patterns=[r"economist\.com/.+"],
    ),
    Source(
        name="财富杂志 Fortune",
        group="international",
        base_url="https://fortune.com",
        homepage="https://fortune.com/",
        section_urls=[
            "https://fortune.com/world/",
            "https://fortune.com/finance/",
            "https://fortune.com/technology/",
        ],
        rss_urls=[],
        article_url_patterns=[r"fortune\.com/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="福布斯 Forbes",
        group="international",
        base_url="https://www.forbes.com",
        homepage="https://www.forbes.com/",
        section_urls=[
            "https://www.forbes.com/business/",
            "https://www.forbes.com/money/",
            "https://www.forbes.com/innovation/",
        ],
        rss_urls=[],
        article_url_patterns=[r"forbes\.com/sites/.+/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="外交政策 Foreign Policy",
        group="international",
        base_url="https://foreignpolicy.com",
        homepage="https://foreignpolicy.com/",
        section_urls=[
            "https://foreignpolicy.com/latest/",
            "https://foreignpolicy.com/category/economics/",
        ],
        rss_urls=[],
        article_url_patterns=[r"foreignpolicy\.com/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="外交事务 Foreign Affairs",
        group="international",
        base_url="https://www.foreignaffairs.com",
        homepage="https://www.foreignaffairs.com/",
        section_urls=[
            "https://www.foreignaffairs.com/world",
            "https://www.foreignaffairs.com/economics",
        ],
        rss_urls=[],
        article_url_patterns=[r"foreignaffairs\.com/.+"],
    ),

    # ---------------- 我顺手补充的科技/财经 ----------------
    Source(
        name="Reuters",
        group="extra",
        base_url="https://www.reuters.com",
        homepage="https://www.reuters.com/",
        section_urls=[
            "https://www.reuters.com/world/",
            "https://www.reuters.com/business/",
            "https://www.reuters.com/technology/",
        ],
        rss_urls=[],
        article_url_patterns=[r"reuters\.com/world/|reuters\.com/business/|reuters\.com/technology/"],
    ),
    Source(
        name="AP News",
        group="extra",
        base_url="https://apnews.com",
        homepage="https://apnews.com/",
        section_urls=[
            "https://apnews.com/world-news",
            "https://apnews.com/business",
            "https://apnews.com/technology",
        ],
        rss_urls=[],
        article_url_patterns=[r"apnews\.com/article/"],
    ),
    Source(
        name="Bloomberg",
        group="extra",
        base_url="https://www.bloomberg.com",
        homepage="https://www.bloomberg.com/",
        section_urls=[
            "https://www.bloomberg.com/world",
            "https://www.bloomberg.com/markets",
            "https://www.bloomberg.com/technology",
        ],
        rss_urls=[],
        article_url_patterns=[r"bloomberg\.com/news/articles/"],
    ),
    Source(
        name="CNBC",
        group="extra",
        base_url="https://www.cnbc.com",
        homepage="https://www.cnbc.com/",
        section_urls=[
            "https://www.cnbc.com/world/",
            "https://www.cnbc.com/finance/",
            "https://www.cnbc.com/technology/",
        ],
        rss_urls=[
            "https://www.cnbc.com/id/100727362/device/rss/rss.html",
            "https://www.cnbc.com/id/19854910/device/rss/rss.html",
        ],
        article_url_patterns=[r"cnbc\.com/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="TechCrunch",
        group="extra",
        base_url="https://techcrunch.com",
        homepage="https://techcrunch.com/",
        section_urls=[
            "https://techcrunch.com/category/startups/",
            "https://techcrunch.com/category/artificial-intelligence/",
        ],
        rss_urls=["https://techcrunch.com/feed/"],
        article_url_patterns=[r"techcrunch\.com/\d{4}/\d{2}/\d{2}/"],
    ),
    Source(
        name="The Verge",
        group="extra",
        base_url="https://www.theverge.com",
        homepage="https://www.theverge.com/",
        section_urls=[
            "https://www.theverge.com/tech",
            "https://www.theverge.com/ai-artificial-intelligence",
        ],
        rss_urls=["https://www.theverge.com/rss/index.xml"],
        article_url_patterns=[r"theverge\.com/\d{4}/\d+/\d+/"],
    ),
    Source(
        name="Ars Technica",
        group="extra",
        base_url="https://arstechnica.com",
        homepage="https://arstechnica.com/",
        section_urls=[
            "https://arstechnica.com/tech-policy/",
            "https://arstechnica.com/gadgets/",
        ],
        rss_urls=["https://feeds.arstechnica.com/arstechnica/index"],
        article_url_patterns=[r"arstechnica\.com/.+/\d{4}/\d{2}/"],
    ),
    Source(
        name="Nikkei Asia",
        group="extra",
        base_url="https://asia.nikkei.com",
        homepage="https://asia.nikkei.com/",
        section_urls=[
            "https://asia.nikkei.com/Politics",
            "https://asia.nikkei.com/Business",
            "https://asia.nikkei.com/Tech-Science",
        ],
        rss_urls=[],
        article_url_patterns=[r"asia\.nikkei\.com/.+"],
    ),
]


def safe_get(url: str, timeout: int = TIMEOUT) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)


def looks_like_xml(text: str) -> bool:
    s = text.lstrip()
    return s.startswith("<?xml") or "<rss" in s[:5000].lower() or "<feed" in s[:5000].lower()


def parse_rss_items(xml_text: str) -> List[Dict[str, str]]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items

    # RSS
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        if link:
            items.append({"title": title.strip(), "link": link.strip()})

    # Atom
    ns_link_candidates = root.findall(".//{*}entry")
    for entry in ns_link_candidates:
        title = entry.findtext("{*}title") or ""
        link = ""
        for link_el in entry.findall("{*}link"):
            href = link_el.attrib.get("href")
            if href:
                link = href
                break
        if link:
            items.append({"title": title.strip(), "link": link.strip()})

    dedup = []
    seen = set()
    for x in items:
        if x["link"] not in seen:
            dedup.append(x)
            seen.add(x["link"])
    return dedup


def normalize_url(base: str, href: str) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if href.startswith("javascript:") or href.startswith("#"):
        return None
    return urljoin(base, href)


def same_domain_or_subdomain(url: str, base_url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        base_host = urlparse(base_url).netloc.lower()
        return host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host)
    except Exception:
        return False


def collect_links_from_html(url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = normalize_url(url, a.get("href"))
        if href:
            links.append(href)

    # og:url / canonical 有时也能帮助识别
    for tag in soup.select('link[rel="canonical"], meta[property="og:url"]'):
        href = tag.get("href") or tag.get("content")
        href = normalize_url(url, href) if href else None
        if href:
            links.append(href)

    dedup = []
    seen = set()
    for x in links:
        if x not in seen:
            dedup.append(x)
            seen.add(x)
    return dedup


def filter_article_links(source: Source, urls: List[str]) -> List[str]:
    out = []
    for u in urls:
        if not same_domain_or_subdomain(u, source.base_url):
            continue
        if any(re.search(p, u) for p in source.article_url_patterns):
            out.append(u)

    dedup = []
    seen = set()
    for u in out:
        if u not in seen:
            dedup.append(u)
            seen.add(u)
    return dedup[: MAX_ARTICLES_PER_SOURCE * 3]


def try_extract_article(url: str) -> Tuple[bool, str]:
    try:
        resp = safe_get(url, timeout=TIMEOUT)
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        downloaded = trafilatura.extract(
            resp.text,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if downloaded and len(downloaded.strip()) >= 150:
            return True, "ok"
        return False, "text_too_short_or_empty"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def probe_homepage(source: Source, result: ProbeResult) -> Optional[str]:
    candidate_pages = [source.homepage] + source.section_urls
    for page in candidate_pages:
        try:
            resp = safe_get(page)
            result.homepage_status = resp.status_code
            result.homepage_final_url = resp.url
            if resp.status_code < 400 and len(resp.text) > 500:
                result.homepage_ok = True
                return resp.text
        except Exception as e:
            result.homepage_error = f"{type(e).__name__}: {e}"
    return None


def probe_rss(source: Source, result: ProbeResult) -> List[str]:
    article_urls = []
    for rss in source.rss_urls:
        try:
            resp = safe_get(rss)
            if resp.status_code >= 400:
                continue
            if not looks_like_xml(resp.text):
                continue
            items = parse_rss_items(resp.text)
            if items:
                result.rss_ok = True
                result.rss_working_url = rss
                result.rss_items_found = len(items)
                article_urls = [x["link"] for x in items if x.get("link")]
                break
        except Exception as e:
            result.rss_error = f"{type(e).__name__}: {e}"
    return article_urls


def classify(result: ProbeResult) -> str:
    if result.rss_ok and result.article_probe_success >= 2:
        return "good"
    if result.homepage_ok and result.article_probe_success >= 1:
        return "partial"
    if result.homepage_ok or result.rss_ok:
        return "blocked"
    return "failed"


def probe_source(source: Source) -> ProbeResult:
    result = ProbeResult(name=source.name, group=source.group, article_sample_urls=[], notes=[])

    homepage_html = probe_homepage(source, result)
    rss_article_urls = probe_rss(source, result)

    candidate_urls = []

    if rss_article_urls:
        candidate_urls.extend(rss_article_urls)

    if homepage_html:
        homepage_links = collect_links_from_html(source.homepage, homepage_html)
        candidate_urls.extend(homepage_links)

    candidate_urls = filter_article_links(source, candidate_urls)
    result.article_candidates = len(candidate_urls)
    result.article_sample_urls = candidate_urls[:MAX_ARTICLES_PER_SOURCE]

    if not candidate_urls:
        result.notes.append("未识别到疑似文章链接；可能需要针对站点单独写 selector 或 API 方案。")

    to_probe = candidate_urls[:MAX_ARTICLES_PER_SOURCE]
    result.article_probe_total = len(to_probe)

    for u in to_probe:
        ok, msg = try_extract_article(u)
        if ok:
            result.article_probe_success += 1
        else:
            result.notes.append(f"正文抓取失败: {u} -> {msg}")

    if result.article_probe_total > 0:
        result.extract_success_rate = round(
            result.article_probe_success / result.article_probe_total, 4
        )

    result.verdict = classify(result)

    if result.verdict == "good":
        result.notes.append("适合接入主流程。")
    elif result.verdict == "partial":
        result.notes.append("可接入，但建议做站点定制解析。")
    elif result.verdict == "blocked":
        result.notes.append("有可达性，但正文提取不稳定；可能存在反爬、动态加载或订阅限制。")
    else:
        result.notes.append("当前脚本未能稳定抓取。")

    return result


def make_markdown(results: List[ProbeResult]) -> str:
    lines = []
    lines.append("# News Source Probe Report")
    lines.append("")
    lines.append("| 来源 | 分组 | 首页 | RSS | 正文成功/总数 | 成功率 | 结论 |")
    lines.append("|---|---|---:|---:|---:|---:|---|")

    for r in results:
        lines.append(
            f"| {r.name} | {r.group} | "
            f"{'✅' if r.homepage_ok else '❌'} | "
            f"{'✅' if r.rss_ok else '❌'} | "
            f"{r.article_probe_success}/{r.article_probe_total} | "
            f"{r.extract_success_rate:.0%} | {r.verdict} |"
        )

    lines.append("")
    lines.append("## Details")
    lines.append("")

    for r in results:
        lines.append(f"### {r.name}")
        lines.append(f"- 分组: {r.group}")
        lines.append(f"- 首页可达: {r.homepage_ok} (status={r.homepage_status}, final={r.homepage_final_url})")
        lines.append(f"- RSS 可用: {r.rss_ok} (url={r.rss_working_url}, items={r.rss_items_found})")
        lines.append(f"- 正文抓取: {r.article_probe_success}/{r.article_probe_total}")
        lines.append(f"- 结论: **{r.verdict}**")
        if r.article_sample_urls:
            lines.append("- 样例文章链接:")
            for u in r.article_sample_urls:
                lines.append(f"  - {u}")
        if r.notes:
            lines.append("- 备注:")
            for n in r.notes[:10]:
                lines.append(f"  - {n}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    started = time.time()
    results: List[ProbeResult] = []

    for idx, source in enumerate(SOURCES, start=1):
        print(f"[{idx}/{len(SOURCES)}] probing {source.name} ...")
        try:
            r = probe_source(source)
        except Exception as e:
            r = ProbeResult(
                name=source.name,
                group=source.group,
                homepage_error=f"{type(e).__name__}: {e}",
                verdict="failed",
                notes=[traceback.format_exc()],
            )
        results.append(r)

    results.sort(key=lambda x: (x.group, x.verdict, x.name))

    os.makedirs("artifacts", exist_ok=True)

    with open("artifacts/news_probe_results.json", "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)

    md = make_markdown(results)
    with open("artifacts/news_probe_report.md", "w", encoding="utf-8") as f:
        f.write(md)

    summary = {
        "total": len(results),
        "good": sum(r.verdict == "good" for r in results),
        "partial": sum(r.verdict == "partial" for r in results),
        "blocked": sum(r.verdict == "blocked" for r in results),
        "failed": sum(r.verdict == "failed" for r in results),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Artifacts written to artifacts/news_probe_results.json and artifacts/news_probe_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
