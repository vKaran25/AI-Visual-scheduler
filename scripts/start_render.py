"""Run migrations, then supervise both Predestination processes on Render."""

import os
import signal
import subprocess
import sys
import time


def stop_service(_signum, _frame):
    raise SystemExit(0)


def main():
    for name in ("DATABASE_URL", "DATABASE_DIRECT_URL", "JWT_SECRET_KEY", "PORT"):
        if not os.environ.get(name):
            raise SystemExit(f"Set {name} before starting Predestination.")

    if not os.environ.get("APP_BASE_URL"):
        os.environ["APP_BASE_URL"] = os.environ["RENDER_EXTERNAL_URL"]
    os.environ["COOKIE_SECURE"] = "true"
    python = sys.executable
    subprocess.run([python, "-m", "app.db.migrate"], check=True)

    signal.signal(signal.SIGTERM, stop_service)
    processes = {}
    try:
        processes["worker"] = subprocess.Popen([python, "-m", "app.runtime.worker"])
        processes["web"] = subprocess.Popen(
            [
                python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                os.environ["PORT"],
                "--workers",
                "1",
            ]
        )
        while True:
            for name, process in processes.items():
                if (code := process.poll()) is not None:
                    raise SystemExit(f"Predestination {name} exited unexpectedly (status {code}).")
            time.sleep(0.5)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
