# -*- coding: utf-8 -*-
import feedparser, html, re, requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace
import logging
import os
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 名前空間の登録
register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
register_namespace("dc", "http://purl.org/dc/elements/1.1/")

# 各RSSフィードのURLリスト
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
    "https://daily-gadget.net/feed/",
]

# HTTPリクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'
}

# キャッシュファイル
CACHE_FILE = "rss_cache.json"

def load_cache():
    """キャッシュをロード"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Cache load error: {e}")
    return {
        "articles": {},  # URL -> 記事データ
        "og_images": {},  # URL -> OG画像URL
        "feed_hashes": {}  # RSS URL -> ハッシュ
    }

def save_cache(cache_data):
    """キャッシュを保存"""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Cache save error: {e}")

def to_utc(st):
    """struct_timeをUTCのdatetimeオブジェクトに変換"""
    return datetime(*st[:6], tzinfo=timezone.utc)

def clean_content_text(content, site_name=""):
    """コンテンツから不要なテキストを除去"""
    if not content:
        return content
    
    # 「続きを読む」系のパターンを除去
    patterns_to_remove = [
        r'続きを読む.*$',
        r'Read more.*$', 
        r'もっと見る.*$',
        r'詳しくは.*$',
        r'full article.*$',
        r'\[…\].*$',
        r'\.\.\..*続き.*$',
        r'→.*続き.*$',
        r'>>.*続き.*$',
    ]
    
    cleaned = content
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    
    # hamusokuの特殊処理
    if 'hamusoku' in site_name.lower():
        # hamusoku特有の「続きを読む」パターン
        cleaned = re.sub(r'続きを読む.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'→\s*続きを読む.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'&gt;&gt;続きを読む.*', '', cleaned, flags=re.IGNORECASE)
    
    # 末尾の空白・改行を整理
    cleaned = cleaned.strip()
    
    return cleaned

def extract_og_image_with_cache(page_url, cache):
    """キャッシュ機能付きOG画像抽出（補完用）"""
    if not page_url:
        return ""
    
    # キャッシュから取得
    if page_url in cache.get("og_images", {}):
        return cache["og_images"][page_url]
    
    try:
        response = requests.get(page_url, headers=HEADERS, timeout=8)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        og_image_tag = soup.find("meta", property="og:image")
        if og_image_tag and og_image_tag.get("content"):
            img_url = og_image_tag["content"]
            result = urljoin(page_url, img_url)
            cache.setdefault("og_images", {})[page_url] = result
            logging.info(f"OG image found: {page_url}")
            return result
        
    except Exception as e:
        logging.warning(f"OG image extraction failed for {page_url}: {e}")
    
    cache.setdefault("og_images", {})[page_url] = ""
    return ""

def get_feed_hash(entries):
    """フィードエントリのハッシュを計算"""
    # 最新10件のタイトルとリンクでハッシュ作成
    items_for_hash = []
    for entry in entries[:10]:
        items_for_hash.append(f"{entry.get('title', '')}{entry.get('link', '')}")
    
    hash_string = "|".join(items_for_hash)
    return hashlib.md5(hash_string.encode()).hexdigest()

def extract_rss_image(entry, article_url):
    """RSS内から画像を優先抽出"""
    thumb = ""
    
    # 1. RSS内の画像メタデータから取得（最優先）
    if "media_thumbnail" in entry and entry.media_thumbnail:
        thumb = entry.media_thumbnail[0]["url"]
        logging.debug(f"Found media_thumbnail: {thumb}")
    elif "media_content" in entry and entry.media_content:
        thumb = entry.media_content[0]["url"]
        logging.debug(f"Found media_content: {thumb}")
    elif "enclosures" in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/") and enc.get("href"):
                thumb = enc["href"]
                logging.debug(f"Found enclosure image: {thumb}")
                break
    
    return thumb

def extract_html_image(html_raw, article_url):
    """HTML内から画像を抽出"""
    if not html_raw:
        return ""
    
    try:
        soup_desc = BeautifulSoup(html_raw, "html.parser")
        img = soup_desc.find("img")
        if img and img.get("src"):
            img_url = urljoin(article_url, img["src"])
            logging.debug(f"Found HTML image: {img_url}")
            return img_url
    except Exception as e:
        logging.warning(f"HTML image extraction error: {e}")
    
    return ""

def process_single_entry(entry, site, cache):
    """単一のエントリを処理"""
    # 日時処理
    dt = None
    if entry.get("published_parsed"):
        dt = to_utc(entry.published_parsed)
    elif entry.get("updated_parsed"):
        dt = to_utc(entry.updated_parsed)
    else:
        dt = datetime.now(timezone.utc)

    # コンテンツ抽出
    html_raw = ""
    for fld in ("content", "summary", "description"):
        if 'content' in entry and isinstance(entry['content'], list) and entry['content']:
            for c_item in entry['content']:
                if c_item and isinstance(c_item, dict) and c_item.get('type') == 'html' and c_item.get('value'):
                    html_raw = c_item['value']
                    break
        if not html_raw and entry.get(fld):
            v = entry.get(fld)
            if isinstance(v, list):
                v = v[0].get('value', '') if v[0] and isinstance(v[0], dict) else (v[0] if v else '')
            if isinstance(v, str):
                html_raw = v
                break

    article_url = entry.get("link", "")
    
    # 画像取得の優先順位
    # 1. RSS内画像メタデータ（最優先）
    thumb = extract_rss_image(entry, article_url)
    
    # 2. HTML内画像（RSS内画像がない場合）
    if not thumb:
        thumb = extract_html_image(html_raw, article_url)
    
    # 3. OG画像（補完として、RSS/HTML内画像がない場合のみ）
    if not thumb and article_url:
        thumb = extract_og_image_with_cache(article_url, cache)
    
    # 最終コンテンツ作成（クリーンアップ適用）
    final_content_html = html_raw or ""
    if thumb and '<img' not in final_content_html:
        final_content_html = f'<img src="{thumb}" loading="lazy" style="max-width:100%; height:auto;"><br>{final_content_html}'
    
    # プレーンテキスト作成（「続きを読む」除去）
    plain_text = html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)) if html_raw else ""
    plain_description = clean_content_text(plain_text, site)

    return {
        "title": f"{site}閂{html.unescape(entry.get('title',''))}",
        "link": article_url,
        "pubDate": dt.isoformat(),
        "description": plain_description,
        "content": final_content_html,
        "site": site,
        "has_image": bool(thumb),
        "processed_at": datetime.now().isoformat()
    }

def fetch_single_rss_optimized(url, cache):
    """最適化された単一RSSフィード取得"""
    start_time = time.time()
    
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        
        if feed.bozo and feed.bozo_exception:
            logging.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")

        site = feed.feed.get("title", "Unknown Site")
        current_hash = get_feed_hash(feed.entries)
        previous_hash = cache.get("feed_hashes", {}).get(url)
        
        items = []
        new_count = 0
        cached_count = 0
        og_fetch_count = 0
        
        # ハッシュが同じ場合は既存記事を使用
        if current_hash == previous_hash:
            logging.info(f"No changes for {url}, using cached articles")
            for entry in feed.entries:
                article_url = entry.get("link", "")
                if article_url in cache.get("articles", {}):
                    items.append(cache["articles"][article_url])
                    cached_count += 1
        else:
            logging.info(f"Changes detected for {url}, processing articles")
            for entry in feed.entries:
                article_url = entry.get("link", "")
                if not article_url:
                    continue
                
                # 既存記事があり、画像も取得済みの場合はキャッシュ使用
                existing_article = cache.get("articles", {}).get(article_url)
                if existing_article and existing_article.get("has_image"):
                    items.append(existing_article)
                    cached_count += 1
                else:
                    # 新規処理
                    processed_item = process_single_entry(entry, site, cache)
                    items.append(processed_item)
                    new_count += 1
                    
                    # OG画像を取得した場合のカウント
                    if not existing_article or not existing_article.get("has_image"):
                        if processed_item.get("has_image"):
                            og_fetch_count += 1
                    
                    # キャッシュに保存
                    cache.setdefault("articles", {})[article_url] = processed_item
            
            # フィードハッシュ更新
            cache.setdefault("feed_hashes", {})[url] = current_hash
        
        elapsed = time.time() - start_time
        logging.info(f"Processed {url} in {elapsed:.2f}s - {new_count} new, {cached_count} cached, {og_fetch_count} OG fetched")
        
        return items
        
    except Exception as e:
        logging.error(f"Error processing RSS feed {url}: {e}", exc_info=True)
        return []

def fetch_and_generate_items():
    """最適化されたメインロジック"""
    start_time = time.time()
    cache = load_cache()
    all_items = []
    
    logging.info("=== RSS FEED UPDATE (RSS画像優先 + OG画像補完 + コンテンツクリーンアップ) ===")
    
    # 並列処理でRSSフィード取得
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {
            executor.submit(fetch_single_rss_optimized, url, cache): url 
            for url in RSS_URLS
        }
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
            except Exception as e:
                logging.error(f"Failed to process {url}: {e}")
    
    # 古いキャッシュ記事を削除（30日以上前）
    cutoff_date = datetime.now() - timedelta(days=30)
    articles_to_remove = []
    for url, article in cache.get("articles", {}).items():
        try:
            processed_at = datetime.fromisoformat(article.get("processed_at", ""))
            if processed_at < cutoff_date:
                articles_to_remove.append(url)
        except:
            pass
    
    for url in articles_to_remove:
        cache["articles"].pop(url, None)
    
    # OG画像キャッシュも古いものを削除（60日以上前のものは削除）
    og_images_to_remove = []
    for img_url in cache.get("og_images", {}):
        # OG画像キャッシュは記事より長期保持（再取得コスト削減）
        # 実際の削除ロジックは複雑なので、ここでは記事と連動
        if img_url not in [article.get("link", "") for article in cache.get("articles", {}).values()]:
            # どの記事からも参照されていないOG画像は削除候補
            pass
    
    if articles_to_remove:
        logging.info(f"Cleaned up {len(articles_to_remove)} old cached articles (30+ days)")
    
    # キャッシュ保存
    save_cache(cache)
    
    # 日時でソート
    for item in all_items:
        if isinstance(item["pubDate"], str):
            item["pubDate"] = datetime.fromisoformat(item["pubDate"].replace('Z', '+00:00'))
    
    all_items.sort(key=lambda x: x["pubDate"], reverse=True)
    
    elapsed = time.time() - start_time
    total_with_images = sum(1 for item in all_items if item.get("has_image"))
    logging.info(f"Update completed in {elapsed:.2f}s - {len(all_items)} articles, {total_with_images} with images")
    
    return all_items[:200]

def generate_rss_xml_string(items, base_url=""):
    """記事アイテムリストからRSS XML文字列を生成"""
    rss_attribs = {"version": "2.0"}
    rss = Element("rss", attrib=rss_attribs)

    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"
    SubElement(ch, "link").text = base_url
    SubElement(ch, "description").text = "複数のRSSフィードを統合（30日キャッシュ・コンテンツクリーンアップ対応）"
    SubElement(ch, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "source").text = it["site"]
        SubElement(i, "pubDate").text = it["pubDate"].astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].astimezone().isoformat()
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]

    from io import StringIO
    f = StringIO()
    ElementTree(rss).write(f, encoding="unicode", xml_declaration=True)
    return f.getvalue()

if __name__ == "__main__":
    logging.info("Starting optimized RSS feed generation...")
    base_url = "https://rss-x2xp.onrender.com/"

    items = fetch_and_generate_items()
    xml_string = generate_rss_xml_string(items, base_url=base_url)
    
    output_dir = "public" 
    os.makedirs(output_dir, exist_ok=True)
    
    output_filepath = os.path.join(output_dir, "rss_output.xml")
    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write(xml_string)
    
    logging.info(f"RSS feed successfully generated and saved to {output_filepath}")