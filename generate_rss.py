import feedparser
import html
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from operator import itemgetter
import xml.etree.ElementTree as ET

RSS_FEEDS = [
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

def fetch_og_image(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, timeout=5, headers=headers)
        soup = BeautifulSoup(res.content, "html.parser")
        og = soup.find("meta", property="og:image")
        return og["content"] if og and og.get("content") else ""
    except:
        return ""

def extract_image(html_content):
    match = re.search(r'<img[^>]+src="([^"]+)"', html_content)
    return match.group(1) if match else ""

def fetch_and_generate():
    items = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url, request_headers={"Cache-Control": "no-cache"})
        site_title = feed.feed.get("title", "")
        for e in feed.entries:
            try:
                pub = e.get("published_parsed") or e.get("updated_parsed")
                if not pub:
                    continue
                title = f"{site_title}閂{e.get('title', '')}"
                link = e.get("link", "")
                summary = e.get("summary", "") or e.get("description", "")
                content_encoded = e.get("content", [{}])[0].get("value", summary)
                thumbnail = extract_image(content_encoded)
                if not thumbnail:
                    thumbnail = fetch_og_image(link)
                if thumbnail:
                    content_encoded = f'<div align="center"><img src="{html.escape(thumbnail)}" /></div><br>{content_encoded}'
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": datetime(*pub[:6]),
                    "description": summary,
                    "content": content_encoded
                })
            except Exception as ex:
                print(f"Error parsing {url}: {ex}")
                continue
    items.sort(key=itemgetter("pubDate"), reverse=True)
    return items[:100]

def generate_rss(items):
    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://example.com"
    ET.SubElement(channel, "description").text = "A combined feed"

    for item in items:
        i = ET.SubElement(channel, "item")
        ET.SubElement(i, "title").text = item["title"]
        ET.SubElement(i, "link").text = item["link"]
        ET.SubElement(i, "description").text = item["description"]
        ET.SubElement(i, "pubDate").text = item["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        content = ET.SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded")
        content.text = ET.CDATA(item["content"])

    tree = ET.ElementTree(rss)
    tree.write("rss_output.xml", encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    generate_rss(fetch_and_generate())
