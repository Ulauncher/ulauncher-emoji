import os
import logging
import sqlite3
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction


logger = logging.getLogger(__name__)
extension_icon = 'images/icon.png'
allowed_skin_tones = ["", "dark", "light", "medium", "medium-dark", "medium-light"]
db_path = os.path.join(os.path.dirname(__file__), 'emoji.sqlite')
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row


class EmojiExtension(Extension):

    def __init__(self):
        super(EmojiExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())


class KeywordQueryEventListener(EventListener):

    def on_event(self, event, extension):
        list_item_size = extension.preferences['list_item_size']
        items_limit = 8 if list_item_size == 'large' else 20
        ResultItem = ExtensionResultItem if list_item_size == 'large' else ExtensionSmallResultItem
        query = r"""SELECT
            em.name, em.code, em.icon, em.keywords,
            skt.code AS skt_code, skt.icon AS skt_icon
            FROM emoji AS em
            LEFT JOIN skin_tone AS skt ON skt.name = em.name AND tone = ?
            WHERE name_search LIKE ?
            LIMIT ?"""

        search_term = ''.join(['%', event.get_argument().replace('%', ''), '%']) if event.get_argument() else None
        if not search_term:
            return RenderResultListAction([
                ResultItem(icon=extension_icon, name='Type in emoji name...', on_enter=DoNothingAction())
            ])

        skin_tone = extension.preferences['skin_tone']
        if skin_tone not in allowed_skin_tones:
            logger.warning('Unknown skin tone "%s"' % skin_tone)
            skin_tone = ''

        items = []
        for row in conn.execute(query, [skin_tone, search_term, items_limit]):
            if row['skt_code']:
                icon = row['skt_icon']
                code = row['skt_code']
            else:
                icon = row['icon']
                code = row['code']

            name = ('%s %s' % (row['name'].capitalize(), code)).encode('utf8')
            items.append(ResultItem(icon=icon, name=name, on_enter=CopyToClipboardAction(code)))

        return RenderResultListAction(items)


if __name__ == '__main__':
    EmojiExtension().run()
