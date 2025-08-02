import os
import asyncio
import aiohttp
import feedparser
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
import html

# RSSフィードを生成するURLのリスト
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

async def fetch_feed(session, url):
    """指定されたURLからRSSフィードを非同期で取得する"""
    try:
        # SSL証明書のエラーを無視
        async with session.get(url, timeout=30, ssl=False) as response:
            return await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"WARNING - RSS fetching error for {url}: {e}")
        return None

def parse_feed(xml_text, url):
    """取得したXMLテキストをパースする"""
    if xml_text:
        try:
            return feedparser.parse(xml_text)
        except Exception as e:
            print(f"WARNING - RSS parsing error for {url}: {e}")
    return None

async def main():
    """メイン処理"""
    print("INFO - Starting RSS feed generation for file output...")

    # フィードジェネレータの初期設定
    fg = FeedGenerator()
    fg.id('http://example.com/rss_output.xml')
    fg.title('RSS Feed Generator')
    fg.author({'name': 'RSS Generator', 'email': 'info@example.com'})
    fg.link(href='http://example.com', rel='alternate')
    fg.language('ja')

    # 非同期で全てのRSSフィードを取得
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in RSS_URLS]
        xml_texts = await asyncio.gather(*tasks)

    # 取得したフィードをパースし、新しいフィードに結合
    all_entries = []
    for url, xml_text in zip(RSS_URLS, xml_texts):
        feed = parse_feed(xml_text, url)
        if feed:
            all_entries.extend(feed.entries)
    
    # 日付でソート
    all_entries.sort(key=lambda entry: getattr(entry, 'published_parsed', None) or (1970,1,1,0,0,0), reverse=True)

    # 重複エントリを除外
    seen_links = set()
    unique_entries = []
    for entry in all_entries:
        link = entry.get('link')
        if link and link not in seen_links:
            unique_entries.append(entry)
            seen_links.add(link)

    # 最新20件のエントリを新しいフィードに追加
    for entry in unique_entries[:20]:
        fe = fg.add_entry()
        fe.id(entry.link)
        fe.title(html.unescape(entry.title))
        fe.link(href=entry.link, rel='alternate')
        
        # published_parsedが存在しない場合は現在日時を使用
        published_date = getattr(entry, 'published_parsed', None)
        if published_date:
            fe.published(datetime(*published_date[:6], tzinfo=timezone.utc))

        # 記事の内容を取得し、descriptionがなくてもエラーにならないように修正
        content = getattr(entry, 'summary', '') or getattr(entry, 'content', [{'value': ''}])[0]['value']
        fe.description(html.unescape(content or ''))
        
    # RSSフィードをXML形式に変換し、ファイルに保存
    output_dir = "public"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "rss_output.xml"), "w", encoding="utf-8") as f:
        fg.rss_file(f, pretty=True)

    print("INFO - RSS feed successfully generated and saved to public/rss_output.xml")

if __name__ == '__main__':
    asyncio.run(main())