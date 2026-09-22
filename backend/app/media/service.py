import json
import math
import shutil
import subprocess
from pathlib import Path
from backend.app.schema import DomainError
from backend.app.camera.simulator import digest
from backend.app.storage.repository import uid


def command(args, timeout):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise DomainError('MEDIA_UNSUPPORTED', '媒体解码或转码失败，请检查完整原片和 FFmpeg',
                          action='check_media') from exc


def prepare(paths: list[Path], projection, target: Path, settings):
    if projection != 'rectilinear':
        raise DomainError('MEDIA_UNSUPPORTED', '全景、双鱼眼或未知投影需先验证自动处理路径',
                          action='check_format')
    if sum(p.stat().st_size for p in paths) > settings.max_source_bytes:
        raise DomainError('MEDIA_UNSUPPORTED', '源文件超过配置上限', action='configure_limits')
    if shutil.disk_usage(target.parent).free < settings.min_free_bytes:
        raise DomainError('STORAGE_FULL', '本地可用空间低于保留阈值', retryable=True, action='free_space')
    target.mkdir(parents=True, exist_ok=True)
    renditions = []
    offset = 0.0
    for source_index, source in enumerate(paths):
        raw = json.loads(command(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                  '-of', 'json', str(source)], 30))
        streams = [s for s in raw.get('streams', []) if s['codec_type'] == 'video']
        duration = float(raw.get('format', {}).get('duration', 0))
        if not streams or not math.isfinite(duration) or duration <= 0:
            raise DomainError('MEDIA_UNSUPPORTED', '视频时长或画面轨无效')
        # Decode the entire source first: an openable container is not proof of completeness.
        command(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source), '-map', '0:v:0',
                 '-f', 'null', '-'], settings.media_timeout)
        start = 0.0
        while start < duration - 0.001:
            length = min(settings.segment_seconds, duration - start)
            rid = uid('rendition')
            output = target / f'{rid}.mp4'
            command(['ffmpeg', '-v', 'error', '-xerror', '-y', '-ss', str(start), '-i', str(source),
                     '-t', str(length), '-map', '0:v:0', '-an', '-vf',
                     r'scale=trunc(min(960\,iw)/2)*2:-2', '-c:v', 'libx264', '-preset', 'veryfast',
                     '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)], settings.media_timeout)
            info = json.loads(command(['ffprobe', '-v', 'error', '-show_format', '-of', 'json',
                                       str(output)], 30))
            actual = float(info['format']['duration'])
            if abs(actual - length) > 1:
                raise DomainError('MEDIA_UNSUPPORTED', '分析副本时长与来源不一致')
            renditions.append(dict(id=rid, path=str(output), duration=actual, sha256=digest(output),
                                   source_index=source_index, source_start=start,
                                   group_start=offset + start, source_duration=length,
                                   projection='rectilinear', profile='h264-960-v1'))
            start += length
        offset += duration
    return renditions
