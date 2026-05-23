import shutil
import subprocess
from pathlib import Path

import pytest


def test_deployment_files_exist():
    assert Path("Dockerfile").exists()
    assert Path("docker-compose.yml").exists()
    assert Path(".dockerignore").exists()
    assert Path(".env.example").exists()


def test_dockerfile_references_streamlit_runtime():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "streamlit" in dockerfile
    assert "app.py --diagnose-config" in dockerfile


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_container_smoke_build_and_diagnose():
    image = "geoqaagent-test:local"
    try:
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pytest.skip("docker daemon is not available")
    subprocess.run(["docker", "build", "-t", image, "."], check=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "GEOQA_AGENT_REPORT_ENABLED=0",
            image,
            "python",
            "app.py",
            "--diagnose-config",
        ],
        check=True,
    )
