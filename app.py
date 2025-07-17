from flask import Flask, Response
from generate_rss import fetch_and_generate
from xml.etree import ElementTree as ET
from datetime import timezone
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "RSS Feed is running. Access /rss to view feed."

@app.route("/rss")
def rss():
    items = fetch_and_generate()

    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:dc": "http://purl.org/dc/elements/1.1/",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "統合フィード"
    ET.SubElement(channel, "link").text = "https://rss-x2xp.onrender.com/rss"
    ET.SubElement(channel, "description").text = "複数RSSを更新順に統合"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = f"{item['site']}｜{item['title']}"
        ET.SubElement(entry, "link").text = item["link"]
        ET.SubElement(entry, "description").text = item["description"]

        dc_date = ET.SubElement(entry, "{http://purl.org/dc/elements/1.1/}date")
        dc_date.text = item["pubDate"].astimezone(timezone.utc).isoformat()

        content_encoded = ET.SubElement(entry, "{http://purl.org/rss/1.0/modules/content/}encoded")
        content_html = ""
        if item["thumbnail"]:
            content_html += f'<img src="{item["thumbnail"]}" /><br>'
        content_html += item["content"]
        content_encoded.text = content_html

    xml_data = ET.tostring(rss, encoding="utf-8", method="xml")
    return Response(xml_data, mimetype="application/rss+xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
