from flask import Flask, Response, send_file, request

app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)
    return send_file("rss_output.xml", mimetype="text/xml")