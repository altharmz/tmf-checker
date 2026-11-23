"""Every check proven both ways against the stub: silent on a conformant server (the
`clean` tests), and each deliberate gap found with its exact line."""

import pytest

from tests.conftest import probe
from tests.stub import Gaps
from tmf_checker.spec import Spec

ALL = (
    "errors",
    "lists",
    "fields",
    "location",
    "requires",
    "roundtrip",
    "polymorphism",
    "patch-formats",
    "patch",
)
PATCH = "TMF620 PATCH /productOffering/{id}"
LIST = "TMF620 GET /productOffering"
ITEM = "TMF620 GET /productOffering/{id}"
CREATE = "TMF620 POST /productOffering"


def gaps_only(lines):
    return [line for line in lines if line.split()[3] not in ("unprobed", "skipped")]


def test_clean_server_has_no_gaps(tmf620):
    lines, stub = probe(tmf620, checks=ALL, writes=True)
    assert gaps_only(lines) == []
    # skips carry a reason: references to other APIs have no fixture yet
    assert f"{CREATE} unprobed agreement no-fixture" in lines


def test_read_only_run_sends_no_writes(tmf620):
    _, stub = probe(tmf620)
    assert {method for method, _ in stub.requests} == {"GET"}


def test_write_checks_need_allow_writes(tmf620):
    with pytest.raises(ValueError, match="--allow-writes"):
        probe(tmf620, checks=("roundtrip",))


# -- read-only checks ----------------------------------------------------------------------

READ_GAPS = [
    (Gaps(unimplemented={"productOffering"}), f"{LIST} unimplemented 404"),
    (Gaps(unknown_id_status=500), f"{ITEM} error-status unknown-id"),
    (Gaps(plain_errors=True), f"{ITEM} error-body unknown-id"),
    (Gaps(wrong_result_count=True), f"{LIST} count-header X-Result-Count"),
    (Gaps(ignore_limit=True), f"{LIST} paging-ignored limit"),
    (Gaps(ignore_offset=True), f"{LIST} paging-ignored offset"),
    (Gaps(ignore_fields=True), f"{LIST} fields-ignored list"),
    (Gaps(ignore_fields=True), f"{ITEM} fields-ignored by-id"),
    (Gaps(drop_selected_field=True), f"{ITEM} fields-dropped by-id"),
    (Gaps(null_unset=("version",)), f"{LIST} null-value version"),
    (Gaps(href="urn"), f"{LIST} href not-a-url"),
    (Gaps(href="other"), f"{LIST} href not-the-item"),
    (Gaps(null_unset=("version",)), f"{ITEM} null-value version"),
]


@pytest.mark.parametrize(
    ("gaps", "line"), READ_GAPS, ids=[g[1].split(" ", 3)[3] for g in READ_GAPS]
)
def test_read_gap_is_found(tmf620, gaps, line):
    lines, _ = probe(tmf620, gaps)
    assert line in lines


def test_bad_date_time_is_found_only_in_v5():
    """v5 seeds carry lastUpdate (spec-quirks #9); v4 ones do not."""
    lines, _ = probe(Spec.bundled("TMF620", 5), Gaps(bad_dates=True))
    assert f"{LIST} invalid lastUpdate format:date-time" in lines
    lines, _ = probe(Spec.bundled("TMF620", 5))
    assert not any("format:date-time" in line for line in lines)


def test_relative_href_and_another_host_are_fine(tmf620):
    """A relative href resolves against the API root; a proxy may report another host."""
    for mode in ("relative", "other-host"):
        lines, _ = probe(tmf620, Gaps(href=mode))
        assert not any(" href " in line for line in lines), mode


def test_paging_needs_two_items(tmf620):
    lines, _ = probe(tmf620, Gaps(ignore_limit=True), count=1)
    assert f"{LIST} skipped paging fewer-than-2-items" in lines
    assert not any("paging-ignored" in line for line in lines)


def test_fields_needs_an_item(tmf620):
    lines, _ = probe(tmf620, count=0)
    assert f"{LIST} skipped fields no-items" in lines


def test_unknown_id_is_shaped_like_a_real_one(tmf620):
    _, stub = probe(tmf620, checks=("errors",))
    known = list(stub.store["productOffering"])
    unknown = [path for method, path in stub.requests if "-unknown-" in path]
    assert unknown and unknown[0].split("/")[-1].startswith(known[0])


def test_malformed_json_needs_writes_and_is_checked(tmf620):
    _, stub = probe(tmf620, Gaps(malformed_status=500), checks=("errors",))
    assert not any(method == "POST" for method, _ in stub.requests)
    lines, _ = probe(tmf620, Gaps(malformed_status=500), checks=("errors",), writes=True)
    assert f"{CREATE} error-status malformed-json" in lines


def test_missing_is_opt_in_and_needs_the_data(tmf620):
    lines, _ = probe(tmf620)
    assert not any(" missing " in line for line in lines)
    lines, _ = probe(tmf620, checks=("missing",))
    assert f"{ITEM} missing isBundle" in lines
    lines, _ = probe(tmf620, checks=("missing",), isBundle=True)
    assert f"{ITEM} missing isBundle" not in lines


def test_missing_looks_one_level_in(tmf620):
    period = {"startDateTime": "2026-01-01T00:00:00Z"}
    lines, _ = probe(tmf620, checks=("missing",), validFor=period)
    assert f"{ITEM} missing validFor.endDateTime" in lines
    assert f"{ITEM} missing validFor.startDateTime" not in lines


# -- write checks --------------------------------------------------------------------------

WRITE_GAPS = [
    (Gaps(no_location=True), f"{CREATE} location missing"),
    (Gaps(wrong_location=True), f"{CREATE} location not-href"),
    (Gaps(create_status=200), f"{CREATE} create-status minimal"),
    (Gaps(require={"description"}), f"{CREATE} requires description"),
    (Gaps(refuse={"validFor"}), f"{CREATE} refused validFor"),
    (Gaps(drop={"description"}), f"{CREATE} dropped description"),
    (Gaps(rewrite={"isBundle": False}), f"{CREATE} rewritten isBundle"),
    (
        Gaps(rewrite={"validFor": {"startDateTime": "2020-01-01T00:00:00Z"}}),
        f"{CREATE} rewritten validFor.startDateTime",
    ),
    (Gaps(no_delete=True), "TMF620 DELETE /productOffering/{id} cleanup-failed delete-refused"),
]


@pytest.mark.parametrize(
    ("gaps", "line"), WRITE_GAPS, ids=[g[1].split(" ", 3)[3] for g in WRITE_GAPS]
)
def test_write_gap_is_found(tmf620, gaps, line):
    lines, _ = probe(tmf620, gaps, checks=("location", "roundtrip"), writes=True)
    assert line in lines


def test_requires_names_each_culprit_and_the_roundtrip_goes_on(tmf620):
    """The server requires two optional attributes: both are named, and the roundtrip
    runs on the server's minimal body, so a dropped attribute is still found."""
    gaps = Gaps(require={"description", "isBundle"}, drop={"version"})
    lines, _ = probe(tmf620, gaps, checks=("roundtrip",), writes=True)
    assert f"{CREATE} requires description" in lines
    assert f"{CREATE} requires isBundle" in lines
    assert f"{CREATE} create-status minimal" not in lines
    assert f"{CREATE} dropped version" in lines


def test_requires_with_a_refused_attribute_in_the_full_body(tmf620):
    """The all-attributes body is refused because of one poison attribute: discovery
    drops it and still finds the culprit."""
    gaps = Gaps(require={"description"}, refuse={"validFor"})
    lines, _ = probe(tmf620, gaps, checks=("requires",), writes=True)
    assert f"{CREATE} requires description" in lines


def test_requires_jointly_is_not_blamed_on_one(tmf620):
    """Two attributes required only together: removing either is refused, so both are
    culprits; nothing is reported for a conformant server."""
    gaps = Gaps(require_together={"description", "version"})
    lines, _ = probe(tmf620, gaps, checks=("requires",), writes=True)
    assert {f"{CREATE} requires description", f"{CREATE} requires version"} <= set(lines)
    lines, _ = probe(tmf620, checks=("requires",), writes=True)
    assert not any(" requires " in line for line in lines)


def test_nested_attributes_are_probed_one_level_in(tmf620):
    lines, _ = probe(
        tmf620, Gaps(refuse={"prodSpecCharValueUse"}), checks=("roundtrip",), writes=True
    )
    assert f"{CREATE} refused prodSpecCharValueUse" in lines
    lines, _ = probe(tmf620, checks=("roundtrip",), writes=True)
    nested = [line for line in lines if " prodSpecCharValueUse." in line]
    # every nested property left out of the generated value is probed or explained
    assert all(" unprobed " in line for line in nested)


PATCH_GAPS = [
    (
        Gaps(refuse_patch_types={"application/merge-patch+json"}),
        f"{PATCH} content-type application/merge-patch+json",
    ),
    (Gaps(no_patch=True), f"{PATCH} unimplemented 405"),
    (Gaps(read_only={"description"}), f"{PATCH} read-only description"),
    (Gaps(patch_drop={"version"}), f"{PATCH} dropped version"),
    (Gaps(ignore_json_patch=True), f"{PATCH} content-type application/json-patch+json ignored"),
    (Gaps(refuse_base_type=True), f"{CREATE} refused @baseType"),
    (Gaps(drop={"@baseType"}), f"{CREATE} dropped @baseType"),
]


@pytest.mark.parametrize(
    ("gaps", "line"), PATCH_GAPS, ids=[g[1].split(" ", 3)[3] for g in PATCH_GAPS]
)
def test_patch_and_polymorphism_gap_is_found(gaps, line):
    spec = Spec.bundled("TMF620", 5)  # four PATCH content types
    lines, _ = probe(spec, gaps, checks=("polymorphism", "patch-formats", "patch"), writes=True)
    assert line in lines


def test_v4_patch_uses_its_one_content_type():
    lines, stub = probe(Spec.bundled("TMF620", 4), checks=("patch-formats",), writes=True)
    assert gaps_only(lines) == []
    assert sum(method == "PATCH" for method, _ in stub.requests) == 1


def test_state_is_not_patched():
    lines, _ = probe(Spec.bundled("TMF637", 5), checks=("patch",), writes=True, resource="product")
    assert "TMF620 PATCH /product/{id} unprobed status state-machine" in lines


def test_orders_need_allow_orders():
    spec = Spec.bundled("TMF622", 5)
    fixtures = {"ProductOffering": {"id": "o1", "href": "/o/1"}, "BillingAccount": {"id": "b1"}}
    lines, stub = probe(spec, checks=("roundtrip",), writes=True, resource="productOrder", count=0)
    assert "TMF620 POST /productOrder skipped roundtrip orders-not-allowed" in lines
    assert not any(method == "POST" for method, _ in stub.requests)
    lines, stub = probe(
        spec,
        checks=("roundtrip",),
        writes=True,
        resource="productOrder",
        orders=True,
        fixtures=fixtures,
        count=0,
    )
    assert any(method == "POST" for method, _ in stub.requests)
    assert gaps_only(lines) == []


def test_everything_created_is_deleted(tmf620):
    _, stub = probe(tmf620, checks=ALL, writes=True)
    seeded = {k: v for k, v in stub.store.items() if v}
    assert list(seeded) == ["productOffering"] and len(seeded["productOffering"]) == 2


def test_references_point_at_created_fixtures(tmf620):
    _, stub = probe(tmf620, checks=("roundtrip",), writes=True)
    posts = [path for method, path in stub.requests if method == "POST"]
    assert "/api/productSpecification" in posts  # the fixture for productSpecification


def test_server_set_and_polymorphism_attributes_are_not_probed():
    lines, _ = probe(
        Spec.bundled("TMF620", 5),
        Gaps(drop={"lastUpdate", "@baseType"}),
        checks=("roundtrip",),
        writes=True,
    )
    assert not any("lastUpdate" in line or "@baseType" in line for line in lines)


def test_unauthorized_stops_the_run_and_credentials_are_redacted(tmf620):
    from tmf_checker.checks import Unauthorized

    with pytest.raises(Unauthorized):
        probe(tmf620, Gaps(cookie="session=s3cret"))
    lines, stub = probe(
        tmf620,
        Gaps(cookie="session=s3cret", ignore_limit=True),
        headers={"Cookie": "session=s3cret"},
    )
    assert f"{LIST} paging-ignored limit" in lines


def test_forbidden_is_a_skip_never_a_gap(tmf620):
    lines, _ = probe(tmf620, Gaps(forbidden={"productOffering"}), checks=ALL, writes=True)
    assert gaps_only(lines) == []
    assert f"{LIST} skipped lists forbidden" in lines
    assert f"{LIST} skipped errors forbidden" in lines
    assert f"{CREATE} skipped roundtrip forbidden" in lines


def test_cleanup_retries_what_a_reference_blocked(tmf620):
    """A delete refused because another created resource still referenced it succeeds on
    the second pass, and is not reported."""
    from tests.stub import serve
    from tmf_checker import runner
    from tmf_checker.checks import Context
    from tmf_checker.client import Client

    with serve(tmf620) as stub:
        ctx = Context("TMF620", tmf620, Client(stub.base_url), "t", allow_writes=True)
        spec_res = {r.collection: r for r in tmf620.resources()}
        parent = stub.add("category", {"name": "p"})
        child = stub.add("productOffering", {"name": "c", "category": [{"id": parent["id"]}]})
        # newest first would delete the category first: the stub refuses while referenced
        ctx.created += [
            (spec_res["/productOffering"], child["id"]),
            (spec_res["/category"], parent["id"]),
        ]
        stub.gaps.refuse_referenced_delete = True
        lines = [f.line for f in runner.create.cleanup(ctx)]
        assert lines == [] and not stub.store["category"] and not stub.store["productOffering"]


def test_requires_with_several_poisons_uses_the_named_attributes(tmf620):
    """Two required attributes and two refused ones: no all-but-one body is accepted, but
    the refusal names the culprits, and removal proves each."""
    gaps = Gaps(
        require_together={"description", "version"},
        refuse={"validFor", "isBundle"},
        name_missing=True,
    )
    lines, _ = probe(tmf620, gaps, checks=("requires",), writes=True)
    assert {f"{CREATE} requires description", f"{CREATE} requires version"} <= set(lines)
    assert f"{CREATE} create-status minimal" not in lines


def test_error_keys_are_not_attribute_names():
    """`status` is both an Error key and a Product attribute: only the error's words
    count when picking the attributes a refusal names."""
    from tmf_checker.checks.create import _error_text
    from tmf_checker.client import Response

    answer = Response(
        "POST", "u", 422, {}, b'{"code":"422","status":"422","message":"name: missing"}'
    )
    assert _error_text(answer) == "name: missing"


def test_a_server_may_refuse_a_patch_that_changes_nothing():
    """patch-formats changes something, and patch skips a value equal to the current one,
    so a server that refuses no-op PATCHes shows no gap."""
    spec = Spec.bundled("TMF620", 5)
    lines, _ = probe(
        spec, Gaps(refuse_noop_patch=True), checks=("patch-formats", "patch"), writes=True
    )
    assert gaps_only(lines) == []


def test_missing_counts_what_the_roundtrip_created(tmf620):
    """No seed has isBundle, but the roundtrip sends it and the server keeps it: not
    missing. A server that drops it: dropped, once."""
    lines, _ = probe(tmf620, checks=("missing", "roundtrip"), writes=True)
    assert f"{ITEM} missing isBundle" not in lines
    lines, _ = probe(tmf620, Gaps(drop={"isBundle"}), checks=("missing", "roundtrip"), writes=True)
    # dropped is the evidence; missing does not report the same absence twice
    assert f"{CREATE} dropped isBundle" in lines and f"{ITEM} missing isBundle" not in lines


def test_a_refused_made_up_free_string_is_unprobed_not_refused():
    """TMF620 v5 version has no example: the placeholder is sent. Its refusal may be a
    vocabulary, so it is unprobed; a preferred value from the fixtures is probed."""
    spec = Spec.bundled("TMF637", 5)
    lines, _ = probe(
        spec,
        Gaps(refuse={"productSerialNumber"}),
        checks=("roundtrip",),
        writes=True,
        resource="product",
    )
    serial = [line for line in lines if "productSerialNumber" in line]
    assert serial == ["TMF620 POST /product refused productSerialNumber"]  # example "N/A"
    lines, _ = probe(
        Spec.bundled("TMF620", 4), Gaps(refuse={"version"}), checks=("roundtrip",), writes=True
    )
    assert f"{CREATE} unprobed version made-up-value" in lines
    assert f"{CREATE} refused version" not in lines


def test_a_patch_conflict_is_unprobed_not_read_only():
    lines, _ = probe(
        Spec.bundled("TMF620", 5),
        Gaps(patch_conflict={"description"}),
        checks=("patch",),
        writes=True,
    )
    assert f"{PATCH} unprobed description conflict" in lines
    assert f"{PATCH} read-only description" not in lines


def test_references_compare_by_id():
    """A server may refresh a reference's name or href; only a different id is a rewrite."""
    from tmf_checker.checks.create import diff

    sent = [{"id": "1", "href": "/c/1", "name": "old", "@referredType": "Category"}]
    assert diff(sent, [{"id": "1", "href": "https://h/c/1", "name": "new"}], "category") is None
    assert diff(sent, [{"id": "2", "name": "old"}], "category") == ("rewritten", "category[].id")


def test_a_create_conflict_is_unprobed_not_refused(tmf620):
    lines, _ = probe(tmf620, Gaps(conflict={"version"}), checks=("roundtrip",), writes=True)
    assert f"{CREATE} unprobed version conflict" in lines
    assert f"{CREATE} refused version" not in lines


def test_own_classes_are_created_not_taken_from_fixtures(tmf620):
    """A fixture of a class this API creates is not linked to: the run makes its own, so
    the user's resource is never changed by what the run creates."""
    fixtures = {"ProductSpecification": {"id": "users-own", "href": "/x"}}
    _, stub = probe(tmf620, checks=("roundtrip",), writes=True, fixtures=fixtures)
    sent = [path for method, path in stub.requests if method == "POST"]
    assert "/api/productSpecification" in sent


def test_scoped_null_fixture_falls_back_to_the_next_class():
    from tmf_checker.checks import Context
    from tmf_checker.checks.create import values
    from tmf_checker.client import Client

    spec = Spec.bundled("TMF666", 5)
    fixtures = {
        "PartyRole": {"id": "cust"},
        "Party": {"id": "ind"},
        "FinancialAccount.PartyRole": None,
    }
    ctx = Context(
        "TMF666", spec, Client("http://127.0.0.1:9"), "t", allow_writes=True, fixtures=fixtures
    )
    res = {r.schema: r for r in spec.resources()}
    with values(ctx).scope("FinancialAccount"):
        owner = values(ctx).minimal(spec.request_schema(res["FinancialAccount"].op("POST")))
    with values(ctx).scope("BillingAccount"):
        cust = values(ctx).minimal(spec.request_schema(res["BillingAccount"].op("POST")))
    assert owner["relatedParty"][0]["partyOrPartyRole"]["@type"] == "PartyRef"
    assert cust["relatedParty"][0]["partyOrPartyRole"]["@type"] == "PartyRoleRef"


def test_missing_does_not_look_into_references_or_unsent_attributes(tmf620):
    """A returned reference lacks most fields of what it refers to: not missing. An
    attribute the roundtrip could not send (no fixture) is not missing either."""
    ref = {"id": "s1", "href": "/s/1"}
    lines, _ = probe(tmf620, checks=("missing", "roundtrip"), writes=True, productSpecification=ref)
    assert not any("missing productSpecification." in line for line in lines)
    assert f"{ITEM} missing agreement" not in lines  # unprobed: no fixture


def test_a_refused_attribute_the_server_sets_is_still_read_one_level_in(tmf620):
    """Like an account balance: refused from clients, filled in by the server, and
    the server's value lacks a nested attribute: missing validFor.endDateTime."""
    gaps = Gaps(
        refuse={"validFor"}, server_sets={"validFor": {"startDateTime": "2026-01-01T00:00:00Z"}}
    )
    lines, _ = probe(tmf620, gaps, checks=("missing", "roundtrip"), writes=True)
    assert f"{CREATE} refused validFor" in lines
    assert f"{ITEM} missing validFor.endDateTime" in lines


def test_missing_ignores_leftovers_of_earlier_runs(tmf620):
    """A resource an earlier run could not delete carries made-up values: not sampled."""
    lines, _ = probe(tmf620, checks=("missing",), count=1, name="tmf-checker-old-1")
    assert f"{ITEM} skipped missing no-items" in lines


def test_required_object_attributes_are_probed_one_level_in():
    """TMF622 productOrderItem is required, so it is in the base body; its optional
    properties are probed (or explained) like those of an optional attribute."""
    spec = Spec.bundled("TMF622", 5)
    fixtures = {"ProductOffering": {"id": "o1", "href": "/o/1"}, "BillingAccount": {"id": "b1"}}
    lines, _ = probe(
        spec,
        checks=("roundtrip",),
        writes=True,
        resource="productOrder",
        orders=True,
        fixtures=fixtures,
        count=0,
    )
    nested = [line for line in lines if " productOrderItem." in line]
    assert nested and all(" unprobed " in line for line in nested)
    assert "TMF620 POST /productOrder unprobed productOrderItem.state server-managed" in lines
