import os
import json
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
from ulauncher.api.shared.action.ActionList import ActionList

logger = logging.getLogger(__name__)
extension_icon = "images/icon.png"
db_path = os.path.join(os.path.dirname(__file__), "emoji.sqlite")
recent_path = os.path.join(os.path.dirname(__file__), "recent.json")
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.row_factory = sqlite3.Row

SEARCH_LIMIT_MIN = 2
SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_MAX = 50

RECENT_LIMIT_MIN = 2
RECENT_LIMIT_DEFAULT = 8
RECENT_LIMIT_MAX = 50
# Keep more on disk than any recent_limit setting can display, so raising
# the preference later doesn't lose history that already fell off the page.
RECENT_STORE_MAX = 50


def clamp_limit(value, minimum, default, maximum):
    try:
        value = int(str(value).strip())
    except Exception:
        return default

    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def load_recent():
    try:
        with open(recent_path, encoding="utf-8") as f:
            names = json.load(f)
        if not isinstance(names, list):
            return []
        return [name for name in names if isinstance(name, str)]
    except Exception:
        return []


def record_recent(name):
    names = load_recent()
    names = [n for n in names if n != name]
    names.insert(0, name)
    names = names[:RECENT_STORE_MAX]
    try:
        with open(recent_path, "w", encoding="utf-8") as f:
            json.dump(names, f)
    except Exception as e:
        logger.warning("Could not persist recent emoji: %s" % e)


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
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

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


class ItemEnterEventListener(EventListener):

    def on_event(self, event, extension):
        data = event.get_data()
        action = data.get("action")

        if action == "record":
            record_recent(data["name"])
            return DoNothingAction()

        if data.get("mode") == "recent":
            # search_term must stay a non-None empty string here: event is an
            # ItemEnterEvent, which has no get_argument(), so search() must not
            # try to re-read the query from it.
            return search(event, extension, search_term="", offset=data["offset"])

        return search(
            event, extension, search_term=data["search_term"], offset=data["offset"]
        )


def search(event, extension, search_term=None, offset=0):
    search_limit = clamp_limit(
        extension.preferences["search_limit"],
        SEARCH_LIMIT_MIN,
        SEARCH_LIMIT_DEFAULT,
        SEARCH_LIMIT_MAX,
    )
    recent_limit = clamp_limit(
        extension.preferences["recent_limit"],
        RECENT_LIMIT_MIN,
        RECENT_LIMIT_DEFAULT,
        RECENT_LIMIT_MAX,
    )

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

    display_char = extension.preferences["display_char"] != "no"

    # Show recently used emoji (falling back to the blank prompt) if user
    # hasn't typed anything
    if not search_term:
        return render_recent(
            recent_limit, offset, icon_style, fallback_icon_style, skin_tone, display_char
        )

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

    # Get list of results from sqlite DB
    items = []
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
                icon=icon,
                name=name,
                on_enter=ActionList(
                    [
                        # Recording is fire-and-forget over the extension's
                        # websocket; the actual copy must stay a direct,
                        # synchronous action or it silently no-ops (see
                        # CopyToClipboardAction's Gtk.Clipboard call vs.
                        # DeferredResultRenderer.handle_response, which runs
                        # off the GTK main thread with no GLib.idle_add)
                        ExtensionCustomAction(
                            data={"action": "record", "name": row["name"]},
                            keep_app_open=False,
                        ),
                        CopyToClipboardAction(code),
                    ]
                ),
            )
        )

        displayed += 1
        if displayed >= search_limit:
            # Add "MORE" result item with a custom action, and let Alt+Enter
            # on any already-listed row page forward too (not just this one)
            more_action = ExtensionCustomAction(
                data={"action": "more", "search_term": search_term, "offset": i},
                keep_app_open=True,
            )
            for item in items:
                item._on_alt_enter = more_action
            items.append(
                ExtensionResultItem(
                    icon="images/more.png",
                    name="View more",
                    description=f"You are viewing results from {offset + 1} to {offset + displayed}. Click for more",
                    on_enter=more_action,
                    on_alt_enter=more_action,
                )
            )
            break

    return RenderResultListAction(items)


def render_recent(recent_limit, offset, icon_style, fallback_icon_style, skin_tone, display_char):
    names = load_recent()

    if not names:
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

    items = []
    i = 0
    displayed = 0
    for name in names:
        i += 1
        if offset > 0 and i <= offset:
            continue

        row = conn.execute(
            """
            SELECT em.name, em.code,
                em.icon_apple, em.icon_noto,
                skt.icon_apple AS skt_icon_apple,
                skt.icon_noto AS skt_icon_noto,
                skt.code AS skt_code
            FROM emoji AS em
            LEFT JOIN skin_tone AS skt
                ON skt.name = em.name AND tone = ?
            WHERE em.name = ?;
            """,
            [skin_tone, name],
        ).fetchone()
        if row is None:
            # emoji was renamed/removed from the DB since it was recorded
            continue

        if row["skt_code"]:
            icon = row["skt_icon_%s" % icon_style]
            icon = row["skt_icon_%s" % fallback_icon_style] if not icon else icon
            code = row["skt_code"]
        else:
            icon = row["icon_%s" % icon_style]
            icon = row["icon_%s" % fallback_icon_style] if not icon else icon
            code = row["code"]

        display_name = row["name"].capitalize()
        if display_char:
            display_name += " | %s" % code

        items.append(
            ExtensionResultItem(
                icon=icon,
                name=display_name,
                on_enter=ActionList(
                    [
                        ExtensionCustomAction(
                            data={"action": "record", "name": row["name"]},
                            keep_app_open=False,
                        ),
                        CopyToClipboardAction(code),
                    ]
                ),
            )
        )

        displayed += 1
        if displayed >= recent_limit:
            more_action = ExtensionCustomAction(
                data={"action": "more", "mode": "recent", "offset": i},
                keep_app_open=True,
            )
            for item in items:
                item._on_alt_enter = more_action
            items.append(
                ExtensionResultItem(
                    icon="images/more.png",
                    name="View more",
                    description=f"You are viewing results from {offset + 1} to {offset + displayed}. Click for more",
                    on_enter=more_action,
                    on_alt_enter=more_action,
                )
            )
            break

    if not items:
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

    return RenderResultListAction(items)


if __name__ == "__main__":
    EmojiExtension().run()
