# Data Model - As Found

> Generated from exploratory analysis. Factual claims match stored notebook outputs in `analytics/exploration/notebooks/exploratory_analysis.ipynb`.

The pre-validation logical ER diagram is in `docs/superpowers/specs/2026-06-11-exploratory-analysis-design.md`, Section 14. The relationships below describe what the EDA observed in the exported Parquet reference tables and sample RPKM TSV files; discrepancies are flagged for review, not pre-judged as bugs.

## Reference Tables

Parquet reference tables are exported from SQLite and loaded by the notebook as DuckDB views.

| Table | Rows | Columns |
|---|---:|---|
| `names` | 2,840,139 | `id VARCHAR`, `tax_id BIGINT`, `name VARCHAR` |
| `nodes` | 2,840,139 | `id BIGINT` |
| `parents` | 2,840,134 | `id VARCHAR`, `tax_id BIGINT`, `t_kingdom BIGINT`, `t_phylum BIGINT`, `t_class BIGINT`, `t_order BIGINT`, `t_family BIGINT`, `t_genus BIGINT`, `t_species BIGINT` |
| `pathway_nodes` | 23,864 | `id VARCHAR`, `name VARCHAR`, `type VARCHAR`, `x BIGINT`, `y BIGINT`, `pathway BIGINT` |
| `pathway_edges` | 46,726 | `id VARCHAR`, `source VARCHAR`, `target VARCHAR`, `pathway BIGINT` |
| `pathway_superpathways` | 193 | `id BIGINT`, `name VARCHAR`, `superpathway VARCHAR` |
| `superpathways` | 13 | `id VARCHAR`, `name VARCHAR` |

Key fields used by the app and EDA:

| Relationship | Key usage | Observed notebook result |
|---|---|---|
| `names.tax_id -> nodes.id` | Taxonomy name lookup | 0 orphan rows in the checked join |
| `parents.t_kingdom -> nodes.id` | Taxonomic rank lookup sampled by EDA | 0 orphan rows in the checked join |
| `pathway_edges.source -> pathway_nodes.id` | Pathway graph source node | 0 orphan rows in the checked join |
| `pathway_superpathways.superpathway -> superpathways.id` | Superpathway lookup | 0 orphan rows in the checked join |
| `pathway_nodes.pathway -> pathway_superpathways.id` | Logical app join, not declared as SQLite FK in the design spec | Missing-link query returned 0 displayed rows |

Additional cardinality checks:

- `names` has exactly 1 row per `tax_id` in this dump: min 1, max 1, median 1.0, average 1.0.
- `parents` has 2,840,134 rows; the rank completeness query found 0 `genus_without_family`, 0 `genus_without_order`, and 0 `phylum_without_kingdom` rows.
- Pathway graph degree is sparse and skewed: out-degree min 0, max 945, median 0.0; in-degree min 0, max 945, median 0.0.
- Pathway edge counts per pathway range from 2 to 2,410, with median 132.0.
- Displayed dangling-node output is led by pathway 1100 with 3,716 dangling nodes, pathway 1110 with 2,480, and pathway 1120 with 1,208.

## RPKM Wide Format

Both sample files are wide TSVs. The fixed columns are:

`GeneID`, `Length`, `Reads`, `EC#`, `RPKM`, `Unclassified`

Every remaining column header is interpreted as a taxonomy `tax_id`. Cross-domain taxonomy joins are evaluated per tax_id column header, not per RPKM row.

| File | Rows | Tax_id columns | Size reported by notebook |
|---|---:|---:|---:|
| `test_rpkm_1.tsv` | 425,828 | 8 | 51.0 MB |
| `test_rpkm_2.tsv` | 461,112 | 12 | 71.1 MB |

Tax_id column overlap:

- `test_rpkm_1.tsv`: 8 tax_id columns.
- `test_rpkm_2.tsv`: 12 tax_id columns.
- Intersection: 6 tax_id columns.
- Only in `test_rpkm_1.tsv`: 2 tax_id columns.
- Only in `test_rpkm_2.tsv`: 6 tax_id columns.

RPKM sparsity was measured for `test_rpkm_1.tsv`: 3,406,624 tax_id cells, 59,439 nonzero cells, 1.74% nonzero.

EC normalization used for joins:

- Null, empty, `None`, `none`, `NA`, and `null` values normalize to `0.0.0.0`.
- `EC:x.y.z` values normalize to `x.y.z`.
- Existing non-prefixed values are preserved as strings.

The most common normalized EC output displayed for `test_rpkm_1.tsv` is `None -> 0.0.0.0` with 235,991 rows. The displayed top EC-prefixed row is `EC:2.7.13.3 -> 2.7.13.3` with 8,513 rows.

## Logical Relationships As Found

| Edge | As-found result |
|---|---|
| RPKM tax_id headers -> `names.tax_id` | `test_rpkm_1.tsv`: 8/8 headers matched at least one `names` row; `test_rpkm_2.tsv`: 12/12 headers matched at least one `names` row |
| RPKM tax_id headers -> `nodes.id` | `test_rpkm_1.tsv`: 8/8 headers matched; `test_rpkm_2.tsv`: 12/12 headers matched |
| RPKM tax_id headers -> `parents.tax_id` | `test_rpkm_1.tsv`: 8/8 headers matched; `test_rpkm_2.tsv`: 12/12 headers matched |
| Normalized RPKM `EC#` -> `pathway_nodes.name` | In `test_rpkm_1.tsv`, 9,034 distinct normalized EC values produced 3,258 matched `pathway_nodes` rows |
| `pathway_nodes.pathway -> pathway_superpathways.id -> superpathways.id` | The missing-link query returned 0 displayed rows |

The pathway node name field is not unique. In displayed duplicate-name output, `1.14.14.1` appears 77 times, `Glycolysis / Gluconeogenesis` appears 49 times, and `C00022` appears 48 times. Any EC-to-pathway join can therefore fan out.

## Discrepancies Vs Pre-Validation Model

These are review flags only.

| Area | Expected from logical model | Observed |
|---|---|---|
| `nodes -> names` cardinality | One node can have many names; synonyms are expected | Current dump has exactly 1 `names` row per `tax_id` by the notebook cardinality query |
| RPKM `EC# -> pathway_nodes.name` coverage | 0..many pathway-node matches per normalized EC | `test_rpkm_1.tsv` has 9,034 distinct normalized EC values and 3,258 matched `pathway_nodes` rows |
| Pathway node graph attachment | Pathway nodes participate in pathway graph edges | Displayed dangling-node query shows pathway nodes without source/target edges, led by pathway 1100 with 3,716 dangling nodes |
| RPKM sample overlap | Samples share schema shape, but tax_id overlap had to be measured | `test_rpkm_1.tsv` and `test_rpkm_2.tsv` share 6 tax_id columns; 2 are only in sample 1 and 6 are only in sample 2 |
| Optional `parents` relationship | Some RPKM tax_id headers may have names/nodes but no parents row | Both sample files have complete parent matches in notebook output: 8/8 and 12/12 |

## Gotchas For Future Analytics

- Do not treat tax_id headers as ordinary row values until the RPKM tables are unpivoted.
- Normalize `EC#` values before joining to pathway tables, and expect `0.0.0.0` to dominate when `EC#` is absent.
- `pathway_nodes.name` is many-to-one from the perspective of EC labels; downstream summaries should decide whether to count distinct ECs, pathway nodes, pathways, or superpathways.
- Several notebook outputs are display-limited top-N tables. For exhaustive audits, rerun or extend the underlying SQL cells rather than inferring from visible rows alone.
- The logical ER diagram is intentionally pre-validation. Keep this as-found document updated when new dumps or sample files are introduced.
