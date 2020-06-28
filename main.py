import os
import logging
import sqlite3
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, PreferencesEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction

logger = logging.getLogger(__name__)
extension_icon = 'images/icon.png'
db_path = os.path.join(os.path.dirname(__file__), 'emoji.sqlite')
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row

def update_extension_icon(emoji_style, extension_icon):
    """Updates the extension icon to conform to emoji_style
    
    If the path extension_icon doesn't exist, it will be
    symlinked into place. Otherwise, if it's a symlink and 
    it's not pointing to emoji_style's icon.png, then it will
    be atomically updated to point to {emoji_style}/icon.png
    
    For example, if extension_icon = 'images/icon.png', and 
    'images/icon.png' doesn't exist yet, then after running 
    update_extension_icon, the directory structure will look
    something like the following:
    
    images
    ├── icon.png       --> {emoji_style}/icon.png
    ├── {emoji_style}
    │   ├── icon.png 
    │   └── emoji
    │       └── (...)
    └── (...)
    """
    styled_extension_icon = '%s/icon.png' % emoji_style
    if not os.path.exists(extension_icon):
        # create a symlink
        os.symlink(styled_extension_icon, extension_icon)
    elif os.path.islink(extension_icon) and styled_extension_icon not in os.readlink(extension_icon):
        # Source: https://stackoverflow.com/a/27788271
        # Replace symlink atomically
        os.symlink(styled_extension_icon, 'images/icon-replacement.png')
        os.rename('images/icon-replacement.png', extension_icon)            

class EmojiExtension(Extension):

    def __init__(self):
        super(EmojiExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.allowed_skin_tones = ["", "dark", "light", "medium", "medium-dark", "medium-light"]
        self.allowed_icon_style = ['apple', 'twemoji', 'noto', 'blobmoji']

class KeywordQueryEventListener(EventListener):

    def on_event(self, event, extension):
        query = r"""SELECT
            em.name, em.code, em.keywords,
            em.icon_apple, em.icon_twemoji, em.icon_noto, em.icon_blobmoji,
            skt.icon_apple AS skt_icon_apple, skt.icon_twemoji AS skt_icon_twemoji, 
            skt.icon_noto AS skt_icon_noto, skt.icon_blobmoji AS skt_icon_blobmoji,
            skt.code AS skt_code
            FROM emoji AS em
            LEFT JOIN skin_tone AS skt ON skt.name = em.name AND tone = ?
            WHERE name_search LIKE ?
            LIMIT 8"""

        search_term = ''.join(['%', event.get_argument().replace('%', ''), '%']) if event.get_argument() else None
        if not search_term:
            return RenderResultListAction([
                ExtensionResultItem(icon=extension_icon,
                                    name='Type in emoji name...',
                                    on_enter=DoNothingAction())
            ])

        skin_tone = extension.preferences['skin_tone']
        if skin_tone not in extension.allowed_skin_tones:
            logger.warning('Unknown skin tone "%s"' % skin_tone)
            skin_tone = ''
        
        items = []
        icon_style = extension.preferences['emoji_style']
        for row in conn.execute(query, [skin_tone, search_term]):
            if row['skt_code']:
                icon = row['skt_icon_%s' % icon_style]
                code = row['skt_code']
            else:
                icon = row['icon_%s' % icon_style]
                code = row['code']
            
            items.append(ExtensionResultItem(icon=icon,
                                             name=row['name'].capitalize(),
                                             on_enter=CopyToClipboardAction(code)))

        return RenderResultListAction(items)

if __name__ == '__main__':
    EmojiExtension().run()
