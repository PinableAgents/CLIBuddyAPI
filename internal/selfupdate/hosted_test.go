// SPDX-FileCopyrightText: 2026 yreidev 与贡献者（见 NOTICE）
// SPDX-License-Identifier: AGPL-3.0-only
// 复制或改写本文件须保留以上声明，并按 NOTICE 的署名条款注明出处：https://github.com/yreidev/workbuddy2api-panel

package selfupdate

import "testing"

// Hosted：数据目录里有更新的版本也不 exec，一键更新与回退都按宿主给的原因拒绝。
func TestHostedNeverSwitchesOrUpdates(t *testing.T) {
	const reason = "由宿主管理版本"
	dataDir := t.TempDir()
	prep := newUpdater(dataDir, "1.1.0")
	installed(t, prep, Manifest{Version: "1.2.0"}, fakeBinary("1.2.0"))
	calls := stubExec(t, nil)

	u := Hosted(dataDir, "1.1.0", reason)
	if len(*calls) != 0 {
		t.Fatalf("托管模式不应 exec: %+v", *calls)
	}
	if st := u.Status(); st.Supported || st.Reason != reason {
		t.Fatalf("Status = %+v", st)
	}
	if err := u.Start("1.2.0"); err == nil || err.Error() != reason {
		t.Fatalf("Start err = %v", err)
	}
	if _, err := u.Rollback(); err == nil || err.Error() != reason {
		t.Fatalf("Rollback err = %v", err)
	}
}
