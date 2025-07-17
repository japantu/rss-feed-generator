from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss
import os

app = Flask(__name__)

@app.route("/")
def home():
    items = fetch_and_generate()
    generate_rss(items)
    return Response("RSS Feed is available at <a href='/rss'>/rss</a>", mimetype="text/html")

@app.route("/rss")
def rss_feed():
    items = fetch_and_generate()
    rss_xml = generate_rss_text(items)
    return Response(rss_xml, mimetype="application/rss+xml")

def generate_rss_text(items):
    from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace
    from io import BytesIO

    register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    
    rss = Element("rss", version="2.0")
    ch  = SubElement(rss, "channel")
    SubElement(ch, "title").text = "Merged RSS Feed"

    for it in items:
        i = SubElement(ch, "item")
        SubElement(i, "title").text = it["title"]
        SubElement(i, "link").text = it["link"]
        SubElement(i, "description").text = it["description"]
        SubElement(i, "pubDate").text = it["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        SubElement(i, "source").text = it["site"]
        SubElement(i, "{http://purl.org/rss/1.0/modules/content/}encoded").text = it["content"]
        SubElement(i, "{http://purl.org/dc/elements/1.1/}date").text = it["dcdate"]

    from xml.etree.ElementTree import ElementTree
    bio = BytesIO()
    ElementTree(rss).write(bio, encoding="utf-8", xml_declaration=True)
    return bio.getvalue()
