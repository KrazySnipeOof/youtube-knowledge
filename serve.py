#!/usr/bin/env python3
"""
Serve the web/ frontend on http://localhost:8000.

The frontend fetches web/data.json, which browsers block when a page is opened
directly from disk (file://). This tiny static server avoids that.

Usage:
  python serve.py            # serve on port 8000
  python serve.py 9000       # serve on a custom port
"""
import http.server
import socketserver
import sys
import webbrowser
from functools import partial
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if not (WEB_DIR / "data.json").exists():
        print("Note: web/data.json not found yet — run the scraper first:")
        print("      python scraper/scrape.py\n")

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB_DIR))
    with socketserver.TCPServer(("", port), handler) as httpd:
        url = f"http://localhost:{port}"
        print(f"Serving {WEB_DIR} at {url}  (Ctrl+C to stop)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
