// SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
// SPDX-License-Identifier: AGPL-3.0-only
// 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel

//go:build !unix && !windows

package main

// platformProcessAlive 其他平台无法探测宿主进程，始终视为在运行（不因误判停机）。
func platformProcessAlive(int) bool { return true }
