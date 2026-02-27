# docrawler

A concurrent web crawler that recursively discovers and downloads documents (PDF, DOCX, and more) from any website.

## Features

- Crawls an entire domain starting from a given URL
- Downloads files matching configurable extensions (`.pdf`, `.docx`, `.doc`, `.odt` by default)
- **Parallel downloads** via a configurable thread pool
- **Resume support** — persists visited and queued URLs to disk so interrupted crawls can be continued
- Automatic retries with exponential backoff on failed requests
- Stays within the target domain (including subdomains)

## Installation

```bash
git clone https://github.com/your-username/docrawler.git
cd docrawler
pip install -r requirements.txt
```

## Usage

```bash
python scraper.py <url> [options]
```

### Arguments

| Argument | Default | Description |
|---|---|---|
| `url` | *(required)* | Starting URL to crawl |
| `-o`, `--output` | `downloads/` | Directory to save downloaded files |
| `-e`, `--extensions` | `.pdf .docx .doc .odt` | File extensions to download |
| `-w`, `--workers` | `5` | Number of concurrent download threads |
| `--domain` | *(inferred from URL)* | Restrict crawling to a specific domain |
| `--visited-file` | `visited.txt` | State file for visited URLs |
| `--queue-file` | `queue.txt` | State file for queued URLs |
| `--log` | `scraper.log` | Log file path |

### Examples

**Basic — download all PDFs from a site:**
```bash
python scraper.py https://example.com
```

**Download only PDFs, save to a specific folder:**
```bash
python scraper.py https://example.com -e .pdf -o ./my-docs
```

**Increase parallelism and add more file types:**
```bash
python scraper.py https://example.com -w 10 -e .pdf .docx .xlsx .pptx
```

**Crawl subdomains under a parent domain:**
```bash
python scraper.py https://docs.example.com --domain example.com
```

**Custom state files (useful for managing multiple crawls):**
```bash
python scraper.py https://example.com --visited-file run1_visited.txt --queue-file run1_queue.txt
```

### Resuming an interrupted crawl

Just re-run the same command — the scraper reads the `visited.txt` and `queue.txt` state files and picks up where it left off:

```bash
python scraper.py https://example.com  # interrupted with Ctrl+C
python scraper.py https://example.com  # resumes automatically
```

## Utilities

`utils.py` provides helpers for managing the crawl state files.

**Remove duplicates from a state file:**
```bash
python utils.py dedup queue.txt
```

**Remove already-visited URLs from the queue:**
```bash
python utils.py subtract queue.txt visited.txt
```

**Merge multiple link files into one:**
```bash
python utils.py merge part1.txt part2.txt part3.txt -o queue.txt
```

## Project structure

```
docrawler/
├── scraper.py       # Main crawler
├── utils.py         # State file utilities
├── requirements.txt
└── .gitignore
```

## Notes

- Only HTML pages are crawled for links; non-HTML responses are skipped
- Files that already exist in the output directory are not re-downloaded
- Errors are logged to `scraper.log` and do not halt the crawl
- Be mindful of a site's `robots.txt` and terms of service before crawling
