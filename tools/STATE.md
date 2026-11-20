# DataMate current state — 2026-11-19

## Repository

- Work only in fork `pl2n/DataMate`, branch `feature/multi-bundle-query`.
- Current implementation/test head: `2522abbafdccb6bb930d3f79f9f0f13af8302d4f`; docs/checkpoint commits follow it.
- Latest implementation code head: `21469c4be7a3d93e5bd2befb879315f3c9c36afd`; branch ref was last checked at `179f5c3383aa456d88ee08f900daca868805c403` before final documentation-only synchronization. Fetch current branch head before the next code change.
- Branch head was verified at `04881307f968d69a6a6f64caa5c25b5211bb6ef9` before the composite-order-line milestone; fetch the current branch head before the next code change.
- Do not modify upstream `DangDuuTapCode/DataMate`. An existing PR #1 is open to upstream `main`; do not create a duplicate or merge it unless requested.
- GitHub API workflow only; no local checkout, local git status, or local test execution.
- Latest implementation baseline: `a6eade98f01e55326ae53bf6423800868b6f77b3`.
- Latest documentation commits: `bc01731c4e445841bbff72ab32b74bbcc18dfb6e` (provenance guide) and `382a75c33fb0bf51617dde33cee1ba172854ef65` (handoff).

## Implemented

- Grouped Excel headers and retained header metadata.
- Exact semantic mapping with ambiguity handling; relationship validation without automatic joins. Key families include order/customer/product/payment receipt plus employee, supplier, purchase receipt, batch/lot, branch, and IMEI; generic row numbers/reference labels remain unmapped.
- Relationship evidence carries both table names and source filenames; capability checks use exact `(table_name, source)` identity to distinguish repeated worksheet names.
- BusinessSchemaCatalog, bundle registry, requirement extraction/schema, composite rules, and shared-context guard.
- BundleCapabilityResolver checks exact canonical fields, co-location, validated relationships, and explicit business-rule evidence.
- Runtime constructs per-business catalogs/planners and records evidence/capability decisions.
- SplitRules/executor conformance for revenue amount/date/status semantics and collection successful-payment policy.
- Dedicated payment-status classifier; unknown values abstain.
- Evidence-approved exact table scope and revenue source shape are enforced by component-specific Executors.
- Business-rule evidence v1 contract and strict local SHA-256 provenance verification.

## Safety and capability boundaries

- Missing, malformed, wrong-business, rejected, incorrectly scoped, unsupported, or digest-invalid evidence blocks composite execution.
- Revenue source shape must be explicitly reviewed as `direct_line` or `detail_to_order`; detail-to-order requires a validated `order_id` relationship.
- Collection requires payment-event amount/date/status in the exact single table scoped by both source-role and settlement-policy claims.
- Collection remains unavailable unless the active rulebook explicitly states the supported successful-payment-only policy.
- Provenance allowlist remains narrow: input-root `rulebook.md`; business-local `data_dictionary.csv/.xlsx/.md` or `README.md`; business-local `operator_attestation.json`. README is treated as schema documentation only and never auto-generates evidence.
- SHA-256 proves byte correspondence only; it does not authenticate reviewer identity or provide a signature.
- No arbitrary path access, automatic joins, fuzzy inference, arbitrary conjunction splitting, or new metrics.

## CI

- Run `44564104588` on commit `a6eade98f01e55326ae53bf6423800868b6f77b3`: 272 tests; 270 passed. All feature tests passed. Two inherited `CODEX PROGRESS` hygiene checks failed (large-file limit and secret-like-pattern false positive).
- Run: https://github.com/pl2n/DataMate/actions/runs/44564104588
- Two docs-only commits followed that run; inspect their Actions results before further code edits.
- Never weaken or modify the inherited hygiene artifact to hide those failures.

## Contest archive and current blocker

The user supplied `Contest.zip`, inspected on 2026-11-19:
- Train root: 30 businesses, 3,000 questions, answers, calendar, and train rulebook.
- Public-test root: 14 businesses, 1,000 questions, calendar, and a separate public-test rulebook.
- Both roots match the runtime's expected directory layout. Every inspected business has a local `README.md` with source/column/table-grain documentation; separate data dictionaries and operator attestations are absent.
- Train and public-test rulebooks differ; each split must be run with its own root.
- Neither rulebook contains the explicit successful-payment-only policy clause. Collection remains unavailable.

Committed after archive inspection:
- `47649aa3ba70ddaaa363986d7beb2a81ba0a8a5f` README provenance allowlist.
- `fa402eae2862463f30a0d3403e7d0c7f82e5c819` README digest regression test.
- `a33ccdd32355f163069c47872e42acdb87b79489` evidence documentation.
- `7edf33b418cce8ed782cc64282c8b7376f08ce40` implementation progress update.
- `f5c73cdef1de583c094507344e270966f3044129` handoff update.

Next: audit public-test questions against the 14 input shapes, then build minimal synthetic fixtures for representative multi-source queries. Do not add the full archive to Git. The new code/test commits still need a verified Actions result. No local checkout or local test run is available.

## Latest multi-source expansion

- Exact aliases and relationship-key families expanded based on Contest.zip schemas.
- Added synthetic tests for exact aliases and six many-to-one relationship families.
- Commits: `8ff2c09`, `37f66c3`, `a784b4f`, `2d866ee`, `a64ba34`, `0465e9d`, `dccf1ba`, `45b3667`, `9d2ceab`.
- CI for these changes is not yet verified. The last known baseline remains run `44565561293` (272 tests; 270 passed, two inherited hygiene failures).

## Source-qualified relationship identity fix

- `RelationshipCandidate` now includes `from_source` and `to_source`.
- Revenue detail-to-order validation compares exact table identities, not worksheet names alone.
- Regression tests cover duplicate `Sheet1` names across workbooks and same-name scoped source pairs.
- Commits: `c4278e8`, `5d2b62e`, `5e67aff`, `abfc0df`, `dfe61ce`, `d16c67a`, `6e3af74`, `38a85ba`.
- CI remains unverified for this continuation.

## Composite order-line relationship milestone

- Active rulebook parser now detects the exact same-order duplicate-row clause; default false when absent.
- Exact `Số thứ tự`/`No.` aliases map to `order_line_number`; `STT` remains unmapped.
- Relationship discovery emits composite `order_id+order_line_number` evidence, with all key columns and source-qualified table identity.
- Exact duplicate rows are removed only for composite relationship profiling and only when the rulebook enables it. No source rows are mutated and no joins are executed.
- Main runtime passes the active rulebook flag into schema catalog construction; catalog schema version 1.1.0.
- Relevant commits: `107216e`, `64c426c`, `01e54b3`, `bd2b1f6`, `0f120e9`, `3191b7a`, `7016a60`, `ef200e2`, `06a579f`, `d0d75b9`, `4f6def6`, `6ae52b0`, `a6da9e4`, `4e17cd9`, `3741d34`, `aa6e746`, `ea5fb27`.
- This change set has no verified Actions result yet; no local checkout or local test run is available.


## Exact approved revenue join contract

- Detail-to-order revenue no longer relies only on a relationship check followed by independent executor header guessing in the composite path.
- `RevenueJoinContract` stores exact line/order table identities, source filenames, canonical key set, and physical key-column indices.
- Resolver emits it only for one exact validated source-qualified `order_id` relationship with safe cardinality; direction is normalized even if catalog order is reversed.
- Composite planner carries the contract and main passes it to the scoped Executor. Executor enforces exact table identity and key-column indices.
- Joined duplicate line rows are deduplicated only with explicit active rulebook authorization; otherwise execution abstains.
- Latest implementation commit before docs: `21469c4be7a3d93e5bd2befb879315f3c9c36afd`.
- CI run `44577298652`: 286 tests, 284 passed; all feature tests pass. Two inherited failures remain for the existing `CODEX PROGRESS` artifact in repository hygiene tests.
- Relevant commits: `c00cd0e`, `11cbcb0`, `ea7f156`, `9b20c0b`, `5e05f2b`, `d926cae`, `09cef43`, `004306d`, `72e94d6`, `3ae9966`, `f3a8bd4`, `059b931`, `21469c4`, plus documentation checkpoints `61e9430`, `705f016`, `7cd271a`.
- This is a narrow revenue detail-to-order contract, not a general join planner. Composite keys, polymorphic references, multi-hop paths, and arbitrary dimension joins remain unsupported.


## Multi-hop relationship path discovery (2026-11-20)

- Added `src/datamate/relationship_paths.py` and `tests/test_relationship_paths.py`.
- Discovery-only graph resolver; not wired into planner/Executor.
- Exact source-qualified table identity; validated edges only; carries composite canonical keys and endpoint column indices.
- Cardinality-aware traversal: many-to-one and one-to-one preserve source grain; one-to-many is `fanout_risk`.
- Unique path only; multiple paths ambiguous; no heuristic ranking.
- CI run `44578825930`: 293 tests, 291 passed; all feature tests pass. Two inherited hygiene failures remain for `CODEX PROGRESS`.
- Implementation commit: `68564ac356af305e63aabe1703ce76d98aadb08f`.
- Next: query-specific execution contract including fact grain, aggregation stage, exact path and fanout policy. Do not enable arbitrary multi-hop joins.
## Relationship path bound hardening (2026-11-20)

- Fixed candidate-cap off-by-one: exactly max_candidates paths may still be a valid unique result; overflow is reported only after observing one more path.
- Invalid/non-integer/boolean limits and malformed or blank table identities return invalid_request.
- Added six synthetic regressions for exact cap, overflow, reverse traversal fanout, hop limit, invalid limits, and cycles.
- Commits: 4212165cece5a9167095984865aca98ae6362890 and fe799c55ac9757a64007fbe03ef0a9028e6ff1f2.
- CI pending; no local test execution.


## Follow-up verification — 2026-11-20

- The first added edge-case run exposed two incorrect test fixtures (cardinality direction and an assertion that expected a longer path despite a direct edge). The fixtures were corrected in commit `2522abbafdccb6bb930d3f79f9f0f13af8302d4f`; no production-code change was needed for those fixture failures.
- GitHub Actions run `44580683573` on `2522abb` executed 299 tests. 297 passed, including all relationship-path tests. The only two failures are the inherited repository-hygiene checks for the pre-existing `CODEX PROGRESS` artifact.
- Run: https://github.com/pl2n/DataMate/actions/runs/44580683573
- The existing upstream PR #1 is open from `pl2n/DataMate:feature/multi-bundle-query` into `DangDuuTapCode/DataMate:main`. It was not created or modified in this work item. GitHub currently reports `mergeable=false`; this should be rechecked before any merge decision.


## Fact join contract structural prototype (2026-11-20)

- Added `src/datamate/join_contracts.py` with `FactJoinContract` and a fail-closed builder over a unique validated relationship path.
- Contract records exact source-qualified fact/target tables, declared fact grain, measure field and physical measure index, aggregation stage, join type, and exact path hops/key indices.
- Builder rejects fanout, unknown cardinality, ambiguous paths, endpoint mismatch, disconnected/repeated nodes, malformed composite key indices, invalid measure index, missing grain/measure declarations, unsupported join types, and pre-join aggregation.
- Added synthetic tests in `tests/test_join_contracts.py` and documentation in `docs/FACT_JOIN_CONTRACT.md`.
- This is a structural prototype only. It is not wired into planner/Executor and does not execute joins or enable a new metric. Grain/measure meaning still requires reviewed query-specific evidence.
- Code commits: `bad2dcda57a71d8c78d7e49a2c84b969e3008071`, `2136219d904b5ce99671e3c3d285d5b60a638aae`, `f5b476972f779b5abe02bf14f8ca438ac143c90f`, `085284c1562af575d55bf12f80715de6b331e3b3`.
- Documentation commit: `d87b325e158da97ab11f21380cb177e36d3ed680`.
- CI verification pending. No local checkout or local test execution was used.


## CI verification — fact join contract prototype

- Latest checked Actions run: `44581612778`, head `77460ea68fcb1750b8a534e87727cb7e99d8e52f`.
- 310 tests executed; 308 passed. All relationship-path and fact-join-contract feature tests passed.
- The only two failures remain `test_no_large_files` and `test_no_secret_like_strings`, both reporting the pre-existing `CODEX PROGRESS` artifact.
- Run: https://github.com/pl2n/DataMate/actions/runs/44581612778
- Existing PR #1 remains open against upstream `main`, head updated with this branch. GitHub reports `mergeable=false`; no merge or PR mutation was performed.


## Post-merge continuation — 2026-11-20

- PR #1 was merged by the repository owner. GitHub reports `state=closed`, `merged=true`, merged at `2026-11-19T17:53:39Z`.
- Upstream merge commit: `99478a179919a7b5121b00072f90522c50117aba`. Comparing upstream `main` with that commit returns `identical`.
- The merged PR head was `15430b417d650e6145ed4e64cb637ebe2a00677c`.
- Created a clean continuation branch on the fork: `feature/query-specific-join-execution`, based on the merged PR head. Continue only on this new fork branch; do not amend the merged branch or modify upstream directly.
- Hardened `FactJoinContract` structural validation to require exactly one reported candidate, immutable typed hops, exact nonblank source-qualified identities, unique canonical keys, valid tuple-shaped physical indices, strict non-fanout boolean, and safe handling of unsupported join-type inputs.
- Added regression tests for forged candidate counts, malformed identities, duplicate key declarations, and non-string join-type inputs.
- Commits: `5c04d9b8498133e28170108ed3ba7fe8ec58301a` (implementation), `783631e99ed584fee284564c126b1275ca453edf` (tests).
- No new Actions result is verified for this continuation yet. The old checked baseline remains run `44581612778` on `77460ea68fcb1750b8a534e87727cb7e99d8e52f` (310 tests, 308 passed; two inherited `CODEX PROGRESS` hygiene failures). No local checkout or local test execution was used.
- The fact-join contract remains structural only. Do not connect it to Planner/Executor until one real query family has explicit, reviewed evidence for fact grain, measure semantics, additive behavior, join path, keys, and aggregation stage.


### Final malformed-cardinality guard

- `_valid_hop` now checks that cardinality is a string before membership testing, so malformed unhashable values also fail closed rather than raising.
- Regression coverage includes a list-valued cardinality.
- Latest commits: `101a5089d1bd71c45b17516f5753a2e01f06f151` (guard), `4e073e4f1a35a216179094ff0d63389f27829775` (test).
- Latest branch head verified: `4e073e4f1a35a216179094ff0d63389f27829775`. No workflow run is currently associated with this commit; CI has not yet been verified.


### Feature-branch CI trigger

- Updated `.github/workflows/tests.yml` so pushes to `feature/**` branches run the Python test workflow; pull requests targeting `main` or `feature/**` are covered.
- Commit: `e74d43413c3966d7d80e6fbe8f985fb5b6ac4de9`.
- The GitHub connector did not surface a workflow run or commit status for this push. Do not claim CI passed; obtain a run from a subsequent PR/check before merge.


### Current checkpoint pointer

- Latest verified fork branch head: `ee45d81a81ee044bb8d05d103b5c5a255bc5a519`.
- This head includes the contract hardening, regression tests, CI trigger update, and synchronized progress/handoff documentation.
- PR #1 remains merged; no new PR has been opened for this continuation branch.


## Contest archive analysis and blank-key LEFT JOIN support — 2026-11-20

- Received the user's uploaded `Contest.zip` at `/mnt/data/Contest.zip`. Archive contains 308 entries; it was inspected in place and was not copied into the repository.
- Selected `biz_129` as a real multi-source training case. Source basis: `Contest/train/data/biz_129/README.md`, `Contest/train/rulebook.md`, and questions `q_264a7294b457`, `q_6ee842fa8f92`, `q_635440e343cc`, `q_d361c00c6829`.
- Measured structure: sales detail 145,479 rows; order header 38,499 rows with unique order IDs; customer catalog 220 rows with unique customer IDs; payment events 38,072 rows. Detail order IDs all match order headers. All 23,309 nonblank order customer IDs match the customer catalog; 15,190 order rows have blank customer IDs.
- Payment events have 37,748 distinct order IDs and up to four payment rows per order. Do not join payment events directly to sales-line fact rows; that can multiply line revenue. Collection queries need their own payment-grain aggregation.
- Added README-scoped semantic aliases for `Số CT` in `chi_tiet_don`, `Số phiếu` in `don_hang`, and `Mã giao dịch` in `thanh_toan`. These remain unmapped in unrelated source contexts.
- Added `validated_left_join` for a non-fanout relationship where target keys are unique and every nonblank source key matches, but source-side blank keys exist. Such a relationship is not promoted to ordinary `validated`, so existing bundle capability checks remain fail-closed.
- Relationship paths now propagate `left_join_required` and mark the exact hop. `FactJoinContract` refuses an inner join for such a path and accepts only a LEFT JOIN.
- Added synthetic README-shaped integration coverage for the sales-detail → order → customer-group path. No contest rows or archive contents were added to the repo.
- Added `docs/CONTEST_BIZ129_JOIN_CASE.md` with the rulebook-backed query family, observed structural counts, and payment-fanout warning.
- Runtime Executor/Planner wiring remains disabled. The contract is still structural; it does not execute joins or calculate the group-share numerator/denominator.
- CI has not surfaced a workflow run or commit status for this continuation branch. No local checkout or local test run was used. Obtain CI through a draft/normal PR before treating tests as passed.


### CI and repository hygiene follow-up

- Initial run `44586101398` executed 318 tests and exposed two fixture expectation mistakes plus two hygiene failures.
- Corrected the README-shaped fixture to include repeated orders for one customer (so the relationship is many-to-one), and corrected the partial-overlap test to expect `candidate` rather than `rejected`.
- Inspected the tracked `CODEX PROGRESS` artifact: it was a 2,026,779-character historical conversation transcript, exceeded the 1 MB repository limit, and contained one sensitive-looking token-pattern match. Replaced its current contents with a short pointer to maintained handoff docs; no token-like text was copied into the replacement.
- Follow-up Actions run `44586527843` on commit `4f7077120f19b29717f5be46f1c53fe9d80d01f4` completed successfully: **318 tests, OK**. This is a GitHub Actions result, not a local test run.
- PR #2 is open as a draft: https://github.com/DangDuuTapCode/DataMate/pull/2. It has not been merged.


## Explicit multi-hop join executor — 2026-11-20

- Added `src/datamate/join_executor.py` with `execute_fact_join_contract(tables, contract)`.
- The executor consumes only an explicit `FactJoinContract`; it revalidates source-qualified table identities, semantic key-to-column mappings, allowed cardinality, non-fanout hops, target key uniqueness, and reachable nonblank source-key matches.
- It enforces LEFT JOIN when a hop requires it, preserves one aligned output row per original fact row, retains duplicate fact lines, and represents unmatched dimension rows as `None`. Keys are exact trimmed text; leading zeroes and case are not coerced.
- Added tests for a two-hop detail → order → customer join, guest-row preservation, duplicate fact lines, duplicate target keys, reachable unmatched keys, malformed rows/contracts, schema-index mismatch, and missing/duplicate source identities.
- GitHub Actions run `44587842656` on commit `6a0bc0b7ad4aef0cb510b234d05b5455a73eb8db`: **328 tests passed**.
- The executor is not wired into `Executor.execute` or `RulePlanner`; it performs no date/status/group filters, aggregation, or ratio calculation.


### Latest branch verification

- Latest branch tip at this checkpoint: `e95608eb8b34281ac5327ecf67d58f16dbab5e38`.
- GitHub Actions run `44588291394` on that exact commit completed successfully: **328 tests passed**.
- PR #2 (`feature/query-specific-join-execution` → upstream `main`) remains open as a draft and has not been merged.


### Join executor hardening

- Added explicit fact-grain validation and tests for complete INNER JOIN paths and exact identifier matching (including leading zeroes).
- Latest code/test commit: `647f6a40bc23aef80f26180214342848e86eb576`.
- Actions run `44588678999` on that commit: **331 tests passed**.


## Customer-group revenue share runtime — 2026-11-20

- Added `src/datamate/customer_group_revenue.py`, a query-specific executor for Contest business `biz_129` only.
- Wired `customer_group_revenue_share` through `RulePlanner`, `QueryPlan.filters`, `Executor.execute_with_reason`, verification, and `main.run`.
- Source scope is exact: `chi_tiet_don.csv` → `don_hang.csv` → `khach_hang.csv`. The order → customer hop uses LEFT JOIN so blank customer IDs keep their sales in the whole-shop denominator.
- Applies rulebook semantics: net line amounts, order-date period, whole-order exclusion for cancelled/returned, include in-transit, deduplicate exact duplicate lines within the same order, and keep guest orders out of every customer group including `lẻ`.
- Planner recognizes the observed customer groups `thân thiết`, `lẻ`, and `sỉ`; it will not enable the intent for other business IDs or unknown group labels.
- Added exact Contest-question planner tests, rulebook-policy tests, failure/abstention tests, and a full `main.run` integration test.
- Independent archive audit references: October 2025 = 20.31%; June 2025 = 19.79%. Raw contest rows are not committed.
- GitHub Actions run `44594130571` on code/test commit `59a7444cb530801e59018149f653bcbdfd76b4e7`: **352 tests passed**.
- PR #2 remains open as a draft and has not been merged.


### Verified branch tip after runtime integration

- Branch tip: `0cd8fb90fe0c197752f84b847537763b09217e2c`.
- GitHub Actions run `44594377793` on that exact tip: **352 tests passed**.
- PR #2 remains open, draft, mergeable, and unmerged.


## 2026-11-20 — customer-group revenue total

- PR #3 merged to upstream main at `92405f26805d0e9f8842b094792e94568cd706f7`; query-specific LEFT JOIN and revenue-share support are now upstream.
- Created `feature/customer-group-revenue-total` on `pl2n/DataMate-temp` from that merge commit.
- Added a separate allowlisted `customer_group_revenue_total` query family for `biz_129`. It sums eligible net sales-line amounts only for the requested customer group; guests are not attributed to a group.
- Preserves the reviewed detail → order → customer LEFT JOIN, order-date period, full cancelled/returned order exclusion, in-transit inclusion, duplicate-line deduplication, and payment-event separation.
- Added planner/executor/scope/integration tests and `docs/CUSTOMER_GROUP_REVENUE_TOTAL.md`.
- No PR has been opened. CI is not yet confirmed for the current branch head.
