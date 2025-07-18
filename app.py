from flask import Flask, Response
from generate_rss import fetch_and_generate
from xml.etree.ElementTree import Element, SubElement, tostring

app = Flask(__name__)

@app.route("/")
def rss_feed():
    items = fetch_and_generate()
    rss = Element("rss", version="2.0", nsmap={
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/"
    })
    ch = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "dc:date").text = it["dc_date"]
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]

    xml_bytes = tostring(rss, encoding="utf-8", xml_declaration=True)
    return Response(xml_bytes, mimetype="application/rss+xml")
