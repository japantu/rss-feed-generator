from flask import Flask, Response
from generate_rss import fetch_and_generate
import xml.etree.ElementTree as ET

app = Flask(__name__)

@app.route("/")
def rss_feed():
    items = fetch_and_generate()

    rss = ET.Element("rss", version="2.0", attrib={"xmlns:dc": "http://purl.org/dc/elements/1.1/"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Merged RSS Feed"
    ET.SubElement(channel, "link").text = "https://rss-x2xp.onrender.com/"
    ET.SubElement(channel, "description").text = "Combined feed from multiple sources"

    for item in items:
        item_elem = ET.SubElement(channel, "item")
        ET.SubElement(item_elem, "title").text = item["title"]
        ET.SubElement(item_elem, "link").text = item["link"]
        ET.SubElement(item_elem, "description").text = item["description"]
        ET.SubElement(item_elem, "dc:date").text = item["dc_date"]

    xml_str = ET.tostring(rss, encoding="utf-8", method="xml")
    return Response(xml_str, mimetype="application/xml")
