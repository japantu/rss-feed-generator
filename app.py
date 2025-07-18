### app.py
from flask import Flask, Response
from generate_rss import fetch_and_generate

app = Flask(__name__)

@app.route("/")
def rss_feed():
    try:
        items = fetch_and_generate()
        rss_xml = generate_xml(items)
        return Response(rss_xml, mimetype="application/rss+xml")
    except Exception as e:
        return f"Internal Server Error: {e}", 500

def generate_xml(items):
    from xml.etree.ElementTree import Element, SubElement, tostring, ElementTree, register_namespace
    from xml.sax.saxutils import escape

    register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    register_namespace("dc", "http://purl.org/dc/elements/1.1/")

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Merged RSS Feed"

    for item in items:
        it = SubElement(channel, "item")
        SubElement(it, "title").text = item["title"]
        SubElement(it, "link").text = item["link"]
        SubElement(it, "description").text = item["description"]
        SubElement(it, "dc:date").text = item["pubDate"]
        SubElement(it, "source").text = item["site"]
        SubElement(it, "content:encoded").text = item["content"]

    return tostring(rss, encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)