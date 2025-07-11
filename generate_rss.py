import feedparser
import html
import re
from datetime import datetime
from operator import itemgetter
import requests
from bs4 import BeautifulSoup

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

def extract_image(desc_html):
    match = re.search(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', desc_html)
    return match.group(1) if match else ""

def fetch_og_image(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        html_doc = requests.get(url, headers=headers, timeout=5).text
        soup = BeautifulSoup(html_doc, "html.parser")
        meta = soup.find("meta", property="og:image")
        if meta and meta.get("content"):
            return meta["content"]
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    except Exception as e:
        print(f"Failed to fetch og:image from {url}: {e}")
    return ""

def fetch_and_generate():
    items = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
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

def save_rss():
    items = fetch_and_generate()
    body = ""
    for i in items:
        body += f"""<item>
<title>{html.escape(i['title'])}</title>
<link>{html.escape(i['link'])}</link>
<description><![CDATA[{i['description']}]]></description>
<pubDate>{i['pubDate'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
<content:encoded><![CDATA[{i['content']}]]></content:encoded>
</item>\n"""
    rss = f"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0' xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Merged RSS</title>
{body}
</channel>
</rss>"""
    with open("rss_output.xml", "w", encoding="utf-8") as f:
        f.write(rss)

save_rss()
