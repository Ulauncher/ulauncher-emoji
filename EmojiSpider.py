# encoding: utf-8
import os
import re
import scrapy
import requests
import lxml.html
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
        CREATE TABLE emoji (
            name VARCHAR PRIMARY KEY, 
            code VARCHAR,
            icon_apple VARCHAR, 
            icon_twemoji VARCHAR,
            icon_noto VARCHAR, 
            icon_blobmoji VARCHAR,
            keywords VARCHAR, 
            name_search VARCHAR
        );
        CREATE TABLE skin_tone (
            name VARCHAR, 
            code VARCHAR, 
            tone VARCHAR,
            icon_apple VARCHAR, 
            icon_twemoji VARCHAR,
            icon_noto VARCHAR, 
            icon_blobmoji VARCHAR
        );
        CREATE TABLE shortcode (
            name VARCHAR,
            code VARCHAR
        );
        CREATE INDEX name_idx ON skin_tone (name);
        ''')
    conn.row_factory = sqlite3.Row

    return conn


def str_to_unicode_emoji(s):
    """
    Converts 'U+FE0E' to u'\U0000FE0E'
    """
    return re.sub(r'U\+([0-9a-fA-F]+)', lambda m: chr(int(m.group(1), 16)), s).replace(' ', '')


def codepoint_to_url(codepoint, style):
    """
    Given an emoji's codepoint (e.g. 'U+FE0E') and a non-apple emoji style, 
    returns a url to to the png image of the emoji in that style. 

    Only works for style = 'twemoji', 'noto', and 'blobmoji'.
    """
    base = codepoint.replace('U+', '').lower()
    if style == 'twemoji':
        # See discussion in commit 8115b76 for more information about
        # why the base needs to be patched like this.
        patched = re.sub(r'0*([1-9a-f][0-9a-f]*)', lambda m: m.group(1), 
                base.replace(' ', '-').replace('fe0f-20e3', '20e3').replace('1f441-fe0f-200d-1f5e8-fe0f', '1f441-200d-1f5e8'))
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

def name_to_shortcodes(shortname):
    """
    Given an emoji's CLDR Shortname (e.g. 'grinning face with smiling eyes'), returns a list
    of common shortcodes used for that emoji.
    
    NOTE: These shortcodes will NOT have colons at the beginning and end, even if they normally
          would.
    """
    url = 'https://emojipedia.org/%s/' % re.sub(r'[^a-z0-9 ]', '', shortname.lower()).replace(' ', '-')
    response = requests.get(url, stream=True)
    response.raw.decode_content = True
    html = lxml.html.parse(response.raw) if response.ok else None
    shortcode_nodes = html.xpath('//ul[@class="shortcodes"]/li/span[@class="shortcode"]') if html else []
    return [s.text for s in shortcode_nodes]

cleanup()
conn = setup_db()

class EmojiSpider(scrapy.Spider):
    name = 'emojispider'
    start_urls = ['http://unicode.org/emoji/charts/emoji-list.html']
    # start_urls = ['http://172.17.0.1:8000/list2.html']

    def parse(self, response):
        icon = 0
        emoji_nodes = response.xpath('//tr[.//td[@class="code"]]')
        for i in range(0, len(emoji_nodes)):
            # Scrape Data from unicode.org
            tr = emoji_nodes[i]
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
            shortcodes = name_to_shortcodes(name)

            # Prepare emoji data to be inserted into DB
            print("Fetching %i/%i: %s %s" % (i+1, len(emoji_nodes), encoded_code, name))
            record = {
                'name': name,
                'code': encoded_code,
                'shortcodes': ' '.join(shortcodes),
                'keywords': keywords,
                'tone': skin_tone,
                'name_search': ' '.join(set(
                    [s[1:-1] for s in shortcodes] + [kw.strip() for kw in ('%s %s' % (name, keywords)).split(' ')]
                )),
                # Merge icon styles into record
                **{ 'icon_%s' % style: '%s/%s.png' \
                        % (ICONS_PATH(style), icon_name) \
                        for style in EMOJI_STYLES \
                }
            }

            # Download Icons for each emoji
            print("🖼  Downloading Icons...")
            supported_styles = []
            for style in EMOJI_STYLES:
                if style == 'apple':
                    icon_data = tr.css('.andr img').xpath('@src').extract_first().split('base64,')[1]
                    icon_data = base64.decodestring(icon_data.encode('utf-8'))
                else:
                    link = codepoint_to_url(code, style)
                    resp = requests.get(link)
                    icon_data = resp.content if resp.ok else None
                    print('- %s: %s' % ('✅' if resp.ok else '❎', style))
                
                if icon_data:
                    with open(record['icon_%s' % style], 'wb') as f:
                        f.write(icon_data)
                    supported_styles += [style] 

            # Prepare emoji insertion query
            supported_styles = ['icon_%s' % style for style in supported_styles]
            if skin_tone:
                query = '''INSERT INTO skin_tone (name, code, tone, ''' + ', '.join(supported_styles) + ''')
                           VALUES (:name, :code, :tone, ''' + ', '.join([':%s' % s for s in supported_styles]) + ''')'''
            else:
                query = '''INSERT INTO emoji (name, code, ''' + ', '.join(supported_styles) + ''', 
                                              keywords, name_search)
                           VALUES (:name, :code, ''' + ', '.join([':%s' % s for s in supported_styles]) + ''',
                                   :keywords, :name_search)'''
            
            # Insert emoji & associated shortcodes into DB
            conn.execute(query, record)
            for sc in shortcodes:
                squery = '''INSERT INTO shortcode (name, code)
                            VALUES (:name, "%s")''' % sc
                conn.execute(squery, record)
            
            if ":sweat_smile:" in shortcodes:
                break
            else:
                yield record

        conn.commit()
