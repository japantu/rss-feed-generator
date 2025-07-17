from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss

app = Flask(__name__)

@app.route("/")
def root():
    return '<h1>Feed is available at <a href="/rss">/rss</a></h1>'

@app.route("/rss")
def rss_feed():
    try:
        items = fetch_and_generate()
        rss_content = generate_rss(items)
        return Response(rss_content, mimetype="application/rss+xml")
    except Exception as e:
        return Response(f"Internal Server Error: {e}", status=500, mimetype="text/plain")
