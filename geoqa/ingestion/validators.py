from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

SUPPORTED_EXTENSIONS = {".geojson", ".json", ".gpkg", ".zip"}


class ValidationError(ValueError):
    """Raised when the input file fails preflight validation."""


def validate_input_file(path: str | Path, max_size_mb: int = 250) -> Path:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise ValidationError(f"Input file does not exist: {file_path}")
    if not file_path.is_file():
        raise ValidationError(f"Input path is not a file: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{file_path.suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    size_bytes = file_path.stat().st_size
    if size_bytes == 0:
        raise ValidationError("Input file is empty.")
    if size_bytes > max_size_mb * 1024 * 1024:
        raise ValidationError(f"Input exceeds the {max_size_mb} MB limit.")
    if file_path.suffix.lower() == ".zip":
        _validate_zipped_shapefile(file_path)
    return file_path


def _validate_zipped_shapefile(path: Path) -> None:
    with ZipFile(path) as archive:
        names = {Path(name).suffix.lower() for name in archive.namelist() if not name.endswith("/")}
    required = {".shp", ".dbf", ".shx"}
    missing = required - names
    if missing:
        raise ValidationError(
            "Zipped shapefile is missing required components: "
            + ", ".join(sorted(missing))
        )
