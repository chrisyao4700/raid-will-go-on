#!/usr/bin/env python3
"""把章节源文件合成为 Markdown，同步到固定的 Notion 阅读页。仅使用标准库。"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
API = "https://api.notion.com/v1"
API_VERSION = "2026-03-11"
MAX_REQUEST_BYTES = 500_000


def page_id(value):
    """接受页面 UUID 或 Notion 页面链接，不误用查询字符串中的 ID。"""
    value = value.strip()
    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        if not (
            host in ("notion.so", "notion.site", "notion.com")
            or host.endswith((".notion.so", ".notion.site", ".notion.com"))
        ):
            raise ValueError("页面链接必须属于 Notion")
        value = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    match = re.search(
        r"(?:^|-)([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$",
        value,
    )
    if not match:
        raise ValueError("NOTION_PAGE_ID 必须是页面 UUID 或包含页面 ID 的 Notion 链接")
    return str(uuid.UUID(match.group(1)))


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


def render_manuscript():
    """与合稿工具复用校验和渲染逻辑，只读取正文及章节清单。"""
    spec = importlib.util.spec_from_file_location("manuscript", ROOT / "工具/合稿.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    title, output, parts = module.read_chapters()
    book, _, counts = module.render(title, parts, ROOT / output)
    revision = git("rev-parse", "HEAD")
    updated = git("show", "-s", "--format=%cI", "HEAD")
    digest = hashlib.sha256(book.encode("utf-8")).hexdigest()
    # 不把分支名、提交说明、编辑记录或设定内容发布到阅读页。
    header = (
        f"> 本页由 Git 正文自动更新。版本：`{revision[:12]}`；"
        f"提交时间：{updated}。\n\n"
    )
    first_line, body = book.split("\n", 1)
    markdown = first_line + "\n\n" + header + body.lstrip("\n")
    return markdown, revision, digest, counts


def replacement(markdown):
    body = {
        "type": "replace_content",
        "allow_async": True,
        "replace_content": {
            "new_str": markdown,
            # 保留 Notion 默认保护：拒绝删除已有子页面及数据库。
            "allow_deleting_content": False,
        },
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        raise ValueError("全文超过 Notion 单次请求大小限制；需改为按章发布")
    return data


class Notion:
    def __init__(self, token, *, opener=urlopen, sleep=time.sleep, now=time.monotonic):
        self.token = token
        self.opener = opener
        self.sleep = sleep
        self.now = now

    def request(self, method, path, data=None):
        if not path.startswith(("/pages/", "/async_tasks/")):
            raise ValueError("无效的 Notion API 路径")
        request = Request(
            API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        for attempt in range(5):
            try:
                with self.opener(request, timeout=120) as response:
                    return json.load(response)
            except HTTPError as error:
                # Notion 区分临时限流和需要用户处理的请求封锁。
                try:
                    code = json.load(error).get("code") if error.fp is not None else None
                except (ValueError, OSError):
                    code = None
                retryable = (
                    error.code == 429 and code != "public_api_request_blocked"
                ) or error.code == 529 or (
                    method == "GET" and error.code in (500, 502, 503, 504)
                )
                if retryable and attempt < 4:
                    delay = max(1.0, float(error.headers.get("Retry-After", 2 ** attempt)))
                    if delay > 60:
                        raise RuntimeError("Notion 要求等待超过 60 秒，请稍后重新运行") from None
                    self.sleep(delay)
                    continue
                hints = {
                    400: "请求无效；检查页面大小、内容格式或页面是否包含子页面/数据库",
                    401: "NOTION_TOKEN 无效",
                    403: "连接缺少页面读取/更新权限",
                    404: "页面不存在，或未向该 Notion 连接授权",
                    429: "Notion 请求限流，请稍后重新运行",
                }
                if code == "public_api_request_blocked":
                    raise RuntimeError("Notion 已封锁此连接的 API 请求；请在 Notion 中检查连接") from None
                # 不输出响应正文、请求头或 token。
                raise RuntimeError(
                    f"Notion HTTP {error.code}："
                    + hints.get(error.code, "请求失败；请检查 Notion 服务状态后重试")
                ) from None
            except (URLError, TimeoutError) as error:
                if method == "GET" and attempt < 4:
                    self.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    "Notion 网络请求失败；若写入已被接受，请先检查页面再重跑"
                ) from None
        raise RuntimeError("Notion 请求重试次数耗尽")

    def wait(self, task, timeout=600):
        deadline = self.now() + timeout
        while task.get("object") == "async_task":
            status = task.get("status")
            if status == "succeeded":
                result = task.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Notion 任务成功但缺少写入结果")
                return result
            if status == "failed":
                code = task.get("error", {}).get("code", "unknown")
                # 错误正文可能含页面内容；只报告预定义的错误码。
                known = {"validation_error", "restricted_resource", "object_not_found",
                         "unauthorized", "rate_limited", "internal_server_error"}
                safe_code = code if code in known else "unknown"
                raise RuntimeError(f"Notion 异步写入失败：{safe_code}")
            if status not in ("queued", "running", "retrying"):
                raise RuntimeError("Notion 返回未知的任务状态")
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError("Notion 返回的任务缺少 ID")
            delay = max(1.0, float(task.get("poll_after_seconds", 2)))
            if self.now() + delay >= deadline:
                raise RuntimeError("Notion 异步写入等待超时；请检查页面及任务后重跑")
            self.sleep(delay)
            # 不跟随响应中的 status_url，避免把凭证发往别的主机。
            task = self.request("GET", "/async_tasks/" + quote(task_id, safe=""))
        return task

    def sync(self, target, data):
        page = self.request("GET", "/pages/" + target)
        if page.get("object") != "page" or page_id(page.get("id", "")) != target:
            raise RuntimeError("Notion 返回的目标页面不匹配")
        if page.get("archived") or page.get("in_trash"):
            raise RuntimeError("目标 Notion 页面已归档或位于回收站")
        result = self.wait(self.request("PATCH", f"/pages/{target}/markdown", data))
        if result.get("object") != "page_markdown" or page_id(result.get("id", "")) != target:
            raise RuntimeError("Notion 未返回对应页面的成功写入结果")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="仅生成本地预览，不调用 Notion")
    args = parser.parse_args()
    try:
        markdown, revision, digest, counts = render_manuscript()
        data = replacement(markdown)
        print(f"待同步：{counts[2]}篇，{counts[3]:,}汉字，{len(data):,}字节")
        print(f"Git 版本：{revision}；正文 SHA256：{digest}")
        if args.dry_run:
            preview = ROOT / ".cache/notion-preview.md"
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_text(markdown, encoding="utf-8")
            print("预览已生成：.cache/notion-preview.md（未调用 Notion）")
            return 0
        token = os.environ.get("NOTION_TOKEN", "").strip()
        if not token:
            raise ValueError("缺少 NOTION_TOKEN；请配置 GitHub Actions Secret")
        target = page_id(os.environ.get("NOTION_PAGE_ID", ""))
        Notion(token).sync(target, data)
        print("Notion 已确认全文更新成功")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"同步失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
