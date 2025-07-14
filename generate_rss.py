import feedparser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import html
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace

# 名前空間を1回だけ登録
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

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

def fetch_and_generate():
    items = []
    for url in RSS_URLS:
        feed = feedparser.parse(url)
        site = feed.feed.get("title", "Unknown Site")

        for e in feed.entries:
            # --- pubDate ---
            if e.get("published_parsed"):
                dt = to_utc(e.published_parsed)
            elif e.get("updated_parsed"):
                dt = to_utc(e.updated_parsed)
            else:
                dt = datetime.now(timezone.utc)

            # --- description テキスト ---
            desc_text = html.unescape(e.get("description", "") or e.get("summary", ""))

            # --- content_html （できるだけ元HTMLをそのまま） ---
            content_html = ""
            if "content:encoded" in e:
                raw = e["content:encoded"]
                if isinstance(raw, list):
                    raw = raw[0]
                content_html = raw
            elif "content" in e and isinstance(e.content, list):
                content_html = e.content[0].value

            # --- サムネイル抽出（content_htmlが無いときの保険） ---
            thumb = ""
            for fld in ("content", "summary", "description"):
                v = e.get(fld)
                if isinstance(v, list):
                    v = v[0]
                if isinstance(v, str):
                    img = BeautifulSoup(v, "html.parser").find("img")
                    if img and img.get("src"):
                        thumb = img["src"]; break

            if not content_html and thumb:
                content_html = f'<img src="{thumb}"><br>{desc_text}'
            elif not content_html:
                content_html = desc_text  # 最低限

            items.append({
                "title": html.unescape(e.get("title", "")),
                "link": e.get("link", ""),
                "pubDate": dt,
                "description": desc_text,
                "content": content_html,
                "site": site,
            })

    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items[:200]

def generate_rss(items):
    rss = Element("rss", version="2.0")
    ch  = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text  = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "pubDate").text = it["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        SubElement(i, "source").text = it["site"]

        # content:encoded に元HTML（img入り）をそのまま入れる
        ctag = SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded")
        ctag.text = it["content"]

    ElementTree(rss).write("rss_output.xml", encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    generate_rss(fetch_and_generate())
