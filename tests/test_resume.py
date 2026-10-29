"""Regression checks for persisted download retries, using only a local server."""

import contextlib
import io
import tempfile
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from config import Settings
from scraper import crawl, load_links


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counts = Counter()
        counts = self.counts

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                counts[self.path] += 1
                status = 200
                if self.path in ("/", "/child"):
                    body = b'<a href="/retry.pdf">Retry</a><a href="/ok.pdf">OK</a>'
                    if self.path == "/":
                        body += b'<a href="/child">More links</a>'
                    content_type = "text/html"
                else:
                    body, content_type = b"%PDF-1.4\nfixture", "application/pdf"
                    if self.path == "/retry.pdf" and counts[self.path] == 1:
                        status = 503
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.visited = self.root / "visited.txt"
        self.queue = self.root / "queue.txt"

    def run_crawl(self, path="/"):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            crawl(
                self.base + path, self.base.split("//")[1],
                str(self.root / "downloads"), {".pdf"}, 2,
                str(self.visited), str(self.queue), Settings(retries=0),
            )
        return output.getvalue()

    def test_failed_download_retries_next_run_without_repeating_successes(self):
        with self.assertLogs(level="ERROR"):
            first = self.run_crawl()
        self.assertIn("1 downloaded, 0 already present, 1 failed", first)
        self.assertNotIn(self.base + "/retry.pdf", load_links(str(self.visited)))
        self.assertIn(self.base + "/retry.pdf", load_links(str(self.queue)))
        self.assertEqual(self.counts["/retry.pdf"], 1)

        second = self.run_crawl()
        self.assertIn("1 downloaded, 0 already present, 0 failed", second)
        self.assertEqual(self.counts["/retry.pdf"], 2)
        self.assertEqual(self.counts["/ok.pdf"], 1)
        self.assertEqual(self.counts["/"], 1)
        self.assertIn(self.base + "/retry.pdf", load_links(str(self.visited)))
        self.assertEqual((self.root / "downloads/retry.pdf").read_bytes(), b"%PDF-1.4\nfixture")
        before = self.counts.copy()
        self.run_crawl()
        self.assertEqual(self.counts, before)

    def test_failed_final_save_of_seed_document_is_retried(self):
        with patch("scraper.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertLogs(level="ERROR"):
                first = self.run_crawl("/ok.pdf")
        self.assertIn("0 downloaded, 0 already present, 1 failed", first)
        self.assertFalse((self.root / "downloads/ok.pdf").exists())
        self.assertNotIn(self.base + "/ok.pdf", load_links(str(self.visited)))
        self.assertIn(self.base + "/ok.pdf", load_links(str(self.queue)))
        self.assertIn("1 downloaded, 0 already present, 0 failed", self.run_crawl("/ok.pdf"))
        self.assertFalse((self.root / "downloads/ok.pdf.part").exists())


if __name__ == "__main__":
    unittest.main()
