from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss_to_stream
import io

app = Flask(__name__)

@app.route("/rss")
def rss_feed():
    items = fetch_and_generate()
    stream = io.BytesIO()
    generate_rss_to_stream(items, stream)
    return Response(stream.getvalue(), mimetype="application/rss+xml")

@app.route("/", methods=["GET", "HEAD"])
def index():
    return "RSS feed available at /rss", 200
