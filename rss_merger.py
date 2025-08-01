# -*- coding: utf-8 -*-
from flask import Flask, Response, request, send_from_directory
import os

app = Flask(__name__)

# 変更点: ルートを '/' から '/rss_output.xml' に変更
@app.route("/rss_output.xml", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    # フォルダからファイルを送信
    # os.getcwd()は Render では /opt/render/project/src を指す
    file_dir = os.path.join(os.getcwd(), 'public')
    file_name = 'rss_output.xml'
    
    file_path = os.path.join(file_dir, file_name)
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")
        
    return send_from_directory(file_dir, file_name, mimetype="application/rss+xml; charset=utf-8")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)