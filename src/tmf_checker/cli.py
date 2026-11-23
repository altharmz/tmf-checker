"""Command line: `tmf-checker <command>`."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from pathlib import Path

import yaml

from tmf_checker import __version__, profile, report, runner
from tmf_checker.checks import Context, Unauthorized
from tmf_checker.client import Client, TransportError
from tmf_checker.findings import compare, read_baseline, updated_baseline
from tmf_checker.spec import BUNDLED, Spec
from tmf_checker.validate import errors


def _spec(args: argparse.Namespace) -> Spec:
    if args.spec:
        return Spec.load(args.spec)
    if not args.api:
        raise SystemExit("give --api (with --major) or --spec")
    return Spec.bundled(args.api.upper(), args.major)


def _cmd_specs(_: argparse.Namespace) -> int:
    for (api, major), filename in sorted(BUNDLED.items()):
        print(f"{api}  v{major}  {filename}")
    return 0


def _cmd_operations(args: argparse.Namespace) -> int:
    spec = _spec(args)
    print(f"# {spec.title} {spec.version}  base path {spec.server_path() or '-'}")
    for op in spec.operations():
        print(f"{op.method:6} {op.path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    spec = _spec(args)
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    body = json.loads(text)
    problems = errors(spec, args.schema, body, partial=args.partial)
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"{len(problems)} problem(s): body does not conform to {args.schema}", file=sys.stderr
        )
        return 1
    print(f"ok: body conforms to {spec.name} {args.schema}")
    return 0


def _headers(raw: list[str]) -> dict[str, str]:
    headers = {}
    for item in raw:
        name, sep, value = item.partition(":")
        if not sep or not name.strip():
            raise ValueError(f"--header must be 'Name: value', got {item!r}")
        headers[name.strip()] = value.strip()
    return headers


def _fixtures(path: str | None) -> tuple[dict[str, dict], dict[str, object]]:
    """`--fixtures` YAML: class name -> an existing resource (`id`, optional `href`, `name`,
    `@referredType`); `<Scope>.<Class>` applies while a resource of class Scope is built,
    and may be null. Plus a reserved `values:` mapping of property name (or
    `<Scope>.<name>`) -> preferred value. Returns (fixtures, preferred values)."""
    if not path:
        return {}, {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: fixtures must be a mapping of class name to resource")
    preferred = data.pop("values", None) or {}
    if not isinstance(preferred, dict):
        raise ValueError(f"{path}: 'values' must map property names to values")
    for name, resource in data.items():
        if resource is None and "." in name:
            continue  # `<Scope>.<Class>: null`: no fixture of that class in that scope
        if not isinstance(resource, dict) or not isinstance(resource.get("id"), str):
            raise ValueError(f"{path}: fixture {name!r} needs a string 'id'")
    return data, preferred


def _api_label(args: argparse.Namespace) -> str:
    if args.api:
        return args.api.upper()
    match = re.search(r"TMF\d{3}", Path(args.spec).name, re.IGNORECASE)
    return match.group(0).upper() if match else "API"


def _cmd_run(args: argparse.Namespace) -> int:
    spec = _spec(args)
    rules = profile.load(args.profile, spec) if args.profile else None
    checks = (
        args.checks.split(",")
        if args.checks
        else runner.default_checks(args.allow_writes, rules is not None)
    )
    client = Client(args.base_url, _headers(args.header), timeout=args.timeout)
    run_id = secrets.token_hex(3)
    fixtures, preferred = _fixtures(args.fixtures)
    if args.allow_orders and not args.allow_writes:
        raise ValueError("--allow-orders needs --allow-writes")
    ctx = Context(
        _api_label(args),
        spec,
        client,
        run_id,
        allow_writes=args.allow_writes,
        allow_orders=args.allow_orders,
        fixtures=fixtures,
        preferred=preferred,
        profile=rules,
    )
    try:
        findings = runner.run(ctx, checks, args.resource)
    except Unauthorized as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except TransportError as exc:
        print(f"error: cannot reach the API: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(report.text(findings))
    print(
        f"{report.summary(findings)}, {len(client.log)} request(s), run {run_id}", file=sys.stderr
    )
    meta = {
        "api": ctx.api,
        "spec": f"{spec.title} {spec.version}",
        "run_id": run_id,
        "base_url": client.base_url,
        "checks": checks,
        **({"profile": args.profile} if args.profile else {}),
    }
    if args.json:
        Path(args.json).write_text(report.as_json(findings, meta), encoding="utf-8")
    if args.html:
        Path(args.html).write_text(report.as_html(findings, meta), encoding="utf-8")
    lines = [f.line for f in findings]
    if not args.baseline:
        return 1 if any(not f.is_skip for f in findings) else 0
    path = Path(args.baseline)
    if args.update_baseline:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(updated_baseline(old, lines), encoding="utf-8")
        print(f"baseline updated: {path}", file=sys.stderr)
        return 0
    result = compare(lines, read_baseline(path))
    for line in result.new:
        print(f"new:   {line}", file=sys.stderr)
    for line in result.fixed:
        print(f"fixed: {line}  (remove it from the baseline)", file=sys.stderr)
    return 1 if result.new else 0


def _add_spec_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api", help="bundled API, e.g. TMF620")
    parser.add_argument("--major", type=int, default=5, help="major version (default 5)")
    parser.add_argument("--spec", help="path to a spec file instead of a bundled one")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmf-checker",
        description="Check TM Forum Open API implementations against the published specs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("specs", help="list the bundled specs").set_defaults(func=_cmd_specs)

    ops = sub.add_parser("operations", help="list a spec's operations")
    _add_spec_options(ops)
    ops.set_defaults(func=_cmd_operations)

    val = sub.add_parser("validate", help="validate a JSON body against a schema")
    _add_spec_options(val)
    val.add_argument("--schema", required=True, help="schema name, e.g. ProductOffering")
    val.add_argument("--partial", action="store_true", help="a fields= projection")
    val.add_argument("file", help="JSON file, or - for stdin")
    val.set_defaults(func=_cmd_validate)

    run = sub.add_parser(
        "run",
        help="probe a running API and report its gaps",
        description="Probe a running API. Read-only unless --allow-writes. Exit 0: no gaps "
        "(with --baseline: no new ones); 1: gaps; 2: error.",
    )
    _add_spec_options(run)
    run.add_argument(
        "--base-url",
        required=True,
        help="the full API root, e.g. https://host/tmf-api/productCatalogManagement/v5",
    )
    run.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="'NAME: VALUE'",
        help="extra request header, repeatable (credentials are redacted)",
    )
    run.add_argument(
        "--allow-writes",
        action="store_true",
        help="allow checks that create (and then delete) resources",
    )
    run.add_argument(
        "--checks",
        help=f"comma-separated, from: {', '.join(runner.CHECKS)} "
        f"(default: {', '.join(runner.DEFAULT_READ)}, plus "
        f"{', '.join(runner.DEFAULT_WRITE)} with --allow-writes)",
    )
    run.add_argument(
        "--resource",
        action="append",
        default=[],
        help="only this collection, e.g. productOffering; repeatable",
    )
    run.add_argument(
        "--allow-orders",
        action="store_true",
        help="also create orders (they start real processes: provisioning, billing)",
    )
    run.add_argument(
        "--fixtures",
        help="YAML: existing resources that bodies may reference, by class (Party, "
        "BillingAccount, ...); see docs/checks.md",
    )
    run.add_argument(
        "--profile",
        help="YAML conformance profile: mandatory operations and attributes, and what a "
        "create must carry, per collection; adds the profile check (see docs/checks.md)",
    )
    run.add_argument("--json", help="also write a JSON report with evidence to this file")
    run.add_argument("--html", help="also write an HTML report with evidence to this file")
    run.add_argument("--baseline", help="compare with this baseline file")
    run.add_argument(
        "--update-baseline",
        action="store_true",
        help="write the findings into --baseline, keeping its comments",
    )
    run.add_argument("--timeout", type=float, default=30.0, help="seconds per request")
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
