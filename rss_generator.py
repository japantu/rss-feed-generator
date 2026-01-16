# -*- coding: utf-8 -*-
"""
統合RSSジェネレータ（画像付きRSS + Tasker向け JSON 出力）
- 複数RSSを並列取得してマージ
- 画像は RSS内の enclosure/media/img を優先、無い場合のみOG補完
- livedoor(index.rdf)系の content:encoded 内 <img> も拾う
- data:image/...;base64 は「画像URLではない」ので除外（rabitsokuhou対策）
- 出力:
  - public/rss_output.xml   (画像付き: <enclosure> 付与)
  - public/feed.json        (Tasker向け: 本文 + 画像URL を1つに統合)
"""

import os
import re
import json
import html
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import StringIO
from urllib.parse import urlparse, urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace


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
DEFAULT_TIMEOUT = (2, 6)  # (connect, read)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (RSS Merger; +KLWP/Tasker)",
    "Accept-Language": "ja,en;q=0.8",
}

# OG補完を積極的に試すドメイン（必要なら追加）
OG_POSITIVE_DOMAINS = {
    "www.4gamer.net",
    "www.lifehacker.jp",
    "www.gizmodo.jp",
}

# 出力先
OUTDIR = "public"
OUT_RSS = os.path.join(OUTDIR, "rss_output.xml")
# JSONは1本だけ（統合版）。ファイル名は既存互換のため feed.json のまま
OUT_JSON = os.path.join(OUTDIR, "feed.json")

# 件数（Tasker向け）
TASKER_MAX_ITEMS = 200
# RSS側は多めでもOK（必要なら調整）
RSS_MAX_ITEMS = 200

# name空間登録
register_namespace("dc", "http://purl.org/dc/elements/1.1/")
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

_IMG_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif)(\?.*)?$", re.I)


# -----------------------------
# requests.Session（接続再利用＋軽リトライ）
# -----------------------------
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


# -----------------------------
# 便利関数
# -----------------------------
def safe_text(s: str) -> str:
    if s is None:
        return ""
    s = html.unescape(str(s))
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)
    return s.strip()

def norm_url(u: str) -> str:
    return (u or "").strip()

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

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
    # feedparser が持つ published_parsed / updated_parsed を優先
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            try:
                return datetime(*v[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)

def clean_html_to_text(s: str) -> str:
    """
    description/content がHTMLの場合に軽くテキスト化
    """
    if not s:
        return ""
    s = safe_text(s)
    if "<" not in s and ">" not in s:
        return s
    try:
        soup = BeautifulSoup(s, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

def is_data_image_uri(u: str) -> bool:
    # rabitsokuhou 等の data:image/png;base64,... を除外
    u = (u or "").strip().lower()
    return u.startswith("data:image/")

def _normalize_img_url(u: str, base: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if not u:
        return ""

    # ★ data URI は除外（画像URLではない）
    if is_data_image_uri(u):
        return ""

    # //example.com/... → https://example.com/...
    if u.startswith("//"):
        u = "https:" + u

    # 相対URL → 絶対URL
    if base and (u.startswith("/") or (not u.startswith("http://") and not u.startswith("https://"))):
        try:
            u = urljoin(base, u)
        except Exception:
            pass

    return u

def _first_img_from_html(html_text: str, base: str) -> str:
    if not html_text:
        return ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_text, re.I)
    if not m:
        return ""
    src = (m.group(1) or "").strip()
    if is_data_image_uri(src):
        return ""
    return _normalize_img_url(src, base)

def extract_image_from_entry(entry) -> str:
    """
    RSSの enclosure / media:content / media_thumbnail / links / summary / content:encoded から画像URLを拾う。
    livedoor(index.rdf)系: content:encoded 内の<img>を拾う必要あり。
    rabitsokuhou等: data:image;base64 は除外。
    """
    base = norm_url(entry.get("link") or "")

    # 0) enclosures（feedparserが持ってくることがある）
    try:
        if getattr(entry, "enclosures", None):
            for enc in entry.enclosures:
                href = norm_url(enc.get("href") or "")
                typ = (enc.get("type") or "").lower().strip()
                if not href:
                    continue
                href = _normalize_img_url(href, base)
                if not href:
                    continue
                if typ.startswith("image/") or _IMG_EXT_RE.search(href):
                    return href
    except Exception:
        pass

    # 1) media_content（typeがimageなら拡張子無しでも採用）
    try:
        mc_list = getattr(entry, "media_content", None) or entry.get("media_content")
        if mc_list:
            for mc in mc_list:
                u = norm_url(mc.get("url") or "")
                typ = (mc.get("type") or "").lower().strip()
                u = _normalize_img_url(u, base)
                if not u:
                    continue
                if typ.startswith("image/") or _IMG_EXT_RE.search(u) or not typ:
                    return u
    except Exception:
        pass

    # 2) media_thumbnail
    try:
        mt_list = getattr(entry, "media_thumbnail", None) or entry.get("media_thumbnail")
        if mt_list:
            for mt in mt_list:
                u = norm_url(mt.get("url") or "")
                u = _normalize_img_url(u, base)
                if u:
                    return u
    except Exception:
        pass

    # 3) links（rel=enclosure / type=image/*）
    try:
        links = getattr(entry, "links", None) or entry.get("links")
        if links:
            for lk in links:
                href = norm_url(lk.get("href") or "")
                rel = (lk.get("rel") or "").lower().strip()
                typ = (lk.get("type") or "").lower().strip()

                href = _normalize_img_url(href, base)
                if not href:
                    continue

                if rel == "enclosure" or "image" in typ:
                    return href

                # livedoor等で related になっているケースも拾う
                if rel == "related" and ("image" in typ or _IMG_EXT_RE.search(href)):
                    return href
    except Exception:
        pass

    # 4) summary/description 内の <img>
    summary = entry.get("summary") or entry.get("description") or ""
    img = _first_img_from_html(summary, base)
    if img:
        return img

    # 5) content:encoded（entry.content）内の <img>
    try:
        c = entry.get("content")
        htmlv = ""
        if isinstance(c, list) and c:
            htmlv = c[0].get("value") or ""
        elif isinstance(c, dict):
            htmlv = c.get("value") or ""
        elif c:
            htmlv = str(c)
        img = _first_img_from_html(htmlv, base)
        if img:
            return img
    except Exception:
        pass

    return ""


def fetch_head_og_image(url: str) -> str:
    """
    軽量に OG画像を取得
    1) HEADでContent-TypeがHTMLでなさそうなら打ち切り（ただし返さないサーバもあるので例外は無視）
    2) GETで先頭だけ読み、head内の og:image を拾う
    """
    if not url:
        return ""

    # HEADでHTMLっぽくないなら基本打ち切り（ただしHEADが信用できない場合があるので例外は無視）
    try:
        r = http_head(url)
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and ("text/html" not in ctype and "application/xhtml" not in ctype):
            return ""
    except Exception:
        pass

    try:
        r = http_get(url, stream=True)
        r.raise_for_status()

        netloc = domain_of(url)
        max_bytes = 200_000 if netloc in OG_POSITIVE_DOMAINS else 80_000

        data = b""
        for chunk in r.iter_content(chunk_size=8192):
            if not chunk:
                break
            data += chunk
            if len(data) >= max_bytes:
                break

        text = data.decode("utf-8", errors="ignore")
        head_end = text.lower().find("</head>")
        if head_end != -1:
            text = text[: head_end + 7]

        soup = BeautifulSoup(text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            u = og.get("content").strip()
            u = _normalize_img_url(u, url)
            if u and not is_data_image_uri(u):
                return u

    except Exception:
        return ""

    return ""


# -----------------------------
# RSS取得＆統合
# -----------------------------
def fetch_feed(url: str) -> dict:
    try:
        r = http_get(url)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:
        logging.warning(f"Fetch failed: {url} ({e})")
        return {"entries": [], "feed": {}}

def build_items_from_feed(feed, source_url: str) -> list[dict]:
    items = []
    entries = feed.get("entries") or []

    feed_title = safe_text((feed.get("feed") or {}).get("title") or "")
    site = feed_title or domain_of(source_url)

    for e in entries:
        title = safe_text(e.get("title") or "")
        link = norm_url(e.get("link") or "")
        pub = parse_date(e)

        desc_html = e.get("summary") or e.get("description") or ""
        desc_txt = clean_html_to_text(desc_html)

        # content（content:encoded相当）
        content_html = ""
        try:
            c = e.get("content")
            if isinstance(c, list) and c:
                content_html = c[0].get("value") or ""
            elif isinstance(c, dict):
                content_html = c.get("value") or ""
            elif c:
                content_html = str(c)
        except Exception:
            content_html = ""

        content_txt = clean_html_to_text(content_html)
        # テキストが空ならdescriptionをfallback
        body_txt = content_txt or desc_txt

        # 画像抽出（RSS内優先 → 無ければOG）
        img = extract_image_from_entry(e)
        if not img:
            img = fetch_head_og_image(link)

        item = {
            "site": site,
            "title": title,
            "link": link,
            "pubDate": pub,               # datetime(UTC)
            "description": desc_txt,
            "content": body_txt,
            "image": img,                 # URL or ""
            "source_url": source_url,
        }
        items.append(item)

    return items

def merge_items(all_items: list[dict]) -> list[dict]:
    """
    重複排除して新しい順に並べる
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
    return merged[:RSS_MAX_ITEMS]

def fetch_and_generate_items() -> list[dict]:
    results = []

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(fetch_feed, u): u for u in RSS_URLS}
        for fut in as_completed(futures):
            u = futures[fut]
            feed = fut.result()
            items = build_items_from_feed(feed, u)
            results.extend(items)

    return merge_items(results)


# -----------------------------
# RSS出力（XML）
# -----------------------------
def generate_rss_xml_string(items: list[dict], channel_title: str, channel_link: str, channel_desc: str) -> str:
    rss = Element("rss", attrib={"version": "2.0"})
    ch = SubElement(rss, "channel")

    SubElement(ch, "title").text = channel_title
    SubElement(ch, "link").text = channel_link
    SubElement(ch, "description").text = channel_desc
    SubElement(ch, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    for it in items:
        i = SubElement(ch, "item")

        # タイトル: 「サイト名」閂「記事タイトル」
        composed_title = f'{it["site"]}閂{it["title"]}'
        SubElement(i, "title").text = composed_title

        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it.get("description") or ""
        SubElement(i, "source").text = it["site"]

        # dc:date（ISO8601, ローカルTZにしたいならここで変換してください）
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].astimezone(timezone.utc).isoformat()

        # pubDate（RFC2822）
        SubElement(i, "pubDate").text = it["pubDate"].astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

        # content:encoded（テキストをそのまま。CDATAにしたいなら別途対応）
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it.get("content") or it.get("description") or ""

        # ★画像をRSS側にも復活（画像付きRSSとして拾われやすい）
        img = norm_url(it.get("image") or "")
        if img and not is_data_image_uri(img):
            enc = SubElement(i, "enclosure")
            enc.set("url", img)
            # typeは厳密でなくてOK（最低限image/*で）
            enc.set("type", "image/jpeg")

    s = StringIO()
    ElementTree(rss).write(s, encoding="unicode", xml_declaration=True)
    return s.getvalue()


# -----------------------------
# Tasker向け JSON 出力（feed.json 1本に統合）
# -----------------------------
def write_tasker_json(items: list[dict], max_items: int = TASKER_MAX_ITEMS):
    os.makedirs(OUTDIR, exist_ok=True)

    sliced = items[:max_items]
    now_iso = datetime.now(timezone.utc).isoformat()

    merged_items = []
    for idx, it in enumerate(sliced, start=1):
        img = norm_url(it.get("image") or "")
        if img and is_data_image_uri(img):
            img = ""

        merged_items.append({
            "id": idx,
            "title": it.get("title", ""),
            "site": it.get("site", ""),
            "date": (it["pubDate"].astimezone(timezone.utc).isoformat() if it.get("pubDate") else ""),
            "link": it.get("link", ""),
            "body": it.get("content", "") or it.get("description", "") or "",
            "image": (img if img else None),
        })

    out_json = {"updated": now_iso, "count": len(merged_items), "items": merged_items}

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    logging.info(f"Tasker JSON generated: {OUT_JSON}")


# -----------------------------
# main
# -----------------------------
if __name__ == "__main__":
    # GitHub Pages のチャンネル情報（表示用。動作には必須ではありません）
    channel_title = "Merged RSS Feed"
    channel_link = "https://japantu.github.io/rss-feed-generator/"
    channel_desc = "複数RSSを統合（画像付きRSS + Tasker向けJSON）"

    items = fetch_and_generate_items()

    # RSS出力（画像付き）
    os.makedirs(OUTDIR, exist_ok=True)
    rss_xml = generate_rss_xml_string(items, channel_title, channel_link, channel_desc)
    with open(OUT_RSS, "w", encoding="utf-8") as f:
        f.write(rss_xml)
    logging.info(f"RSS generated: {OUT_RSS}")

    # Tasker向けJSON出力（1本）
    write_tasker_json(items, max_items=TASKER_MAX_ITEMS)

