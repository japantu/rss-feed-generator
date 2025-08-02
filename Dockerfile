FROM python:3.11-slim

WORKDIR /app

# ライブラリのインストールは一度だけ行う
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# その他のファイルをコピー
COPY . .

CMD ["python", "rss_generator.py"]
