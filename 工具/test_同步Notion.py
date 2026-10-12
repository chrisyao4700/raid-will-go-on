"""验证发布边界、Notion 错误处理及异步完成；不访问网络。"""

import importlib.util
from io import BytesIO
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError


spec = importlib.util.spec_from_file_location(
    "notion_sync", Path(__file__).with_name("同步Notion.py")
)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
TARGET = "584e0b9a-371e-82a2-ba26-8108739458ab"


class ClientTests(unittest.TestCase):
    def client(self, replies):
        requests, sleeps = [], []

        def opener(request, timeout):
            requests.append(request)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return BytesIO(json.dumps(reply).encode())

        return sync.Notion("test-token", opener=opener, sleep=sleeps.append), requests, sleeps

    def test_page_url_and_id(self):
        for value in (
            TARGET,
            TARGET.replace("-", ""),
            "https://app.notion.com/p/" + TARGET.replace("-", "") + "?source=copy_link",
            "https://example.notion.site/Reading-" + TARGET.replace("-", ""),
        ):
            self.assertEqual(sync.page_id(value), TARGET)
        for value in ("", "bad", "https://example.com/" + TARGET):
            with self.assertRaises(ValueError):
                sync.page_id(value)

    def test_unicode_payload_and_child_page_protection(self):
        data = sync.replacement("# 小说\n\n“我来。”\n\n---\n")
        self.assertIn("小说".encode(), data)
        body = json.loads(data)
        self.assertEqual(body["replace_content"]["new_str"], '# 小说\n\n“我来。”\n\n---\n')
        self.assertFalse(body["replace_content"]["allow_deleting_content"])
        self.assertTrue(body["allow_async"])
        with self.assertRaises(ValueError):
            sync.replacement("中" * 200_000)

    def test_async_success_polls_known_api_host(self):
        page = {"object": "page", "id": TARGET}
        result = {"object": "page_markdown", "id": TARGET}
        task = {"object": "async_task", "id": "task_test", "status": "queued",
                "status_url": "https://example.com/leak", "poll_after_seconds": 2}
        client, requests, sleeps = self.client([
            page, task,
            {**task, "status": "running"},
            {**task, "status": "succeeded", "result": result},
        ])
        client.sync(TARGET, sync.replacement("# 正文"))
        self.assertEqual([r.method for r in requests], ["GET", "PATCH", "GET", "GET"])
        self.assertTrue(all(r.full_url.startswith(sync.API + "/") for r in requests))
        self.assertEqual(sleeps, [2, 2])

    def test_async_failure_does_not_pass_or_expose_response(self):
        client, _, _ = self.client([])
        with self.assertRaisesRegex(RuntimeError, "validation_error") as caught:
            client.wait({"object": "async_task", "status": "failed",
                         "error": {"code": "validation_error", "message": "private content"}})
        self.assertNotIn("private", str(caught.exception))

    def test_async_timeout(self):
        client, requests, _ = self.client([])
        with self.assertRaisesRegex(RuntimeError, "超时"):
            client.wait({"object": "async_task", "id": "test", "status": "running",
                         "poll_after_seconds": 2}, timeout=1)
        self.assertEqual(requests, [])

    def test_archived_page_is_not_written(self):
        client, requests, _ = self.client([{"object": "page", "id": TARGET, "archived": True}])
        with self.assertRaisesRegex(RuntimeError, "归档"):
            client.sync(TARGET, sync.replacement("# 正文"))
        self.assertEqual(len(requests), 1)

    def test_rate_limit_is_retried(self):
        error = HTTPError(sync.API, 429, "rate limited", {"Retry-After": "3"}, None)
        client, requests, sleeps = self.client([error, {"object": "page_markdown", "id": TARGET}])
        client.request("PATCH", f"/pages/{TARGET}/markdown", sync.replacement("# 正文"))
        self.assertEqual(len(requests), 2)
        self.assertEqual(sleeps, [3])

    def test_ambiguous_write_failure_is_not_retried(self):
        error = HTTPError(sync.API, 503, "unavailable", {}, None)
        client, requests, _ = self.client([error])
        with self.assertRaisesRegex(RuntimeError, "503"):
            client.request("PATCH", f"/pages/{TARGET}/markdown", sync.replacement("# 正文"))
        self.assertEqual(len(requests), 1)

    def test_blocked_connection_is_not_retried(self):
        error = HTTPError(
            sync.API, 429, "blocked", {"Retry-After": "3"},
            BytesIO(b'{"code":"public_api_request_blocked"}'),
        )
        client, requests, sleeps = self.client([error])
        with self.assertRaisesRegex(RuntimeError, "封锁"):
            client.request("PATCH", f"/pages/{TARGET}/markdown", sync.replacement("# 正文"))
        self.assertEqual(len(requests), 1)
        self.assertEqual(sleeps, [])

    def test_denied_page_is_not_written(self):
        error = HTTPError(sync.API, 404, "not found", {}, None)
        client, requests, _ = self.client([error])
        with self.assertRaisesRegex(RuntimeError, "授权"):
            client.sync(TARGET, sync.replacement("# 正文"))
        self.assertEqual(len(requests), 1)

    def test_render_uses_all_manuscript_sources_without_editor_notes(self):
        markdown, revision, digest, counts = sync.render_manuscript()
        self.assertEqual(counts[2], 24)
        self.assertEqual(len(revision), 40)
        self.assertEqual(len(digest), 64)
        for heading in ("# 下周照常开团", "### 第1章", "### 尾声", "## 第四部"):
            self.assertIn(heading, markdown)
        self.assertNotIn("## Git约定", markdown)
        self.assertNotIn("v4基线校验", markdown)
        self.assertLess(len(sync.replacement(markdown)), sync.MAX_REQUEST_BYTES)


if __name__ == "__main__":
    unittest.main()
