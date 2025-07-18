# -*- coding: utf-8 -*-
import feedparser, html, re, requests
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace

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
            if e.get("published_parsed"):
                dt = to_utc(e.published_parsed)
            elif e.get("updated_parsed"):
                dt = to_utc(e.updated_parsed)
            else:
                dt = datetime.now(timezone.utc)

            html_raw = ""
            for tag in ("content:encoded", "content", "summary", "description"):
                value = e.get(tag)
                if isinstance(value, list): value = value[0]
                if isinstance(value, str) and "<img" in value:
                    html_raw = value; break
                elif isinstance(value, str) and not html_raw:
                    html_raw = value

            thumb = ""
            if "media_thumbnail" in e:
                thumb = e.media_thumbnail[0]["url"]
            elif "media_content" in e:
                thumb = e.media_content[0]["url"]
            elif "enclosures" in e and e.enclosures:
                thumb = e.enclosures[0]["href"]
            if not thumb and html_raw:
                img = BeautifulSoup(html_raw, "html.parser").find("img")
                if img and img.get("src"):
                    thumb = img["src"]
            if not thumb:
                thumb = extract_og_image(e.get("link", ""))

            if thumb and '<img' not in html_raw:
                content_html = f'<img src="{thumb}"><br>{html_raw}'
            else:
                content_html = html_raw or e.get("link", "")

            items.append({
                "title": f"{site}閂{html.unescape(e.get('title',''))}",
                "link": e.get("link", ""),
                "pubDate": dt,
                "description": html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)),
                "content": content_html,
                "site": site,
                "dc_date": dt.isoformat()
            })

    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items[:100]
