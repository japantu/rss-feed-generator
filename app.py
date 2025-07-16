from flask import Flask, Response
from generate_rss import fetch_and_generate
import xml.etree.ElementTree as ET

app = Flask(__name__)

@app.route("/")
def index():
    return "RSS Generator is running"

@app.route("/rss")
def rss():
    items = fetch_and_generate()

    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://your-domain.com/rss"
    ET.SubElement(channel, "description").text = "Combined feed of multiple sources"

    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = f"{item['site']} 閂 {item['title']}"
        ET.SubElement(entry, "link").text = item["link"]
        ET.SubElement(entry, "description").text = item["description"]
        ET.SubElement(entry, "pubDate").text = item["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        content_encoded = ET.SubElement(entry, "content:encoded")
        content_encoded.text = f"<![CDATA[{item['content']}]]>"

    xml_data = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return Response(xml_data, mimetype="application/rss+xml")
