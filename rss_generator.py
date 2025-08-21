# rss_generator.py の以下の関数を修正：

def get_feed_hash(entries):
    """フィードエントリのハッシュを計算 - より安定したハッシュ"""
    # 最新10件のタイトルとリンクでハッシュ作成（正規化して安定化）
    items_for_hash = []
    for entry in entries[:10]:
        title = entry.get('title', '').strip()
        link = entry.get('link', '').strip()
        # URLパラメータを除去して安定化
        if '?' in link:
            link = link.split('?')[0]
        items_for_hash.append(f"{title}|{link}")
    
    hash_string = "||".join(items_for_hash)
    hash_value = hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    # デバッグ情報
    logging.debug(f"Hash calculation for {len(entries)} entries: {hash_value[:8]}...")
    if len(entries) > 0:
        logging.debug(f"First entry: {entries[0].get('title', '')[:50]}...")
    
    return hash_value

def fetch_single_rss_optimized(url, cache):
    """最適化された単一RSSフィード取得 - キャッシュデバッグ付き"""
    start_time = time.time()
    
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        
        if feed.bozo and feed.bozo_exception:
            logging.warning(f"RSS parsing error for {url}: {feed.bozo_exception}")

        site = feed.feed.get("title", "Unknown Site")
        current_hash = get_feed_hash(feed.entries)
        previous_hash = cache.get("feed_hashes", {}).get(url)
        
        # キャッシュ状態のデバッグ情報
        logging.info(f"Cache check for {site}: current={current_hash[:8]}..., previous={previous_hash[:8] if previous_hash else 'None'}")
        
        items = []
        new_count = 0
        cached_count = 0
        og_fetch_count = 0
        
        # ハッシュが同じ場合は既存記事を使用
        if current_hash == previous_hash:
            logging.info(f"✓ Cache HIT for {site} - using cached articles")
            cached_articles_found = 0
            for entry in feed.entries:
                article_url = entry.get("link", "")
                if article_url in cache.get("articles", {}):
                    items.append(cache["articles"][article_url])
                    cached_count += 1
                    cached_articles_found += 1
                else:
                    # キャッシュにない記事は新規処理
                    processed_item = process_single_entry(entry, site, cache)
                    items.append(processed_item)
                    new_count += 1
                    cache.setdefault("articles", {})[article_url] = processed_item
            
            logging.info(f"Cache result: {cached_articles_found} articles found in cache, {new_count} new articles processed")
            
        else:
            logging.info(f"✗ Cache MISS for {site} - processing articles")
            if previous_hash:
                logging.info(f"Hash changed from {previous_hash[:8]}... to {current_hash[:8]}...")
            else:
                logging.info("No previous hash found (first run or cache cleared)")
                
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
        logging.info(f"Processed {site} in {elapsed:.2f}s - {new_count} new, {cached_count} cached, {og_fetch_count} OG fetched")
        
        return items
        
    except Exception as e:
        logging.error(f"Error processing RSS feed {url}: {e}", exc_info=True)
        return []

def load_cache():
    """キャッシュをロード - 詳細情報付き"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            # キャッシュ統計
            articles_count = len(cache_data.get("articles", {}))
            og_images_count = len(cache_data.get("og_images", {}))
            feed_hashes_count = len(cache_data.get("feed_hashes", {}))
            
            logging.info(f"Cache loaded: {articles_count} articles, {og_images_count} OG images, {feed_hashes_count} feed hashes")
            
            # 古いキャッシュの確認
            if articles_count > 0:
                oldest_date = None
                newest_date = None
                for article in cache_data.get("articles", {}).values():
                    if article.get("processed_at"):
                        try:
                            processed_at = datetime.fromisoformat(article["processed_at"])
                            if oldest_date is None or processed_at < oldest_date:
                                oldest_date = processed_at
                            if newest_date is None or processed_at > newest_date:
                                newest_date = processed_at
                        except:
                            pass
                
                if oldest_date and newest_date:
                    logging.info(f"Cache date range: {oldest_date.strftime('%Y-%m-%d %H:%M')} to {newest_date.strftime('%Y-%m-%d %H:%M')}")
            
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
