"""dbt Python model: wide RPKM TSV → long form.

The scripts package is importable because profiles.yml includes
module_paths: ["transform"], which adds analytics/transform/ to sys.path.

rpkm_path and sample_id are surfaced as model config via dbt_project.yml:
  staging: +rpkm_path / +sample_id rendered from project vars.
Access them with dbt.config.get().
"""

from scripts.stg_rpkm_long import _transform


def model(dbt, session):
    dbt.config(materialized="table")

    rpkm_path = dbt.config.get("rpkm_path")
    sample_id = dbt.config.get("sample_id")

    if not rpkm_path:
        raise ValueError("dbt var 'rpkm_path' is required. Pass via --vars '{rpkm_path: /path}'")
    if not sample_id:
        raise ValueError("dbt var 'sample_id' is required. Pass via --vars '{sample_id: name}'")

    return _transform(session, rpkm_path, sample_id)
