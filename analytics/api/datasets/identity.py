from pathlib import Path


def sample_id_from_path(data_root: Path, rpkm_path: Path) -> str:
    rel = rpkm_path.relative_to(data_root)
    parent = rel.parent
    if str(parent) == ".":
        return "_root"
    return str(parent).replace("/", "__")


def dev_fixture_sample_id(path: Path | str) -> str:
    return Path(path).stem
