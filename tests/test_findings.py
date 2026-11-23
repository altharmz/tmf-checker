import pytest

from tmf_checker.findings import Finding, compare, read_baseline, unique_sorted, updated_baseline


def f(kind="dropped", detail="validFor", path="/productOffering"):
    return Finding("TMF620", "POST", path, kind, detail)


def test_line_format():
    assert f().line == "TMF620 POST /productOffering dropped validFor"


def test_unknown_kind_and_multiline_detail_are_rejected():
    with pytest.raises(ValueError, match="kind"):
        f(kind="oops")
    with pytest.raises(ValueError, match="one line"):
        f(detail="a\nb")
    with pytest.raises(ValueError, match="one line"):
        f(detail="")


def test_evidence_does_not_change_identity():
    a = Finding("TMF620", "GET", "/x", "missing", "a", {"status": 200})
    b = Finding("TMF620", "GET", "/x", "missing", "a", {"status": 500})
    assert a == b
    assert len(unique_sorted([b, a])) == 1


def test_unique_sorted_orders_by_line():
    lines = [x.line for x in unique_sorted([f(detail="z"), f(detail="a"), f(detail="a")])]
    assert lines == sorted(set(lines)) and len(lines) == 2


def test_skips_are_not_gaps():
    assert f(kind="skipped", detail="paging fewer-than-2-items").is_skip
    assert not f().is_skip


BASELINE = """# accepted gaps
TMF620 POST /a dropped x

# reason: the store cannot keep y
TMF620 POST /c dropped y
"""


def test_baseline_ignores_comments_and_blanks(tmp_path):
    path = tmp_path / "b.txt"
    path.write_text(BASELINE)
    assert read_baseline(path) == {"TMF620 POST /a dropped x", "TMF620 POST /c dropped y"}


def test_compare_new_and_fixed():
    result = compare(
        ["TMF620 POST /a dropped x", "TMF620 POST /b new z"],
        {"TMF620 POST /a dropped x", "TMF620 POST /c dropped y"},
    )
    assert result.new == ["TMF620 POST /b new z"]
    assert result.fixed == ["TMF620 POST /c dropped y"]


def test_update_keeps_comments_removes_fixed_inserts_sorted():
    out = updated_baseline(BASELINE, ["TMF620 POST /c dropped y", "TMF620 POST /b dropped z"])
    assert out == (
        "# accepted gaps\n\n"
        "TMF620 POST /b dropped z\n"
        "# reason: the store cannot keep y\n"
        "TMF620 POST /c dropped y\n"
    )


def test_update_appends_after_the_last_gap():
    out = updated_baseline(
        "# head\nTMF620 POST /a dropped x\n", ["TMF620 POST /a dropped x", "TMF620 POST /z x y"]
    )
    assert out == "# head\nTMF620 POST /a dropped x\nTMF620 POST /z x y\n"


def test_update_from_nothing():
    assert updated_baseline("", ["b", "a"]) == "a\nb\n"
