"""Offline checks for the interactive local password reset helper."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


class ResetLocalPasswordTest(unittest.TestCase):
    def test_reset_existing_account_only_and_revoke_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {
                "CAMPUS_SKIP_DOTENV": "1",
                "MEMORY_BACKEND": "sqlite",
                "MEMORY_DB_PATH": str(Path(tmp) / "memory.db"),
                "LANGSMITH_TRACING": "false",
            }
            with patch.dict(os.environ, settings):
                import auth
                import reset_local_password as reset

                auth.init_auth()
                old_token = auth.register("TST2601001", "Oldpass123")
                self.assertTrue(reset.account_exists("TST2601001"))
                self.assertFalse(reset.account_exists("TST2601002"))
                self.assertFalse(reset.reset_password("TST2601002", "Newpass123"))
                with self.assertRaises(ValueError):
                    reset.reset_password("TST2601001", "too-short")
                with self.assertRaises(ValueError):
                    reset.reset_password("TST2601001", "A1" + "x" * 127)
                self.assertTrue(reset.reset_password("TST2601001", "Newpass123"))
                self.assertIsNone(auth.authenticate(old_token))
                with self.assertRaises(auth.AuthError):
                    auth.login("TST2601001", "Oldpass123")
                self.assertTrue(auth.authenticate(auth.login("TST2601001", "Newpass123")))


if __name__ == "__main__":
    unittest.main()
