#!/bin/bash

set -e

mkdir -p .cache

emojilist_file=.cache/emoji-list.html
if [ ! -f "$emojilist_file" ] || [ "$USE_CACHE" != "1" ]; then
    echo "$emojilist_file not found or cache disabled."
    read -p "Do you want to re-download $emojilist_file from unicode.org? This may take a while. (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Downloading $emojilist_file. May take a while..."
        wget https://unicode.org/emoji/charts/$emojilist_file -O $emojilist_file
    else
        echo "Skipping download $emojilist_file. Using existing file."
    fi
fi

if [ "$USE_CACHE" != "1" ] || [ ! -d "emojibase" ]; then
    echo "Cloning milesj/emojibase repository"
    git clone --depth 1 git@github.com:milesj/emojibase.git
else
    echo "Updating milesj/emojibase repository"
    cd emojibase
    git pull
    cd ..
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
