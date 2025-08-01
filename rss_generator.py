# -*- coding: utf-8 -*-
import feedparser, html, re, requests
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace
import logging # エラーログ出力用
import os # ファイル操作用

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 名前空間の登録（重複防止）
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
        response = requests.get(page_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            og_image_tag = soup.find("meta", property="og:image")
            if og_image_tag and og_image_tag.get("content"):
                img_url = og_image_tag["content"]
                return urljoin(page_url, img_url)
        except Exception as soup_error:
            logging.error(f"BeautifulSoup parsing error for {page_url}: {soup_error}", exc_info=True)
            return ""
        
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout when extracting OGP image from {page_url}")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request error when extracting OGP image from {page_url}: {e}")
    except Exception as e:
        logging.error(f"General error in extract_og_image for {page_url}: {e}", exc_info=True)
    return ""

def fetch_and_generate_items():
    """複数のRSSフィードから記事をフェッチし、必要な情報を整形して返す"""
    items = []
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")
                pass

            site = feed.feed.get("title", "Unknown Site")

            for e in feed.entries:
                dt = None
                if e.get("published_parsed"):
                    dt = to_utc(e.published_parsed)
                elif e.get("updated_parsed"):
                    dt = to_utc(e.updated_parsed)
                else:
                    dt = datetime.now(timezone.utc)

                html_raw = ""
                for fld in ("content", "summary", "description"):
                    if 'content' in e and isinstance(e['content'], list) and e['content']:
                        for c_item in e['content']:
                            if c_item and isinstance(c_item, dict) and c_item.get('type') == 'html' and c_item.get('value'):
                                html_raw = c_item['value']
                                break
                    if not html_raw and e.get(fld):
                        v = e.get(fld)
                        if isinstance(v, list):
                            v = v[0].get('value', '') if v[0] and isinstance(v[0], dict) else (v[0] if v else '')
                        if isinstance(v, str) and "<img" in v:
                            html_raw = v; break
                        elif isinstance(v, str) and not html_raw:
                            html_raw = v

                thumb = ""
                if "media_thumbnail" in e and e.media_thumbnail:
                    thumb = e.media_thumbnail[0]["url"]
                elif "media_content" in e and e.media_content:
                    thumb = e.media_content[0]["url"]
                elif "enclosures" in e and e.enclosures:
                    for enc in e.enclosures:
                        if enc.get("type", "").startswith("image/") and enc.get("href"):
                            thumb = enc["href"]
                            break
                if not thumb and html_raw:
                    soup_desc = BeautifulSoup(html_raw, "html.parser")
                    img = soup_desc.find("img")
                    if img and img.get("src"):
                        thumb = urljoin(e.get("link", ""), img["src"])
                if not thumb:
                    thumb = extract_og_image(e.get("link", ""))
                
                final_content_html = html_raw or ""
                if thumb and '<img' not in final_content_html:
                    final_content_html = f'<img src="{thumb}" loading="lazy" style="max-width:100%; height:auto;"><br>{final_content_html}'
                
                plain_description = html.unescape(BeautifulSoup(html_raw, "html.parser").get_text(" ", strip=True)) if html_raw else ""

                items.append({
                    "title": f"{site}閂{html.unescape(e.get('title',''))}",
                    "link": e.get("link", ""),
                    "pubDate": dt,
                    "description": plain_description,
                    "content": final_content_html,
                    "site": site
                })
        except requests.exceptions.Timeout:
            logging.error(f"Timeout when fetching RSS feed from {url}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error when fetching RSS feed from {url}: {e}")
        except Exception as e:
            logging.error(f"Error processing RSS feed {url}: {e}", exc_info=True)

    items.sort(key=lambda x: x["pubDate"], reverse=True)
    return items[:200]

def generate_rss_xml_string(items, base_url=""):
    """記事アイテムリストからRSS XML文字列を生成"""
    # 変更点: attribsからxmlns属性を削除し、versionのみにする
    rss_attribs = {
        "version": "2.0"
    }
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
    logging.info("Starting RSS feed generation for file output...")
    base_url = "https://rss-x2xp.onrender.com/rss_output.xml" 

    items = fetch_and_generate_items()
    xml_string = generate_rss_xml_string(items, base_url=base_url)
    
    output_dir = "public" 
    os.makedirs(output_dir, exist_ok=True)
    
    output_filepath = os.path.join(output_dir, "rss_output.xml")
    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write(xml_string)
    
    logging.info(f"RSS feed successfully generated and saved to {output_filepath}")