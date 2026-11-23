import pytest

from tests.stub import Gaps, Stub, serve
from tmf_checker import runner
from tmf_checker.checks import Context
from tmf_checker.client import Client
from tmf_checker.spec import Spec
from tmf_checker.values import Values

RUN_ID = "test01"


def seed(stub: Stub, collection: str, count: int, **extra) -> list[dict]:
    """`count` conformant resources: the spec's minimal create body plus `extra`."""
    if count == 0:
        return []
    spec = stub.spec
    resource = next(r for r in spec.resources() if r.collection == "/" + collection)
    body = Values(spec, "seed").minimal(spec.request_schema(resource.op("POST")))
    return [stub.add(collection, {**body, "name": f"seed-{i}", **extra}) for i in range(count)]


def probe(
    spec: Spec,
    gaps: Gaps | None = None,
    *,
    checks=runner.DEFAULT_READ,
    writes: bool = False,
    count: int = 2,
    resource: str = "productOffering",
    headers: dict | None = None,
    orders: bool = False,
    fixtures: dict | None = None,
    **extra,
) -> tuple[list[str], Stub]:
    """Run checks on one resource of a stub seeded with `count` items; the finding lines."""
    with serve(spec, gaps) as stub:
        seed(stub, resource, count, description="seeded", **extra)
        ctx = Context(
            "TMF620",
            spec,
            Client(stub.base_url, headers),
            RUN_ID,
            allow_writes=writes,
            allow_orders=orders,
            fixtures=fixtures or {},
        )
        findings = runner.run(ctx, checks, [resource])
        return [f.line for f in findings], stub


@pytest.fixture(params=[4, 5], ids=["v4", "v5"])
def tmf620(request) -> Spec:
    return Spec.bundled("TMF620", request.param)
