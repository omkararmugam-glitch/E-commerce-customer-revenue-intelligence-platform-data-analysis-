"""Start the FastAPI backend and the Streamlit web app together.

    python run_app.py              # API on :8000, web app on :8501, opens the browser
    python run_app.py --no-browser
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
API_PORT, WEB_PORT = 8000, 8501


def wait_for(url: str, timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    env = {**os.environ, "OLIST_API_URL": f"http://127.0.0.1:{API_PORT}"}
    quiet = {"cwd": ROOT, "env": env, "stdin": subprocess.DEVNULL}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app",
                            "--host", "127.0.0.1", "--port", str(API_PORT)], **quiet)
    web = None
    try:
        if not wait_for(f"http://127.0.0.1:{API_PORT}/health"):
            sys.exit("API did not start - check the output above")
        print(f"API ready:  http://127.0.0.1:{API_PORT}/docs", flush=True)

        web = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app/dashboard/streamlit_app.py",
                                "--server.port", str(WEB_PORT), "--server.headless", "true"], **quiet)
        if not wait_for(f"http://localhost:{WEB_PORT}/_stcore/health"):
            sys.exit("Web app did not start - check the output above")
        print(f"Web app:    http://localhost:{WEB_PORT}   (Ctrl+C to stop both)", flush=True)
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://localhost:{WEB_PORT}")
        web.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (web, api):
            if proc and proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
