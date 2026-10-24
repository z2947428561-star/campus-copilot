"""Probe documented read-only Dorm endpoints; never save credentials or response rows."""
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/local/xmumdorm/preview-gateway-check.json"
HOST = "xmumdorm-200-lyzz-production.up.railway.app"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    base = os.environ.get("PREVIEW_GATEWAY_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.netloc != HOST or parsed.path:
        print("Set PREVIEW_GATEWAY_URL to the team's exact HTTPS gateway origin.")
        return 1
    token = os.environ.get("PREVIEW_GATEWAY_TOKEN", "").strip()
    if not token:
        print("Set PREVIEW_GATEWAY_TOKEN in the process environment.")
        return 1
    headers = {"X-Preview-Token": token,
               "Origin": os.environ.get("PREVIEW_GATEWAY_ORIGIN", "http://localhost:5173")}
    opener = build_opener(NoRedirect())
    report = {"credentials_saved": False, "response_rows_saved": False, "checks": []}

    def probe(path, *, gateway=True, collection=None):
        item = {"path": path, "authenticated_gateway": gateway, "ok": False}
        started = time.monotonic()
        try:
            request = Request(base + path, headers=headers if gateway else {}, method="GET")
            with opener.open(request, timeout=25) as response:
                item["http_status"] = response.status
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("response_too_large")
            payload = json.loads(body)
            item["ok"] = payload.get("status") == 0
            data = payload.get("data") or {}
            if collection:
                rows = data if isinstance(data, list) else data.get(collection)
                item["returned_count"] = len(rows) if isinstance(rows, list) else None
            if isinstance(data, dict) and isinstance(data.get("baseUrl"), str):
                item["public_file_base_configured"] = bool(data["baseUrl"])
        except HTTPError as error:
            item["http_status"] = error.code
        except Exception as error:
            item["error_type"] = type(error).__name__
        item["seconds"] = round(time.monotonic() - started, 2)
        report["checks"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        return item["ok"]

    authenticated = probe("/api/preview/health")
    if authenticated:
        probe("/api/preview/materials/courses?limit=1", collection="courses")
        probe("/api/preview/materials?pageSize=1&page=1", collection="items")
    # Public list is SELECT-only; unlike article detail, it does not increment views.
    probe("/api/handbook/tabs", gateway=False, collection="tabs")
    probe("/api/handbook/articles?tab=all&pageSize=1&page=1", gateway=False, collection="list")
    report["gateway_authenticated"] = authenticated
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(check["ok"] for check in report["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
