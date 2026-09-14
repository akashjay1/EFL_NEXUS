import io
import json
import marshal
import os
import unittest
from unittest.mock import patch

from outlook_email_gui import ConfigStore
from patch_auditship_credentials import _bridge_script


class AuditShipCredentialsTests(unittest.TestCase):
    def test_settings_keep_auditship_credentials_separate(self):
        store = ConfigStore("nonexistent-auditship-test-config.json")
        output = io.StringIO()

        class Capture:
            def __enter__(self):
                return output

            def __exit__(self, *args):
                pass

        with patch("builtins.open", return_value=Capture()):
            self.assertTrue(store.save(
                korber_user="cloud-user",
                auditship_user="audit-user",
                auditship_pass=" password with spaces ",
            ))

        saved = json.loads(output.getvalue())
        self.assertEqual(saved["auditship_user"], "audit-user")
        self.assertEqual(saved["auditship_pass"], " password with spaces ")
        self.assertEqual(saved["korber_user"], "cloud-user")
        self.assertEqual(saved["korber_pass"], "")

    def test_bridge_replaces_compiled_login_values(self):
        original = compile(
            'LOGIN_USERNAME = "compiled user"\n'
            'LOGIN_PASSWORD = "compiled password"\n'
            'def login(): return LOGIN_USERNAME, LOGIN_PASSWORD\n',
            "sample_auditship", "exec",
        )
        namespace = {"__name__": "__main__"}
        with patch.dict(os.environ, {
            "AUDITSHIP_USER": "settings-user",
            "AUDITSHIP_PASS": "settings-password",
        }):
            exec(marshal.loads(_bridge_script(marshal.dumps(original))), namespace)

        self.assertEqual(namespace["login"](), ("settings-user", "settings-password"))


if __name__ == "__main__":
    unittest.main()
