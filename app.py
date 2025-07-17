from flask import Flask, Response
from generate_rss import fetch_and_generate
import xml.etree.ElementTree as ET

app = Flask(__name__)

@app.route("/")
def index():
    items = fetch_and_generate()

    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
        "xmlns:dc": "http://purl.org/dc/elements/1.1/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://example.com/"
    ET.SubElement(channel, "description").text = "Combined feed from multiple sources"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = f"{item['site']}閂{item['title']}"
        ET.SubElement(entry, "link").text = item["link"]
        ET.SubElement(entry, "dc:date").text = item["pubDate"].isoformat()
        ET.SubElement(entry, "source").text = item["site"]

        # <description> に画像を直接含める（CDATAなし）
        if item["thumbnail"]:
            desc = f'<img src="{item["thumbnail"]}"><br>{item["description"]}'
        else:
            desc = item["description"]
        ET.SubElement(entry, "description").text = desc

        ET.SubElement(entry, "content:encoded").text = item["content"]

    xml_data = ET.tostring(rss, encoding="utf-8", method="xml")
    return Response(xml_data, mimetype="application/rss+xml")

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))  # Renderが割り当てたPORTを取得
    app.run(host="0.0.0.0", port=port)
