"""Calculate decode progress from consumed bytes and input sizes."""
from pathlib import Path


def input_progress(inputs):
    if not inputs:
        return None
    total = consumed = complete = missing = 0
    for item in inputs:
        try:
            size = Path(item["path"]).stat().st_size
        except OSError:
            missing += 1
            continue
        offset = max(0, item.get("bytes", 0))
        total += size
        consumed += min(offset, size)
        complete += int(offset >= size)
    return dict(
        read_bytes=consumed,
        total_bytes=total,
        files_read=complete,
        total_files=len(inputs),
        missing_files=missing,
        percent=(100.0 * consumed / total) if total and not missing else None,
        complete=not missing and complete == len(inputs),
    )
