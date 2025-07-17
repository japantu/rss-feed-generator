import feedparser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import html
import xml.etree.ElementTree as ET

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
    "https://www.gizmodo.jp/atom.xml"
]

def fetch_and_generate():
    items = []

    for url in RSS_URLS:
        feed = feedparser.parse(url)
        site_title = feed.feed.get("title", "Unknown Site")

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            pub_date = entry.get("published", "") or entry.get("updated", "")
            try:
                pub_date_obj = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pub_date_obj = datetime.now(timezone.utc)

            description = entry.get("description", "") or entry.get("summary", "")
            content = ""
            if "content" in entry and entry.content:
                content = entry.content[0].value
            elif "content:encoded" in entry:
                content = entry["content:encoded"]
            else:
                content = description

            # サムネイル画像を description に埋め込む
            thumbnail = ""
            for tag in ("content", "summary", "description"):
                if tag in entry:
                    soup = BeautifulSoup(entry[tag], "html.parser")
                    img_tag = soup.find("img")
                    if img_tag and img_tag.get("src"):
                        thumbnail = img_tag["src"]
                        break

            if thumbnail:
                description = f'<img src="{thumbnail}" /><br>{description}'

            items.append({
                "title": html.unescape(title),
                "link": link,
                "pubDate": pub_date_obj,
                "description": html.unescape(description),
                "content": html.unescape(content),
                "site": site_title
            })

    sorted_items = sorted(items, key=lambda x: x["pubDate"], reverse=True)
    return sorted_items[:200]

def generate_rss(items):
    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://rss-x2xp.onrender.com/"
    ET.SubElement(channel, "description").text = "Combined feed of multiple sources"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = f"{item['site']} 閂 {item['title']}"
        ET.SubElement(entry, "link").text = item["link"]
        ET.SubElement(entry, "description").text = f"<![CDATA[{item['description']}]]>"
        ET.SubElement(entry, "pubDate").text = item["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        content_encoded = ET.SubElement(entry, "content:encoded")
        content_encoded.text = f"<![CDATA[{item['content']}]]>"

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)
