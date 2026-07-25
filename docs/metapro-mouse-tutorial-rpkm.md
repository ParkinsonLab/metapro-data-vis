# MetaPro mouse tutorial: legacy RPKM headers

The analytics pipeline expects **numeric NCBI `tax_id` values** as tax column headers (after the fixed columns `GeneID`, `Length`, `Reads`, `EC#`, `RPKM`). Current MetaPro output uses this format.

The mouse tutorial bundle from [MetaPro_tutorial release 1.0](https://github.com/ParkinsonLab/MetaPro_tutorial/releases/tag/1.0) (assets dated August 2021) ships an older `RPKM_table.tsv`: tax columns use **scientific names** (`Firmicutes`, `Bacteroides`, …) instead of tax ids. Pipeline ingest fails on that header until it is updated.

Use that release for reproducible tutorial data. After unpacking, edit only the **first line** of:

`mouse1_run/outputs/final_results/RPKM_table.tsv`

Data rows stay unchanged. Replace the header with:

```
GeneID	Length	Reads	EC#	RPKM	2	1239	1378168	91061	1224	201174	186802	186803	1235800	1235799	397290	841	397287	1506553	216572	552398	171549	816	671267	194924	1485	459786	1235797	239759	1730	97253	1235835	1235798
```

This header matches the tutorial file’s column order and maps each legacy name to a `tax_id` recognized by the reference taxonomy baked into this app (including NCBI renames such as `Firmicutes` → `1239` / Bacillota and `Bacteroides sartorii` → `671267` / Phocaeicola sartorii).

## Legacy name reference

Lookup for the release 1.0 tutorial columns (same order as the header above):

| Legacy header (tutorial) | tax_id |
|---|---:|
| Bacteria | 2 |
| Firmicutes | 1239 |
| Firmicutes bacterium ASF500 | 1378168 |
| Bacilli | 91061 |
| Proteobacteria | 1224 |
| Actinobacteria | 201174 |
| Clostridiales | 186802 |
| Lachnospiraceae | 186803 |
| Lachnospiraceae bacterium 10-1 | 1235800 |
| Lachnospiraceae bacterium 3-2 | 1235799 |
| Lachnospiraceae bacterium A2 | 397290 |
| Roseburia | 841 |
| Lachnospiraceae bacterium 28-4 | 397287 |
| Lachnoclostridium | 1506553 |
| Ruminococcaceae | 216572 |
| Ruminococcaceae bacterium D16 | 552398 |
| Bacteroidales | 171549 |
| Bacteroides | 816 |
| Bacteroides sartorii | 671267 |
| Desulfovibrionaceae | 194924 |
| Clostridium | 1485 |
| Oscillibacter | 459786 |
| Oscillibacter sp. 1-3 | 1235797 |
| Alistipes | 239759 |
| Eubacterium | 1730 |
| Eubacterium plexicaudatum | 97253 |
| Anaerotruncus sp. G3(2012) | 1235835 |
| Dorea sp. 5-2 | 1235798 |
