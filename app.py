import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from engine import ResearchEngine


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"


class ResearchRequestHandler(SimpleHTTPRequestHandler):
    engine = ResearchEngine.from_path(DATA_DIR / "corpus.json")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self._send_json({"ok": True, "documents": len(self.engine.documents)})
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/research":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Body must be valid JSON")
            return

        query = str(payload.get("query", "")).strip()
        if not query:
            self.send_error(HTTPStatus.BAD_REQUEST, "Query is required")
            return

        result = self.engine.run(query)
        self._send_json(result)

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), ResearchRequestHandler)
    print(f"Serving Rootstock research engine at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


def run_cli(query: str):
    engine = ResearchEngine.from_path(DATA_DIR / "corpus.json")
    result = engine.run(query)
    print(result["report_markdown"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rootstock Hackathon research engine prototype")
    parser.add_argument("--port", type=int, default=8000, help="Local server port")
    parser.add_argument("--query", type=str, help="Run a one-off CLI research query")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.query:
        run_cli(args.query)
    else:
        run_server(args.port)
