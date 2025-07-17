from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss
import io

app = Flask(__name__)

@app.route("/rss")
def rss_feed():
    items = fetch_and_generate()
    xml_io = io.BytesIO()
    generate_rss_to_stream(items, xml_io)
    return Response(xml_io.getvalue(), mimetype="application/rss+xml")

# ヘッドアクセス対策
@app.route("/", methods=["GET", "HEAD"])
def index():
    return "RSS feed is available at /rss", 200

# ↓ generate_rss_to_stream 関数を定義（generate_rss.pyから分離）
def generate_rss_to_stream(items, stream):
    from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace

    register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    register_namespace("dc", "http://purl.org/dc/elements/1.1/")

    rss = Element("rss", version="2.0")
    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["pubDate"].isoformat()
        SubElement(i, "source").text = it["site"]
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]

    ElementTree(rss).write(stream, encoding="utf-8", xml_declaration=True)
