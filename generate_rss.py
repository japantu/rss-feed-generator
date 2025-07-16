# -*- coding: utf-8 -*-
import feedparser, html, re, requests
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace

# 名前空間の登録（重複防止）
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
register_namespace("dc", "http://purl.org/dc/elements/1.1/")

RSS_URLS = [
    "http://himasoku.com/index.rdf",
    "https://hamusoku.com/index.rdf",
    "http://blog.livedoor.jp/kinisoku/index.rdf",
    "https://www.lifehacker.jp/feed/index.xml",
    "https://itainews.com/index.rdf",
    "http://blog.livedoor.jp/news23vip/index.rdf",
    "http://yaraon-blog.com/feed",
    "http://blog.livedoor.jp/bluejay01-review/index.rdf",
    "https://www.4gamer.net/rss/index.xml",
    "https://www.gizmodo.jp/atom.xml",
]

def to_utc(st):
    return datetime(*st[:6], tzinfo=timezone.utc)

def extract_og_image(page_url):
    try:
        html_txt = requests.get(page_url, timeout=4).text
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I)
        if m:
            return urljoin(page_url, m.group(1))
    except Exception:
        pass
    return ""

def fetch_and_generate():
    items = []
    for url in RSS_URLS:
        feed = feedparser.parse(url)
        site = feed.feed.get("title", "Unknown Site")

        for e in feed.entries:
            # 投稿日時の取得
            if e.get("published_parsed"):
                dt = to_utc(e.published_parsed)
            elif e.get("updated_parsed"):
                dt = to_utc(e.updated_parsed)
            else:
                dt = datetime.now(timezone.utc)

            # 元HTMLの抽出（<img>付きが優先）
            html_raw = ""
            for fld in ("content:encoded", "content", "summary", "description"):
                v = e.get(fld)
                if isinstance(v, list): v = v[0]
                if isinstance(v, str) and "<img" in v:
                    html_raw = v; break
                elif isinstance(v, str) and not html_raw:
                    html_raw = v

            # サムネイル抽出
            thumb = ""
            if "media_thumbnail" in e:
                thumb = e.media_thumbnail[0]["url"]
            elif "media_content" in e:
                thumb = e.media_content[0]["url"]
            elif "enclosures" in e and e.enclosures:
                thumb = e.enclosures[0]["href"]
            if not thumb and html_raw:
                img = BeautifulSoup(html_raw, "html.parser").find("img")
                if img and img.get("src"): thumb = img["src"]
            if not thumb:
                thumb = extract_og_image(e.get("link", ""))

            # content:encoded の内容を組み立て
            if thumb and ('<img' not in html_raw):
                content_html = f'<img src="{thumb}"><br>{html_raw}'
            else:
                content_html = html_raw or e.get("link", "")

            items.append({
                "title": f"{site}閂{html.unescape(e.get('title',''))}",
                "link": e.get("link", ""),
                "pubDate": dt,
                "description": html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)),
                "content": content_html,
                "site": site
            })

    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items[:200]

def generate_rss(items):
    rss = Element("rss", version="2.0")
    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "source").text = it["site"]
        # dc:date に ISO 8601 形式で出力
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].astimezone().isoformat()
        # content:encoded に HTML 本文
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]

    ElementTree(rss).write("rss_output.xml", encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    generate_rss(fetch_and_generate())
