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


def run_cli(query: str, export_format: str | None = None, export_path: str | None = None):
    engine = ResearchEngine.from_path(DATA_DIR / "corpus.json")
    result = engine.run(query)
    if export_format:
        payload_by_format = {
            "markdown": result["report_markdown"],
            "html": result["report_html"],
            "json": json.dumps(result, indent=2),
        }
        body = payload_by_format[export_format]
        if export_path:
            Path(export_path).write_text(body, encoding="utf-8")
            print(f"Saved {export_format} report to {export_path}")
        else:
            print(body)
        return
    print(result["report_markdown"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rootstock Hackathon research engine prototype")
    parser.add_argument("--port", type=int, default=8000, help="Local server port")
    parser.add_argument("--query", type=str, help="Run a one-off CLI research query")
    parser.add_argument(
        "--export-format",
        choices=["markdown", "html", "json"],
        help="Export CLI output in the selected format",
    )
    parser.add_argument("--export-path", type=str, help="Optional output path for exported report")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.query:
        run_cli(args.query, args.export_format, args.export_path)
    else:
        run_server(args.port)
