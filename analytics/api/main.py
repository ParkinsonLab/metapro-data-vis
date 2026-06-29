from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chord_service import build_chord_from_duckdb
from api.envelope import wrap_handler
from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
)
from api.schemas import ChordRequest

app = FastAPI(title="Metapro Viz API (Python)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/viz/chord")
def chord_endpoint(body: ChordRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        if len(body.names) > 1:
            raise ValueError("comparison mode not supported on duckdb backend")
        sample_id = sample_id_from_names(body.names)
        ann_filter = normalise_ann_filter(body.selected_ann_cat, body.ann_level)
        taxon_filter = normalise_taxon_filter(body.selected_taxon)
        return build_chord_from_duckdb(
            sample_id=sample_id,
            tax_level=body.tax_level,
            ann_level=body.ann_level,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
            names=body.names,
        )

    return wrap_handler(_handle)
