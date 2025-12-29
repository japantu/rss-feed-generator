# -*- coding: utf-8 -*-
"""
高速版 RSS マージャー（OG画像補完維持／タイトルは「サイト名」閂「記事タイトル」）
- フィードは並列取得（max_workers=12）
- 画像は RSS内のものを優先、無いときだけOG補完
- OG補完は <head> だけ先に取得して最小コスト化。必要ドメインだけ200KBまで本体を読む
- 失敗/成功を含めた結果を rss_cache.json に保存（Actions で永続化推奨）
- 出力: public/rss_output.xml
- 追加出力: public/feed.json, public/images.json（Tasker向け）
"""

import os
import re
import json
import html
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from io import StringIO
from urllib.parse import urlparse

import requests
import feedparser
from bs4 import BeautifulSoup

from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -----------------------------
# 設定
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 統合したいRSS
RSS_URLS = [
    "https://www.4gamer.net/rss/index.xml",
    "https://www.gizmodo.jp/atom.xml",
    "https://www.lifehacker.jp/feed/index.xml",
    "https://daily-gadget.net/feed/",
    "http://blog.livedoor.jp/news23vip/index.rdf",
    "http://blog.livedoor.jp/bluejay01-review/index.rdf",
    "http://blog.livedoor.jp/kinisoku/index.rdf",
    "https://itainews.com/index.rdf",
    "http://yaraon-blog.com/feed",
    "https://rabitsokuhou.2chblog.jp/index.rdf",
    "https://hamusoku.com/index.rdf",
]

# HTTPリクエスト設定
DEFAULT_TIMEOUT = (2, 3)  # (connect, read) 秒
HEADERS = {
    "User-Agent": "Mozilla/5.0 (+KLWP/rss)",
    "Accept-Language": "ja,en;q=0.8",
}

# requests.Session（接続再利用＋軽リトライ）
SESSION = requests.Session()
retries = Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
)
adapter = HTTPAdapter(max_retries=retries, pool_connections=50, pool_maxsize=50)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

# OG補完を積極的に試すドメイン（必要に応じて追加）
OG_POSITIVE_DOMAINS = {
    "www.4gamer.net",
    "www.lifehacker.jp",
    "www.gizmodo.jp",
}

# キャッシュファイル
CACHE_FILE = "rss_cache.json"

# name空間登録
register_namespace("dc", "http://purl.org/dc/elements/1.1/")
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")


# -----------------------------
# 便利関数
# -----------------------------
def safe_text(s: str) -> str:
    if s is None:
        return ""
    # HTMLエンティティを復元
    s = html.unescape(str(s))
    # 変な制御文字を除去
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)
    return s.strip()


def norm_url(u: str) -> str:
    if not u:
        return ""
    return u.strip()


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save cache: {e}")


def http_get(url: str, timeout=DEFAULT_TIMEOUT, headers=None, stream=False):
    h = HEADERS.copy()
    if headers:
        h.update(headers)
    return SESSION.get(url, headers=h, timeout=timeout, stream=stream)


def http_head(url: str, timeout=DEFAULT_TIMEOUT, headers=None):
    h = HEADERS.copy()
    if headers:
        h.update(headers)
    return SESSION.head(url, headers=h, timeout=timeout, allow_redirects=True)


def parse_date(entry) -> datetime:
    # feedparserが提供するpublished_parsed/updated_parsedを優先
    # 無い場合は現在時刻
    dt = None
    for key in ("published_parsed", "updated_parsed"):
        if key in entry and entry.get(key):
            try:
                dt = datetime.fromtimestamp(
                    datetime(*entry[key][:6], tzinfo=timezone.utc).timestamp(), tz=timezone.utc
                )
                break
            except Exception:
                pass
    if not dt:
        dt = datetime.now(timezone.utc)
    return dt


def extract_image_from_entry(entry) -> str:
    # RSSのenclosure / media:content / media_thumbnail / links等から画像URLを拾う
    try:
        # media_content
        if "media_content" in entry and entry.media_content:
            for mc in entry.media_content:
                u = mc.get("url") or ""
                if u and re.search(r"\.(jpg|jpeg|png|webp|gif)(\?.*)?$", u, re.I):
                    return u

        # media_thumbnail
        if "media_thumbnail" in entry and entry.media_thumbnail:
            for mt in entry.media_thumbnail:
                u = mt.get("url") or ""
                if u and re.search(r"\.(jpg|jpeg|png|webp|gif)(\?.*)?$", u, re.I):
                    return u

        # links（rel=enclosure等）
        if "links" in entry and entry.links:
            for lk in entry.links:
                href = lk.get("href") or ""
                rel = (lk.get("rel") or "").lower()
                typ = (lk.get("type") or "").lower()
                if rel in ("enclosure", "related") or "image" in typ:
                    if href and re.search(r"\.(jpg|jpeg|png|webp|gif)(\?.*)?$", href, re.I):
                        return href

        # summary/description内のimgタグ
        summary = entry.get("summary") or entry.get("description") or ""
        if summary:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.I)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def fetch_head_og_image(url: str) -> str:
    """
    なるべく軽くOG画像を取る。
    1) HEADでContent-Typeをチェック
    2) GETで先頭だけ読み、head内のog:imageを探す
    """
    if not url:
        return ""

    try:
        # まずHEAD
        r = http_head(url, timeout=DEFAULT_TIMEOUT)
        ctype = (r.headers.get("Content-Type") or "").lower()
        # HTMLでない可能性が高いものはやめる
        if "text/html" not in ctype and "application/xhtml" not in ctype and ctype != "":
            return ""

    except Exception:
        # HEAD失敗時はGETへ
        pass

    # GETで軽く読む（まずはhead周辺だけ）
    try:
        r = http_get(url, timeout=DEFAULT_TIMEOUT, stream=True)
        r.raise_for_status()

        # ドメインによってはheadだけ取れないので最大サイズを設定
        netloc = domain_of(url)
        max_bytes = 200_000 if netloc in OG_POSITIVE_DOMAINS else 80_000

        data = b""
        for chunk in r.iter_content(chunk_size=8192):
            if not chunk:
                break
            data += chunk
            if len(data) >= max_bytes:
                break

        # head終端で切る
        text = data.decode("utf-8", errors="ignore")
        head_end = text.lower().find("</head>")
        if head_end != -1:
            text = text[: head_end + 7]

        soup = BeautifulSoup(text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og.get("content").strip()

    except Exception:
        return ""

    return ""


def clean_html_to_text(s: str) -> str:
    """
    description/contentがHTMLの場合に軽く整形（完全に消しすぎない）
    """
    if not s:
        return ""
    s = safe_text(s)
    # すでにプレーンっぽいならそのまま
    if "<" not in s and ">" not in s:
        return s
    try:
        soup = BeautifulSoup(s, "html.parser")
        # 画像タグ等は削除
        for t in soup(["img", "script", "style", "noscript"]):
            t.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        # 失敗したら雑にタグ除去
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s


# -----------------------------
# RSS取得＆統合
# -----------------------------
def fetch_feed(url: str) -> dict:
    """
    1つのRSSを取得してfeedparserで解析した結果を返す。
    """
    try:
        r = http_get(url, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:
        logging.warning(f"Fetch failed: {url} ({e})")
        return {"entries": [], "feed": {}}


def build_items_from_feed(feed, source_url: str) -> list[dict]:
    items = []
    entries = feed.get("entries") or []

    # サイト名（feedタイトル or ドメイン）
    site = safe_text((feed.get("feed") or {}).get("title") or "") or domain_of(source_url)

    for e in entries:
        title = safe_text(e.get("title") or "")
        link = norm_url(e.get("link") or "")
        pub = parse_date(e)

        # 本文（description/summary）
        desc = e.get("summary") or e.get("description") or ""
        desc = clean_html_to_text(desc)

        # content:encodedがあれば優先して保持（RSS出力にも使う）
        content = ""
        try:
            if "content" in e and e.content:
                # feedparserのcontentはlistの場合がある
                if isinstance(e.content, list) and len(e.content) > 0:
                    content = e.content[0].get("value") or ""
                elif isinstance(e.content, dict):
                    content = e.content.get("value") or ""
                else:
                    content = str(e.content)
        except Exception:
            content = ""

        content = clean_html_to_text(content)

        # 画像
        img = extract_image_from_entry(e)
        if not img:
            # OG補完
            img = fetch_head_og_image(link)

        item = {
            "site": site,
            "title": title,
            "link": link,
            "pubDate": pub,
            "description": desc,
            "content": content,
            "image": img,
            "source_url": source_url,
        }

        items.append(item)

    return items


def merge_items(all_items: list[dict]) -> list[dict]:
    """
    重複排除して新しい順に。
    """
    seen = set()
    merged = []
    for it in all_items:
        key = sha1((it.get("link") or "") + "|" + (it.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(it)

    merged.sort(key=lambda x: x["pubDate"], reverse=True)
    return merged[:200]


def fetch_and_generate_items() -> list[dict]:
    cache = load_cache()
    results = []

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(fetch_feed, u): u for u in RSS_URLS}
        for fut in as_completed(futures):
            u = futures[fut]
            feed = fut.result()
            items = build_items_from_feed(feed, u)
            results.extend(items)

            # キャッシュへ結果（成功/失敗含め）保存
            cache[u] = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "count": len(items),
            }

    save_cache(cache)
    return merge_items(results)


# -----------------------------
# RSS出力（XML文字列）
# -----------------------------
def generate_rss_xml_string(items: list[dict], base_url: str = "") -> str:
    rss = Element("rss", attrib={"version": "2.0"})
    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"
    SubElement(ch, "link").text = base_url
    SubElement(ch, "description").text = "複数RSSを統合（OG補完・キャッシュ・並列最適化対応）"
    SubElement(ch, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    for it in items:
        i = SubElement(ch, "item")
        # ★ここを復元：タイトルは「サイト名」閂「記事タイトル」
        composed_title = f'{it["site"]}閂{it["title"]}'
        SubElement(i, "title").text = composed_title
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"] or ""
        SubElement(i, "source").text = it["site"]
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].astimezone().isoformat()
        SubElement(i, "pubDate").text = it["pubDate"].astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"] or it["description"]

    s = StringIO()
    ElementTree(rss).write(s, encoding="unicode", xml_declaration=True)
    return s.getvalue()


# -----------------------------
# Tasker向け JSON 出力（feed.json / images.json）
# -----------------------------
def write_tasker_json(items, outdir="public", max_items=130):
    """
    Taskerで扱いやすいように、本文用(feed.json)と画像URL用(images.json)を分けて出力します。
    - feed.json: title/body/date/link/site を保持（imageは含めない）
    - images.json: image URLのみ（idで対応）
    """
    os.makedirs(outdir, exist_ok=True)

    sliced = items[:max_items]
    now_iso = datetime.now().astimezone().isoformat()

    feed_items = []
    image_items = []

    for idx, it in enumerate(sliced, start=1):
        body = it.get("content") or it.get("description") or ""
        feed_items.append({
            "id": idx,
            "title": it.get("title", ""),
            "site": it.get("site", ""),
            "date": (it["pubDate"].astimezone().isoformat() if it.get("pubDate") else ""),
            "link": it.get("link", ""),
            "body": body,
        })

        img = it.get("image")
        image_items.append({
            "id": idx,
            "image": (img if img else None),
        })

    feed_json = {"updated": now_iso, "count": len(feed_items), "items": feed_items}
    images_json = {"updated": now_iso, "count": len(image_items), "items": image_items}

    feed_path = os.path.join(outdir, "feed.json")
    images_path = os.path.join(outdir, "images.json")

    with open(feed_path, "w", encoding="utf-8") as f:
        json.dump(feed_json, f, ensure_ascii=False, indent=2)

    with open(images_path, "w", encoding="utf-8") as f:
        json.dump(images_json, f, ensure_ascii=False, indent=2)

    logging.info(f"Tasker JSON successfully generated: {feed_path}, {images_path}")


# -----------------------------
# main
# -----------------------------
if __name__ == "__main__":
    base_url = "https://<YOUR_PAGES_USERNAME>.github.io/<YOUR_REPO>/"  # 任意
    items = fetch_and_generate_items()
    xml_string = generate_rss_xml_string(items, base_url=base_url)

    outdir = "public"
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, "rss_output.xml")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(xml_string)

    # Tasker向け JSON（本文/画像URL）も同時生成
    write_tasker_json(items, outdir=outdir, max_items=130)

    logging.info(f"RSS feed successfully generated: {outpath}")

