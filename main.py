import os
import logging
import sqlite3
from pprint import pprint
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction

logger = logging.getLogger(__name__)
extension_icon = 'images/icon.png'
db_path = os.path.join(os.path.dirname(__file__), 'emoji.sqlite')
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row

def normalize_skin_tone(tone):
    """
    Converts from the more visual skin tone preferences string to a more
    machine-readable format.
    """
    if tone == "👌 default": return ''
    elif tone == "👌🏻 light": return 'light'
    elif tone == "👌🏼 medium-light": return 'medium-light'
    elif tone == "👌🏽 medium": return 'medium'
    elif tone == "👌🏾 medium-dark": return 'medium-dark'
    elif tone == "👌🏿 dark": return 'dark'
    else: return None

class EmojiExtension(Extension):

    def __init__(self):
        super(EmojiExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        
        self.allowed_skin_tones = ["", "dark", "light", "medium", "medium-dark", "medium-light"]

class KeywordQueryEventListener(EventListener):

    def on_event(self, event, extension):
        icon_style = extension.preferences['emoji_style']
        fallback_icon_style = extension.preferences['fallback_emoji_style']
        search_term = event.get_argument().replace('%', '') if event.get_argument() else None
        search_with_shortcodes = extension.preferences['search_with'] == 'shortcodes' \
                or (search_term and search_term.startswith(':'))
        # Add %'s to search term (since LIKE %?% doesn't work)
        if search_term and search_with_shortcodes:
            search_term = ''.join([search_term, '%'])
        elif search_term:
            search_term = ''.join(['%', search_term, '%'])
        if search_with_shortcodes:
            query = '''
                SELECT em.name, em.code, em.keywords,
                       em.icon_apple, em.icon_twemoji, em.icon_noto, em.icon_blobmoji,
                       skt.icon_apple AS skt_icon_apple, skt.icon_twemoji AS skt_icon_twemoji,
                       skt.icon_noto AS skt_icon_noto, skt.icon_blobmoji AS skt_icon_blobmoji,
                       skt.code AS skt_code, sc.code as "shortcode"
                FROM emoji AS em
                  LEFT JOIN skin_tone AS skt 
                    ON skt.name = em.name AND tone = ?
                  LEFT JOIN shortcode AS sc 
                    ON sc.name = em.name
                WHERE sc.code LIKE ?
                GROUP BY em.name
                ORDER BY length(replace(sc.code, trim('{st}', '%'), ''))
                LIMIT 8
                '''.format(st=search_term)
        else:
            query = '''
                SELECT em.name, em.code, em.keywords,
                       em.icon_apple, em.icon_twemoji, em.icon_noto, em.icon_blobmoji,
                       skt.icon_apple AS skt_icon_apple, skt.icon_twemoji AS skt_icon_twemoji,
                       skt.icon_noto AS skt_icon_noto, skt.icon_blobmoji AS skt_icon_blobmoji,
                       skt.code AS skt_code
                FROM emoji AS em
                  LEFT JOIN skin_tone AS skt 
                    ON skt.name = em.name AND tone = ?
                WHERE em.name LIKE ?
                LIMIT 8
                '''

        # Display blank prompt if user hasn't typed anything
        if not search_term:
            search_icon = 'images/%s/icon.png' % icon_style
            return RenderResultListAction([
                ExtensionResultItem(icon=search_icon,
                                    name='Type in emoji name...',
                                    on_enter=DoNothingAction())
            ])

        skin_tone = normalize_skin_tone(extension.preferences['skin_tone'])
        if skin_tone not in extension.allowed_skin_tones:
            logger.warning('Unknown skin tone "%s"' % skin_tone)
            skin_tone = ''
        
        # Get list of results from sqlite DB
        items = []
        display_char = extension.preferences['display_char'] != 'no'
        for row in conn.execute(query, [skin_tone, search_term]):
            if row['skt_code']:
                icon = row['skt_icon_%s' % icon_style]
                icon = row['skt_icon_%s' % fallback_icon_style] if not icon else icon
                code = row['skt_code']
            else:
                icon = row['icon_%s' % icon_style]
                icon = row['icon_%s' % fallback_icon_style] if not icon else icon
                code = row['code']
            
            name = row['shortcode'] if search_with_shortcodes else row['name'].capitalize() 
            if display_char: name += ' | %s' % code

            items.append(ExtensionResultItem(icon=icon, name=name,
                                             on_enter=CopyToClipboardAction(code)))

        return RenderResultListAction(items)

if __name__ == '__main__':
    EmojiExtension().run()
