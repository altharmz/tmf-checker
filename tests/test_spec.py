"""Loading and walking v4 (Swagger 2.0) and v5 (OpenAPI 3.0) specs."""

import pytest

from tmf_checker.spec import BUNDLED, Spec


@pytest.mark.parametrize(("api", "major"), sorted(BUNDLED))
def test_every_bundled_spec_loads_with_its_version(api, major):
    spec = Spec.bundled(api, major)
    assert spec.is_swagger is (major == 4)
    assert spec.version.split(".")[0] == str(major)
    assert spec.schemas
    assert any(op.method == "GET" for op in spec.operations())


def test_unknown_bundled_spec_names_the_known_ones():
    with pytest.raises(KeyError, match="TMF620 v5"):
        Spec.bundled("TMF999", 5)


def test_server_path_v4_base_path_and_v5_server_url():
    """v4 basePath includes /tmf-api; v5 server URLs do not, and most v5 specs give none at
    all (docs/spec-quirks.md) - so the user always supplies the API root URL."""
    assert Spec.bundled("TMF620", 4).server_path() == "/tmf-api/productCatalogManagement/v4/"
    assert Spec.bundled("TMF620", 5).server_path() == "/productCatalogManagement/v5/"
    assert Spec.bundled("TMF622", 5).server_path() == ""


def test_listener_operations_are_skipped_unless_asked():
    spec = Spec.bundled("TMF620", 5)
    assert not any(op.path.startswith("/listener/") for op in spec.operations())
    assert any(op.path.startswith("/listener/") for op in spec.operations(listeners=True))


def test_properties_follow_allof_to_the_base_entity():
    spec = Spec.bundled("TMF620", 5)
    props = spec.properties({"$ref": "#/components/schemas/ProductOffering"})
    assert {"id", "href", "@type", "name", "productOfferingPrice"} <= set(props)


def test_properties_include_both_branches_of_a_ref_or_value():
    spec = Spec.bundled("TMF620", 5)
    props = spec.properties({"$ref": "#/components/schemas/ProductOfferingPriceRefOrValue"})
    assert {"id", "price", "priceType"} <= set(props)


def test_required_v4_and_v5():
    v4 = Spec.bundled("TMF620", 4)
    assert v4.required({"$ref": "#/definitions/ProductOffering_Create"}) == {"name"}
    v5 = Spec.bundled("TMF620", 5)
    assert "@type" in v5.required({"$ref": "#/components/schemas/ProductOffering_FVO"})


def test_request_schema_v4_body_parameter_and_v5_request_body():
    for major, expected in ((4, "ProductOffering_Create"), (5, "ProductOffering_FVO")):
        spec = Spec.bundled("TMF620", major)
        post = next(
            op for op in spec.operations() if op.method == "POST" and op.path == "/productOffering"
        )
        schema = spec.request_schema(post)
        assert spec.resolve(schema) is spec.schemas[expected]


def test_patch_content_types():
    v5 = Spec.bundled("TMF620", 5)
    patch = next(op for op in v5.operations() if op.method == "PATCH")
    assert "application/merge-patch+json" in v5.request_content_types(patch)
    v4 = Spec.bundled("TMF620", 4)
    patch = next(op for op in v4.operations() if op.method == "PATCH")
    assert v4.request_content_types(patch) == ["application/json;charset=utf-8"]
