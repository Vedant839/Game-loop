"""Production app configuration must not register local media serving."""

import os
import subprocess
import sys


def test_media_route_is_404_in_production(tmp_path):
    env = os.environ.copy()
    env["ENV"] = "production"
    env["GAME_LOOP_DB_PATH"] = str(tmp_path / "production-test.db")
    code = (
        "from fastapi.testclient import TestClient; "
        "from backend.main import app; "
        "assert TestClient(app).get('/media/not-a-real-file.mp4').status_code == 404"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True, text=True)
