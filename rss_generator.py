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

# ログ設定
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
                cache_data = json.load(f)
                
            articles_count = len(cache_data.get("articles", {}))
            og_images_count = len(cache_data.get("og_images", {}))
            feed_hashes_count = len(cache_data.get("feed_hashes", {}))
            
            logging.info(f"Cache loaded: {articles_count} articles, {og_images_count} OG images, {feed_hashes_count} feed hashes")
            return cache_data
            
        except Exception as e:
            logging.warning(f"Cache load error: {e}")
    else:
        logging.info("No existing cache file found - starting fresh")
        
    return {
        "articles": {},
        "og_images": {},
        "feed_hashes": {}
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
    
    if 'hamusoku' in site_name.lower():
        cleaned = re.sub(r'続きを読む.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'→\s*続きを読む.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'&gt;&gt;続きを読む.*', '', cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()

def extract_og_image_with_cache(page_url, cache):
    """キャッシュ機能付きOG画像抽出（超高速版）"""
    if not page_url:
        return ""
    
    # キャッシュから取得
    if page_url in cache.get("og_images", {}):
        return cache["og_images"][page_url]
    
    try:
        response = requests.get(page_url, headers=HEADERS, timeout=2)  # 3秒→2秒
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        og_image_tag = soup.find("meta", property="og:image")
        if og_image_tag and og_image_tag.get("content"):
            img_url = og_image_tag["content"]
            result = urljoin(page_url, img_url)
            cache.setdefault("og_images", {})[page_url] = result
            return result
        
    except Exception as e:
        logging.debug(f"OG image extraction failed for {page_url}: {e}")
    
    cache.setdefault("og_images", {})[page_url] = ""
    return ""

def get_feed_hash(entries):
    """フィードエントリのハッシュを計算 - 4Gamer対応版"""
    items_for_hash = []
    for entry in entries[:10]:  # 上位10件でハッシュ計算
        title = entry.get('title', '').strip()
        link = entry.get('link', '').strip()
        
        # 4Gamerの場合、URLパラメータとタイムスタンプを正規化
        if '4gamer.net' in link:
            # URLパラメータを除去
            if '?' in link:
                link = link.split('?')[0]
            # 末尾のスラッシュを統一
            link = link.rstrip('/')
        elif '?' in link:
            link = link.split('?')[0]
            
        items_for_hash.append(f"{title}|{link}")
    
    hash_string = "||".join(items_for_hash)
    hash_value = hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    logging.debug(f"Hash for {len(entries)} entries: {hash_value[:8]}... (first: {entries[0].get('title', '')[:30]}...)")
    
    return hash_value

def extract_rss_image(entry, article_url):
    """RSS内から画像を優先抽出"""
    thumb = ""
    
    if "media_thumbnail" in entry and entry.media_thumbnail:
        thumb = entry.media_thumbnail[0]["url"]
    elif "media_content" in entry and entry.media_content:
        thumb = entry.media_content[0]["url"]
    elif "enclosures" in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/") and enc.get("href"):
                thumb = enc["href"]
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
            return urljoin(article_url, img["src"])
    except Exception as e:
        logging.debug(f"HTML image extraction error: {e}")
    
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
    thumb = extract_rss_image(entry, article_url)
    
    if not thumb:
        thumb = extract_html_image(html_raw, article_url)
    
    # OG画像は補完として使用（RSS/HTML内に画像がない場合のみ）
    if not thumb and article_url:
        thumb = extract_og_image_with_cache(article_url, cache)
    
    # 最終コンテンツ作成
    final_content_html = html_raw or ""
    if thumb and '<img' not in final_content_html:
        final_content_html = f'<img src="{thumb}" loading="lazy" style="max-width:100%; height:auto;"><br>{final_content_html}'
    
    # プレーンテキスト作成
    plain_text = html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)) if html_raw else ""
    plain_description = clean_content_text(plain_text, site)

    return {
        "title": f"{site}】{html.unescape(entry.get('title',''))}",
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
        
        # ハッシュが同じ場合は、キャッシュから既存記事を返す
        if current_hash == previous_hash:
            logging.info(f"No updates for {site} (hash match: {current_hash[:8]})")
            cached_articles = []
            for entry in feed.entries:
                article_url = entry.get("link", "")
                if article_url and article_url in cache.get("articles", {}):
                    cached_articles.append(cache["articles"][article_url])
            return cached_articles
        
        # 新しい記事がある場合は更新処理
        logging.info(f"Processing updates for {site} (hash: {previous_hash[:8] if previous_hash else 'none'} -> {current_hash[:8]})")
        
        items = []
        new_count = 0
        og_skip_count = 0
        
        for i, entry in enumerate(feed.entries):
            article_url = entry.get("link", "")
            if not article_url:
                continue
            
            # キャッシュにない記事のみ処理
            if article_url not in cache.get("articles", {}):
                processed_item = process_single_entry(entry, site, cache)
                
                # OG画像取得を大幅制限（新着記事の最初の2件のみ）
                if not processed_item.get("has_image") and new_count < 2:
                    og_thumb = extract_og_image_with_cache(article_url, cache)
                    if og_thumb and '<img' not in processed_item["content"]:
                        processed_item["content"] = f'<img src="{og_thumb}" loading="lazy" style="max-width:100%; height:auto;"><br>{processed_item["content"]}'
                        processed_item["has_image"] = True
                else:
                    og_skip_count += 1
                
                cache.setdefault("articles", {})[article_url] = processed_item
                new_count += 1
            
            # キャッシュから記事を取得
            if article_url in cache.get("articles", {}):
                items.append(cache["articles"][article_url])
        
        # フィードハッシュ更新
        cache.setdefault("feed_hashes", {})[url] = current_hash
        
        elapsed = time.time() - start_time
        logging.info(f"Processed {site} in {elapsed:.2f}s - {new_count} new, {og_skip_count} OG skipped")
        
        return items
        
    except Exception as e:
        logging.error(f"Error processing RSS feed {url}: {e}")
        return []

def fetch_and_generate_items():
    """最適化されたメインロジック"""
    start_time = time.time()
    cache = load_cache()
    all_items = []
    
    logging.info("=== RSS FEED UPDATE ===")
    
    # 並列処理数を削減（安定性優先）
    with ThreadPoolExecutor(max_workers=2) as executor:
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
    
    # 古いキャッシュ記事を削除（7日以上前）
    cutoff_date = datetime.now() - timedelta(days=7)
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
    
    if articles_to_remove:
        logging.info(f"Cleaned up {len(articles_to_remove)} old cached articles (7+ days)")
    
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
    SubElement(ch, "description").text = "複数のRSSフィードを統合"
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
    import sys
    
    logging.info("Starting optimized RSS feed generation...")
    
    # GitHub PagesのベースURL
    base_url = "https://japantu.github.io/rss-feed-generator/"

    # 強制キャッシュクリアオプション
    force_clear_cache = "--clear-cache" in sys.argv
    
    if force_clear_cache:
        logging.info("Force clearing cache...")
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            logging.info("Cache file deleted")

    items = fetch_and_generate_items()
    xml_string = generate_rss_xml_string(items, base_url=base_url)
    
    output_dir = "public" 
    os.makedirs(output_dir, exist_ok=True)
    
    output_filepath = os.path.join(output_dir, "rss_output.xml")
    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write(xml_string)
    
    logging.info(f"RSS feed generated with {len(items)} articles")
    if items:
        latest_date = items[0]["pubDate"]
        if isinstance(latest_date, str):
            latest_date = datetime.fromisoformat(latest_date.replace('Z', '+00:00'))
        logging.info(f"Latest article date: {latest_date.strftime('%Y-%m-%d %H:%M:%S')}")
    
    logging.info(f"RSS feed successfully generated and saved to {output_filepath}")
