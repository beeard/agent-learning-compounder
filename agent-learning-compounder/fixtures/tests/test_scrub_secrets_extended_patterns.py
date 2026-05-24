"""Tests for B1: extended scrub_secrets pattern coverage."""

import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def scrub(text: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "scrub_secrets.py")],
        input=text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout


class ExtendedPatternsTests(unittest.TestCase):
    def test_gitlab_pat(self):
        out = scrub("token=glpat-AbCdEfGhIjKlMnOpQrSt")
        self.assertIn("[REDACTED:gitlab_pat]", out)

    def test_huggingface_token(self):
        out = scrub("auth: hf_abcdefghijklmnopqrstuvwxyz012345")
        self.assertIn("[REDACTED:huggingface_token]", out)

    def test_aws_access_key_id(self):
        out = scrub("AKIAIOSFODNN7EXAMPLE")
        # Either label is acceptable since both AWS patterns match this shape.
        self.assertTrue(
            "[REDACTED:aws_access_key]" in out
            or "[REDACTED:aws_access_key_id]" in out,
            msg=out,
        )

    def test_twilio_sid_sk(self):
        sk = "SK" + "0" * 32
        out = scrub(sk)
        self.assertIn("[REDACTED:twilio_sk]", out)

    def test_twilio_sid_ac(self):
        ac = "AC" + "a" * 32
        out = scrub(ac)
        self.assertIn("[REDACTED:twilio_ac]", out)

    def test_telegram_bot_token(self):
        tok = "123456789:" + "A" * 35
        out = scrub(tok)
        self.assertIn("[REDACTED:telegram_bot_token]", out)

    def test_basic_auth_url(self):
        out = scrub("connect to https://alice:s3cret@example.com/api now")
        self.assertIn("[REDACTED:basic_auth_url]", out)

    def test_plain_url_passes_through(self):
        plain = "see https://example.com/path?q=1 for details"
        out = scrub(plain)
        self.assertEqual(plain, out)

    def test_connection_string_mongodb(self):
        out = scrub("mongodb+srv://user:pw@cluster0.mongodb.net/mydb")
        self.assertIn("[REDACTED:connection_string_credentials]", out)

    def test_connection_string_postgres(self):
        out = scrub("postgres://u:p@db.example.com:5432/app")
        self.assertIn("[REDACTED:connection_string_credentials]", out)

    def test_multiline_json_secret(self):
        text = '{"api_key":\n  "abcdef1234567890XYZ"}'
        out = scrub(text)
        # Either the multiline assignment fires, or the generic catch-all does.
        self.assertTrue(
            "[REDACTED:generic_secret_assignment_multiline]" in out
            or "[REDACTED:generic_secret_assignment]" in out,
            msg=out,
        )
        self.assertNotIn("abcdef1234567890XYZ", out)


if __name__ == "__main__":
    unittest.main()
