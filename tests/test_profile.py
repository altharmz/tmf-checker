"""The conformance profile (`--profile`): loading, the `profile` check, and how it changes
`unimplemented`, `requires` and the base create. Each effect proven both ways."""

import pytest

from tests.conftest import probe
from tests.stub import Gaps
from tmf_checker.profile import lacking, load, parse
from tmf_checker.spec import Spec

LIST = "TMF620 GET /productOffering"
PATCH = "TMF620 PATCH /productOffering/{id}"
CREATE = "TMF620 POST /productOffering"
PO = "productOffering"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "maps collection names"),
        ({"nope": {}}, "no such collection"),
        ({PO: {"mandatory": []}}, "keys operations, attributes, create"),
        ({PO: {"operations": ["get"]}}, "unknown operation 'get'"),
        ({PO: {"operations": "list"}}, "must be a list of names"),
        ({PO: {"attributes": ["nope"]}}, "has no attribute 'nope'"),
        ({PO: {"attributes": ["validFor.nope"]}}, "'validFor' has no attribute 'nope'"),
        ({PO: {"attributes": ["validFor.a.b"]}}, "one level in at most"),
        ({PO: {"create": ["nope"]}}, "create body has no attribute 'nope'"),
    ],
)
def test_profile_names_are_checked_against_the_spec(tmf620, data, message):
    with pytest.raises(ValueError, match=message):
        parse(data, tmf620)


def test_profile_without_rules_is_fine(tmf620):
    rules = parse({PO: None}, tmf620).rules["/productOffering"]
    assert rules.operations is None and rules.attributes == () and rules.create == ()


def test_lacking():
    attrs = ("name", "validFor.startDateTime")
    assert lacking({"name": "x"}, attrs) == []  # no validFor: a.b is not judged
    assert lacking({"name": None, "validFor": {}}, attrs) == list(attrs)
    assert lacking({"name": "x", "validFor": [{"startDateTime": "t"}, {}]}, attrs) == [attrs[1]]


# -- the profile check ---------------------------------------------------------------------


def test_mandatory_attributes_present_is_silent(tmf620):
    profile = {PO: {"attributes": ["id", "href", "name", "description"]}}
    lines, _ = probe(tmf620, checks=("profile",), profile=profile)
    assert lines == []


@pytest.mark.parametrize("gaps", [Gaps(drop={"description"}), Gaps(null_unset=("version",))])
def test_mandatory_attribute_lacking_is_a_gap(tmf620, gaps):
    name = next(iter(gaps.drop or gaps.null_unset))
    profile = {PO: {"attributes": ["name", name]}}
    lines, _ = probe(tmf620, gaps, checks=("profile",), profile=profile)
    assert lines == [f"{LIST} profile-missing {name}"]


def test_mandatory_nested_attribute(tmf620):
    profile = {PO: {"attributes": ["validFor.startDateTime"]}}
    end = {"endDateTime": "2030-01-01T00:00:00Z"}
    lines, _ = probe(tmf620, checks=("profile",), profile=profile, validFor=end)
    assert lines == [f"{LIST} profile-missing validFor.startDateTime"]
    both = {**end, "startDateTime": "2026-01-01T00:00:00Z"}
    lines, _ = probe(tmf620, checks=("profile",), profile=profile, validFor=both)
    assert lines == []


def test_profile_reads_what_the_run_created(tmf620):
    checks = ("location", "profile")
    profile = {PO: {"attributes": ["name", "version"], "create": ["version"]}}
    lines, _ = probe(
        tmf620, Gaps(drop={"version"}), checks=checks, writes=True, count=0, profile=profile
    )
    assert lines == [f"{LIST} profile-missing version"]
    lines, _ = probe(tmf620, checks=checks, writes=True, count=0, profile=profile)
    assert lines == []


def test_profile_does_not_judge_what_the_run_left_out(tmf620):
    # the run's base create has no version and a validFor it built: not the server's gap
    profile = {PO: {"attributes": ["name", "version", "validFor.endDateTime"]}}
    checks = ("location", "profile")
    lines, _ = probe(tmf620, checks=checks, writes=True, count=0, profile=profile)
    assert lines == []
    # the same attributes on the user's data are judged
    lines, _ = probe(tmf620, checks=("profile",), profile=profile, validFor={})
    assert lines == [
        f"{LIST} profile-missing validFor.endDateTime",
        f"{LIST} profile-missing version",
    ]


def test_profile_with_no_items_skips(tmf620):
    profile = {PO: {"attributes": ["name"]}}
    lines, _ = probe(tmf620, checks=("profile",), count=0, profile=profile)
    assert lines == [f"{LIST} skipped profile no-items"]


def test_profile_check_needs_a_profile(tmf620):
    with pytest.raises(ValueError, match="--profile"):
        probe(tmf620, checks=("profile",))


def test_profile_check_does_nothing_without_attributes(tmf620):
    lines, _ = probe(tmf620, checks=("profile",), profile={PO: {"operations": ["list"]}})
    assert lines == []


# -- operations ----------------------------------------------------------------------------


def test_unimplemented_optional_operation_is_a_skip(tmf620):
    gaps = Gaps(unimplemented={PO})
    lines, _ = probe(tmf620, gaps, checks=("lists",), profile={PO: {"operations": ["list"]}})
    assert lines == [f"{LIST} unimplemented 404"]
    lines, _ = probe(tmf620, gaps, checks=("lists",), profile={PO: {"operations": ["create"]}})
    assert lines == [f"{LIST} skipped profile optional-operation"]
    lines, _ = probe(tmf620, gaps, checks=("lists",), profile={PO: {}})  # no operations given
    assert lines == [f"{LIST} unimplemented 404"]


def test_unimplemented_optional_patch_is_a_skip(tmf620):
    gaps = Gaps(no_patch=True)
    mandatory = {PO: {"operations": ["list", "create", "patch"]}}
    lines, _ = probe(tmf620, gaps, checks=("patch-formats",), writes=True, profile=mandatory)
    assert f"{PATCH} unimplemented 405" in lines
    optional = {PO: {"operations": ["list", "create"]}}
    lines, _ = probe(tmf620, gaps, checks=("patch-formats",), writes=True, profile=optional)
    assert f"{PATCH} unimplemented 405" not in lines
    assert f"{PATCH} skipped profile optional-operation" in lines


def test_unimplemented_optional_create_is_a_skip(tmf620):
    gaps = Gaps(no_create=True)
    lines, _ = probe(tmf620, gaps, checks=("location",), writes=True)
    assert f"{CREATE} create-status minimal" in lines
    optional = {PO: {"operations": ["list"]}}
    lines, stub = probe(tmf620, gaps, checks=("location",), writes=True, profile=optional)
    assert lines == [f"{CREATE} skipped location optional-operation"]
    assert sum(method == "POST" for method, _ in stub.requests) == 1  # no discovery


# -- create --------------------------------------------------------------------------------


def test_profile_create_attribute_is_not_a_requires_gap(tmf620):
    gaps = Gaps(require={"version"})
    lines, _ = probe(tmf620, gaps, checks=("requires",), writes=True)
    assert f"{CREATE} requires version" in lines
    profile = {PO: {"create": ["version"]}}
    lines, stub = probe(tmf620, gaps, checks=("requires",), writes=True, profile=profile)
    assert lines == []
    assert sum(method == "POST" for method, _ in stub.requests) == 1  # the base, at once


def test_profile_loads_from_yaml(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("productOffering:\n  attributes: [name]\n")
    profile = load(path, Spec.bundled("TMF620", 5))
    assert profile.rules["/productOffering"].attributes == ("name",)
