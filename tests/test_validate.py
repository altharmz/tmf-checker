"""The validator itself: it must resolve allOf and honour discriminators.

Proven on TMF620 v5 ProductOfferingPriceRefOrValue - a oneOf of ProductOfferingPrice (only
`@type` required) and ProductOfferingPriceRef (`@type` and `id` required). A plain reference
satisfies both branches, so only the discriminator can pick one.
"""

import jsonschema
import pytest
from openapi_schema_validator import OAS30Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

from tmf_checker.spec import BUNDLED, Spec
from tmf_checker.validate import errors

REF = {"@type": "ProductOfferingPriceRef", "id": "42", "href": "/x/42", "name": "Monthly"}
VALUE = {
    "@type": "ProductOfferingPrice",
    "name": "Monthly",
    "priceType": "recurring",
    "price": {"unit": "USD", "value": 19.99},
}


def _tmf620() -> Spec:
    return Spec.bundled("TMF620", 5)


def _errors(instance) -> list[str]:
    return errors(_tmf620(), "ProductOfferingPriceRefOrValue", instance)


def test_discriminator_accepts_a_ref_and_a_value():
    assert _errors(REF) == []
    assert _errors(VALUE) == []


def test_plain_jsonschema_cannot_validate_the_same_ref():
    """Why an OAS-aware validator is needed: without the discriminator, oneOf is ambiguous."""
    schema = {"$ref": "#/components/schemas/ProductOfferingPriceRefOrValue", **_tmf620().doc}
    found = [e.message for e in jsonschema.Draft4Validator(schema).iter_errors(REF)]
    assert len(found) == 1
    assert "valid under each of" in found[0]


def test_library_discriminator_handling_recurses_on_tmf_schemas():
    """Why TmfValidator overrides it: upstream dispatches on the self-mapping discriminator
    next to allOf and never returns."""
    registry = Registry().with_resource(
        "urn:x", Resource(contents=_tmf620().doc, specification=DRAFT4)
    )
    upstream = OAS30Validator({"$ref": "urn:x#/components/schemas/Error"}, registry=registry)
    with pytest.raises(RecursionError):
        list(upstream.iter_errors({"@type": "Error", "code": "404", "reason": "Not Found"}))


def test_discriminator_picks_the_branch_named_by_type():
    # Without `id` this would still be a valid ProductOfferingPrice (which requires only
    # @type) - it is rejected because @type selects the Ref branch, where id is mandatory.
    no_id = {k: v for k, v in REF.items() if k != "id"}
    assert any("'id' is a required property" in e for e in _errors(no_id))


def test_missing_discriminator_property_is_rejected():
    no_type = {k: v for k, v in REF.items() if k != "@type"}
    assert any("@type" in e for e in _errors(no_type))


def test_unknown_discriminator_value_is_rejected():
    assert _errors({**REF, "@type": "NoSuchThing"}) != []
    assert _errors({**REF, "@type": "NoSuchThing", "@baseType": "AlsoUnknown"}) != []
    assert _errors({**REF, "@type": ["ProductOfferingPriceRef"]}) != []  # not a crash


def test_extension_subtype_is_validated_as_its_base_type():
    """TMF630 extension pattern: a vendor subclass keeps its own @type and names the class it
    extends in @baseType. It conforms when it conforms to the base branch."""
    subtype = {**REF, "@type": "AcmePriceRef", "@baseType": "ProductOfferingPriceRef"}
    assert _errors(subtype) == []
    # ...and is still held to the base branch: a Ref without `id` is rejected.
    no_id = {k: v for k, v in subtype.items() if k != "id"}
    assert any("'id' is a required property" in e for e in _errors(no_id))


def test_allof_is_resolved_down_to_nested_money():
    # price -> Money.value is declared three $ref/allOf levels below the oneOf branch
    broken = {**VALUE, "price": {"unit": "USD", "value": "19.99"}}
    assert any(e.startswith("price/value:") and "number" in e for e in _errors(broken))


def test_wrong_type_in_an_inherited_property_is_rejected():
    # `href` comes from the Entity base schema via allOf
    assert any(e.startswith("href:") for e in _errors({**VALUE, "href": 5}))


def test_fields_projection_waives_only_omitted_top_level_required_fields():
    tmf637 = Spec.bundled("TMF637", 5)
    body = {"@type": "Product"}
    broken = {"@type": "Product", "productPrice": [{"@type": "ProductPrice", "price": {}}]}
    assert any(
        "productPrice/0/price" in e and "@type" in e
        for e in errors(tmf637, "Product", broken, partial=True)
    )
    assert errors(tmf637, "Product", body, partial=True) == []


def test_v4_swagger_schemas_validate():
    tmf620 = Spec.bundled("TMF620", 4)
    ok = {"id": "1", "name": "Gold", "lifecycleStatus": "Active"}
    assert errors(tmf620, "ProductOffering", ok) == []
    assert any(e.startswith("name:") for e in errors(tmf620, "ProductOffering", {"name": 5}))


def test_unknown_schema_is_a_key_error():
    with pytest.raises(KeyError, match="no schema named"):
        errors(_tmf620(), "NoSuchSchema", {})


@pytest.mark.parametrize(("api", "major"), sorted(BUNDLED))
def test_error_schema_requires_code_and_reason(api, major):
    spec = Spec.bundled(api, major)
    body = {"code": "404", "reason": "Not Found"}
    if not spec.is_swagger:
        body["@type"] = "Error"
    assert errors(spec, "Error", body) == []
    assert errors(spec, "Error", {k: v for k, v in body.items() if k != "reason"}) != []


# -- issues: stable (path, keyword) pairs for findings ---------------------------------------


def _offering(**extra):
    return {
        "@type": "ProductOffering",
        "id": "1",
        "href": "/x/1",
        "name": "Gold",
        "lifecycleStatus": "Active",
        "lastUpdate": "2026-01-01T00:00:00Z",
        **extra,
    }


def test_issues_are_stable_pairs_with_array_indices_collapsed():
    from tmf_checker.validate import issues

    body = _offering(
        productOfferingPrice=[
            REF,
            {"@type": "ProductOfferingPriceRef"},
            {"@type": "ProductOfferingPriceRef", "href": 5},
        ]
    )
    found = [(i.path, i.keyword) for i in issues(_tmf620(), "ProductOffering", body)]
    assert found == [
        ("productOfferingPrice[].href", "type:string"),
        ("productOfferingPrice[].id", "required"),
    ]


def test_a_null_is_one_issue():
    from tmf_checker.validate import issues

    found = issues(_tmf620(), "ProductOffering", _offering(description=None))
    assert [(i.path, i.keyword) for i in found] == [("description", "null")]


def test_date_time_is_format_checked_both_ways():
    from tmf_checker.validate import issues

    spec = _tmf620()
    assert issues(spec, "ProductOffering", _offering()) == []
    for bad in ("2026-01-01T00:00:00", "2026-01-01T00:00:00.000+0000", "yesterday"):
        found = issues(spec, "ProductOffering", _offering(lastUpdate=bad))
        assert [(i.path, i.keyword) for i in found] == [("lastUpdate", "format:date-time")], bad
