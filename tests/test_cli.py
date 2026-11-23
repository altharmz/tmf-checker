import json

import pytest

from tmf_checker import __version__
from tmf_checker.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_specs_lists_every_bundled_spec(capsys):
    assert main(["specs"]) == 0
    out = capsys.readouterr().out
    assert "TMF620  v4" in out and "TMF678  v5" in out


def test_operations(capsys):
    assert main(["operations", "--api", "tmf622", "--major", "4"]) == 0
    out = capsys.readouterr().out
    assert "/tmf-api/productOrderingManagement/v4/" in out
    assert "POST   /productOrder" in out


def test_validate_ok_and_problems(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"@type": "Error", "code": "404", "reason": "Not Found"}))
    assert main(["validate", "--api", "TMF620", "--schema", "Error", str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"@type": "Error", "code": "404"}))
    assert main(["validate", "--api", "TMF620", "--schema", "Error", str(bad)]) == 1
    assert "reason" in capsys.readouterr().out


def test_unknown_api_is_exit_2(tmp_path, capsys):
    body = tmp_path / "b.json"
    body.write_text("{}")
    assert main(["validate", "--api", "TMF999", "--schema", "Error", str(body)]) == 2
    assert "no bundled spec" in capsys.readouterr().err


# -- run -----------------------------------------------------------------------------------

from tests.conftest import seed  # noqa: E402
from tests.stub import Gaps, serve  # noqa: E402
from tmf_checker.spec import Spec  # noqa: E402

GAP = "TMF620 GET /productOffering paging-ignored limit"


def _run(capsys, gaps=None, *args):
    with serve(Spec.bundled("TMF620", 5), gaps) as stub:
        seed(stub, "productOffering", 2)
        code = main(
            [
                "run",
                "--api",
                "TMF620",
                "--base-url",
                stub.base_url,
                "--resource",
                "productOffering",
                *args,
            ]
        )
    out, err = capsys.readouterr()
    return code, out, err


def test_run_clean_is_exit_0(capsys):
    code, out, err = _run(capsys)
    assert code == 0 and out == "" and "0 gap(s)" in err


def test_run_gap_is_exit_1_with_the_line(capsys, tmp_path):
    report = tmp_path / "r.json"
    code, out, _ = _run(capsys, Gaps(ignore_limit=True), "--json", str(report))
    assert code == 1 and out == GAP + "\n"
    doc = json.loads(report.read_text())
    assert doc["findings"][0]["line"] == GAP
    assert doc["findings"][0]["evidence"]["status"] == 200


def test_run_baseline_locks_gaps(capsys, tmp_path):
    baseline = tmp_path / "gaps.txt"
    baseline.write_text("# known: the store pages itself\n")
    code, _, err = _run(capsys, Gaps(ignore_limit=True), "--baseline", str(baseline))
    assert code == 1 and f"new:   {GAP}" in err
    code, _, _ = _run(
        capsys, Gaps(ignore_limit=True), "--baseline", str(baseline), "--update-baseline"
    )
    assert code == 0
    assert baseline.read_text() == f"# known: the store pages itself\n{GAP}\n"
    code, _, _ = _run(capsys, Gaps(ignore_limit=True), "--baseline", str(baseline))
    assert code == 0
    code, _, err = _run(capsys, None, "--baseline", str(baseline))
    assert code == 0 and f"fixed: {GAP}" in err


def test_run_unauthorized_is_exit_2(capsys):
    code, _, err = _run(capsys, Gaps(cookie="s=1"))
    assert code == 2 and "401" in err and "--header" in err
    code, _, _ = _run(capsys, Gaps(cookie="s=1"), "--header", "Cookie: s=1")
    assert code == 0


def test_run_bad_header_and_write_check_are_exit_2(capsys):
    assert _run(capsys, None, "--header", "no-colon")[0] == 2
    code, _, err = _run(capsys, None, "--checks", "roundtrip")
    assert code == 2 and "--allow-writes" in err


def test_run_unreachable_is_exit_2(capsys):
    code = main(["run", "--api", "TMF620", "--base-url", "http://127.0.0.1:9", "--timeout", "2"])
    assert code == 2 and "cannot reach" in capsys.readouterr().err


def test_run_html_report_escapes_server_text(capsys, tmp_path):
    page = tmp_path / "r.html"
    gaps = Gaps(ignore_limit=True, plain_errors=True)
    code, _, _ = _run(capsys, gaps, "--html", str(page))
    html = page.read_text()
    assert code == 1 and html.startswith("<!doctype html>")
    assert "paging-ignored" in html and "Not a TM Forum conformance certification" in html


def test_html_escapes_evidence():
    from tmf_checker.findings import Finding
    from tmf_checker.report import as_html

    evil = Finding(
        "TMF620", "GET", "/x", "invalid", "a type", {"response_body": "<script>x</script>"}
    )
    html = as_html([evil], {"api": "TMF620"})
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_fixtures_file_is_validated(capsys, tmp_path):
    bad = tmp_path / "f.yaml"
    bad.write_text("Party: {name: no-id}\n")
    code, _, err = _run(capsys, None, "--fixtures", str(bad))
    assert code == 2 and "needs a string 'id'" in err


def test_allow_orders_needs_allow_writes(capsys):
    code, _, err = _run(capsys, None, "--allow-orders")
    assert code == 2 and "--allow-writes" in err


def test_profile_adds_the_profile_check(capsys, tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("productOffering:\n  attributes: [name, version]\n")
    code, out, _ = _run(capsys, None, "--profile", str(path))
    assert code == 1 and out == "TMF620 GET /productOffering profile-missing version\n"


def test_profile_file_is_validated(capsys, tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("productOffering:\n  attributes: [nope]\n")
    code, _, err = _run(capsys, None, "--profile", str(path))
    assert code == 2 and "has no attribute 'nope'" in err
