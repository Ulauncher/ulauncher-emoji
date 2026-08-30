import json
import pickle

import pytest

import main
from ulauncher.api.shared.event import ItemEnterEvent
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction


class FakeExtension:
    def __init__(self, **prefs):
        self.preferences = {
            "search_limit": "8",
            "recent_limit": "8",
            "skin_tone": "👌 default",
            "display_char": "no",
            **prefs,
        }
        self.allowed_skin_tones = [
            "",
            "dark",
            "light",
            "medium",
            "medium-dark",
            "medium-light",
        ]


class FakeEvent:
    def __init__(self, argument=None):
        self._argument = argument

    def get_argument(self):
        return self._argument


@pytest.fixture(autouse=True)
def isolated_recent_file(tmp_path, monkeypatch):
    # main.py's recent.json lives next to the extension; never touch the
    # real file from a test run, point at a throwaway path per test instead
    monkeypatch.setattr(main, "recent_path", str(tmp_path / "recent.json"))


def item_names(render_action):
    return [item.get_name() for item in render_action.result_list]


def select_data(item):
    record_action, copy_action = item.on_enter(None)
    return pickle.loads(record_action._data), copy_action


class TestClampLimit:
    def test_default_on_garbage(self):
        assert main.clamp_limit("nonsense", 2, 8, 50) == 8

    def test_passthrough_valid(self):
        assert main.clamp_limit("5", 2, 8, 50) == 5
        assert main.clamp_limit(5, 2, 8, 50) == 5

    def test_clamps_below_min(self):
        assert main.clamp_limit("0", 2, 8, 50) == 2

    def test_clamps_above_max(self):
        assert main.clamp_limit("999", 2, 8, 50) == 50


class TestRecentStore:
    def test_load_missing_file_returns_empty(self):
        assert main.load_recent() == []

    def test_load_corrupt_json_returns_empty(self):
        with open(main.recent_path, "w") as f:
            f.write("{not valid json")
        assert main.load_recent() == []

    def test_load_non_list_json_returns_empty(self):
        with open(main.recent_path, "w") as f:
            json.dump({"oops": True}, f)
        assert main.load_recent() == []

    def test_record_inserts_most_recent_first(self):
        main.record_recent("grinning face")
        main.record_recent("smiling face")
        assert main.load_recent() == ["smiling face", "grinning face"]

    def test_record_dedupes_moves_to_front(self):
        main.record_recent("grinning face")
        main.record_recent("smiling face")
        main.record_recent("grinning face")
        assert main.load_recent() == ["grinning face", "smiling face"]

    def test_record_caps_at_store_max(self):
        for i in range(main.RECENT_STORE_MAX + 10):
            main.record_recent("emoji %d" % i)
        names = main.load_recent()
        assert len(names) == main.RECENT_STORE_MAX
        assert names[0] == "emoji %d" % (main.RECENT_STORE_MAX + 9)


class TestSearchAndRecent:
    def test_empty_query_no_recent_shows_placeholder(self):
        res = main.search(FakeEvent(None), FakeExtension())
        assert item_names(res) == ["Type in emoji name..."]

    def test_search_returns_matching_results(self):
        res = main.search(FakeEvent("grinning"), FakeExtension())
        assert item_names(res)[0] == "Grinning face"

    def test_search_paginates_with_view_more(self):
        res = main.search(FakeEvent("face"), FakeExtension(search_limit="2"))
        names = item_names(res)
        assert len(names) == 3  # 2 results + "View more"
        assert names[-1] == "View more"

    def test_non_last_item_alt_enter_matches_view_more_action(self):
        res = main.search(FakeEvent("face"), FakeExtension(search_limit="2"))
        items = res.result_list
        first_alt = items[0].on_alt_enter(None)
        more_enter = items[-1].on_enter(None)
        assert pickle.loads(first_alt._data) == pickle.loads(more_enter._data)

    def test_last_page_items_have_no_alt_enter(self):
        # search_limit larger than the total match count for this query,
        # so there's no next page to wire Alt+Enter to
        res = main.search(FakeEvent("grinning face"), FakeExtension(search_limit="50"))
        items = res.result_list
        assert items
        assert all(item.on_alt_enter(None) is None for item in items)

    def test_select_action_records_and_prepares_clipboard_copy(self):
        res = main.search(FakeEvent("grinning"), FakeExtension())
        item = res.result_list[0]
        record_data, copy_action = select_data(item)

        assert record_data == {"action": "record", "name": "grinning face"}
        assert copy_action.text == "\U0001F600"

    def test_item_enter_event_record_action_persists_and_is_a_no_op_response(self):
        ext = FakeExtension()
        listener = main.ItemEnterEventListener()
        data = {"action": "record", "name": "grinning face"}

        response = listener.on_event(ItemEnterEvent(pickle.dumps(data)), ext)

        assert main.load_recent() == ["grinning face"]
        assert isinstance(response, DoNothingAction)

    def test_shortcode_search_select_still_wired(self):
        # regression guard: on_enter used to be a bare CopyToClipboardAction;
        # this must stay an ActionList([record, copy]) for both search branches
        res = main.search(FakeEvent(":grinning"), FakeExtension())
        items = res.result_list
        assert items
        record_data, copy_action = select_data(items[0])
        assert record_data["action"] == "record"
        assert copy_action.text

    def test_empty_query_shows_recent_after_select(self):
        main.record_recent("grinning face")
        res = main.search(FakeEvent(None), FakeExtension())
        assert item_names(res) == ["Grinning face"]

    def test_display_char_appends_code_to_recent_name(self):
        main.record_recent("grinning face")
        res = main.search(FakeEvent(None), FakeExtension(display_char="yes"))
        assert item_names(res) == ["Grinning face | \U0001F600"]

    def test_recent_entry_missing_from_db_is_skipped(self):
        main.record_recent("this emoji does not exist")
        res = main.search(FakeEvent(None), FakeExtension())
        assert item_names(res) == ["Type in emoji name..."]

    def test_recent_pagination_via_more_event(self):
        ext = FakeExtension(recent_limit="2")
        for name in ["grinning face", "smiling face", "winking face"]:
            main.record_recent(name)

        res = main.search(FakeEvent(None), ext)
        items = res.result_list
        assert item_names(res) == ["Winking face", "Smiling face", "View more"]

        more_data = pickle.loads(items[-1].on_enter(None)._data)
        assert more_data == {"action": "more", "mode": "recent", "offset": 2}

        listener = main.ItemEnterEventListener()
        res2 = listener.on_event(ItemEnterEvent(pickle.dumps(more_data)), ext)
        assert item_names(res2) == ["Grinning face"]
