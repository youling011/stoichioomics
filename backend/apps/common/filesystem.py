from pathlib import Path
from django.conf import settings


def get_workspace_root() -> Path:
    root = Path(settings.WORKSPACE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_job_dir(job_id: str) -> Path:
    return get_workspace_root() / job_id
