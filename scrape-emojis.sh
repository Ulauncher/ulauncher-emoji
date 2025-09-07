#!/bin/bash

set -e

if [ ! -f "emoji-list.html" ] || [ "$USE_CACHE" != "1" ]; then
    echo "emoji-list.html not found or cache disabled."
    read -p "Do you want to re-download emoji-list.html from unicode.org? This may take a while. (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Downloading emoji-list.html. May take a while..."
        wget https://unicode.org/emoji/charts/emoji-list.html -O emoji-list.html
    else
        echo "Skipping download emoji-list.html. Using existing file."
    fi
fi

if [ "$USE_CACHE" != "1" ] || [ ! -d "noto-emoji" ]; then
    echo "Cloning noto-emoji repository"
    git clone --depth 1 git@github.com:googlefonts/noto-emoji.git
else
    echo "Updating noto-emoji repository"
    cd noto-emoji
    git pull
    cd ..
fi

echo "Scraping emojis from downloaded files..."
scrapy runspider EmojiSpider.py
