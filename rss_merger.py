# -*- coding: utf-8 -*-
import feedparser, html, re, requests
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace
import logging # エラーログ出力用

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 名前空間の登録（重複防止）
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
register_namespace("dc", "http://purl.org/dc/elements/1.1/")

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

# HTTPリクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'
}

def to_utc(st):
    """struct_timeをUTCのdatetimeオブジェクトに変換"""
    return datetime(*st[:6], tzinfo=timezone.utc)

def extract_og_image(page_url):
    """ページのOGP画像URLを抽出"""
    if not page_url:
        return ""
    try:
        # タイムアウトを10秒に延長し、User-Agentを追加
        response = requests.get(page_url, headers=HEADERS, timeout=10)
        response.raise_for_status() # HTTPエラーがあれば例外を発生させる
        soup = BeautifulSoup(response.text, "html.parser")
        og_image_tag = soup.find("meta", property="og:image")
        if og_image_tag and og_image_tag.get("content"):
            img_url = og_image_tag["content"]
            # 相対URLの場合も考慮してurljoin
            return urljoin(page_url, img_url)
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout when extracting OGP image from {page_url}")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request error when extracting OGP image from {page_url}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error extracting OGP image from {page_url}: {e}")
    return ""

def fetch_and_generate_items():
    """複数のRSSフィードから記事をフェッチし、必要な情報を整形して返す"""
    items = []
    for url in RSS_URLS:
        try:
            # feedparserにUser-Agentとタイムアウトを設定
            feed = feedparser.parse(url, request_headers=HEADERS)
            
            # feedparserのエラーチェック
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")
                # エラーが深刻な場合はこのフィードをスキップ
                if isinstance(feed.bozo_exception, feedparser.NonXMLRSSException):
                    continue

            site = feed.feed.get("title", "Unknown Site") # サイト名取得

            for e in feed.entries:
                # 投稿日時の取得
                dt = None
                if e.get("published_parsed"):
                    dt = to_utc(e.published_parsed)
                elif e.get("updated_parsed"):
                    dt = to_utc(e.updated_parsed)
                else:
                    dt = datetime.now(timezone.utc) # 取得できない場合は現在時刻

                # 元HTMLの抽出（<img>付きが優先）
                html_raw = ""
                # "content:encoded" > "content" > "summary" > "description" の順に内容をチェック
                for fld in ("content", "summary", "description"): # content:encoded はXMLツリーで直接アクセス
                    # content:encoded モジュールからの取得を試みる
                    if 'content' in e and isinstance(e['content'], list) and e['content']:
                        for c_item in e['content']:
                            if c_item.get('type') == 'html' and c_item.get('value'):
                                html_raw = c_item['value']
                                break
                    if not html_raw and e.get(fld):
                        v = e.get(fld)
                        if isinstance(v, list): # リスト形式の場合に対応
                            v = v[0].get('value', '') if v[0] and isinstance(v[0], dict) else (v[0] if v else '')
                        if isinstance(v, str) and "<img" in v:
                            html_raw = v; break
                        elif isinstance(v, str) and not html_raw:
                            html_raw = v

                # サムネイル抽出ロジック
                thumb = ""
                if "media_thumbnail" in e and e.media_thumbnail:
                    thumb = e.media_thumbnail[0]["url"]
                elif "media_content" in e and e.media_content:
                    thumb = e.media_content[0]["url"]
                elif "enclosures" in e and e.enclosures:
                    # enclosureが画像であることを確認
                    for enc in e.enclosures:
                        if enc.get("type", "").startswith("image/") and enc.get("href"):
                            thumb = enc["href"]
                            break
                if not thumb and html_raw:
                    # BeautifulSoupでHTMLからimgタグのsrcを抽出
                    soup_desc = BeautifulSoup(html_raw, "html.parser")
                    img = soup_desc.find("img")
                    if img and img.get("src"):
                        thumb = urljoin(e.get("link", ""), img["src"]) # 相対URL考慮
                if not thumb:
                    # 最後の手段としてOGP画像を試す
                    thumb = extract_og_image(e.get("link", ""))
                
                # content:encoded の内容を組み立て
                # 画像がない場合、OGP画像があればそれを先頭に追加
                final_content_html = html_raw or ""
                if thumb and '<img' not in final_content_html: # 元のHTMLにimgタグがない場合
                    final_content_html = f'<img src="{thumb}" loading="lazy" style="max-width:100%; height:auto;"><br>{final_content_html}'
                
                # descriptionはHTMLタグを除去してプレーンテキストにする
                plain_description = html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)) if html_raw else ""

                items.append({
                    "title": f"{site}閂{html.unescape(e.get('title',''))}", # サイト名とタイトルを結合
                    "link": e.get("link", ""), # 記事のリンク
                    "pubDate": dt, # 投稿日時 (datetimeオブジェクト)
                    "description": plain_description, # プレーンテキストの要約
                    "content": final_content_html, # HTML形式の本文（画像含む）
                    "site": site # サイト名
                })
        except requests.exceptions.Timeout:
            logging.error(f"Timeout when fetching RSS feed from {url}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error when fetching RSS feed from {url}: {e}")
        except Exception as e:
            logging.error(f"Error processing RSS feed {url}: {e}", exc_info=True)

    items.sort(key=lambda x: x["pubDate"], reverse=True) # 更新日時で降順ソート
    return items[:200] # 最新200件に限定

def generate_rss_xml_string(items, base_url=""):
    """記事アイテムリストからRSS XML文字列を生成"""
    rss = Element("rss", version="2.0")
    # 名前空間をルート要素に明示的に定義
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    rss.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")

    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"
    SubElement(ch, "link").text = base_url if base_url else "http://example.com/unified_rss" # 配信URL
    SubElement(ch, "description").text = "複数のRSSフィードを統合"
    SubElement(ch, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "source").text = it["site"]
        # pubDate (RFC 822)
        SubElement(i, "pubDate").text = it["pubDate"].astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        # dc:date (ISO 8601)
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].astimezone().isoformat()
        # content:encoded に HTML 本文
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]

    # ElementTreeをStringIOで文字列化して返す
    from io import StringIO
    f = StringIO()
    # xml_declaration=True は文字列化の際に自動で追加されるはずだが明示的に
    ElementTree(rss).write(f, encoding="unicode", xml_declaration=True)
    return f.getvalue()


# Flaskアプリとして動かすための設定
from flask import Flask, Response, request

app = Flask(__name__)

@app.route("/unified_rss", methods=["GET", "HEAD"]) # KLWPからアクセスしやすいパス
def serve_unified_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    logging.info("Fetching and generating RSS feed...")
    items = fetch_and_generate_items() # RSSフィードをフェッチし処理
    # Renderで動作する際のホストURLを渡す
    base_url = request.url_root if request.url_root else "http://example.com/unified_rss"
    xml_string = generate_rss_xml_string(items, base_url=base_url) # XML文字列を生成
    logging.info("RSS feed generated successfully.")

    return Response(xml_string, mimetype="application/rss+xml")

# RenderのGunicornが起動する際にメインとなるエントリーポイント
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000) # ローカルテスト用