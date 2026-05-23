from __future__ import annotations

import json
from pathlib import Path

from geoqa.models import RunRecord


def write_run_log(run_record: RunRecord, output_root: str | Path) -> str:
    log_path = Path(output_root) / "run_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_record.to_dict()) + "\n")
    return str(log_path)
