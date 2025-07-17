from flask import Flask, Response
from generate_rss import fetch_and_generate
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

app = Flask(__name__)

@app.route('/')
def rss_feed():
    items = fetch_and_generate()

    rss = Element('rss', {
        'version': '2.0',
        'xmlns:dc': 'http://purl.org/dc/elements/1.1/',
        'xmlns:content': 'http://purl.org/rss/1.0/modules/content/'
    })
    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = 'Merged RSS Feed'
    SubElement(channel, 'link').text = 'https://rss-x2xp.onrender.com/'
    SubElement(channel, 'description').text = 'Merged feed from multiple sources.'

    for item in items:
        entry = SubElement(channel, 'item')
        SubElement(entry, 'title').text = f"{item['title']} 閂 {item['site']}"
        SubElement(entry, 'link').text = item['link']
        SubElement(entry, 'description').text = f'<img src="{item["thumbnail"]}" /><br>{item["description"]}'
        SubElement(entry, 'dc:date').text = item['pubDate'].isoformat()
        SubElement(entry, 'source').text = item['site']
        content = SubElement(entry, 'content:encoded')
        content.text = item["content"]

    xml_string = tostring(rss, encoding='utf-8')
    pretty_xml = parseString(xml_string).toprettyxml(indent="  ", encoding='utf-8')
    return Response(pretty_xml, content_type='text/xml')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
