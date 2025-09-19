
#!/usr/bin/env python3
"""
Cross-platform launcher that doesn't require executable permissions on macOS Finder.
Double-click me ("Launch App.py").

- Creates .venv (if missing)
- Installs requirements.txt
- Runs gui.py
"""
import os, sys, subprocess, venv, platform, pathlib, shutil

HERE = pathlib.Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
PY_EXE = None

def ensure_venv():
    global PY_EXE
    if not VENV_DIR.exists():
        print("[setup] Creating virtualenv at", VENV_DIR)
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    if platform.system() == "Windows":
        PY_EXE = VENV_DIR / "Scripts" / "python.exe"
        PIP_EXE = VENV_DIR / "Scripts" / "pip.exe"
    else:
        PY_EXE = VENV_DIR / "bin" / "python3"
        PIP_EXE = VENV_DIR / "bin" / "pip"
    # Upgrade pip and install requirements
    print("[setup] Upgrading pip...")
    subprocess.check_call([str(PY_EXE), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])
    req = HERE / "requirements.txt"
    if req.exists():
        print("[setup] Installing requirements from", req)
        subprocess.check_call([str(PIP_EXE), "install", "-r", str(req)])
    else:
        print("[warn] requirements.txt not found; proceeding")

def maybe_fix_permissions():
    """Best-effort: remove quarantine and set +x on .command if present (optional)."""
    cmd = HERE / "Run GUI.command"
    try:
        if cmd.exists():
            try:
                subprocess.run(["xattr", "-d", "com.apple.quarantine", str(cmd)], check=False)
            except Exception:
                pass
            try:
                os.chmod(str(cmd), 0o755)
            except Exception:
                pass
    except Exception:
        pass

def run_gui():
    print("[run] Launching GUI...")
    gui = HERE / "gui.py"
    if not gui.exists():
        print("[error] gui.py not found")
        sys.exit(1)
    # Run gui.py within the venv interpreter
    env = os.environ.copy()
    # Ensure TZ consistent with system; leave as-is
    subprocess.check_call([str(PY_EXE), str(gui)])

if __name__ == "__main__":
    ensure_venv()
    maybe_fix_permissions()
    run_gui()
