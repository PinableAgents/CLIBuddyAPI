# Pinable Desktop 运行时

本仓库除了常规的 `vX.Y.Z` Release 与镜像，还为 [Pinable Desktop](https://github.com/PinableLab) 出一套按需下载的便携运行时，出包方案与 [PinableAgents/CLIProxyAPI](https://github.com/PinableAgents/CLIProxyAPI) 的 pinable-runtime 一致。它不是 Desktop 安装包，也不替换常规 Release 与面板一键更新。

- [宿主契约](#宿主契约)
- [平台与构建方式](#平台与构建方式)
- [压缩包内容](#压缩包内容)
- [流水线与发布](#流水线与发布)
- [Desktop 怎么用](#desktop-怎么用)
- [本地命令](#本地命令)

## 宿主契约

契约版本 `1`，由 `cmd/server/hosted.go` 实现：

| 参数 | 作用 |
|---|---|
| `-version` | 只打印一行版本号后退出，不读配置、不建文件 |
| `-runtime-info` | 打印一行 JSON 后退出：`contract_version`、`app_version`、`component_version`、`commit`、`commit_time`，同样不读配置、不建文件 |
| `-config <路径>` | 宿主写好的托管配置 |
| `-parent-pid <PID>` | 进入托管模式：宿主进程退出后程序自行优雅停机；面板的一键更新与回退一律拒绝，原因里注明「由 Pinable Desktop 托管」，升级交给 Desktop 的组件管理 |

托管模式下，程序不会切换到数据目录里由一键更新下载的版本，始终运行 Desktop 装好的那一份。`WB2A_*` 环境变量会覆盖配置文件，Desktop 启动子进程时应去掉它们。

`component_version`、`commit`、`commit_time` 由出包脚本通过 `-ldflags -X main.runtime*` 写入；普通 `go build` 出来的程序这几项为空，契约版本照常输出。

## 平台与构建方式

| 平台 | 原生构建机 | 压缩格式 |
|---|---|---|
| windows/amd64 | windows-2025 | ZIP |
| windows/arm64 | windows-11-arm | ZIP |
| darwin/amd64 | macos-15-intel | tar.gz |
| darwin/arm64 | macos-15 | tar.gz |
| linux/amd64 | ubuntu-22.04 | tar.gz |
| linux/arm64 | ubuntu-22.04-arm | tar.gz |

统一使用 `desktop-portable` 配置：CGO=0、基线 CPU 指令集、`-trimpath`、`-buildvcs=false`、go.mod 声明的 Go 版本。构建要求工作区干净，且面板前端已先构建到 `internal/panel/dist/`（流水线里单独的 `web` 任务负责）。macOS 程序做 ad-hoc 签名，未做 Developer ID 签名与公证；Windows 程序未签名。

## 压缩包内容

压缩包命名为 `CLIBuddyAPI_pinable_<版本>_<os>_<arch>.zip`（Windows）或 `.tar.gz`（其余平台），旁边附同名的 `.manifest.json`。包内恰好四个普通文件：

```text
wb2api[.exe]
LICENSE
NOTICE
runtime.json
```

不含配置、账号凭证、日志或数据目录；面板前端已内嵌在程序里。成员的顺序、时间戳、属主与权限固定，LICENSE 与 NOTICE 的换行统一为 LF。manifest 记录源码仓库与完整 SHA、提交时间、Go 版本、契约版本、能力、LICENSE/NOTICE 校验和、解包后程序与压缩包各自的大小和 SHA256；包内的 `runtime.json` 是同一份记录（不含压缩包自身的校验和）。

本程序按 AGPL-3.0-only 发布：分发运行时的一方须随附 LICENSE 与 NOTICE，并按 NOTICE 的要求注明出处。

## 流水线与发布

流水线：`.github/workflows/pinable-runtime.yml`。

- `web` 构建面板前端；`quality` 跑出包脚本测试与完整 `go test ./...`；`package` 在六个平台的原生机器上构建，并实际运行打好的程序做冒烟（元数据探测、内嵌面板、面板与公开接口的鉴权、托管模式下拒绝一键更新、宿主退出后自行停机）；`assemble` 汇总校验，生成 `runtime-index.json`、`validation.json` 与 `SHA256SUMS`。
- 每次推送到 `main` 都会在上述检查全部通过后，自动发布 `pinable-runtime-<版本>` Release。版本默认是源码提交时间加短 SHA，不需要手动改版本号，也与 `appVersion` 无关。
- 相关 PR 只产出候选下载，不发布；手动运行默认也只产出 Actions 产物，勾选 `publish_release` 才在 `main` 上发布。
- 发布只接受本仓库 `main` 上与测试一致的提交，标签已存在就拒绝；先建草稿、上传并核对每个资产的大小与 SHA256，再以 `prerelease=false`、`make_latest=false` 公开。已发布的资产不会被替换。
- 不要手动推送 `pinable-runtime-*` 标签。这些 Release 不影响面板的更新检查（它读的是更新日志），也不会被常规发版流程当成新版本。

## Desktop 怎么用

Desktop 从最新的 `pinable-runtime-*` Release 读取 `runtime-index.json`，按当前平台挑出压缩包，校验压缩包与解包后程序的 SHA256、契约版本和包内成员，再把 `wb2api[.exe]` 安装为 `PINABLE_HOME/bin/clibuddyapi[.exe]`。配置、账号与状态放在 `PINABLE_HOME/components/clibuddyapi/data/`，更新组件时不会被替换。

Desktop 写入的托管配置只监听回环地址、关闭面板的更新检查，`api_key` 由 Desktop 生成并保存在这份配置里；启动时传 `-config <配置> -parent-pid <Desktop 的 PID>`，以 `/readyz` 判断就绪。

## 本地命令

```bash
(cd web && npm ci && npm run build)
python -m unittest discover -s scripts/pinable -p 'test_*runtime.py' -v
python scripts/pinable/runtime.py build --target linux/amd64 --output /tmp/clibuddyapi-runtime
python scripts/pinable/smoke_runtime.py --artifact-dir /tmp/clibuddyapi-runtime
```

出包脚本只依赖 Python 3.10+ 标准库与 Go；构建产物只写到指定目录，冒烟用临时目录，结束后清理。不要提交生成的运行时。
