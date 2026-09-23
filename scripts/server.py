"""Local server lifecycle with foreground and explicit background modes."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
data = Path(os.getenv('BOLD_DATA_DIR', root / 'data')).resolve()
data.mkdir(parents=True, exist_ok=True)
pidfile = data / 'server.pid'
host = os.getenv('BOLD_HOST', '127.0.0.1')
port = int(os.getenv('BOLD_PORT', '8765'))
server_url = f'http://{host}:{port}'
health_url = f'{server_url}/api/v1/health'


def read_pid():
    try:
        return int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def process_command(pid):
    try:
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else ''


def alive(pid):
    command = process_command(pid)
    if command is None:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    return bool(command and (
        'scripts/server.py run' in command
        or 'uvicorn backend.app.api.main:app' in command
    ))


def clear_stale_pidfile():
    pid = read_pid()
    if pid is not None and alive(pid):
        return pid
    pidfile.unlink(missing_ok=True)
    return None


def wait_until_ready(process=None):
    for _ in range(80):
        if process is not None and process.poll() is not None:
            return False
        try:
            with urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def run_foreground():
    running = clear_stale_pidfile()
    if running and running != os.getpid():
        sys.exit(f'服务已在运行（PID {running}）：{server_url}')
    pidfile.write_text(str(os.getpid()))
    try:
        import uvicorn
        uvicorn.run('backend.app.api.main:app', host=host, port=port)
    finally:
        if read_pid() == os.getpid():
            pidfile.unlink(missing_ok=True)


def start_background():
    running = clear_stale_pidfile()
    if running:
        sys.exit(f'服务已在运行（PID {running}）：{server_url}')
    (data / 'logs').mkdir(exist_ok=True)
    with (data / 'logs/server.log').open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), 'run'],
            cwd=root, stdout=log, stderr=log, start_new_session=True,
        )
    if not wait_until_ready(process):
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
        sys.exit('启动失败或服务尚未响应，请查看数据目录下 logs/server.log。')
    print(f'拍摄工作台：{server_url}（后台 PID {process.pid}）')
    print('停止服务：scripts/stop')


def stop():
    pid = read_pid()
    if pid is None:
        sys.exit('没有此数据目录的启动记录。')
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(120):
            if not alive(pid):
                break
            time.sleep(0.25)
        else:
            sys.exit('服务仍在优雅退出，保留 PID 记录；稍后再次运行 scripts/stop。')
    pidfile.unlink(missing_ok=True)
    print('服务已停止；项目、任务和媒体均保留。')


def status():
    pid = clear_stale_pidfile()
    if pid:
        print(f'服务运行中（PID {pid}）：{server_url}')
        return
    print('服务未运行。')


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'run'
    actions = {'run': run_foreground, 'background': start_background, 'stop': stop, 'status': status}
    if command not in actions:
        sys.exit('用法：server.py [run|background|stop|status]')
    actions[command]()


if __name__ == '__main__':
    main()
