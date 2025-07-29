from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss
import os

app = Flask(__name__)

@app.route("/")
def index():
    items = fetch_and_generate()
    generate_rss(items)
    with open("rss_output.xml", "r", encoding="utf-8") as f:
        xml_content = f.read()
    return Response(xml_content, mimetype="application/rss+xml")
