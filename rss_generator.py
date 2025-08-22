# -*- coding: utf-8 -*-
"""
高速版 RSS マージャー（OG画像補完を維持）
- フィードは並列取得（max_workers=12）
- 画像は RSS内のものを優先、無いときだけOG補完
- OG補完は <head> だけ先に取得して最小コスト化。必要ドメインだけ200KBまで本体を読む
- 失敗/成功を含めた結果を rss_cache.json に保存（Actions で永続化推奨）
- 出力: public/rss_output.xml
"""

import os
import re
import json
import time
import html
import hashlib
import logging
from io import StringIO
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -----------------------------
# 設定
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ここに統合したいRSSを列挙（必要に応じて追加/削除してください）
RSS_URLS = [
    # ニュース/テック（例）
    "https://www.4gamer.net/rss/index.xml",
    "https://www.gizmodo.jp/atom.xml",
    "https://www.lifehacker.jp/feed/index.xml",
    "https://daily-gadget.net/feed/",
    # ライブドア系など（例）
    "http://blog.livedoor.jp/news23vip/index.rdf",
    "http://blog.livedoor.jp/bluejay01-review/index.rdf",
    "http://blog.livedoor.jp/kinisoku/index.rdf",
    # まとめ系（例）
    "https://itainews.com/index.rdf",
    # はちま・やらおん等（必要なら）
    "http://yaraon-blog.com/feed",
    # はむ速（HTML整形対応あり）
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
    total=3,
    backoff_factor=0.3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "HEAD"],
)
adapter = HTTPAdapter(max_retries=retries, pool_connections=50, pool_maxsize=50)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

# 外部サイトへの同時アクセス制御（礼儀として10本程度に制限）
OUTBOUND_SEM = Semaphore(10)

# OG補完を積極的に試すドメイン（必要に応じて追加）
OG_POSITIVE_DOMAINS = {
    "www.4gamer.net",
    "www.lifehacker.jp",
    "www.gizmodo.jp",
}

# キャッシュファイル
CACHE_FILE = "rss_cache.json"

# name空間の登録（dc:date / content:encoded を使うため）
register_namespace("dc", "http://purl.org/dc/elements/1.1/")
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

# -----------------------------
# キャッシュ
# -----------------------------
def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Cache load error: {e}")
    return {
        "articles": {},      # URL -> 記事データ（縮約）
        "feed_hashes": {},   # フィードURL -> entriesハッシュ
        "og_images": {},     # 記事URL -> 画像URL（空文字 = 取れなかった）
    }

def save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Cache save error: {e}")

# -----------------------------
# 文字列/HTML処理
# -----------------------------
def clean_content(content: str, site_name: str) -> str:
    """よくある『続きを読む』等のノイズを除去"""
    if not content:
        return ""
    patterns_to_remove = [
        r"続きを読む.*$",
        r"Read more.*$",
        r"もっと見る.*$",
        r"詳しくは.*$",
        r"full article.*$",
        r"\[…\].*$",
        r"\.\.\..*続き.*$",
        r"→.*続き.*$",
        r">>.*続き.*$",
    ]
    cleaned = content
    for pat in patterns_to_remove:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

    if "hamusoku" in site_name.lower():
        cleaned = re.sub(r"続きを読む.*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"→\s*続きを読む.*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"&gt;&gt;続きを読む.*", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()

def extract_html_image(html_raw: str, article_url: str) -> str:
    """content:encoded 等の本文HTMLから <img> を1枚抽出"""
    if not html_raw:
        return ""
    try:
        soup = BeautifulSoup(html_raw, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return urljoin(article_url, img["src"])
    except Exception as e:
        logging.debug(f"HTML image extraction error: {e}")
    return ""

# -----------------------------
# 画像抽出（RSS優先→OG補完）
# -----------------------------
def get_thumb_from_entry(entry) -> str:
    """RSS内（thumbnail / media:content / enclosure）から画像を取る"""
    # media_thumbnail
    if "media_thumbnail" in entry and entry.media_thumbnail:
        t = entry.media_thumbnail[0].get("url") or entry.media_thumbnail[0].get("href")
        if t:
            return t
    # media_content
    if "media_content" in entry and entry.media_content:
        t = entry.media_content[0].get("url")
        if t:
            return t
    # enclosure (type=image/*)
    if "enclosures" in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/") and enc.get("href"):
                return enc["href"]
    return ""

def fetch_head_html(url: str) -> str | None:
    """ページ全文ではなく<head>終端までを最小限取得"""
    with OUTBOUND_SEM:
        try:
            resp = SESSION.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, stream=True)
            resp.raise_for_status()
            chunks = []
            for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
                if not chunk:
                    break
                chunks.append(chunk)
                joined = "".join(chunks)
                if "</head>" in joined.lower():
                    break
            return "".join(chunks)
        except Exception:
            return None

def extract_og_from_html_head(head_html: str) -> str | None:
    """<head> から og:image / twitter:image を抽出"""
    if not head_html:
        return None
    try:
        soup = BeautifulSoup(head_html, "html.parser")
        for attrs in (
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return tag["content"].strip()
    except Exception:
        pass
    return None

def extract_og_image_with_cache(article_url: str, cache: dict) -> str | None:
    """キャッシュ付きOG画像抽出（必要サイトは積極、それ以外は軽く）"""
    # キャッシュ尊重
    og_cache = cache.setdefault("og_images", {})
    if article_url in og_cache:
        return og_cache[article_url] or None

    host = urlparse(article_url).netloc
    aggressive = host in OG_POSITIVE_DOMAINS

    # まずは<head>だけ取得
    head_html = fetch_head_html(article_url)
    og = extract_og_from_html_head(head_html or "")

    # 必要ドメインだけは200KBまで本文を読んで再挑戦
    if not og and aggressive:
        with OUTBOUND_SEM:
            try:
                resp = SESSION.get(article_url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, stream=True)
                resp.raise_for_status()
                size = 0
                chunks = []
                for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 200_000:  # 200KBまで
                        break
                html_text = "".join(chunks)
                soup = BeautifulSoup(html_text, "html.parser")
                # 再度抽出
                tag = soup.find("meta", attrs={"property": "og:image"})
                if tag and tag.get("content"):
                    og = tag["content"].strip()
                if not og:
                    tag = soup.find("meta", attrs={"name": "twitter:image"})
                    if tag and tag.get("content"):
                        og = tag["content"].strip()
            except Exception:
                og = None

    # キャッシュ保存（None も空文字で保存して次回スキップ）
    og_cache[article_url] = og or ""
    return og

# -----------------------------
# RSS処理
# -----------------------------
def get_feed_hash(entries) -> str:
    """エントリ群の軽量ハッシュ（URL+更新日時ベース）"""
    h = hashlib.sha256()
    for e in entries:
        link = e.get("link") or ""
        updated = (
            e.get("updated") or
            e.get("published") or
            e.get("updated_parsed") or
            e.get("published_parsed") or ""
        )
        h.update((link + str(updated)).encode("utf-8", errors="ignore"))
    return h.hexdigest()

def parse_date(entry) -> datetime:
    """entry から日時をなるべく拾って datetime（ローカルTZ） に"""
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            try:
                dt = datetime(*entry[key][:6])
                return dt
            except Exception:
                pass
    for key in ("published", "updated"):
        if entry.get(key):
            try:
                return datetime.fromisoformat(entry[key].replace("Z", "+00:00"))
            except Exception:
                pass
    return datetime.now()

def entry_to_item(entry, site: str, cache: dict) -> dict | None:
    """feedparser の entry を内部アイテムdictへ"""
    title = html.unescape(entry.get("title", "")).strip() or "(no title)"
    link = entry.get("link")
    if not link:
        return None

    # 説明と本文
    desc = entry.get("summary", "") or entry.get("description", "") or ""
    content_html = ""
    if "content" in entry and entry.content:
        # content:encoded 相当
        content_html = entry.content[0].get("value") or ""
    plain_description = clean_content(html.unescape(desc), site)
    content_html = clean_content(content_html, site)

    # 画像：RSS内 → 本文内 → OG補完
    thumb = get_thumb_from_entry(entry)
    if not thumb:
        html_img = extract_html_image(content_html, link)
        if html_img:
            thumb = html_img
    if not thumb:
        og = extract_og_image_with_cache(link, cache)
        if og:
            thumb = og

    # 本文に画像無い時、サムネを先頭に差す（KLWP向け）
    final_content_html = content_html
    if thumb and "<img" not in content_html:
        safe = html.escape(thumb, quote=True)
        final_content_html = f'<p><img src="{safe}" /></p>' + (content_html or "")

    dt = parse_date(entry)

    return {
        "title": title,
        "link": link,
        "pubDate": dt,
        "description": plain_description,
        "content": final_content_html or plain_description,
        "site": site,
        "has_image": bool(thumb),
        "processed_at": datetime.now().isoformat(),
    }

def fetch_single_rss(url: str, cache: dict) -> list[dict]:
    """単一RSSを取得→必要に応じてOG補完"""
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        if feed.bozo and feed.bozo_exception:
            logging.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")

        site = feed.feed.get("title", "Unknown Site")
        current_hash = get_feed_hash(feed.entries)
        prev_hash = cache.get("feed_hashes", {}).get(url)

        items = []
        if current_hash == prev_hash:
            # 変更なし：キャッシュ記事を復元
            art = cache.get("articles", {})
            for link, a in art.items():
                if a.get("site") == site:
                    items.append({
                        "title": a["title"],
                        "link": link,
                        "pubDate": datetime.fromisoformat(a["pubDate"]),
                        "description": a["description"],
                        "content": a["content"],
                        "site": a["site"],
                        "has_image": a["has_image"],
                        "processed_at": a["processed_at"],
                    })
            logging.info(f"[cache] {site}: {len(items)} items")
            return items

        # 新規パース
        for e in feed.entries:
            item = entry_to_item(e, site, cache)
            if item:
                items.append(item)

        # 新キャッシュ保存
        cache["feed_hashes"][url] = current_hash
        for it in items:
            # 記事URLを key に縮約保存
            cache["articles"][it["link"]] = {
                "title": it["title"],
                "pubDate": it["pubDate"].isoformat(),
                "description": it["description"],
                "content": it["content"],
                "site": it["site"],
                "has_image": it["has_image"],
                "processed_at": it["processed_at"],
            }

        logging.info(f"[fresh] {site}: {len(items)} items")
        return items

    except Exception as e:
        logging.error(f"Error processing RSS feed {url}: {e}", exc_info=True)
        return []

def fetch_and_generate_items() -> list[dict]:
    """全フィードを並列取得して結合・ソート"""
    cache = load_cache()
    all_items: list[dict] = []

    # 並列でRSS取得
    with ThreadPoolExecutor(max_workers=12) as ex:
        futmap = {ex.submit(fetch_single_rss, u, cache): u for u in RSS_URLS}
        for fut in as_completed(futmap):
            try:
                all_items.extend(fut.result())
            except Exception as e:
                logging.error(f"Worker error: {e}")

    # 古いキャッシュ（30日より前の記事）は掃除
    cutoff = datetime.now() - timedelta(days=30)
    to_del = []
    for link, a in list(cache.get("articles", {}).items()):
        try:
            ts = datetime.fromisoformat(a.get("pubDate"))
            if ts < cutoff:
                to_del.append(link)
        except Exception:
            to_del.append(link)
    for link in to_del:
        cache["articles"].pop(link, None)

    # キャッシュ保存
    save_cache(cache)

    # 新しい順にソートして200件まで
    all_items.sort(key=lambda x: x["pubDate"], reverse=True)
    return all_items[:200]

# -----------------------------
# RSS出力
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
        SubElement(i, "title").text = it["title"]
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

    logging.info(f"RSS feed successfully generated: {outpath}")
