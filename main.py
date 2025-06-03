import os
import logging
import sqlite3
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction

logger = logging.getLogger(__name__)
extension_icon = "images/icon.png"
db_path = os.path.join(os.path.dirname(__file__), "emoji.sqlite")
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row

SEARCH_LIMIT_MIN = 2
SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_MAX = 50


def normalize_skin_tone(tone):
    """
    Converts from the more visual skin tone preferences string to a more
    machine-readable format.
    """
    if tone == "👌 default":
        return ""
    elif tone == "👌🏻 light":
        return "light"
    elif tone == "👌🏼 medium-light":
        return "medium-light"
    elif tone == "👌🏽 medium":
        return "medium"
    elif tone == "👌🏾 medium-dark":
        return "medium-dark"
    elif tone == "👌🏿 dark":
        return "dark"
    else:
        return None


class EmojiExtension(Extension):

    def __init__(self):
        super(EmojiExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, MoreEnterEventListener())

        self.allowed_skin_tones = [
            "",
            "dark",
            "light",
            "medium",
            "medium-dark",
            "medium-light",
        ]


class KeywordQueryEventListener(EventListener):

    def on_event(self, event, extension):
        return search(event, extension)


class MoreEnterEventListener(EventListener):

    def on_event(self, event, extension):
        data = event.get_data()
        return search(
            event, extension, search_term=data["search_term"], offset=data["offset"]
        )


def search(event, extension, search_term=None, offset=0):
    search_limit = extension.preferences["search_limit"]

    try:
        search_limit = search_limit.strip()
        search_limit = int(search_limit)

        if search_limit < SEARCH_LIMIT_MIN:
            search_limit = SEARCH_LIMIT_MIN
        elif search_limit > SEARCH_LIMIT_MAX:
            search_limit = SEARCH_LIMIT_MAX
    except Exception as e:
        search_limit = SEARCH_LIMIT_DEFAULT

    icon_style = "noto"
    fallback_icon_style = "apple"
    search_term = (
        (event.get_argument().replace("%", "") if event.get_argument() else None)
        if search_term is None
        else search_term
    )
    search_with_shortcodes = search_term and search_term.startswith(":")
    # Add %'s to search term (since LIKE %?% doesn't work)

    skin_tone = normalize_skin_tone(extension.preferences["skin_tone"])
    if skin_tone not in extension.allowed_skin_tones:
        logger.warning('Unknown skin tone "%s"' % skin_tone)
        skin_tone = ""

    search_term_orig = search_term
    if search_term and search_with_shortcodes:
        search_term = "".join([search_term, "%"])
    elif search_term:
        search_term = "".join(["%", search_term, "%"])
    if search_with_shortcodes:
        query = """
            SELECT em.name, em.code, em.keywords,
                    em.icon_apple, em.icon_noto,
                    skt.icon_apple AS skt_icon_apple,
                    skt.icon_noto AS skt_icon_noto,
                    skt.code AS skt_code, sc.code as "shortcode"
            FROM emoji AS em
                LEFT JOIN skin_tone AS skt
                ON skt.name = em.name AND tone = ?
                LEFT JOIN shortcode AS sc
                ON sc.name = em.name
            WHERE sc.code LIKE ?
            GROUP BY em.name
            ORDER BY length(replace(sc.code, ?, ''))
            LIMIT ?;
            """
        sql_args = [skin_tone, search_term, search_term_orig, SEARCH_LIMIT_MAX]
    else:
        query = """
            SELECT em.name, em.code,
                em.icon_apple, em.icon_noto,
                skt.icon_apple AS skt_icon_apple,
                skt.icon_noto AS skt_icon_noto,
                skt.code AS skt_code
            FROM emoji AS em
            LEFT JOIN skin_tone AS skt
                ON skt.name = em.name AND tone = ?
            WHERE em.name LIKE ?
                OR em.name_search LIKE ?
            ORDER BY
                CASE
                    WHEN em.name LIKE ? THEN 0
                    WHEN em.name_search LIKE ? THEN 1
                END
            LIMIT ?;
            """
        sql_args = [
            skin_tone,
            search_term,
            search_term,
            search_term,
            search_term,
            SEARCH_LIMIT_MAX,
        ]

    # Display blank prompt if user hasn't typed anything
    if not search_term:
        search_icon = "images/%s/icon.png" % icon_style
        return RenderResultListAction(
            [
                ExtensionResultItem(
                    icon=search_icon,
                    name="Type in emoji name...",
                    on_enter=DoNothingAction(),
                )
            ]
        )

    # Get list of results from sqlite DB
    items = []
    display_char = extension.preferences["display_char"] != "no"
    i = 0
    displayed = 0
    for row in conn.execute(query, sql_args):
        i += 1
        if offset > 0 and i <= offset:
            continue

        if row["skt_code"]:
            icon = row["skt_icon_%s" % icon_style]
            icon = row["skt_icon_%s" % fallback_icon_style] if not icon else icon
            code = row["skt_code"]
        else:
            icon = row["icon_%s" % icon_style]
            icon = row["icon_%s" % fallback_icon_style] if not icon else icon
            code = row["code"]

        name = row["shortcode"] if search_with_shortcodes else row["name"].capitalize()
        if display_char:
            name += " | %s" % code

        items.append(
            ExtensionResultItem(
                icon=icon, name=name, on_enter=CopyToClipboardAction(code)
            )
        )

        displayed += 1
        if displayed >= search_limit:
            # Add "MORE" result item with a custom action
            items.append(
                ExtensionResultItem(
                    icon="images/more.png",
                    name="View more",
                    description=f"You are viewing results from {offset + 1} to {offset + i}. Click for more",
                    on_enter=ExtensionCustomAction(
                        data={"offset": i, "search_term": search_term},
                        keep_app_open=True,
                    ),
                )
            )
            break

    return RenderResultListAction(items)


if __name__ == "__main__":
    EmojiExtension().run()
