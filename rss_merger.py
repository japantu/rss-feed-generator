# -*- coding: utf-8 -*-
from flask import Flask, Response, request, send_from_directory
import os

app = Flask(__name__)

# 変更点: ルーティングを元の '/' に戻す
@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    file_dir = os.path.join(os.getcwd(), 'public')
    file_name = 'rss_output.xml'
    
    file_path = os.path.join(file_dir, file_name)
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")

    # 変更点: レスポンスヘッダーを明示的に設定
    response = send_from_directory(file_dir, file_name, mimetype="application/rss+xml; charset=utf-8")
    response.headers['Content-Disposition'] = 'inline' # ここで表示を強制
    return response

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)