import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_entry_point_loads_bundled_dataset(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None

    dist = tmp_path / "dist"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    wheel = next(dist.glob("*.whl"))

    venv = tmp_path / "venv"
    subprocess.run(
        [uv, "venv", "--python", sys.executable, str(venv)],
        text=True,
        capture_output=True,
        check=True,
    )
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        text=True,
        capture_output=True,
        check=True,
    )

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [scripts / ("sparseir-check-dataset.exe" if os.name == "nt" else "sparseir-check-dataset")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "loaded 3 records" in completed.stdout
    assert "grids: 2x2, 4x4, 6x6" in completed.stdout
