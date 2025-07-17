from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss
from io import BytesIO

app = Flask(__name__)

@app.route("/")
def index():
    items = fetch_and_generate()
    xml_buffer = BytesIO()
    generate_rss(items)
    with open("rss_output.xml", "rb") as f:
        return Response(f.read(), mimetype="application/rss+xml")
