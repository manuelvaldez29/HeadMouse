"""Guardado atómico que tolera bloqueos transitorios de OneDrive/antivirus."""
import unittest
from unittest.mock import patch
import profiles


class ReplaceRetryTests(unittest.TestCase):
    def test_retries_transient_permission_errors(self):
        calls = []
        def flaky(source, target):
            calls.append((source, target))
            if len(calls) < 3:
                raise PermissionError(5, "Acceso denegado")
        with patch.object(profiles.os, "replace", flaky), patch.object(profiles.time, "sleep"):
            profiles.replace_with_retry("a.tmp", "b.json")
        self.assertEqual(len(calls), 3)

    def test_persistent_lock_still_fails(self):
        with patch.object(profiles.os, "replace", side_effect=PermissionError(5, "Acceso denegado")), \
                patch.object(profiles.time, "sleep"):
            with self.assertRaises(PermissionError):
                profiles.replace_with_retry("a.tmp", "b.json", attempts=3)


if __name__ == "__main__": unittest.main()
