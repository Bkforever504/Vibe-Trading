# Failure categorization — 2026-09-06

| Category | Failures | Root cause | Fix |
|---|---:|---|---|
| Flip contract-limit fixtures | 6 | The host exports `FLIP_MAX_TOTAL_OPEN_CONTRACTS=1`; tests intended to exercise submit, consensus, re-entry, and fill handling but inherited that unrelated integration setting. | Pin the documented five-contract limit inside the test module only. Production code is unchanged. |
| Needs-review dates | 4 | Historical June 2026 fixtures were evaluated against the moving wall clock and aged out of the bounded queue. | Freeze `date.today()` to the fixture session inside the test module. Queue production logic is unchanged. |
| Shadow-volume coverage | 1 | Discovery treated orchestration/evidence modules as strategy programs and six genuine new strategies were absent from the explicit coverage manifest. | Exclude named non-strategy modules and add honest, strategy-specific classifications. |

No skip, xfail, assertion loosening, or execution-logic change was used.
