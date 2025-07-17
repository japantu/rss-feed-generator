import feedparser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import html
import email.utils

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

def parse_datetime(entry):
    # 優先度付きでタイムスタンプを抽出
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    elif "published" in entry:
        try:
            return datetime.fromtimestamp(email.utils.mktime_tz(email.utils.parsedate_tz(entry.published)), tz=timezone.utc)
        except Exception:
            pass
    elif "updated" in entry:
        try:
            return datetime.fromtimestamp(email.utils.mktime_tz(email.utils.parsedate_tz(entry.updated)), tz=timezone.utc)
        except Exception:
            pass
    # fallback: 現在時刻（ただしミリ秒違いを強制的に加える）
    return datetime.now(timezone.utc)

def extract_image(entry):
    # content フィールドからHTML抽出を試みる
    if "content" in entry and isinstance(entry["content"], list):
        for c in entry["content"]:
            if "value" in c:
                soup = BeautifulSoup(c["value"], "html.parser")
                img = soup.find("img")
                if img and img.get("src"):
                    return img["src"]

    # content:encoded を文字列で取り出す
    for field in ["content:encoded", "summary", "description"]:
        value = entry.get(field)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        if isinstance(value, str):
            soup = BeautifulSoup(value, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                return img["src"]

    return ""

def fetch_and_generate():
    items = []

    for url in RSS_URLS:
        feed = feedparser.parse(url)
        site_title = feed.feed.get("title", "Unknown Site")

        for entry in feed.entries:
            title = html.unescape(entry.get("title", ""))
            link = entry.get("link", "")
            pub_date = parse_datetime(entry)
            description = html.unescape(entry.get("description", "") or entry.get("summary", ""))

            image_url = extract_image(entry)
            if image_url:
                description = f'<img src="{image_url}"><br>{description}'

            items.append({
                "title": f"{site_title}閂{title}",
                "link": link,
                "pubDate": pub_date,
                "dc_date": pub_date.isoformat(),
                "description": description
            })

    # 更新時間順にソート
    sorted_items = sorted(items, key=lambda x: x["pubDate"], reverse=True)
    return sorted_items[:200]
