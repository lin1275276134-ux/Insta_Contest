"""Local launcher. PID and invocation checked before termination."""
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


def alive(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
    return result.returncode == 0 and 'uvicorn backend.app.api.main:app' in result.stdout


if sys.argv[1] == 'stop':
    if not pidfile.exists():
        sys.exit('没有此数据目录的启动记录。')
    pid = int(pidfile.read_text())
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(120):
            if not alive(pid):
                break
            time.sleep(0.25)
        else:
            sys.exit('服务仍在优雅退出，保留 PID 记录；稍后再次运行 stop。')
    pidfile.unlink(missing_ok=True)
    print('服务已停止；项目、任务和媒体均保留。')
else:
    if pidfile.exists() and alive(int(pidfile.read_text())):
        sys.exit('服务已在运行：http://127.0.0.1:8765')
    (data / 'logs').mkdir(exist_ok=True)
    with (data / 'logs/server.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.api.main:app',
                                    '--host', '127.0.0.1', '--port', '8765'], cwd=root,
                                   stdout=log, stderr=log, start_new_session=True)
    pidfile.write_text(str(process.pid))
    for _ in range(60):
        if process.poll() is not None:
            pidfile.unlink(missing_ok=True)
            sys.exit('启动失败，请查看数据目录下 logs/server.log。')
        try:
            with urlopen('http://127.0.0.1:8765/api/v1/health', timeout=1) as response:
                if response.status == 200:
                    print('拍摄工作台：http://127.0.0.1:8765')
                    break
        except OSError:
            pass
        time.sleep(0.25)
    else:
        sys.exit('服务尚未响应，请查看数据目录下 logs/server.log。')
