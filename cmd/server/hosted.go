// SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
// SPDX-License-Identifier: AGPL-3.0-only
// 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel

// hosted.go 宿主托管契约：由 Pinable Desktop 等宿主拉起时，用 -parent-pid 绑定宿主进程，
// 宿主退出后本进程走一遍优雅停机再退出；-runtime-info 输出出包元数据供宿主核对。
// 契约细节见 docs/desktop-runtime.md。
package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"time"
)

// hostContractVersion 宿主契约版本：-parent-pid、-runtime-info 的语义不兼容地变化时才升。
const hostContractVersion = "1"

// hostedUpdateReason 托管模式下面板一键更新被拒绝时显示的原因。
const hostedUpdateReason = "由 Pinable Desktop 托管，请在 Desktop 的组件管理里更新"

// parentPollInterval 检查宿主进程是否还在的间隔。
const parentPollInterval = time.Second

// 出包时由 scripts/pinable/runtime.py 经 -ldflags -X 写入；本地构建保持空值。
var (
	runtimeVersion    = ""
	runtimeCommit     = ""
	runtimeCommitTime = ""
)

// runtimeInfo -runtime-info 输出的元数据，字段名是宿主契约的一部分。
type runtimeInfo struct {
	ContractVersion  string `json:"contract_version"`
	AppVersion       string `json:"app_version"`
	ComponentVersion string `json:"component_version"`
	Commit           string `json:"commit"`
	CommitTime       string `json:"commit_time"`
}

// writeRuntimeInfo 输出一行 JSON：不读配置、不起服务、不写文件。
func writeRuntimeInfo(w io.Writer) error {
	return json.NewEncoder(w).Encode(runtimeInfo{
		ContractVersion:  hostContractVersion,
		AppVersion:       appVersion,
		ComponentVersion: runtimeVersion,
		Commit:           runtimeCommit,
		CommitTime:       runtimeCommitTime,
	})
}

// processAlive 判断宿主进程是否还在（按平台实现，测试可替换）。
var processAlive = platformProcessAlive

// watchParent 宿主进程退出后调用 stop 触发优雅停机；ctx 结束时停止检查。
func watchParent(ctx context.Context, pid int, stop context.CancelFunc) {
	ticker := time.NewTicker(parentPollInterval)
	defer ticker.Stop()
	for {
		if !processAlive(pid) {
			log.Printf("宿主进程 %d 已退出，开始停机", pid)
			stop()
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
