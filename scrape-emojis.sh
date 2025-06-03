#!/bin/bash

set -ex

wget https://unicode.org/emoji/charts/emoji-list.html

git clone --depth 1 git@github.com:googlefonts/noto-emoji.git

scrapy runspider EmojiSpider.py
