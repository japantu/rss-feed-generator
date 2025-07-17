from flask import Flask, Response
from generate_rss import fetch_and_generate
import xml.etree.ElementTree as ET
from datetime import datetime

app = Flask(__name__)

@app.route("/")
def index():
    return "Feed is available at /rss"

@app.route("/rss")
def rss():
    items = fetch_and_generate()

    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://example.com/"
    ET.SubElement(channel, "description").text = "Combined feed from multiple sources"
    ET.SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = f"{item['site']}閂{item['title']}"
        ET.SubElement(entry, "link").text = item["link"]
        ET.SubElement(entry, "pubDate").text = item["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(entry, "source").text = item["site"]

        # description に画像タグを含めて出力
        description = f'<img src="{item["thumbnail"]}" alt="thumbnail"><br>{item["description"]}' if item["thumbnail"] else item["description"]
        ET.SubElement(entry, "description").text = f"<![CDATA[{description}]]>"

        content_encoded = ET.SubElement(entry, "content:encoded")
        content_encoded.text = f"<![CDATA[{item['content']}]]>"

    xml_str = ET.tostring(rss, encoding="utf-8", method="xml")
    return Response(xml_str, mimetype="application/rss+xml")

if __name__ == "__main__":
    app.run()
