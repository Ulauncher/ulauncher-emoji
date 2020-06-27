# encoding: utf-8
import os
import re
import scrapy
import sqlite3
import shutil
import base64

EMOJI_STYLES = ['apple', 'twemoji', 'noto', 'blobmoji']
ICONS_PATH = lambda s: 'images/%s/emoji' % s
DB_PATH = 'emoji.sqlite'


def rm_r(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def cleanup():
    for style in EMOJI_STYLES: rm_r(ICONS_PATH(style))
    rm_r(DB_PATH)
    for style in EMOJI_STYLES: os.makedirs(ICONS_PATH(style))

def setup_db():
    conn = sqlite3.connect('emoji.sqlite', check_same_thread=False)
    conn.executescript('''
        CREATE TABLE emoji (name VARCHAR PRIMARY KEY, code VARCHAR,
                            icon_apple VARCHAR, icon_twemoji VARCHAR,
                            icon_noto VARCHAR, icon_blobmoji VARCHAR,
                            keywords VARCHAR, name_search VARCHAR);
        CREATE TABLE skin_tone (name VARCHAR, code VARCHAR, tone VARCHAR,
                                icon_apple VARCHAR, icon_twemoji VARCHAR,
                                icon_noto VARCHAR, icon_blobmoji VARCHAR);
        CREATE INDEX name_idx ON skin_tone (name);'''
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
            code = tr.css('.code a::text').extract_first()
            encoded_code = str_to_unicode_emoji(code)
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
                'code': encoded_code,
                'keywords': keywords,
                'tone': skin_tone,
                'name_search': ' '.join(set(
                    [kw.strip() for kw in ('%s %s' % (name, keywords)).split(' ')]
                )),
                # Icons Styles 
                **{ 'icon_%s' % style: '%s/%s.png' \
                        % (ICONS_PATH(style), icon_name.encode('ascii', 'ignore')) \
                        for style in EMOJI_STYLES \
                }
            }

            # CREATE TABLE emoji (name VARCHAR PRIMARY KEY, code VARCHAR,
            #                     icon_apple VARCHAR, icon_twemoji VARCHAR,
            #                     icon_noto VARCHAR, icon_blobmoji VARCHAR,
            #                     keywords VARCHAR, name_search VARCHAR);
            # CREATE TABLE skin_tone (name VARCHAR, code VARCHAR, tone VARCHAR,
            #                         icon_apple VARCHAR, icon_twemoji VARCHAR,
            #                         icon_noto VARCHAR, icon_blobmoji VARCHAR);
            # CREATE INDEX name_idx ON skin_tone (name);'''
            for style in EMOJI_STYLES:
                if style == 'apple':
                    with open(record['icon_%s' % style],'w') as f:
                        f.write(base64.decodestring(icon_b64))
                else:
                    # TODO: depending on the style, download the 
                    #       emoji from github based on the emoji code
                    # - twemoji: 
                    #   - root: https://github.com/twitter/twemoji/raw/master/assets/72x72/
                    #   - pattern: (CODE, LOWERCASE, DASH(-) SEPERATED).png
                    # - noto: 
                    #   - root: https://github.com/googlefonts/noto-emoji/raw/master/png/128/
                    #   - pattern: emoji_u(CODE, LOWERCASE, UNDERSCORE (_) SEPERATED).png
                    # - blobmoji: 
                    #   - root: https://github.com/C1710/blobmoji/raw/master/png/128/
                    #   - pattern: emoji_u(CODE, LOWERCASE, UNDERSCORE (_) SEPERATED).png
                    pass 

            if skin_tone:
                query = '''INSERT INTO skin_tone (name, code, tone, icon_apple, icon_twemoji, 
                                                  icon_noto, icon_blobmoji)
                           VALUES (:name, :code, :tone, :icon_apple, :icon_twemoji, 
                                   :icon_noto, :icon_blobmoji)'''
            else:
                query = '''INSERT INTO emoji (name, code, icon_apple, icon_twemoji, 
                                              icon_noto, icon_blobmoji, keywords, name_search)
                           VALUES (:name, :code, :icon_apple, :icon_twemoji, 
                                   :icon_noto, :icon_blobmoji, :keywords, :name_search)'''
            conn.execute(query, record)

            yield record

        conn.commit()
