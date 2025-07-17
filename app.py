from flask import Flask, Response
from generate_rss import fetch_and_generate
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from datetime import timezone

import os

app = Flask(__name__)

@app.route("/", methods=["GET"])
def serve_rss():
    items = fetch_and_generate()

    rss = Element("rss", version="2.0", attrib={
        "xmlns:dc": "http://purl.org/dc/elements/1.1/",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Merged RSS Feed"

    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = f"{item['site']} 閂 {item['title']}"
        SubElement(entry, "link").text = item["link"]
        SubElement(entry, "description").text = item["description"]

        # 画像入りの content:encoded
        content_html = item["description"]
        if item["thumbnail"]:
            content_html = f'<img src="{item["thumbnail"]}"><br>{content_html}'
        content = SubElement(entry, "content:encoded")
        content.text = content_html

        SubElement(entry, "dc:date").text = item["pubDate"].astimezone(timezone.utc).isoformat()

    rough_string = tostring(rss, encoding="utf-8")
    pretty_xml = minidom.parseString(rough_string).toprettyxml(indent="  ", encoding="utf-8")

    return Response(pretty_xml, content_type="application/rss+xml")


# ✅ これがないとRenderがHTTPポートを検知できない！
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
