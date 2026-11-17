// SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
// SPDX-License-Identifier: AGPL-3.0-only
// 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel

package main

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/yreidev/workbuddy2api-panel/internal/selfupdate"
)

// -runtime-info：输出一行契约 JSON 并以 0 退出，不读配置、不起服务。
func TestMainRuntimeInfoFlag(t *testing.T) {
	env := stubMainEnv(t)
	oldVersion, oldCommit, oldTime := runtimeVersion, runtimeCommit, runtimeCommitTime
	runtimeVersion, runtimeCommit, runtimeCommitTime = "20261117000000-0123456789ab", strings.Repeat("a", 40), "2026-11-17T00:00:00Z"
	t.Cleanup(func() { runtimeVersion, runtimeCommit, runtimeCommitTime = oldVersion, oldCommit, oldTime })
	os.Args = []string{"wb2api", "-config", t.TempDir() + "/missing/config.json", "-runtime-info"}

	oldStdout := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdout = w
	code, exited := callMain(t)
	_ = w.Close()
	os.Stdout = oldStdout
	raw, _ := io.ReadAll(r)
	_ = r.Close()

	if !exited || code != 0 {
		t.Fatalf("退出码 = %d exited=%v want 0,true", code, exited)
	}
	var info runtimeInfo
	if err := json.Unmarshal(raw, &info); err != nil {
		t.Fatalf("输出不是 JSON: %q", raw)
	}
	want := runtimeInfo{hostContractVersion, appVersion, runtimeVersion, runtimeCommit, runtimeCommitTime}
	if info != want || strings.Count(strings.TrimSpace(string(raw)), "\n") != 0 {
		t.Fatalf("runtime info = %+v want %+v (raw=%q)", info, want, raw)
	}
	if env.output(t) != "" {
		t.Fatalf("-runtime-info 不应有日志: %s", env.output(t))
	}
}

// -parent-pid：不走一键更新的版本切换；宿主进程不在后优雅停机，main 正常返回。
func TestMainParentExitStopsGracefully(t *testing.T) {
	env := stubMainEnv(t)
	cfg := newRunTestConfig(t)
	cfg.Listen = freeAddr(t)
	path := writeMainConfig(t, cfg)

	var launched atomic.Int32
	launchUpdater = func(string, string) *selfupdate.Updater { launched.Add(1); return &selfupdate.Updater{} }
	oldAlive := processAlive
	t.Cleanup(func() { processAlive = oldAlive })
	var parentGone atomic.Bool
	processAlive = func(pid int) bool { return pid == 4242 && !parentGone.Load() }
	stubMainUpstream(newRunUpstream(&runRT{}))
	os.Args = []string{"wb2api", "-config", path, "-parent-pid", "4242"}

	out := goMain(t)
	waitHealthy(t, cfg.Listen)
	if code, body := panelRequest(t, http.MethodGet, "http://"+cfg.Listen+"/panel/api/version", ""); code != http.StatusOK ||
		!strings.Contains(body, strconv.Quote(hostedUpdateReason)) {
		t.Fatalf("托管模式的更新状态应带宿主原因: %d %s", code, body)
	}
	parentGone.Store(true)
	res := awaitMain(t, out)
	if res.exited {
		t.Fatalf("宿主退出后应正常停机（code=%d 日志=%s）", res.code, env.output(t))
	}
	if launched.Load() != 0 {
		t.Fatal("托管模式不应调用 launchUpdater")
	}
	if !strings.Contains(env.output(t), "宿主进程 4242 已退出") {
		t.Fatalf("缺少宿主退出日志: %s", env.output(t))
	}
}

// 平台探测：自己在运行；已退出并回收的子进程不在。
func TestPlatformProcessAlive(t *testing.T) {
	if !platformProcessAlive(os.Getpid()) {
		t.Fatal("当前进程应判为在运行")
	}
	child := exec.Command(os.Args[0], "-test.run=^$")
	if err := child.Run(); err != nil {
		t.Fatal(err)
	}
	if platformProcessAlive(child.Process.Pid) {
		t.Fatal("已退出的子进程应判为不在")
	}
}
