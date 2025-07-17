import feedparser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import html

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
            if "content" in entry and isinstance(entry["content"], list):
                content = entry["content"][0].value
            elif "content:encoded" in entry:
                content = entry["content:encoded"]

            # 画像抽出（description または content 優先）
            thumbnail = ""
            for tag in ("content", "description", "summary"):
                value = entry.get(tag)
                if isinstance(value, list):
                    value = " ".join(str(v) for v in value)
                elif not isinstance(value, str):
                    continue
                soup = BeautifulSoup(value, "html.parser")
                img_tag = soup.find("img")
                if img_tag and img_tag.get("src"):
                    thumbnail = img_tag["src"]
                    break

            # 画像をdescriptionに含める
            if thumbnail:
                description = f'<img src="{thumbnail}"><br>{html.unescape(description)}'

            items.append({
                "title": f"{site_title}閂{html.unescape(title)}",
                "link": link,
                "pubDate": pub_date_obj,
                "dc_date": pub_date_obj.isoformat(),
                "description": html.unescape(description)
            })

    sorted_items = sorted(items, key=lambda x: x["pubDate"], reverse=True)
    return sorted_items[:200]
