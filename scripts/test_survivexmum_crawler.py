"""Offline privacy and export regression tests; public networking is forbidden."""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import requests
from requests.adapters import HTTPAdapter
import urllib3.util.connection

import crawl_survivexmum as crawler


def response(payload, status=200):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.json.return_value = payload
    return result


class CrawlerTests(unittest.TestCase):
    def setUp(self):
        self.proxy = crawler.ProxyConfig("127.0.0.1", 12345, "fake-user", "fake-password")
        self.client = crawler.WikiClient(self.proxy)
        self.addCleanup(self.client.close)

    def test_config_missing_credentials_prevents_client_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".env.survivexmum"
            config.write_text("WEBSHARE_PROXY_HOST=127.0.0.1\nWEBSHARE_PROXY_PORT=80\n")
            with patch.object(crawler, "WikiClient") as client, patch.object(
                crawler.sys, "argv", ["crawler", "--config", str(config), "--check"]
            ), redirect_stderr(io.StringIO()):
                self.assertEqual(crawler.main(), 1)
            client.assert_not_called()

    def test_config_is_local_only_and_does_not_expand_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".env.survivexmum"
            config.write_text(
                "WEBSHARE_PROXY_HOST=127.0.0.1\nWEBSHARE_PROXY_PORT=80\n"
                "WEBSHARE_PROXY_USERNAME=fake-user\n"
                "WEBSHARE_PROXY_PASSWORD='${SECRET_FROM_OTHER_APP}'\n"
            )
            with patch.dict(os.environ, {"SECRET_FROM_OTHER_APP": "must-not-be-read"}):
                loaded = crawler.ProxyConfig.load(config)
            self.assertEqual(loaded.password, "${SECRET_FROM_OTHER_APP}")
            self.assertNotIn("fake-user", repr(loaded))
            self.assertNotIn("SECRET_FROM_OTHER_APP", repr(loaded))

    def test_proxy_requires_literal_ip_and_encodes_credentials(self):
        with self.assertRaises(crawler.CrawlError):
            crawler.ProxyConfig("proxy.example.invalid", 80, "user", "password")
        proxy = crawler.ProxyConfig("::1", 80, "a@b", "p:#/ word")
        self.assertEqual(proxy.url, "http://a%40b:p%3A%23%2F%20word@[::1]:80")

    def test_explicit_proxy_overrides_environment_and_keeps_tls(self):
        with patch.dict(os.environ, {
            "HTTPS_PROXY": "http://must-not-be-used.invalid:80", "NO_PROXY": "*",
        }), patch.object(self.client._session, "get", return_value=response({
            "code": 0, "data": {"pages": []},
        })) as get:
            self.assertEqual(self.client.get_data("/api/wiki/manifest"), {"pages": []})
        self.assertFalse(self.client._session.trust_env)
        kwargs = get.call_args.kwargs
        self.assertEqual(kwargs["proxies"], {"http": self.proxy.url, "https": self.proxy.url})
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertIs(kwargs["verify"], True)

    def test_proxy_failure_never_retries_or_discloses_secrets(self):
        error = requests.exceptions.ProxyError(f"private proxy URL: {self.proxy.url}")
        with patch.object(self.client._session, "get", side_effect=error) as get:
            with self.assertRaises(crawler.CrawlError) as raised:
                self.client.get_data("/api/wiki/manifest")
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("fake-password", str(raised.exception))
        self.assertNotIn("fake-user", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_redirect_and_denied_responses_stop_immediately(self):
        for status in (301, 302, 307, 401, 403, 407, 429, 503):
            with self.subTest(status=status), patch.object(
                self.client._session, "get", return_value=response({}, status)
            ) as get:
                with self.assertRaises(crawler.CrawlError):
                    self.client.get_data("/api/wiki/manifest")
                self.assertEqual(get.call_count, 1)

    def test_api_error_message_is_not_echoed(self):
        with patch.object(self.client._session, "get", return_value=response({
            "code": 1, "message": "do-not-print-remote-error-or-client-IP",
        })):
            with self.assertRaises(crawler.CrawlError) as raised:
                self.client.get_data("/api/wiki/manifest")
            self.assertNotIn("do-not-print", str(raised.exception))

    def test_adapter_blocks_direct_requests_before_transport(self):
        adapter = crawler.ProxyOnlyAdapter(self.proxy.url)
        self.addCleanup(adapter.close)
        request = requests.Request("GET", crawler.BASE + "/api/wiki/manifest").prepare()
        bad_options = (
            {"proxies": None, "verify": True},
            {"proxies": {"http": self.proxy.url}, "verify": True},
            {"proxies": {"http": self.proxy.url, "https": "http://other.invalid"}, "verify": True},
            {"proxies": self.client._proxies, "verify": False},
        )
        with patch.object(HTTPAdapter, "send") as transport:
            for options in bad_options:
                with self.subTest(options=list(options)), self.assertRaises(crawler.CrawlError):
                    adapter.send(request, **options)
        transport.assert_not_called()

    def test_adapter_blocks_other_hosts_http_and_ip_forwarding_headers(self):
        adapter = crawler.ProxyOnlyAdapter(self.proxy.url)
        self.addCleanup(adapter.close)
        urls = (
            "http://surivivexmum.wiki/api/wiki/manifest",
            "https://other.invalid/api/wiki/manifest",
            crawler.BASE + "/api/user/profile",
            "https://surivivexmum.wiki:444/api/wiki/manifest",
        )
        with patch.object(HTTPAdapter, "send") as transport:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(crawler.CrawlError):
                    adapter.send(requests.Request("GET", url).prepare(),
                                 proxies=self.client._proxies, verify=True)
            for header in ("Forwarded", "X-Forwarded-For", "X-Real-IP", "Client-IP", "True-Client-IP"):
                prepared = requests.Request("GET", crawler.BASE + "/api/wiki/manifest",
                                            headers={header: "192.0.2.1"}).prepare()
                with self.subTest(header=header), self.assertRaises(crawler.CrawlError):
                    adapter.send(prepared, proxies=self.client._proxies, verify=True)
        transport.assert_not_called()

    def test_actual_failed_connect_uses_only_loopback_proxy_without_target_dns(self):
        seen = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                seen.append(self.rfile.readline().decode("ascii").strip())
                while self.rfile.readline().strip():
                    pass
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            proxy = crawler.ProxyConfig("127.0.0.1", server.server_address[1], "fake", "fake")
            client = crawler.WikiClient(proxy)
            original_connect = urllib3.util.connection.create_connection
            original_lookup = socket.getaddrinfo

            def loopback_only(address, *args, **kwargs):
                self.assertEqual(address, server.server_address, "A direct connection was attempted")
                return original_connect(address, *args, **kwargs)

            def proxy_dns_only(host, *args, **kwargs):
                self.assertEqual(host, "127.0.0.1", "Local target DNS lookup was attempted")
                return original_lookup(host, *args, **kwargs)

            try:
                with patch("urllib3.util.connection.create_connection", side_effect=loopback_only), patch(
                    "socket.getaddrinfo", side_effect=proxy_dns_only
                ), self.assertRaises(crawler.CrawlError):
                    client.get_data("/api/wiki/manifest")
            finally:
                client.close()
                server.shutdown()
                thread.join(timeout=2)
        self.assertEqual(len(seen), 1)
        self.assertRegex(seen[0], r"^CONNECT surivivexmum\.wiki:443 HTTP/1\.[01]$")

    def test_export_preserves_metadata_and_never_uses_remote_paths_as_filenames(self):
        path = "../生活篇/CON"
        page = {"path": path, "title": "虚构指南", "category": "生活篇",
                "version": 3, "lastUpdated": "2026-10-03T00:00:00Z", "content": "# 测试正文\n"}
        client = MagicMock()
        client.get_data.side_effect = [
            {"pages": [{"path": "draft", "draft": True}, {"path": path, "category": "生活篇"}]},
            page,
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(crawler.time, "sleep"), patch("builtins.print"):
            output = Path(tmp)
            crawler.crawl(client, output, 2, ["生活篇"], 2)
            snapshot = next(output.iterdir())
            record = json.loads((snapshot / "pages.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["version"], 3)
            self.assertEqual(record["lastUpdated"], page["lastUpdated"])
            self.assertEqual(record["source_type"], "student_wiki")
            self.assertEqual(record["content"], page["content"])
            self.assertEqual(len(record["sha256"]), 64)
            self.assertEqual((snapshot / record["markdown_file"]).read_text(encoding="utf-8"), page["content"])
            self.assertEqual(json.loads((snapshot / "snapshot.json").read_text())["status"], "complete")
            self.assertEqual(len(list(output.iterdir())), 1)
        client.get_data.assert_called_with("/api/wiki/page", {"path": path})

    def test_interrupted_snapshot_is_marked_incomplete(self):
        client = MagicMock()
        client.get_data.side_effect = [
            {"pages": [{"path": "one"}]}, crawler.CrawlError("模拟代理故障"),
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(crawler.time, "sleep"), self.assertRaises(crawler.CrawlError):
            try:
                crawler.crawl(client, Path(tmp), None, [], 2)
            finally:
                snapshot = next(Path(tmp).iterdir())
                self.assertEqual(json.loads((snapshot / "snapshot.json").read_text())["status"], "incomplete")

    def test_interval_rejects_fast_or_invalid_values(self):
        for value in ("0", "1", "nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(crawler.argparse.ArgumentTypeError):
                crawler.crawl_interval(value)


if __name__ == "__main__":
    unittest.main()
