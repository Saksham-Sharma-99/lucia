from lucia.studio.diff import diff


def test_diff_reports_add_remove_change_with_pointers() -> None:
    before = {"a": 1, "b": {"c": [1, 2]}, "gone": True}
    after = {"a": 2, "b": {"c": [1, 3, 4]}, "new": "x"}
    assert [(d.path, d.op, d.before, d.after) for d in diff(before, after)] == [
        ("/a", "change", 1, 2),
        ("/b/c/1", "change", 2, 3),
        ("/b/c/2", "add", None, 4),
        ("/gone", "remove", True, None),
        ("/new", "add", None, "x"),
    ]


def test_identical_configs_have_no_diff() -> None:
    assert diff({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}) == []
