// SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
// SPDX-License-Identifier: AGPL-3.0-only
// 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel

//go:build windows

package main

import (
	"errors"
	"syscall"
)

// platformProcessAlive 以 SYNCHRONIZE 权限打开进程句柄并零等待：仍在运行时返回 WAIT_TIMEOUT。
// 打不开且不是权限问题（进程已退出、pid 无效）视为已退出。
func platformProcessAlive(pid int) bool {
	h, err := syscall.OpenProcess(syscall.SYNCHRONIZE, false, uint32(pid))
	if err != nil {
		return errors.Is(err, syscall.ERROR_ACCESS_DENIED)
	}
	defer syscall.CloseHandle(h)
	event, err := syscall.WaitForSingleObject(h, 0)
	return err == nil && event == syscall.WAIT_TIMEOUT
}
