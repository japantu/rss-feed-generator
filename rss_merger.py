# -*- coding: utf-8 -*-
from flask import Flask, Response, send_file, request
import os

app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    # GitHub Actionsが生成したXMLファイルを返す
    # ファイルのパスは `public/rss_output.xml`
    file_path = os.path.join(os.getcwd(), 'public', 'rss_output.xml')

    # ファイルが存在するか確認
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")

    # ファイルを送信
    return send_file(file_path, mimetype="application/rss+xml")

if __name__ == "__main__":
    # ローカルテスト用
    app.run(host='0.0.0.0', port=5000)