#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
# SPDX-License-Identifier: AGPL-3.0-only
# 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel
"""把 main 推送或手动请求的构建发布为不可覆盖的 Pinable 运行时 Release（不标 Latest）。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
import runtime


def api(path, payload=None, method=None):
    args = ["gh", "api", path]
    if payload is not None:
        args += ["--method", method or "POST", "--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            check=True, text=True, stdout=subprocess.PIPE)
    return json.loads(result.stdout)


def validate(directory, expected_commit):
    index = json.loads((directory / "runtime-index.json").read_text())
    runtime.require(index["source"]["commit"] == expected_commit and
                    runtime.HEX40.fullmatch(expected_commit), "source mismatch")
    paths = sorted(directory.glob("*.manifest.json"))
    manifests = [runtime.verify(p, expected_commit)[0] for p in paths]
    runtime.require(len(manifests) == 6 and {m["target"] for m in manifests} == set(runtime.TARGETS),
                    "incomplete runtime set")
    runtime.require(sorted(manifests, key=lambda m: m["target"]) == index["targets"], "index mismatch")
    runtime.require(all(m["version"] == index["version"] for m in manifests), "mixed versions")
    validation = json.loads((directory / "validation.json").read_text())
    reports = validation["native_smoke"]
    runtime.require(validation["quality"] == "passed" and validation["source_commit"] == expected_commit,
                    "quality check did not pass")
    hashes = {m["target"]: m["binary"]["sha256"] for m in manifests}
    runtime.require(len(reports) == 6 and {r["target"] for r in reports} == set(runtime.TARGETS)
                    and all(r["status"] == "passed" and r["source_commit"] == expected_commit
                            and r["binary_sha256"] == hashes[r["target"]] for r in reports),
                    "native smoke validation incomplete")
    files = {m["archive"]["file"] for m in manifests} | {p.name for p in paths}
    files |= {"runtime-index.json", "validation.json", "SHA256SUMS"}
    runtime.require({p.name for p in directory.iterdir()} == files, "unexpected release file")
    seen = set()
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        runtime.require(name in files - {"SHA256SUMS"} and name not in seen, "unsafe/duplicate checksum entry")
        path = directory / name
        runtime.require(path.is_file() and not path.is_symlink() and
                        hashlib.sha256(path.read_bytes()).hexdigest() == checksum, "release checksum mismatch")
        seen.add(name)
    runtime.require(seen == files - {"SHA256SUMS"}, "incomplete checksums")
    return index, sorted(files)


def publish(directory, expected_commit):
    repo = runtime.REPOSITORY.removeprefix("https://github.com/")
    runtime.require(os.environ.get("GITHUB_REPOSITORY") == repo and
                    os.environ.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch") and
                    os.environ.get("GITHUB_REF") == "refs/heads/main" and
                    os.environ.get("GITHUB_SHA") == expected_commit,
                    "publication requires a main push or manual run at the expected source")
    index, files = validate(directory, expected_commit)
    runtime.require(api(f"repos/{repo}/git/ref/heads/main")["object"]["sha"] == expected_commit,
                    "main moved after validation; build the new revision before publishing")
    tag = "pinable-runtime-" + index["version"]
    refs = api(f"repos/{repo}/git/matching-refs/tags/{tag}")
    runtime.require(not any(r["ref"] == "refs/tags/" + tag for r in refs),
                    "runtime tag already exists; publication never overwrites artifacts")
    created = api(f"repos/{repo}/git/refs", {"ref": "refs/tags/" + tag, "sha": expected_commit})
    runtime.require(created["object"]["sha"] == expected_commit, "reserved tag source mismatch")
    notes = (f"供 Pinable Desktop 托管的 CLIBuddyAPI（wb2api）便携运行时，源码 `{expected_commit}`。\n\n"
             "六个平台的程序都在原生机器上通过了宿主契约冒烟检查，发布前跑过完整的 Go 测试。\n\n"
             "Desktop 按 runtime-index.json 与 SHA256SUMS 校验下载内容。CGO=0 构建；macOS 程序为 ad-hoc "
             "签名（未做 Developer ID 签名与公证），Windows 程序未签名。这不是 Desktop 安装包，"
             "也不替换 vX.Y.Z 的常规 Release 与面板一键更新。\n\n"
             "本程序按 AGPL-3.0-only 发布，压缩包内附 LICENSE 与 NOTICE。")
    release = api(f"repos/{repo}/releases", {"tag_name": tag, "target_commitish": expected_commit,
                  "name": "Pinable runtime " + index["version"], "body": notes,
                  "draft": True, "prerelease": False, "make_latest": "false"})
    subprocess.run(["gh", "release", "upload", tag, "--repo", repo,
                    *[str(directory / name) for name in files]], check=True)
    runtime.require(api(f"repos/{repo}/git/ref/tags/{tag}")["object"]["sha"] == expected_commit,
                    "release tag moved")
    runtime.require(api(f"repos/{repo}/git/ref/heads/main")["object"]["sha"] == expected_commit,
                    "main moved during publication; leave draft for inspection")
    assets = api(f"repos/{repo}/releases/{release['id']}/assets?per_page=100")
    runtime.require(len(assets) == len(files) and {a["name"] for a in assets} == set(files),
                    "uploaded asset set mismatch")
    for asset in assets:
        path = directory / asset["name"]
        runtime.require(asset["state"] == "uploaded" and asset["size"] == path.stat().st_size and
                        asset["digest"] == "sha256:" + runtime.digest(path.read_bytes()),
                        "uploaded asset hash/size mismatch")
    published = api(f"repos/{repo}/releases/{release['id']}",
                    {"draft": False, "prerelease": False, "make_latest": "false"}, method="PATCH")
    runtime.require(published["draft"] is False and published["prerelease"] is False and published["tag_name"] == tag,
                    "stable release publication not confirmed")
    print(published["html_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    publish(args.directory.resolve(), args.expected_commit)
