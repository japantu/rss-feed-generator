from flask import Flask, Response
from generate_rss import fetch_and_generate, generate_rss

app = Flask(__name__)

@app.route("/")
@app.route("/rss")
def rss_feed():
    items = fetch_and_generate()
    rss_xml = generate_rss(items)
    return Response(rss_xml, content_type="application/xml; charset=utf-8")
