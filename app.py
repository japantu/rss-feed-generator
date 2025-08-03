from flask import Flask, send_from_directory

app = Flask(__name__, static_folder='public', static_url_path='/')

@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'rss_output.xml')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)

if __name__ == '__main__':
    app.run()