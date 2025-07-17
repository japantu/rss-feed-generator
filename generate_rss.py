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
            if "content" in entry and isinstance(entry.content, list):
                content = entry.content[0].value
            elif "content:encoded" in entry:
                encoded = entry["content:encoded"]
                if isinstance(encoded, list):
                    content = encoded[0]
                else:
                    content = encoded

            # サムネイル抽出
            thumbnail = ""
            for tag in ("content", "summary", "description"):
                if tag in entry:
                    tag_data = entry[tag]
                    if isinstance(tag_data, list):
                        tag_data = tag_data[0]
                    if isinstance(tag_data, str):
                        soup = BeautifulSoup(tag_data, "html.parser")
                        img_tag = soup.find("img")
                        if img_tag and img_tag.get("src"):
                            thumbnail = img_tag["src"]
                            break

            items.append({
                "title": html.unescape(title),
                "link": link,
                "pubDate": pub_date_obj,
                "description": html.unescape(description),
                "content": html.unescape(content),
                "thumbnail": thumbnail,
                "site": site_title
            })

    # 全体で200件に絞って返す（更新日時順）
    sorted_items = sorted(items, key=lambda x: x["pubDate"], reverse=True)
    return sorted_items[:200]
