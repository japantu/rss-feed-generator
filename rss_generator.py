import os
import requests
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

def main():
    print("INFO - Starting RSS feed generation for file output...")

    # フィードジェネレータの初期設定
    fg = FeedGenerator()
    fg.id('http://example.com/rss_output.xml')
    fg.title('RSS Feed Generator')
    fg.author({'name': 'RSS Generator', 'email': 'info@example.com'})
    fg.link(href='http://example.com', rel='alternate')
    fg.language('ja')

    # 各RSSフィードを順次取得
    all_entries = []
    for url in RSS_URLS:
        try:
            res = requests.get(url, timeout=30)
            feed = feedparser.parse(res.text)
            all_entries.extend(feed.entries)
        except Exception as e:
            print(f"WARNING - RSS fetching error for {url}: {e}")

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
    main()