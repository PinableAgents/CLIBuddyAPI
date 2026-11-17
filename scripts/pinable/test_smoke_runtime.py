#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
# SPDX-License-Identifier: AGPL-3.0-only
# 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel
"""冒烟脚本辅助函数的测试：不启动运行时，也不发出真实请求。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import smoke_runtime


class SmokeRequestTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("smoke_runtime.urllib.request.build_opener")
        self.opener = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.opener.return_value
        response = self.client.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"ok":true}'

    def request_sent(self):
        args, kwargs = self.client.open.call_args
        self.assertEqual(kwargs, {"timeout": 2})
        self.assertEqual(self.opener.call_args.args[0].proxies, {})
        return args[0]

    def test_get_has_no_body_or_default_authentication(self):
        self.assertEqual(smoke_runtime.request(12345, "/readyz"), (200, b'{"ok":true}'))
        request = self.request_sent()
        self.assertEqual(request.full_url, "http://127.0.0.1:12345/readyz")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header("Authorization"))

    def test_key_is_sent_as_bearer(self):
        smoke_runtime.request(12345, "/panel/api/version", "test-key")
        self.assertEqual(self.request_sent().get_header("Authorization"), "Bearer test-key")

    def test_http_errors_remain_available_to_negative_auth_checks(self):
        self.client.open.side_effect = HTTPError("http://127.0.0.1/", 401, "Unauthorized", {}, io.BytesIO(b"denied"))
        self.assertEqual(smoke_runtime.request(12345, "/panel/api/version", "wrong"), (401, b"denied"))


class HostedServerTests(unittest.TestCase):
    def responses(self, update):
        version = json.dumps({"self_update": update}).encode()
        table = {("/panel/", ""): (200, b"<!doctype html><html></html>"),
                 ("/panel/api/version", ""): (401, b""), ("/panel/api/version", "wrong"): (401, b""),
                 ("/panel/api/version", "key"): (200, version), ("/v1/models", ""): (401, b"")}
        return lambda port, path, key="": table[(path, key)]

    def test_hosted_update_must_be_disabled(self):
        hosted = {"supported": False, "reason": "由 Pinable Desktop 托管，请在 Desktop 的组件管理里更新"}
        with patch("smoke_runtime.request", side_effect=self.responses(hosted)):
            smoke_runtime.check_hosted_server(1, "key")
        for update in ({"supported": True}, {"supported": False, "reason": "Windows 不支持原地重启"}, None):
            with self.subTest(update=update), patch("smoke_runtime.request", side_effect=self.responses(update)), \
                    self.assertRaisesRegex(ValueError, "self-update"):
                smoke_runtime.check_hosted_server(1, "key")

    def test_configuration_is_loopback_only_without_update_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = smoke_runtime.configuration(Path(tmp), 7000, "key")
        self.assertEqual(cfg["listen"], "127.0.0.1:7000")
        self.assertIs(cfg["panel"]["update_check"], False)


if __name__ == "__main__":
    unittest.main()
