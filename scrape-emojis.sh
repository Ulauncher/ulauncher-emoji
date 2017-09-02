#!/bin/bash

set -ex

docker build -t emoji-scraper .

docker run \
    --rm \
    -it \
    -v $(pwd):/root/scraper \
    -v $HOME/.bash_history:/root/.bash_history \
    --name emoji-scraper \
    emoji-scraper \
    bash -c "scrapy runspider EmojiSpider.py"