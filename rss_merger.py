# -*- coding: utf-8 -*-
from flask import Flask, Response, request
import os

app = Flask(__name__)

# ルーティングをルートURL ('/') に設定
@app.route("/", methods=["GET", "HEAD"])
def serve_rss():
    if request.method == "HEAD":
        return Response("OK", status=200)

    # publicフォルダ内のrss_output.xmlへのパス
    file_path = os.path.join(os.getcwd(), 'public', 'rss_output.xml')
    
    # ファイルの存在を確認
    if not os.path.exists(file_path):
        return Response("RSS feed not found.", status=503, mimetype="text/plain")

    # ファイルの内容を直接読み込み
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            xml_content = f.read()
    except Exception as e:
        return Response(f"Error reading file: {str(e)}", status=500, mimetype="text/plain")

    # MIMEタイプを明示的に指定してレスポンスとして返す
    return Response(xml_content, mimetype="application/rss+xml; charset=utf-8")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)