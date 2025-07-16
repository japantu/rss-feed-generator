# app.py
from flask import Flask, Response
from generate_rss import fetch_and_generate
from xml.sax.saxutils import escape
from datetime import timezone

app = Flask(__name__)

@app.route("/")
def index():
    return "RSS Generator is running"

@app.route("/rss")
def rss():
    items = fetch_and_generate()
    body = "\n".join(f"""<item>
<title>{escape(i['site'])} 閂 {escape(i['title'])}</title>
<link>{escape(i['link'])}</link>
<description><![CDATA[{i['description']}]]></description>
<dc:date>{i['pubDate'].astimezone(timezone.utc).isoformat()}</dc:date>
<source>{escape(i['site'])}</source>
<media:thumbnail url="{escape(i['thumbnail'])}" />
<content:encoded><![CDATA[{i['content']}]]></content:encoded>
</item>""" for i in items)

    rss = f"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'
xmlns:media="http://search.yahoo.com/mrss/"
xmlns:dc="http://purl.org/dc/elements/1.1/"
xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Merged RSS Feed</title>
{body}
</channel>
</rss>"""
    return Response(rss, mimetype="application/xml")
