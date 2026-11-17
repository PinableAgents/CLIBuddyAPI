#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
# SPDX-License-Identifier: AGPL-3.0-only
# 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel
"""在目标系统上实际运行打好的程序，检查 Pinable Desktop 宿主契约；不需要任何账号凭证。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).parent))
import runtime

# 宿主契约版本，与 cmd/server/hosted.go 的 hostContractVersion 一致。
CONTRACT_VERSION = "1"
# 托管模式下面板一键更新的拒绝原因里一定带这个词。
HOSTED_REASON_MARK = "Pinable Desktop"


def request(port, path, key="", method="GET", data: bytes | None = None):
    headers = {"Authorization": "Bearer " + key} if key else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    elif method == "POST":
        data = b""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers, data=data, method=method)
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(req, timeout=2) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_until(predicate, process, description, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        runtime.require(process.poll() is None, "runtime exited before " + description)
        try:
            if predicate():
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)  # 有上限的集成就绪轮询，不是单元测试时钟。
    raise ValueError("timed out waiting for " + description)


def stop(process):
    if process is not None and process.poll() is None:
        process.kill()
        process.wait(timeout=10)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def configuration(case: Path, port: int, key: str) -> dict:
    """与 Desktop 写入的托管配置同形：只听回环地址，关闭更新检查，数据放在 case 目录。"""
    return {"listen": f"127.0.0.1:{port}", "api_key": key,
            "auth_dir": str(case / "auths"), "state_file": str(case / "data" / "state.json"),
            "panel": {"update_check": False}}


def probe_metadata(binary: Path, isolated: Path, env: dict, manifest: dict, checks: list) -> None:
    output = subprocess.check_output([str(binary), "-version"], cwd=isolated, env=env, timeout=10, text=True)
    runtime.require(len(output.splitlines()) == 1 and output.strip(), "version probe must print one line")
    output = subprocess.check_output([str(binary), "-runtime-info"], cwd=isolated, env=env, timeout=10, text=True)
    runtime.require(len(output.splitlines()) == 1, "runtime info must be one JSON line")
    info = json.loads(output)
    runtime.require(info.get("contract_version") == CONTRACT_VERSION
                    and info.get("component_version") == manifest["version"]
                    and info.get("commit") == manifest["source"]["commit"]
                    and info.get("commit_time") == manifest["source"]["commit_time"],
                    "runtime info metadata mismatch")
    runtime.require(not list(isolated.iterdir()), "metadata probes must not start services or create files")
    checks.append("version and runtime-info probes without configuration")


def check_hosted_server(port: int, key: str) -> None:
    code, body = request(port, "/panel/")
    runtime.require(code == 200 and b"<html" in body.lower(), "embedded web panel unavailable")
    runtime.require(request(port, "/panel/api/version")[0] in (401, 403), "panel API must require the key")
    runtime.require(request(port, "/panel/api/version", "wrong")[0] in (401, 403), "panel accepted a wrong key")
    code, body = request(port, "/panel/api/version", key)
    runtime.require(code == 200, "panel API rejected the configured key")
    update = json.loads(body).get("self_update") or {}
    runtime.require(update.get("supported") is False and HOSTED_REASON_MARK in update.get("reason", ""),
                    "self-update must be disabled while hosted")
    runtime.require(request(port, "/v1/models")[0] in (401, 403), "public API must require a key")


def smoke(artifact_dir: Path):
    manifests = list(artifact_dir.glob("*.manifest.json"))
    runtime.require(len(manifests) == 1, "expected one native platform artifact")
    manifest, _ = runtime.verify(manifests[0])
    target = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"x86_64": "amd64", "AMD64": "amd64", "arm64": "arm64", "aarch64": "arm64", "ARM64": "arm64"}[platform.machine()]
    runtime.require(manifest["target"] == target + "/" + arch, "smoke must run on the native target architecture")
    checks = []
    with tempfile.TemporaryDirectory(prefix="pinable-runtime-smoke-") as tmp:
        root = Path(tmp)
        binary = root / runtime.binary_name(manifest["target"])
        runtime.stage(manifests[0], binary, manifest["source"]["commit"], manifest["binary"]["sha256"])
        isolated = root / "empty"
        isolated.mkdir()
        # WB2A_* 会覆盖配置文件，冒烟只认写进去的托管配置。
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("WB2A_")}
        probe_metadata(binary, isolated, env, manifest, checks)
        if target == "darwin":
            subprocess.run(["codesign", "--verify", "--strict", str(binary)], check=True)
            checks.append("ad-hoc signature verified after extraction")

        for test_parent_exit in (False, True):
            case = root / ("parent-exit" if test_parent_exit else "hosted")
            case.mkdir()
            key = secrets.token_hex(24)
            port = free_port()
            cfg = case / "config.json"
            cfg.write_text(json.dumps(configuration(case, port, key)), encoding="utf-8")
            parent = process = None
            try:
                if test_parent_exit:
                    parent = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait()"],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                parent_pid = parent.pid if parent else os.getpid()
                with (case / "process.log").open("wb") as log:
                    process = subprocess.Popen([str(binary), "-config", str(cfg), "-parent-pid", str(parent_pid)],
                                               cwd=case, env=env, stdout=log, stderr=subprocess.STDOUT)
                    wait_until(lambda: request(port, "/readyz")[0] == 200, process, "readiness")
                    if test_parent_exit:
                        stop(parent)
                        process.wait(timeout=20)
                        runtime.require(process.returncode == 0, "parent-exit shutdown failed")
                        checks.append("parent death triggers graceful runtime exit")
                    else:
                        check_hosted_server(port, key)
                        checks.extend(["embedded web panel served on loopback",
                                       "panel and public API authentication enforced",
                                       "panel self-update disabled while hosted"])
                        for path in case.rglob("*"):
                            if path.is_file() and path.name not in ("process.log", "config.json"):
                                runtime.require(key.encode() not in path.read_bytes(), "api key persisted outside config")
                        checks.append("api key stays in the hosted configuration")
            except Exception:
                log = case / "process.log"
                if log.exists():
                    print(log.read_text(errors="replace")[-16000:].replace(key, "[REDACTED]"), file=sys.stderr)
                raise
            finally:
                stop(process)
                stop(parent)
    report = {"schema_version": 1, "target": manifest["target"], "source_commit": manifest["source"]["commit"],
              "binary_sha256": manifest["binary"]["sha256"], "status": "passed", "checks": checks,
              "live_provider_api_tested": False}
    (artifact_dir / "smoke-report.json").write_bytes(runtime.encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    smoke(args.artifact_dir.resolve())
