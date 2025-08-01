# -*- coding: utf-8 -*-
from flask import Flask, Response, request
import os

app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    file_path = os.path.join(os.getcwd(), 'public', 'rss_output.xml')
    
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")

    # 変更点: send_fileを使わず、ファイルの内容を直接読み込む
    with open(file_path, "r", encoding="utf-8") as f:
        xml_content = f.read()

    # mimetypeとcharsetを明示的に指定してResponseを返す
    return Response(xml_content, mimetype="application/rss+xml; charset=utf-8")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)