"""Generated values conform to the spec, and references are never made up."""

import pytest

from tmf_checker.spec import Spec
from tmf_checker.validate import errors
from tmf_checker.values import Unbuildable, Values

FOUND = {"id": "42", "href": "https://x/42", "name": "n"}


def _create(spec, collection="/productOffering"):
    resource = next(r for r in spec.resources() if r.collection == collection)
    return spec.request_schema(resource.op("POST"))


@pytest.mark.parametrize("major", [4, 5])
@pytest.mark.parametrize("collection", ["/productOffering", "/category", "/productSpecification"])
def test_minimal_body_conforms_to_the_create_schema(major, collection):
    spec = Spec.bundled("TMF620", major)
    schema = _create(spec, collection)
    body = Values(spec, "r1").minimal(schema)
    name = schema["$ref"].rsplit("/", 1)[-1]
    assert errors(spec, name, body) == []
    assert set(body) == spec.required(schema)


def test_v5_minimal_body_has_type_and_quirk_9_attributes():
    body = Values(Spec.bundled("TMF620", 5), "r1").minimal(_create(Spec.bundled("TMF620", 5)))
    assert body["@type"] == "ProductOffering"
    assert {"lastUpdate", "lifecycleStatus"} <= set(body)
    assert body["name"].startswith("tmf-checker-r1-")


@pytest.mark.parametrize("major", [4, 5])
def test_a_period_ends_after_it_starts(major):
    spec = Spec.bundled("TMF620", major)
    period = Values(spec, "r1").value(spec.properties(_create(spec))["validFor"], "validFor")
    assert period["endDateTime"] > period["startDateTime"]


@pytest.mark.parametrize("major", [4, 5])
def test_references_use_the_fixture_of_the_longest_matching_class(major):
    spec = Spec.bundled("TMF620", major)
    asked = []
    values = Values(spec, "r1", refs=lambda c: asked.append(c) or FOUND)
    props = spec.properties(_create(spec))
    price = values.value(props["productOfferingPrice"], "productOfferingPrice")[0]
    assert asked[-1] == "ProductOfferingPrice"  # not ProductOffering
    assert price["id"] == "42"
    bundled = values.value(props["bundledProductOffering"], "bundledProductOffering")[0]
    assert asked[-1] == "ProductOffering" and bundled["id"] == "42"


@pytest.mark.parametrize(
    ("major", "collection", "attr"),
    [
        (4, "/catalog", "relatedParty"),  # v4 RelatedParty: a reference without "Ref"
        (5, "/productOffering", "agreement"),  # another API
        (4, "/category", "parentId"),  # a plain id string
    ],
)
def test_unbuildable_references_say_why(major, collection, attr):
    spec = Spec.bundled("TMF620", major)
    schema = spec.properties(_create(spec, collection))[attr]
    with pytest.raises(Unbuildable, match=f"no-fixture {attr}"):
        Values(spec, "r1", refs=lambda c: FOUND).value(schema, attr)


def test_enum_values_are_stripped():
    """TMF637 v5 ProductStatusType ends with 'aborted ' (spec-quirks #5); the first value
    is used, stripped."""
    spec = Spec.bundled("TMF637", 5)
    value = Values(spec, "r1").value({"$ref": "#/components/schemas/ProductStatusType"})
    assert value == value.strip()


def test_free_strings_use_the_value_the_spec_examples_use():
    """lifecycleStatus is a free string; TMF620 v5's examples say Active. A made-up value
    would test the server's vocabulary, not whether it stores the attribute."""
    spec = Spec.bundled("TMF620", 5)
    body = Values(spec, "r1").minimal(_create(spec))
    assert body["lifecycleStatus"] == "Active"
    assert body["name"].startswith("tmf-checker-r1-")  # our marker, not an example's name
    price = Values(spec, "r1").minimal(_create(spec, "/productOfferingPrice"))
    assert price["priceType"] == "recurring"


def test_preferred_values_win_for_scalars_only():
    """`values:` in the fixtures file: a server's vocabulary (role: customer)."""
    spec = Spec.bundled("TMF666", 5)
    found = {"id": "c1", "@referredType": "Customer"}
    values = Values(
        spec,
        "r1",
        refs=lambda c: found,
        extra_classes={"PartyRole": found},
        preferred={"role": "customer"},
    )
    body = values.minimal(_create(spec, "/billingAccount"))
    party = body["relatedParty"][0]
    assert party["role"] == "customer"
    assert party["partyOrPartyRole"]["@type"] == "PartyRoleRef"
    assert party["partyOrPartyRole"]["@referredType"] == "Customer"


def test_a_nested_merge_value_is_completed_as_its_full_value_object():
    spec = Spec.bundled("TMF622", 5)
    resource = next(r for r in spec.resources() if r.collection == "/productOrder")
    mvo = spec.request_schema(resource.op("PATCH", item=True))
    external = Values(spec, "r1").value(spec.properties(mvo)["externalId"], "externalId")[0]
    assert "id" in external  # ExternalIdentifier_FVO requires it; _MVO does not
    again = Values(spec, "r1")
    first = again.value(spec.properties(mvo)["externalId"], "externalId")[0]["id"]
    assert first != again.value(spec.properties(mvo)["externalId"], "externalId")[0]["id"]
    assert "id" not in Values(spec, "r1").minimal(mvo)  # the top level stays minimal


def test_names_are_unique_per_value():
    spec = Spec.bundled("TMF620", 5)
    values = Values(spec, "r1")
    assert values.minimal(_create(spec))["name"] != values.minimal(_create(spec))["name"]


def test_class_scoped_preferred_values():
    spec = Spec.bundled("TMF666", 5)
    found = {"id": "c1"}
    values = Values(
        spec,
        "r1",
        refs=lambda c: found,
        extra_classes={"PartyRole": found},
        preferred={"role": "customer", "FinancialAccount.role": "owner"},
    )
    with values.scope("FinancialAccount"):
        owner = values.minimal(_create(spec, "/financialAccount"))
    with values.scope("BillingAccount"):
        customer = values.minimal(_create(spec, "/billingAccount"))
    assert owner["relatedParty"][0]["role"] == "owner"
    assert customer["relatedParty"][0]["role"] == "customer"
