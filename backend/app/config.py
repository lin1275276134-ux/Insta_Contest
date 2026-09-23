from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class Settings:
    data_dir: Path
    simulation: bool = False
    model_api_key: str = field(default='', repr=False)
    model_name: str = 'qwen3-vl-flash'
    model_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    model_timeout: float = 90
    model_max_video_bytes: int = 7 * 1024**2
    model_video_fps: float = 4
    # Historical probe-only settings. They are not used by the product runtime.
    camera_profile: str = 'unconfigured'
    x5_base_url: str = 'http://192.168.42.1'
    x5_timeout: float = 8
    x5_stable_seconds: float = 10
    x5_readiness_verified: bool = False
    x5_single_lens_confirmed: bool = False
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
        # Parse local key=value data without shell evaluation. Existing process env wins.
        env_path = Path(os.getenv('BOLD_ENV_FILE', Path(__file__).resolve().parents[2] / '.env'))
        values = {}
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, sep, value = line.partition('=')
                if sep and (key.startswith('BOLD_') or key == 'DASHSCOPE_API_KEY'):
                    values[key.strip()] = value.strip().strip('\"').strip("'")
        def setting(key, default):
            return os.environ.get(key, values.get(key, default))
        return cls(data_dir=Path(setting('BOLD_DATA_DIR', 'data')).resolve(),
                   simulation=setting('BOLD_SIMULATION', '0') == '1',
                   model_api_key=setting('DASHSCOPE_API_KEY', ''),
                   model_name=setting('BOLD_MODEL_NAME', 'qwen3-vl-flash'),
                   model_base_url=setting('BOLD_MODEL_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                   model_timeout=float(setting('BOLD_MODEL_TIMEOUT', '90')),
                   model_max_video_bytes=int(setting('BOLD_MODEL_MAX_VIDEO_BYTES', str(7 * 1024**2))),
                   model_video_fps=float(setting('BOLD_MODEL_VIDEO_FPS', '4')),
                   segment_seconds=float(setting('BOLD_SEGMENT_SECONDS', '30')),
                   media_timeout=float(setting('BOLD_MEDIA_TIMEOUT', '1800')),
                   poll_seconds=float(setting('BOLD_POLL_SECONDS', '5')),
                   freshness_seconds=float(setting('BOLD_FRESHNESS_SECONDS', '15')),
                   max_source_bytes=int(setting('BOLD_MAX_SOURCE_BYTES', str(20 * 1024**3))),
                   min_free_bytes=int(setting('BOLD_MIN_FREE_BYTES', str(1024**3))))
