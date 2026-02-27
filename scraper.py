"""
docrawler — Concurrent web crawler for bulk document downloading.

Recursively crawls a website and downloads all files matching the given
extensions (PDF, DOCX, etc.) using a thread pool for parallel downloads.
Supports resuming interrupted crawls via persisted state files.
"""

import argparse
import logging
import os
import concurrent.futures
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS = [".pdf", ".docx", ".doc", ".odt"]
DEFAULT_WORKERS = 5
DEFAULT_OUTPUT_DIR = "downloads"
DEFAULT_VISITED_FILE = "visited.txt"
DEFAULT_QUEUE_FILE = "queue.txt"
DEFAULT_LOG_FILE = "scraper.log"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def build_session(retries: int = 3, backoff: float = 1.0) -> requests.Session:
    """Create a requests session with retry logic."""
    strategy = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    adapter = HTTPAdapter(max_retries=strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def get_domain(url: str) -> str:
    return urlparse(url).netloc


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme) and bool(parsed.netloc)


def is_same_domain(url: str, domain: str) -> bool:
    netloc = urlparse(url).netloc
    return netloc == domain or netloc.endswith(f".{domain}")


def get_file_extension(url: str) -> str:
    return os.path.splitext(urlparse(url).path)[-1].lower()


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------

def load_links(filepath: str) -> set:
    """Load a newline-delimited set of URLs from a file."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_links(links: set, filepath: str) -> None:
    """Append URLs to a state file."""
    with open(filepath, "a", encoding="utf-8") as f:
        for link in links:
            f.write(f"{link}\n")


# ---------------------------------------------------------------------------
# Core crawl logic
# ---------------------------------------------------------------------------

def extract_links(session: requests.Session, url: str, domain: str) -> set:
    """
    Fetch a page and return all same-domain links found in anchor tags.
    Returns an empty set on any error or non-HTML response.
    """
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type", ""):
            return set()
        soup = BeautifulSoup(response.text, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            full_url = urljoin(url, a["href"])
            if is_valid_url(full_url) and is_same_domain(full_url, domain):
                links.add(full_url)
        return links
    except requests.RequestException as e:
        logging.error("Failed to fetch %s: %s", url, e)
        return set()


def download_file(session: requests.Session, url: str, output_dir: str) -> None:
    """Download a single file to output_dir. Skips if already present."""
    try:
        filename = urlparse(url).path.split("/")[-1] or "document"
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath):
            logging.debug("Already exists: %s", filename)
            return
        response = session.get(url, timeout=30)
        response.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(response.content)
        print(f"  [+] {filename}")
        logging.info("Downloaded: %s", filename)
    except Exception as e:
        logging.error("Failed to download %s: %s", url, e)


def crawl(
    start_url: str,
    domain: str,
    output_dir: str,
    extensions: set,
    workers: int,
    visited_file: str,
    queue_file: str,
) -> None:
    """
    Crawl `domain` starting from `start_url`, downloading any file whose
    extension is in `extensions`. State is persisted so the crawl can be
    resumed after interruption.
    """
    os.makedirs(output_dir, exist_ok=True)

    visited = load_links(visited_file)
    queue = load_links(queue_file)

    # First run — seed the queue with the start URL
    if not queue:
        queue.add(start_url)

    session = build_session()

    print(f"\nCrawling : {domain}")
    print(f"Output   : {output_dir}")
    print(f"Workers  : {workers}")
    print(f"Filetypes: {', '.join(sorted(extensions))}")
    print(f"Queue    : {len(queue):,} | Visited: {len(visited):,}\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = set()
        while queue:
            url = queue.pop()
            if url in visited:
                continue

            visited.add(url)
            append_links({url}, visited_file)

            if get_file_extension(url) in extensions:
                print(f"Queuing download : {url}")
                future = executor.submit(download_file, session, url, output_dir)
                futures.add(future)
            else:
                print(f"Crawling         : {url}")
                new_links = extract_links(session, url, domain) - visited
                if new_links:
                    queue.update(new_links)
                    append_links(new_links, queue_file)

        # Wait for any remaining downloads
        concurrent.futures.wait(futures)

    print(f"\nDone. Files saved to '{output_dir}/'")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="docrawler",
        description=(
            "Recursively crawl a website and download all documents "
            "matching the specified file extensions."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help="Directory to save downloaded files",
    )
    parser.add_argument(
        "-e", "--extensions",
        nargs="+",
        default=DEFAULT_EXTENSIONS,
        metavar="EXT",
        help="File extensions to download",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help="Number of concurrent download threads",
    )
    parser.add_argument(
        "--domain",
        default=None,
        metavar="DOMAIN",
        help="Restrict crawling to this domain (inferred from URL if omitted)",
    )
    parser.add_argument(
        "--visited-file",
        default=DEFAULT_VISITED_FILE,
        metavar="FILE",
        help="State file tracking visited URLs (enables resume)",
    )
    parser.add_argument(
        "--queue-file",
        default=DEFAULT_QUEUE_FILE,
        metavar="FILE",
        help="State file tracking queued URLs (enables resume)",
    )
    parser.add_argument(
        "--log",
        default=DEFAULT_LOG_FILE,
        metavar="FILE",
        help="Log file path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        filename=args.log,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    domain = args.domain or get_domain(args.url)
    if not domain:
        print("Error: could not determine domain from URL.")
        raise SystemExit(1)

    extensions = {ext if ext.startswith(".") else f".{ext}" for ext in args.extensions}

    crawl(
        start_url=args.url,
        domain=domain,
        output_dir=args.output,
        extensions=extensions,
        workers=args.workers,
        visited_file=args.visited_file,
        queue_file=args.queue_file,
    )


if __name__ == "__main__":
    main()
