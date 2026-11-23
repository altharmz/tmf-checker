# Checks

Each check: what it sends, what counts as a gap, and the rule behind it. A gap is one line:

```
<API> <METHOD> <spec path> <kind> <detail>
TMF620 POST /productOffering dropped validFor
```

The detail holds only stable facts (attribute paths, schema keywords, the probe), so a
report can be locked as a baseline; statuses, bodies and ids are in the JSON and HTML
reports' evidence. `src/tmf_checker/findings.py` (`KINDS`) is the list of kinds.

Read-only checks run by default. Write checks run only with `--allow-writes`; they name
what they create `tmf-checker-<run id>-<n>` and delete it at the end. Orders start real
processes (provisioning, billing) and are created only with `--allow-orders` too; jobs,
cancellations and on-demand bills are never created.

| Check | Sends | Gap kinds | Rule | Writes |
|---|---|---|---|---|
| `errors` | GET of an unknown id (a real id with a suffix, so syntax checks pass); with writes, a POST of malformed JSON | `error-status`, `error-body` | 404 / 400 with the spec's `Error` resource (v5: `@type: Error`) | no (the POST: yes) |
| `lists` | GET of the collection, GET by id of the first 3 items, `limit=1`, `offset=1&limit=1` | `unimplemented`, `list-body`, `invalid`, `null-value`, `count-header`, `href`, `param-refused`, `paging-ignored`, `error-status listed-id` | Items validate against the resource schema (incl. `date-time`); count headers agree when present (spec-quirks #14); `href` is an http(s) URL of the item (TMF630); paging works (needs 2 items) | no |
| `fields` | `fields=<attr>` on the list and by id, for an attribute the first item has | `fields-ignored`, `fields-dropped`, `param-refused` | TMF630: only the selection plus `id`, `href` and `@`-attributes | no |
| `filters` | `<attr>=<value>` on the list, for a top-level string attribute the schema defines and two listed items hold different values of, with the first item's value | `filter-refused`, `filter-ignored`, `filter-empty`, `list-body` | TMF630 equality filter: only resources with that value come back, and the item that has it is not lost. Not sent: values with `,` (alternatives), `.` or operators, date-times. Not judged: items without the attribute, values differing only in case. Comma lists, operators and `sort` are not checked yet | no |
| `missing` | GET by id of up to 20 listed items and of everything the run created | `missing` (`a`, or `a.b` one level into a value object) | An attribute the schema defines never comes back. **Opt-in** (`--checks missing`): see below | no |
| `profile` | reads the listed items, up to 20 by id, and what the run created | `profile-missing` | Every returned resource has each attribute the `--profile` makes mandatory (`a.b`: in each present `a`). Runs when `--profile` is given: see below | no |
| `location` | the base create | `create-status`, `location` | 201 with a `Location` equal to the new resource's `href` (TMF630; no spec declares it: spec-quirks #10). `202` skips with `async` | yes |
| `requires` | the base create; when refused, discovery (below) | `requires`, `create-status` | The server must not require what the spec leaves optional | yes |
| `roundtrip` | base + one optional attribute, GET it back; one level into object attributes | `refused`, `server-error`, `dropped`, `rewritten`, `unprobed` | An attribute the create schema defines is stored and returned as sent | yes |
| `polymorphism` | base + `@baseType`, GET it back | `refused`, `dropped`, `rewritten` | TMF630 polymorphism. `@schemaLocation` is not sent: a server that validates against it would fetch a schema we cannot give | yes |
| `patch-formats` | a PATCH of `description` (else `name`) to a new value, with each declared content type, read back | `content-type`, `content-type <type> ignored`, `unimplemented` | The spec lists the PATCH content types (spec-quirks #4); not a no-op, which a server may rightly refuse | yes |
| `patch` | merge-PATCH of each optional attribute of the PATCH schema, read back | `read-only`, `server-error`, `dropped`, `rewritten` | An attribute the PATCH schema defines can be changed | yes |
| `hub` | POST/DELETE `/hub`; trigger an event; listener receives it | `hub`, `event-body` | Event payloads validate against the listener schemas | M4 |

## The base create and `requires`

Every write check works on one base resource per collection. The base create posts the
spec's minimal body (the required attributes). When the server refuses it (4xx),
discovery finds a body it accepts, trying in order: the minimal body plus the optional
attributes the refusal names, plus every buildable optional attribute, plus each one alone,
every attribute but one. Then it removes each optional attribute from that body: a 400 or
422 proves the server requires it, one `requires <attr>` line each. The message only picks
where to start; the removal is the proof. The base is then the minimal body plus those
attributes, so a server with business rules can still be probed. A 409 is a conflict with
some resource's state, never proof.

## Comparison

Only what was sent must come back: extra attributes the server adds are fine. Date-times
compare as instants, numbers as decimals, and a reference by its `id` (its `name` and
`href` are copies the server may refresh).

## Skips are lines too

A check that cannot judge says why, as a `skipped <check> <reason>` or an
`unprobed <attribute> <reason>` line, never silently and never as a gap:

| Reason | Meaning |
|---|---|
| `forbidden` | the API answered 403 (a 401 stops the run instead: pass credentials with `--header`) |
| `no-fixture` | a reference to another API (`relatedParty`, `agreement`) or a plain `...Id`, and no fixture for it; references are never made up |
| `made-up-value` | a free string with no example, enum or preferred value was refused: the server may have a vocabulary. Give it in `values:` |
| `conflict` | a 409: a conflict with some resource's state (a completed order), not with the attribute |
| `same-value` | the PATCH value equals the current one, which proves nothing |
| `state-machine` | `state`/`status` are not PATCHed: a refusal may be a transition rule |
| `server-managed` | a nested `state`, `status` or date is never sent as an extra |
| `sibling-reference` | a nested `...Relationship` that names another part of the same body |
| `no-distinct-values` | `filters`: no attribute with two different usable values in the listed items, so an ignored filter could not be seen |
| `optional-operation` | the `--profile` lists the mandatory operations and leaves this one out, and it answered 404, 405 or 501 |
| `fewer-than-2-items`, `no-items` | not enough data to judge paging, projections or `missing` |
| `task-resource`, `orders-not-allowed` | see the top of this page |
| `async` | the server answered 202 |
| `read-failed`, `no-id` | the created resource could not be read back |

## `missing` is opt-in

Absent data and a server that cannot return an attribute look the same. `missing` runs after
the write checks, so what `roundtrip` sent is there to be read, and it skips what a write
check already reported (`unprobed`, `refused`, `dropped`, `read-only`) and leftovers of
earlier runs. It looks one level into value objects, not into references or
`...RefOrValue` unions. An attribute the server refuses from clients but fills in itself
(an account balance) is still read one level in: that is where server-built values lack
attributes. A value the run itself sent (by POST or PATCH) is not read one level in: it
lacks whatever the run left out (such as a nested `href`), and `roundtrip` already compared
it with what was sent. Use it on data known to be complete.

## Conformance profile

The OAS is the default reference. TM Forum says a conformance profile wins when the two
disagree (spec-quirks #8), but profiles are member-only and cannot be bundled, so
`--profile FILE` takes the part you need as YAML, keyed by collection:

```yaml
productOffering:
  operations: [list, retrieve, create, patch, delete]   # the mandatory ones
  attributes: [id, href, name, lifecycleStatus, validFor.startDateTime]
  create: [name, lifecycleStatus]
```

- `operations` (from `list`, `retrieve`, `create`, `patch`, `delete`): an operation the
  spec defines and the list leaves out may be missing. Its `unimplemented` line becomes
  `skipped profile optional-operation`; an optional create that answers 404/405/501 skips
  the write checks with `optional-operation` instead of `create-status`.
- `attributes`: mandatory in every returned resource; the `profile` check reports each one
  a resource lacks (absent or null) as `profile-missing`, one line per attribute on the
  collection path, the resource in the evidence. `a.b` is judged only where `a` is present.
  On a resource the run created, an attribute the client could have sent and the run did
  not is not judged (nor `a.b` in a value the run built): that body is ours. Put an
  attribute the client must provide in `create`, and the run sends it.
- `create`: attributes a create must carry. They join the spec's minimal body, so a server
  may require them without a `requires` line.

Every key is optional; a collection the profile leaves out is checked against the OAS
alone. Names are checked against the spec when the profile loads, so a typo is an error
(exit 2), not a silent no-op. The format is tmf-checker's own: TM Forum's profiles are
documents, not machine-readable files.

## Values and fixtures

`values.py` builds bodies from the schemas. A scalar comes from, in order: the user's
preferred value (`values:` below), the property's `example`, its first `enum` value, its
format, the value the spec's examples use most for that property name (spec-quirks #15),
its type. Names are unique per value (`tmf-checker-<run>-<n>`), and so are ids inside
values (order items). A nested `X_MVO` value is completed as `X_FVO` requires.

A reference points at a resource of the API under test created by the run (never at the
user's data, which a link could change), else at a fixture. `--fixtures FILE` (YAML) names
existing resources by class, for references to other APIs:

```yaml
values:                          # preferred values by property name
  role: customer
  FinancialAccount.role: owner   # only while a FinancialAccount is being built
PartyRole: {id: "4739...", href: "/tmf-api/customer/v5/customer/4739...", "@referredType": Customer}
Party: {id: "25fa...", "@referredType": Individual}
FinancialAccount.PartyRole: null # its owner is a party: the union falls back to Party
BillingAccount: {id: "aca9...", href: "/tmf-api/accountManagement/v5/billingAccount/aca9..."}
ProductOffering: {id: "6a57..."}
```

A union of references (`PartyRefOrPartyRoleRef`) takes the longest class with a fixture,
and the branch of that class (`PartyRoleRef`). The fixture's `@referredType` wins over the
class name, since `Party` is abstract.
