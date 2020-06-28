# encoding: utf-8
import os
import re
import scrapy
import requests
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
        CREATE INDEX name_idx ON skin_tone (name);''')
    conn.row_factory = sqlite3.Row

    return conn


def str_to_unicode_emoji(s):
    """
    Converts 'U+FE0E' to u'\U0000FE0E'
    """
    return re.sub(r'U\+([0-9a-fA-F]+)', lambda m: chr(int(m.group(1), 16)), s).replace(' ', '')


def str_to_emoji_dl(string, style):
    """
    Given an emoji's codepoint (e.g. 'U+FE0E') and a non-apple emoji style, 
    returns a potentially-broken download link to a png image of the emoji 
    in that style. 
    """
    base = string.replace('U+', '').lower()
    if style == 'twemoji':
        # See discussion in commit 8115b76 for more information about
        # why the base needs to be patched like this.
        patched = re.sub(r'0*([1-9a-f][0-9a-f]*)', lambda m: m.group(1), 
                base.replace(' ', '-').replace('fe0f-20e3', '20e3').replace('-fe0f-', '-').replace('fe0f-', '').replace('-fe0f', ''))
        
        response = requests.get('https://github.com/twitter/twemoji/raw/gh-pages/v/latest')
        version = response.text if response.ok else None
        if version:
            return 'https://github.com/twitter/twemoji/raw/gh-pages/v/%s/72x72/%s.png' \
                    % (version, patched)
        else:
            return 'https://github.com/twitter/twemoji/raw/master/assets/72x72/%s.png' \
                    % patched
    elif style == 'noto':
        return 'https://github.com/googlefonts/noto-emoji/raw/master/png/128/emoji_u%s.png' \
                % base.replace(' ', '_')
    elif style == 'blobmoji':
        return 'https://github.com/C1710/blobmoji/raw/master/png/128/emoji_u%s.png' \
                % base.replace(' ', '_')

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
                        % (ICONS_PATH(style), icon_name) \
                        for style in EMOJI_STYLES \
                }
            }

            for style in EMOJI_STYLES:
                if style == 'apple':
                    icon_data = tr.css('.andr img').xpath('@src').extract_first().split('base64,')[1]
                    icon_data = base64.decodestring(icon_data.encode('utf-8'))
                else:
                    link = str_to_emoji_dl(code, style)
                    resp = requests.get(link)
                    icon_data = resp.content if resp.ok else None
                    print('[%s] %s' % ('OK' if resp.ok else 'BAD', link))

                if icon_data:
                    with open(record['icon_%s' % style], 'wb') as f:
                        f.write(icon_data)
                    
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
