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

from config import Settings, load_settings


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS = Settings()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def build_session(
    retries: int = DEFAULTS.retries,
    backoff: float = DEFAULTS.backoff,
    user_agent: str = DEFAULTS.user_agent,
) -> requests.Session:
    """Create a requests session with retry logic."""
    strategy = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
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
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


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
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "a", encoding="utf-8") as f:
        for link in links:
            f.write(f"{link}\n")


# ---------------------------------------------------------------------------
# Core crawl logic
# ---------------------------------------------------------------------------

def extract_links(
    session: requests.Session, url: str, domain: str,
    timeout: float = DEFAULTS.page_timeout,
) -> set:
    """
    Fetch a page and return all same-domain links found in anchor tags.
    Returns an empty set on any error or non-HTML response.
    """
    try:
        response = session.get(url, timeout=timeout)
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
    except (requests.RequestException, ValueError) as e:
        logging.error("Failed to fetch %s: %s", url, e)
        return set()


def download_file(
    session: requests.Session, url: str, output_dir: str,
    timeout: float = DEFAULTS.download_timeout,
) -> str:
    """Return downloaded, skipped, or failed without leaving a partial final file."""
    try:
        filename = urlparse(url).path.split("/")[-1] or "document"
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath):
            logging.debug("Already exists: %s", filename)
            return "skipped"
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        # A failed write must not become an existing file on the next run.
        partial_path = filepath + ".part"
        with open(partial_path, "wb") as f:
            f.write(response.content)
        os.replace(partial_path, filepath)
        print(f"  [+] {filename}")
        logging.info("Downloaded: %s", filename)
        return "downloaded"
    except (requests.RequestException, OSError, ValueError) as e:
        logging.error("Failed to download %s: %s", url, e)
        print(f"  [!] Download failed: {url}. See the log for details.")
        return "failed"


def crawl(
    start_url: str,
    domain: str,
    output_dir: str,
    extensions: set,
    workers: int,
    visited_file: str,
    queue_file: str,
    settings: Settings = DEFAULTS,
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
        append_links({start_url}, queue_file)

    session = build_session(settings.retries, settings.backoff, settings.user_agent)

    print(f"\nCrawling : {domain}")
    print(f"Output   : {output_dir}")
    print(f"Workers  : {workers}")
    print(f"Filetypes: {', '.join(sorted(extensions))}")
    print(f"Queue    : {len(queue):,} | Visited: {len(visited):,}\n")

    with session, concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        scheduled = set()
        results = {"downloaded": 0, "skipped": 0, "failed": 0}
        while queue:
            url = queue.pop()
            if url in visited or url in scheduled:
                continue

            if get_file_extension(url) in extensions:
                print(f"Queuing download : {url}")
                future = executor.submit(
                    download_file, session, url, output_dir, settings.download_timeout
                )
                futures[future] = url
                scheduled.add(url)
            else:
                visited.add(url)
                append_links({url}, visited_file)
                print(f"Crawling         : {url}")
                new_links = extract_links(session, url, domain, settings.page_timeout) - visited
                if new_links:
                    queue.update(new_links)
                    append_links(new_links, queue_file)

        # Only completed downloads enter visited; failures stay in the saved queue.
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result] += 1
            if result != "failed":
                url = futures[future]
                visited.add(url)
                append_links({url}, visited_file)

    print(
        f"\nSummary: {results['downloaded']} downloaded, "
        f"{results['skipped']} already present, {results['failed']} failed"
    )
    if results["failed"]:
        print("Failed downloads remain queued. Re-run with the same state files to retry.")
    print(f"\nDone. Files saved to '{output_dir}/'")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parse_args(settings: Settings = DEFAULTS) -> argparse.Namespace:
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
        default=settings.output_dir,
        metavar="DIR",
        help="Directory to save downloaded files",
    )
    parser.add_argument(
        "-e", "--extensions",
        nargs="+",
        default=list(settings.extensions),
        metavar="EXT",
        help="File extensions to download",
    )
    parser.add_argument(
        "-w", "--workers",
        type=positive_int,
        default=settings.workers,
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
        default=settings.visited_file,
        metavar="FILE",
        help="State file tracking visited URLs (enables resume)",
    )
    parser.add_argument(
        "--queue-file",
        default=settings.queue_file,
        metavar="FILE",
        help="State file tracking queued URLs (enables resume)",
    )
    parser.add_argument(
        "--log",
        default=settings.log_file,
        metavar="FILE",
        help="Log file path",
    )
    args = parser.parse_args()
    try:
        if not is_valid_url(args.url):
            parser.error("url must be an absolute http:// or https:// URL")
        if args.domain and (
            not is_valid_url(f"https://{args.domain}")
            or urlparse(f"https://{args.domain}").netloc != args.domain
            or not is_same_domain(args.url, args.domain)
        ):
            parser.error("--domain must be a host containing the starting URL")
        paths = [os.path.normcase(os.path.abspath(p)) for p in (
            args.visited_file, args.queue_file, args.log
        )]
        if len(set(paths)) != len(paths):
            parser.error("visited, queue, and log files must use different paths")
    except ValueError as e:
        parser.error(f"invalid URL or path: {e}")
    return args


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as e:
        raise SystemExit(f"Configuration error: {e}") from None
    args = parse_args(settings)

    domain = args.domain or get_domain(args.url)
    if not domain:
        print("Error: could not determine domain from URL.")
        raise SystemExit(1)

    extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in args.extensions}

    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
        logging.basicConfig(
            filename=args.log,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        crawl(
            start_url=args.url,
            domain=domain,
            output_dir=args.output,
            extensions=extensions,
            workers=args.workers,
            visited_file=args.visited_file,
            queue_file=args.queue_file,
            settings=settings,
        )
    except (OSError, UnicodeError) as e:
        logging.error("Cannot access crawl files: %s", e)
        raise SystemExit(f"File error: {e}. Check the configured paths and permissions.") from None
    except KeyboardInterrupt:
        raise SystemExit("Crawl interrupted. Re-run with the same state files to resume discovery.") from None


if __name__ == "__main__":
    main()
