# -*- coding: utf-8 -*-
from flask import Flask, Response, send_file, request
import os

app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    file_path = os.path.join(os.getcwd(), 'public', 'rss_output.xml')
    
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")

    # 変更点: as_attachment=False を追加
    # これにより、ファイルをダウンロードせず、ブラウザに直接表示させます。
    return send_file(file_path, mimetype="application/rss+xml", as_attachment=False)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)