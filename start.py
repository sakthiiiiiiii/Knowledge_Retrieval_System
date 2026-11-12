"""Start both local services with one command. Never prints or embeds a session token."""

import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def prepare_env():
    from dotenv import dotenv_values, set_key

    path = ROOT / ".env"

    # Create local configuration only when missing so existing settings and API keys
    # are preserved.
    if not path.exists():
        path.write_text(
            (ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
    values = dotenv_values(path)
    mode = os.environ.get("AUTH_MODE", values.get("AUTH_MODE", "demo"))
    if mode in ("disabled", "demo", ""):
        set_key(path, "AUTH_MODE", "demo")
        os.environ["AUTH_MODE"] = "demo"
        token = os.environ.get("DEMO_API_TOKEN", values.get("DEMO_API_TOKEN", "")) or ""

        # Generate an unpredictable session token instead of shipping a shared
        # credential.
        if len(token) < 24 or token.startswith("REPLACE"):
            token = secrets.token_urlsafe(32)
            set_key(path, "DEMO_API_TOKEN", token)
        os.environ["DEMO_API_TOKEN"] = token
    try:
        path.chmod(0o600)
    except OSError:
        pass
    from dotenv import load_dotenv

    # Let explicit environment settings take priority over the local configuration
    # file.
    load_dotenv(path, override=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    args = parser.parse_args()
    try:
        import requests
        import streamlit
        import uvicorn

        prepare_env()
    except ImportError as exc:
        raise SystemExit(
            "Install dependencies first: python -m pip install -r requirements.txt"
        ) from exc

    # Check both ports first so startup fails clearly if an older server is still
    # running.
    for port in (args.api_port, args.ui_port):
        try:
            with socket.socket() as check:
                check.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SystemExit(
                f"Port {port} is in use. Stop the earlier server, "
                "or choose --api-port and --ui-port."
            ) from exc
    env = dict(os.environ)
    env["API_URL"] = f"http://127.0.0.1:{args.api_port}"
    processes = []
    try:
        # Use this Python interpreter for both services so they share the same virtual
        # environment.
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "hr_rag.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            cwd=ROOT,
            env=env,
        )
        processes.append(api)

        # Wait for the API to respond before the interface attempts to connect.
        for _ in range(100):
            if api.poll() is not None:
                raise RuntimeError("The API exited. Read the error above.")
            try:
                if requests.get(env["API_URL"] + "/health", timeout=1).ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("API startup timed out.")
        print("Preparing the supplied documents…", flush=True)

        # Prepare the searchable corpus before opening the UI for a local demo
        # session.
        if env.get("AUTH_MODE") == "demo":
            response = requests.get(
                env["API_URL"] + "/ready",
                headers={"Authorization": "Bearer " + env["DEMO_API_TOKEN"]},
                timeout=300,
            )
            if not response.ok:
                print(
                    (
                        "Index setup needs attention. Open Connection "
                        "settings in the app for details."
                    ),
                    flush=True,
                )
        ui = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app.py",
                "--server.address=127.0.0.1",
                f"--server.port={args.ui_port}",
                "--browser.gatherUsageStats=false",
            ],
            cwd=ROOT,
            env=env,
        )
        processes.append(ui)
        print(
            f"Open http://localhost:{args.ui_port} — press Ctrl+C here to stop both services.",
            flush=True,
        )
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Stop both child processes on exit so they do not leave occupied ports
        # behind.
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
