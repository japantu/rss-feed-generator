import os
import asyncio
import aiohttp
import feedparser
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
import html
import ssl
import certifi

# RSSフィードを取得するURLのリスト
RSS_URLS = [
    'https://www.lifehacker.jp/feed/index.xml',
    'https://www.gizmodo.jp/feed/index.xml',
    'https://www.kotaku.jp/feed/index.xml',
    'https://www.digimonostation.jp/feed/index.xml',
    'https://www.roomie.jp/feed/index.xml',
    'https://www.machi-ya.jp/feed/index.xml',
    'https://www.businessinsider.jp/rss',
    'https://www.techinsight.jp/feed',
    'https://www.sankeibiz.jp/rss/news/business_all.xml',
    'https://jp.techcrunch.com/feed/',
    'https://wired.jp/feed/'
]

# SSL証明書のエラーを回避するための設定
ssl_context = ssl.create_default_context(cafile=certifi.where())

async def fetch_feed(session, url):
    try:
        async with session.get(url, timeout=30, ssl=ssl_context) as response:
            return await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"WARNING - RSS fetching error for {url}: {e}")
        return None

def parse_feed(xml_text, url):
    if xml_text:
        try:
            return feedparser.parse(xml_text)
        except Exception as e:
            print(f"WARNING - RSS parsing error for {url}: {e}")
    return None

async def main():
    print("INFO - Starting RSS feed generation for file output...")

    fg = FeedGenerator()
    fg.id('http://example.com/rss_output.xml')
    fg.title('RSS Feed Generator')
    fg.author({'name': 'RSS Generator', 'email': 'info@example.com'})
    fg.link(href='http://example.com', rel='alternate')
    fg.language('ja')
    fg.description("Generated RSS feed combining multiple sources.")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        tasks = [fetch_feed(session, url) for url in RSS_URLS]
        xml_texts = await asyncio.gather(*tasks)

    all_entries = []
    for url, xml_text in zip(RSS_URLS, xml_texts):
        feed = parse_feed(xml_text, url)
        if feed:
            all_entries.extend(feed.entries)

    # 公開日時でソート（古い記事を除外）
    all_entries.sort(key=lambda entry: getattr(entry, 'published_parsed', None) or (1970, 1, 1, 0, 0, 0), reverse=True)

    seen_links = set()
    unique_entries = []
    for entry in all_entries:
        link = entry.get('link')
        if link and link not in seen_links:
            unique_entries.append(entry)
            seen_links.add(link)

    for entry in unique_entries[:20]:
        fe = fg.add_entry()
        fe.id(entry.link)
        fe.title(html.unescape(entry.title))
        fe.link(href=entry.link, rel='alternate')

        # published_parsedがある場合のみ設定
        published = getattr(entry, 'published_parsed', None)
        if published:
            pub_date = datetime(*published[:6], tzinfo=timezone.utc)
            fe.published(pub_date)
            fe.dc('date', pub_date.isoformat())
        else:
            now = datetime.now(timezone.utc)
            fe.published(now)
            fe.dc('date', now.isoformat())

        content = getattr(entry, 'summary', '') or getattr(entry, 'content', [{'value': ''}])[0]['value']
        fe.description(html.unescape(content or ''))

    output_dir = "public"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "rss_output.xml"), "w", encoding="utf-8") as f:
        fg.rss_file(f, pretty=True)

    print("INFO - RSS feed successfully generated and saved to public/rss_output.xml")

if __name__ == '__main__':
    asyncio.run(main())
