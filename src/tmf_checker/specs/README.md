# Bundled TM Forum Open API specifications

Unmodified copies of the official TM Forum Open API definitions, from the
[tmforum-apis](https://github.com/tmforum-apis) GitHub organization. Each file is pinned to
an upstream commit and licensed under the **Apache License 2.0** (see each source
repository's `LICENSE` and this project's `NOTICE`).

Three checks prove different things:

- **README vs upstream:** `make specs-verify` (`scripts/verify_specs_upstream.py`) fetches
  each file's git blob SHA from the GitHub API at the pinned commit and compares it with the
  table below. It needs the network, so it is not part of `make test`.
- **Files vs README:** `tests/test_spec_provenance.py` recomputes each local file's blob SHA
  offline and compares it with the table.
- **Later tampering:** `sha256sum -c SHA256SUMS` (run in this folder).

To add or update a file: download it at a pinned commit, add its rows to both tables and to
`BUNDLED` in `src/tmf_checker/spec.py`, regenerate `SHA256SUMS`, and run `make specs-verify`.

## Sources

| File | API | Version | Source |
|------|-----|---------|--------|
| `TMF620-ProductCatalog-v4.1.0.swagger.json` | TMF620 Product Catalog | 4.1.0 | [TMF620_ProductCatalog](https://github.com/tmforum-apis/TMF620_ProductCatalog/blob/24e69f3026f2b514baa27d7206540fc7b55bcb45/TMF620-ProductCatalog-v4.1.0.swagger.json) |
| `TMF620-Product_Catalog_Management-v5.0.0.oas.yaml` | TMF620 Product Catalog | 5.0.0 | [TMF620_ProductCatalog](https://github.com/tmforum-apis/TMF620_ProductCatalog/blob/24e69f3026f2b514baa27d7206540fc7b55bcb45/TMF620-Product_Catalog_Management-v5.0.0.oas.yaml) |
| `TMF622-ProductOrder-v4.0.0.swagger.json` | TMF622 Product Ordering | 4.0.0 | [TMF622_ProductOrder](https://github.com/tmforum-apis/TMF622_ProductOrder/blob/a3825f95248eb04fb1c7e2321305bc99631168a4/TMF622-ProductOrder-v4.0.0.swagger.json) |
| `TMF622-ProductOrdering-v5.0.0.oas.yaml` | TMF622 Product Ordering | 5.0.0 | [TMF622_ProductOrder](https://github.com/tmforum-apis/TMF622_ProductOrder/blob/a3825f95248eb04fb1c7e2321305bc99631168a4/TMF622-ProductOrdering-v5.0.0.oas.yaml) |
| `TMF637-ProductInventory-v4.0.0.swagger.json` | TMF637 Product Inventory | 4.0.0 | [TMF637_ProductInventory](https://github.com/tmforum-apis/TMF637_ProductInventory/blob/f598b4a02186071f2794b8f9b4f6904ef0a8aa52/TMF637-ProductInventory-v4.0.0.swagger.json) |
| `TMF637-ProductInventory-v5.0.0.oas.yaml` | TMF637 Product Inventory | 5.0.0 | [TMF637_ProductInventory](https://github.com/tmforum-apis/TMF637_ProductInventory/blob/f598b4a02186071f2794b8f9b4f6904ef0a8aa52/TMF637-ProductInventory-v5.0.0.oas.yaml) |
| `TMF666-Account-v4.0.0.swagger.json` | TMF666 Account | 4.0.0 | [TMF666_AccountManagement](https://github.com/tmforum-apis/TMF666_AccountManagement/blob/8b9c4f62cbf8c41f5b71f5836f48486a3fd856b8/TMF666-Account-v4.0.0.swagger.json) |
| `TMF666-Account_Management-v5.0.0.oas.yaml` | TMF666 Account | 5.0.0 | [TMF666_AccountManagement](https://github.com/tmforum-apis/TMF666_AccountManagement/blob/8b9c4f62cbf8c41f5b71f5836f48486a3fd856b8/TMF666-Account_Management-v5.0.0.oas.yaml) |
| `TMF678-CustomerBill-v4.0.0.swagger.json` | TMF678 Customer Bill | 4.0.0 | [TMF678_CustomerBill](https://github.com/tmforum-apis/TMF678_CustomerBill/blob/6d1628e7ac15f077083216f9bccd469e9f1af74f/TMF678-CustomerBill-v4.0.0.swagger.json) |
| `TMF678-CustomerBill-v5.0.0.oas.yaml` | TMF678 Customer Bill | 5.0.0 | [TMF678_CustomerBill](https://github.com/tmforum-apis/TMF678_CustomerBill/blob/6d1628e7ac15f077083216f9bccd469e9f1af74f/TMF678-CustomerBill-v5.0.0.oas.yaml) |

## Upstream blob SHAs

| File | Upstream blob SHA |
|------|-------------------|
| `TMF620-ProductCatalog-v4.1.0.swagger.json` | `5cb659a9933914a1c420036481b1138984022eec` |
| `TMF620-Product_Catalog_Management-v5.0.0.oas.yaml` | `545dedbca967b0949e2df054268ada76e44fd564` |
| `TMF622-ProductOrder-v4.0.0.swagger.json` | `2be7de5c517b4805f80da4746828bbaf71f8c488` |
| `TMF622-ProductOrdering-v5.0.0.oas.yaml` | `64a933b31d8ad9ce433e174dee330e491319b2e9` |
| `TMF637-ProductInventory-v4.0.0.swagger.json` | `74d37b15f31f5003a740bc0dc142f540ac6f9ca3` |
| `TMF637-ProductInventory-v5.0.0.oas.yaml` | `637ee2e7e156adf8e640102d9bd951d229ab24e9` |
| `TMF666-Account-v4.0.0.swagger.json` | `e3cef173bbf5ea98c6819d5531a53f9fd22972b0` |
| `TMF666-Account_Management-v5.0.0.oas.yaml` | `082fb3d09777b8c894283f9c6649c5daa690660f` |
| `TMF678-CustomerBill-v4.0.0.swagger.json` | `ba9f33807ad9951332404cccdc85835c5dfa31a2` |
| `TMF678-CustomerBill-v5.0.0.oas.yaml` | `9425d310fda1e739b21595d2b445b7bc6ca6d5cb` |
