# encoding: utf-8
import os
import re
import scrapy
import sqlite3
import shutil
import base64


ICONS_PATH = 'images/emoji'
DB_PATH = 'emoji.sqlite'


def rm_r(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def cleanup():
    rm_r(ICONS_PATH)
    rm_r(DB_PATH)
    os.makedirs(ICONS_PATH)


def setup_db():
    conn = sqlite3.connect('emoji.sqlite', check_same_thread=False)
    conn.executescript('''
        CREATE TABLE emoji (name VARCHAR PRIMARY KEY, code VARCHAR,
                            icon VARCHAR, keywords VARCHAR, name_search VARCHAR);
        CREATE TABLE skin_tone (name VARCHAR, code VARCHAR, icon VARCHAR, tone VARCHAR);
        CREATE INDEX name_idx ON skin_tone (name);''')
    conn.row_factory = sqlite3.Row

    return conn


def str_to_unicode_emoji(s):
    """
    Converts 'U+FE0E' to u'\U0000FE0E'
    """
    return re.sub(r'U\+([0-9a-fA-F]+)', lambda m: unichr(int(m.group(1), 16)), s).replace(' ', '')


cleanup()
conn = setup_db()


class EmojiSpider(scrapy.Spider):
    name = 'emojispider'
    start_urls = ['http://unicode.org/emoji/charts/emoji-list.html']
    # start_urls = ['http://172.17.0.1:8000/list2.html']

    def parse(self, response):
        icon = 0
        for tr in response.xpath('//tr[.//td[@class="code"]]'):
            code = str_to_unicode_emoji(tr.css('.code a::text').extract_first())
            name = ''.join(tr.xpath('(.//td[@class="name"])[1]//text()').extract())
            keywords = ''.join(tr.xpath('(.//td[@class="name"])[2]//text()').extract())
            keywords = ' '.join([kw.strip() for kw in keywords.split('|') if 'skin tone' not in kw])
            icon_b64 = tr.css('.andr img').xpath('@src').extract_first().split('base64,')[1]
            name = name.replace(u'⊛', '').strip()
            icon_name = name.replace(':', '').replace(' ', '_')
            skin_tone = ''
            found = re.search(r'(?P<skin_tone>[-\w]+) skin tone', name, re.I)
            if found:
                skin_tone = found.group('skin_tone')
                name = name.replace(': %s skin tone' % skin_tone, '')

            record = {
                'name': name,
                'icon': '%s/%s.png' % (ICONS_PATH, icon_name.encode('ascii', 'ignore')),
                'code': code,
                'keywords': keywords,
                'tone': skin_tone,
                'name_search': ' '.join(set(
                    [kw.strip() for kw in ('%s %s' % (name, keywords)).split(' ')]
                ))
            }

            with open(record['icon'], 'w') as f:
                f.write(base64.decodestring(icon_b64))

            if skin_tone:
                query = '''INSERT INTO skin_tone (icon, code, name, tone)
                           VALUES (:icon, :code, :name, :tone)'''
            else:
                query = '''INSERT INTO emoji (icon, code, name, keywords, name_search)
                           VALUES (:icon, :code, :name, :keywords, :name_search)'''
            conn.execute(query, record)

            yield record

        conn.commit()
