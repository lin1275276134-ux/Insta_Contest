from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class Settings:
    data_dir: Path
    simulation: bool = False
    poll_seconds: float = 5
    freshness_seconds: float = 15
    lease_seconds: float = 60
    max_attempts: int = 3
    max_source_bytes: int = 20 * 1024**3
    min_free_bytes: int = 1024**3
    segment_seconds: float = 60
    media_timeout: float = 1800
    allowed_origins: tuple[str, ...] = ('http://127.0.0.1:8765', 'http://localhost:8765',
                                       'http://127.0.0.1:5173', 'http://localhost:5173')

    @classmethod
    def from_env(cls):
        return cls(data_dir=Path(os.getenv('BOLD_DATA_DIR', 'data')).resolve(),
                   simulation=os.getenv('BOLD_SIMULATION', '0') == '1',
                   poll_seconds=float(os.getenv('BOLD_POLL_SECONDS', '5')),
                   freshness_seconds=float(os.getenv('BOLD_FRESHNESS_SECONDS', '15')),
                   max_source_bytes=int(os.getenv('BOLD_MAX_SOURCE_BYTES', str(20 * 1024**3))),
                   min_free_bytes=int(os.getenv('BOLD_MIN_FREE_BYTES', str(1024**3))))
