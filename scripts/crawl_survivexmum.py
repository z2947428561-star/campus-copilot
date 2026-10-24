"""Download public SurviveXMUM Markdown through one required Webshare proxy.

No direct connection, environment proxy, redirect, retry or login is used.
Snapshots stay in the ignored data/local directory; this does not rebuild RAG.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values
import requests
from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://surivivexmum.wiki"
API_PATHS = {"/api/wiki/manifest", "/api/wiki/page"}


class CrawlError(Exception):
    """A safe user-facing error, never containing credentials or raw responses."""


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self):
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            raise CrawlError("代理地址必须是 Webshare 列表中的 IP 地址。") from None
        if not 1 <= self.port <= 65535 or not self.username or not self.password:
            raise CrawlError("代理端口、用户名或密码未正确配置。")

    @classmethod
    def load(cls, path: Path) -> ProxyConfig:
        if not path.is_file():
            raise CrawlError("缺少本机代理配置文件，请参考 docs/survivexmum.md。")
        # Read only this file. Never interpolate secrets from the process environment.
        values = dotenv_values(path, interpolate=False)
        try:
            return cls(
                host=values.get("WEBSHARE_PROXY_HOST") or "",
                port=int(values.get("WEBSHARE_PROXY_PORT") or "0"),
                username=values.get("WEBSHARE_PROXY_USERNAME") or "",
                password=values.get("WEBSHARE_PROXY_PASSWORD") or "",
            )
        except ValueError:
            raise CrawlError("代理端口必须是整数。") from None

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return (
            f"http://{quote(self.username, safe='')}:{quote(self.password, safe='')}"
            f"@{host}:{self.port}"
        )


class ProxyOnlyAdapter(HTTPAdapter):
    """Guard the final transport call, including requests made outside get_data."""

    def __init__(self, proxy_url: str):
        self._proxy_url = proxy_url
        super().__init__(max_retries=0)

    def send(self, request, **kwargs):
        url = urlsplit(request.url)
        if (
            request.method != "GET"
            or url.scheme != "https"
            or url.netloc != "surivivexmum.wiki"
            or url.path not in API_PATHS
        ):
            raise CrawlError("已拦截非本站公开 HTTPS 文章接口的请求。")
        proxies = kwargs.get("proxies") or {}
        if any(proxies.get(scheme) != self._proxy_url for scheme in ("http", "https")):
            raise CrawlError("已拦截缺少指定代理的请求；禁止直连。")
        if kwargs.get("verify") is not True:
            raise CrawlError("已拦截关闭 HTTPS 证书验证的请求。")
        if any(header in request.headers for header in (
            "Forwarded", "X-Forwarded-For", "X-Real-IP", "Client-IP", "True-Client-IP",
        )):
            raise CrawlError("已拦截携带来源 IP 转发头的请求。")
        return super().send(request, **kwargs)


class WikiClient:
    def __init__(self, proxy: ProxyConfig):
        self._proxies = {"http": proxy.url, "https": proxy.url}
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.headers.update({"User-Agent": "CampusCopilotResearch/0.1"})
        self._session.mount("http://", ProxyOnlyAdapter(proxy.url))
        self._session.mount("https://", ProxyOnlyAdapter(proxy.url))

    def close(self):
        self._session.close()

    def get_data(self, path: str, params: dict | None = None) -> dict:
        try:
            with self._session.get(
                BASE + path,
                params=params,
                proxies=self._proxies.copy(),
                allow_redirects=False,
                verify=True,
                timeout=(10, 30),
            ) as response:
                if response.status_code != 200:
                    raise CrawlError(
                        f"请求返回 HTTP {response.status_code}，已停止；不会重试或直连。"
                    )
                result = response.json()
        except requests.RequestException:
            # requests errors can include authenticated proxy URLs: do not log them.
            raise CrawlError("代理连接或 HTTPS 请求失败，已停止；不会回退直连。") from None
        except ValueError:
            raise CrawlError("接口没有返回有效 JSON，已停止。") from None
        if not isinstance(result, dict) or result.get("code") != 0:
            raise CrawlError("公开文章接口返回错误，已停止。")
        data = result.get("data")
        if not isinstance(data, dict):
            raise CrawlError("公开文章接口的数据格式异常，已停止。")
        return data


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def crawl(client: WikiClient, output: Path, limit: int | None, categories: list[str], interval: float):
    manifest = client.get_data("/api/wiki/manifest")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or any(
        not isinstance(page, dict) or not isinstance(page.get("path"), str) or not page["path"]
        for page in pages
    ):
        raise CrawlError("文章目录格式异常，已停止。")
    selected = [page for page in pages if not page.get("draft") and (
        not categories or page.get("category") in categories
    )]
    if limit is not None:
        selected = selected[:limit]
    run_dir = output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "manifest.json", manifest)
    status = {"status": "in_progress", "selected": len(selected), "saved": 0}
    write_json(run_dir / "snapshot.json", status)
    try:
        with (run_dir / "pages.jsonl").open("w", encoding="utf-8") as index:
            for item in selected:
                time.sleep(interval)
                # No track=1: automated reads must not increment the site's view count.
                page = client.get_data("/api/wiki/page", {"path": item["path"]})
                content = page.get("content")
                if page.get("path") != item["path"] or not isinstance(content, str):
                    raise CrawlError("文章路径或 Markdown 正文格式异常，已停止。")
                record = {
                    "path": page["path"],
                    "title": page.get("title", item.get("title", "")),
                    "category": page.get("category", item.get("category", "")),
                    "version": page.get("version"),
                    "lastUpdated": page.get("lastUpdated"),
                    "source_url": BASE + "/docs/" + quote(page["path"], safe="/"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "source_type": "student_wiki",
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "content": content,
                }
                # Remote paths never become local paths (including ../ or Windows names).
                filename = hashlib.sha256(page["path"].encode("utf-8")).hexdigest() + ".md"
                (run_dir / filename).write_text(content, encoding="utf-8")
                record["markdown_file"] = filename
                index.write(json.dumps(record, ensure_ascii=False) + "\n")
                index.flush()
                status["saved"] += 1
                print(f"已保存 {status['saved']}/{len(selected)} 篇。", flush=True)
        status["status"] = "complete"
    except BaseException:
        status["status"] = "incomplete"
        raise
    finally:
        write_json(run_dir / "snapshot.json", status)
    print(f"抓取完成：{run_dir}")


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须是正整数。")
    return result


def crawl_interval(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 2:
        raise argparse.ArgumentTypeError("请求间隔至少为 2 秒。")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".env.survivexmum")
    parser.add_argument("--output", type=Path, default=ROOT / "data/local/survivexmum")
    parser.add_argument("--limit", type=positive_int, help="只抓前 N 篇公开文章")
    parser.add_argument("--category", action="append", default=[], help="只抓指定分类，可重复")
    parser.add_argument("--interval", type=crawl_interval, default=2.0)
    parser.add_argument("--check", action="store_true", help="只通过代理验证文章目录，不保存正文")
    args = parser.parse_args()
    client = None
    try:
        client = WikiClient(ProxyConfig.load(args.config))
        if args.check:
            manifest = client.get_data("/api/wiki/manifest")
            if not isinstance(manifest.get("pages"), list):
                raise CrawlError("文章目录格式异常。")
            print(f"代理请求成功，目录含 {len(manifest['pages'])} 个条目。")
        else:
            crawl(client, args.output, args.limit, args.category, args.interval)
        return 0
    except CrawlError as error:
        print(f"已停止：{error}", file=sys.stderr)
        return 1
    except OSError:
        print("已停止：本机配置或输出文件无法读写。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("抓取已取消。", file=sys.stderr)
        return 130
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
