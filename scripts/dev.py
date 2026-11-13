"""One-command local development without Docker: embedded PostgreSQL + API + worker.

    python scripts/dev.py up        start database, migrate, API (8000) and worker
    python scripts/dev.py test ...  run pytest against the local *_test database
    python scripts/dev.py seed      load the demo student calendar
    python scripts/dev.py mcp       run the MCP server (stdio)
    python scripts/dev.py db        print the local connection strings

The database lives in .pgdata/ (git-ignored) and keeps running between commands.
"""

import os
import pathlib
import subprocess
import sys
import time

import pixeltable_pgserver as pgserver

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable
APP_DB, TEST_DB = "predestination", "predestination_test"


def database() -> dict[str, str]:
    data = ROOT / ".pgdata" / "cluster"
    data.parent.mkdir(exist_ok=True)
    server = pgserver.get_server(data, cleanup_mode=None)
    existing = server.psql("select datname from pg_database;")
    for name in (APP_DB, TEST_DB):
        if name not in existing:
            server.psql(f'create database "{name}";')
    base = server.get_uri().rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1)
    return {"app": f"{base}/{APP_DB}", "test": f"{base}/{TEST_DB}"}


def env_for_app(urls: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(DATABASE_URL=urls["app"], DATABASE_DIRECT_URL=urls["app"], TEST_DATABASE_URL=urls["test"])
    env.setdefault("APP_BASE_URL", "http://127.0.0.1:8000")
    env["PYTHONPATH"] = str(ROOT)
    return env


def run(args: list[str], env: dict[str, str]) -> int:
    return subprocess.call([PY, *args], cwd=ROOT, env=env)


def up() -> None:
    env = env_for_app(database())
    if run(["-m", "app.db.migrate"], env):
        sys.exit("Migration failed")
    api = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, env=env
    )
    worker = subprocess.Popen([PY, "-m", "app.runtime.worker"], cwd=ROOT, env=env)
    print(
        "\nPredestination is starting: http://127.0.0.1:8000/home  (use 127.0.0.1, not localhost)\n",
        flush=True,
    )
    try:
        while api.poll() is None and worker.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (api, worker):
            if proc.poll() is None:
                proc.terminate()


def main() -> None:
    command, rest = (sys.argv[1] if len(sys.argv) > 1 else "up"), sys.argv[2:]
    if command == "up":
        up()
    elif command == "db":
        print(database())
    elif command == "test":
        env = env_for_app(database())
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        sys.exit(run(["-m", "pytest", *(rest or ["-q"])], env))
    elif command == "seed":
        env = env_for_app(database())
        run(["-m", "app.db.migrate"], env)
        sys.exit(run(["-m", "app.demo_seed", *rest], env))
    elif command == "exec":  # python <args> with the local database configured
        sys.exit(run(rest, env_for_app(database())))
    elif command == "mcp":
        env = env_for_app(database())
        sys.exit(run(["-m", "app.mcp_server"], env))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
