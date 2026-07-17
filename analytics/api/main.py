from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chord_service import build_chord_from_duckdb
from api.datasets.routes import router as datasets_router
from api.envelope import wrap_handler
from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
)
from api.graph_service import build_graph_from_duckdb
from api.network_service import build_network_from_duckdb
from api.krona_service import build_krona_from_duckdb
from api.overview_service import build_overview_from_duckdb
from api.pathway_list_service import build_pathway_list_from_duckdb
from api.schemas import (
    ChordRequest,
    GraphRequest,
    KronaRequest,
    NetworkRequest,
    OverviewRequest,
    PathwayListRequest,
)

app = FastAPI(title="Metapro Viz API (Python)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets_router, prefix="/api/datasets", tags=["datasets"])


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


@app.post("/api/viz/overview")
def overview_endpoint(body: OverviewRequest):
    def _handle():
        return build_overview_from_duckdb(names=body.names).model_dump()

    return wrap_handler(_handle)


@app.post("/api/viz/pathway-list")
def pathway_list_endpoint(body: PathwayListRequest):
    def _handle():
        return build_pathway_list_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            selected_ann_cat=body.selected_ann_cat,
            selected_taxon=body.selected_taxon,
        )

    return wrap_handler(_handle)


@app.post("/api/viz/krona")
def krona_endpoint(body: KronaRequest):
    def _handle():
        return build_krona_from_duckdb(
            names=body.names,
            tax_rank=body.tax_rank,
            selected_taxon=body.selected_taxon,
        ).model_dump(exclude_none=True)

    return wrap_handler(_handle)


@app.post("/api/viz/graph")
def graph_endpoint(body: GraphRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        return build_graph_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            selected_ann_cat=body.selected_ann_cat,
            selected_taxon=body.selected_taxon,
        )

    return wrap_handler(_handle)


@app.post("/api/viz/network")
def network_endpoint(body: NetworkRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        return build_network_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            selected_taxon=body.selected_taxon,
            pathway_name=body.pathway_name,
            width=body.width,
            height=body.height,
        )

    return wrap_handler(_handle)
