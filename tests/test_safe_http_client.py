import socket
import unittest

from harness.safe_http_client import SafeHttpError, is_safe_ip, safe_resolve


def fake_resolver(ip: str):
    def _resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    return _resolve


class SafeHttpClientTests(unittest.TestCase):
    def test_rejects_non_http_protocol(self):
        with self.assertRaises(SafeHttpError):
            safe_resolve("file:///etc/passwd", resolver=fake_resolver("8.8.8.8"))

    def test_rejects_private_resolved_ip(self):
        with self.assertRaises(SafeHttpError):
            safe_resolve("https://safe.example.com/news", resolver=fake_resolver("127.0.0.1"))

    def test_rejects_link_local_and_reserved_ips(self):
        self.assertFalse(is_safe_ip("169.254.169.254"))
        self.assertFalse(is_safe_ip("0.0.0.0"))

    def test_allows_public_resolved_ip_when_domain_allowed(self):
        target = safe_resolve(
            "https://finance.example.com/news",
            resolver=fake_resolver("8.8.8.8"),
            allowed_domains=["example.com"],
        )

        self.assertEqual(target.host, "finance.example.com")
        self.assertEqual(target.ip, "8.8.8.8")
        self.assertEqual(target.port, 443)

    def test_rejects_domain_outside_allowlist(self):
        with self.assertRaises(SafeHttpError):
            safe_resolve(
                "https://evil.test/news",
                resolver=fake_resolver("8.8.8.8"),
                allowed_domains=["example.com"],
            )


if __name__ == "__main__":
    unittest.main()
