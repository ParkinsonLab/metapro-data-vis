from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

_ANALYTICS_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_REFERENCE_PARQUET_DIR = _ANALYTICS_DIR / "transform" / "reference" / "parquet"


@dataclass(frozen=True)
class Settings:
    data_root: Path
    runs_dir: Path
    reference_parquet_dir: Path
    enable_dev_datasets: bool


@lru_cache
def get_settings() -> Settings:
    data_root = Path(os.environ.get("DATA_ROOT", "./local-data")).resolve()
    runs_dir = Path(os.environ.get("RUNS_DIR", str(data_root / "vis" / "runs"))).resolve()
    ref = Path(
        os.environ.get("REFERENCE_PARQUET_DIR", str(_DEFAULT_REFERENCE_PARQUET_DIR))
    ).resolve()
    dev = os.environ.get("ENABLE_DEV_DATASETS", "0") == "1"
    return Settings(
        data_root=data_root,
        runs_dir=runs_dir,
        reference_parquet_dir=ref,
        enable_dev_datasets=dev,
    )


def db_path(sample_id: str) -> Path:
    return get_settings().runs_dir / sample_id / "sample.duckdb"
