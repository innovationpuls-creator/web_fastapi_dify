from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AppStartupSmokeTests(unittest.TestCase):
    def test_root_entrypoint_registers_chat_and_health_routes(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        temp_root = repo_root / "output" / "test-temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="app-startup-", dir=temp_root))
        try:
            env = os.environ.copy()
            env.update(
                {
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_BASE_URL": "http://127.0.0.1:1234/v1",
                    "OPENAI_MODEL": "test-model",
                    "CHAT_DATABASE_PATH": str(temp_dir / "chat.sqlite3"),
                    "CHAT_ASSETS_DIR": str(temp_dir / "chat-assets"),
                    "CHAT_UPLOADS_DIR": str(temp_dir / "chat-uploads"),
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json; "
                        "from main import app; "
                        "print(json.dumps(sorted(route.path for route in app.routes)))"
                    ),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

        route_paths = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIn("/chat/stream", route_paths)
        self.assertIn("/chat/uploads", route_paths)
        self.assertIn("/conversations", route_paths)
        self.assertIn("/health", route_paths)
        self.assertIn("/health/deep", route_paths)
