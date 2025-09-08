import os
import re
import scrapy
import sqlite3
import shutil
import base64
import json
from tqdm import tqdm

EMOJI_STYLES = ["apple", "noto"]
ICONS_PATH = lambda s: "images/%s/emoji" % s
DB_PATH = "emoji.sqlite"
USE_CACHE = os.getenv("USE_CACHE", "0") == "1"


class EmojiSpider(scrapy.Spider):
    name = "emojispider"
    start_urls = [
        "file://" + os.path.abspath(".cache/emoji-list.html"),
        "file://" + os.path.abspath(".cache/full-emoji-modifiers.html"),
    ]

    def parse(self, response):
        emoji_nodes = response.xpath('//tr[.//td[@class="code"]]')

        # Wrap the loop with tqdm for progress bar
        for i in tqdm(range(len(emoji_nodes)), desc="Processing emojis", leave=True):
            tr = emoji_nodes[i]
            code = tr.css(".code a::text").extract_first()
            encoded_code = str_to_unicode_emoji(code)
            name = "".join(tr.xpath('(.//td[@class="name"])[1]//text()').extract())
            keywords = "".join(tr.xpath('(.//td[@class="name"])[2]//text()').extract())
            keywords = " ".join(
                [kw.strip() for kw in keywords.split("|") if "skin tone" not in kw]
            )
            name = name.replace("⊛", "").strip()
            icon_name = name.replace(":", "").replace(" ", "_")
            skin_tone = ""
            found = re.search(r"(?P<skin_tone>[-\w]+) skin tone", name, re.I)
            if found:
                skin_tone = found.group("skin_tone")
                name = name.replace(": %s skin tone" % skin_tone, "")
            shortcodes = code_to_shortcodes(encoded_code)

            # Update progress bar description with current emoji
            tqdm.write(f"Fetching {i + 1}/{len(emoji_nodes)}: {encoded_code} {name}")
            tqdm.write(f"#️⃣ Shortcodes: {', '.join(shortcodes) if shortcodes else '❌'}")

            record = {
                "name": name,
                "code": encoded_code,
                "shortcodes": " ".join(shortcodes),
                "keywords": keywords,
                "tone": skin_tone,
                "name_search": " ".join(
                    set(
                        [s[1:-1] for s in shortcodes]
                        + [kw.strip() for kw in ("%s %s" % (name, keywords)).split(" ")]
                    )
                ),
                # Merge icon styles into record
                **{
                    "icon_%s" % style: "%s/%s.png" % (ICONS_PATH(style), icon_name)
                    for style in EMOJI_STYLES
                },
            }

            # Extract icons for each emoji
            tqdm.write("🖼  Extracting Icons...")
            supported_styles = []
            for style in EMOJI_STYLES:
                icon_data = None
                if style == "apple":
                    icon_data = (
                        tr.css(".andr img")
                        .xpath("@src")
                        .extract_first()
                        .split("base64,")[1]
                    )
                    icon_data = base64.decodebytes(icon_data.encode("utf-8"))
                else:
                    file_path = codepoint_to_noto_path(code)
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            icon_data = f.read()

                tqdm.write(f"- {'✅' if icon_data else '❌'}: {style}")

                if icon_data:
                    with open(record["icon_%s" % style], "wb") as f:
                        f.write(icon_data)
                    supported_styles += [style]

            # Prepare emoji insertion query
            supported_styles = ["icon_%s" % style for style in supported_styles]
            if skin_tone:
                query = (
                    """INSERT OR IGNORE INTO skin_tone (name, code, tone, """
                    + ", ".join(supported_styles)
                    + """)
                            VALUES (:name, :code, :tone, """
                    + ", ".join([":%s" % s for s in supported_styles])
                    + """)"""
                )
            else:
                query = (
                    """INSERT OR IGNORE INTO emoji (name, code, """
                    + ", ".join(supported_styles)
                    + """,
                                                keywords, name_search)
                            VALUES (:name, :code, """
                    + ", ".join([":%s" % s for s in supported_styles])
                    + """,
                                    :keywords, :name_search)"""
                )

            # Insert emoji & associated shortcodes into DB
            conn.execute(query, record)
            for sc in shortcodes:
                squery = (
                    """INSERT OR IGNORE INTO shortcode (name, code)
                            VALUES (:name, "%s")"""
                    % sc
                )
                conn.execute(squery, record)

        conn.commit()


def rm_r(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def cleanup():
    for style in EMOJI_STYLES:
        rm_r(ICONS_PATH(style))
    rm_r(DB_PATH)
    for style in EMOJI_STYLES:
        os.makedirs(ICONS_PATH(style))


def setup_db():
    global conn
    conn = sqlite3.connect("emoji.sqlite", check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE emoji (
            name VARCHAR PRIMARY KEY,
            code VARCHAR,
            icon_apple VARCHAR,
            icon_noto VARCHAR,
            keywords VARCHAR,
            name_search VARCHAR
        );
        CREATE TABLE skin_tone (
            name VARCHAR,
            code VARCHAR,
            tone VARCHAR,
            icon_apple VARCHAR,
            icon_noto VARCHAR
        );
        CREATE TABLE shortcode (
            name VARCHAR,
            code VARCHAR
        );
        CREATE INDEX name_idx ON skin_tone (name);
        CREATE UNIQUE INDEX tone_name_tone_code_idx ON skin_tone (name, tone, code);
        CREATE UNIQUE INDEX shortcode_code_idx ON shortcode (code, name);
        """
    )
    conn.row_factory = sqlite3.Row

    return conn


def str_to_unicode_emoji(s):
    """
    Converts 'U+FE0E' to u'\U0000fe0e'
    """
    return re.sub(r"U\+([0-9a-fA-F]+)", lambda m: chr(int(m.group(1), 16)), s).replace(
        " ", ""
    )


def codepoint_to_noto_path(codepoint):
    """
    Given an emoji's codepoint (e.g. 'U+FE0E') returns a path to the png image
    """
    base = codepoint.replace("U+", "").lower()

    return f"noto-emoji/png/128/emoji_u{base}.png"


def code_to_shortcodes(emoji: str) -> list[str]:
    code = emoji_to_hex(emoji)
    shortcodes: set[str] = set()
    emojibase_preset_names = [
        "cldr-native",
        "joypixels",
        "emojibase",
        "iamcal",
        "github",
        "cldr",
    ]
    for preset in emojibase_preset_names:
        path = f"emojibase/packages/data/en/shortcodes/{preset}.raw.json"
        if not os.path.exists(path):
            continue
        with open(path, "r") as f:
            data = json.load(f)
            shortcode = data.get(code)
            if shortcode is not None:
                if isinstance(shortcode, str):
                    shortcodes.add(data[code])
                elif isinstance(shortcode, list):
                    for sc in shortcode:
                        shortcodes.add(sc)
                else:
                    raise ValueError(
                        f"Unexpected shortcode type for {code} in {preset}: {type(shortcode)}"
                    )

    return [f":{sc}:" for sc in shortcodes]


def emoji_to_hex(emoji):
    """Convert emoji to hex code points"""
    code_points = []
    for char in emoji:
        code_points.append(f"{ord(char):X}")
    return "-".join(code_points).upper()


cleanup()
conn = setup_db()
