import feedparser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import html
from xml.etree.ElementTree import Element, SubElement, ElementTree

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

def to_utc(struct_time_obj):
    """time.struct_time → aware datetime(UTC)"""
    return datetime(*struct_time_obj[:6], tzinfo=timezone.utc)

def fetch_and_generate():
    items = []

    for url in RSS_URLS:
        feed = feedparser.parse(url)
        site_title = feed.feed.get("title", "Unknown Site")

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")

            # ---- pubDate ----
            if entry.get("published_parsed"):
                pub_dt = to_utc(entry.published_parsed)
            elif entry.get("updated_parsed"):
                pub_dt = to_utc(entry.updated_parsed)
            else:
                pub_dt = datetime.now(timezone.utc)  # フォールバック

            # ---- description / content ----
            description = entry.get("description", "") or entry.get("summary", "")
            content = ""
            if isinstance(entry.get("content"), list) and entry.content:
                content = entry.content[0].value
            elif entry.get("content:encoded"):
                content = entry["content:encoded"]

            # ---- thumbnail ----
            thumbnail = ""
            for field in ("content", "summary", "description"):
                raw = entry.get(field)
                if isinstance(raw, list):
                    raw = raw[0]
                if isinstance(raw, str):
                    img = BeautifulSoup(raw, "html.parser").find("img")
                    if img and img.get("src"):
                        thumbnail = img["src"]
                        break

            items.append(
                {
                    "title": html.unescape(title),
                    "link": link,
                    "pubDate": pub_dt,
                    "description": html.unescape(description),
                    "content": html.unescape(content),
                    "thumbnail": thumbnail,
                    "site": site_title,
                }
            )

    # ---- 最新200件に統一 ----
    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items[:200]

def generate_rss(items):
    rss = Element("rss", version="2.0", attrib={"xmlns:media": "http://search.yahoo.com/mrss/"})
    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        itm = SubElement(ch, "item")
        SubElement(itm, "title").text = it["title"]
        SubElement(itm, "link").text = it["link"]
        SubElement(itm, "description").text = it["description"]
        SubElement(itm, "pubDate").text = it["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        SubElement(itm, "source").text = it["site"]
        if it["thumbnail"]:
            SubElement(itm, "media:thumbnail", {"url": it["thumbnail"]})

    ElementTree(rss).write("rss_output.xml", encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    generate_rss(fetch_and_generate())
