# 拍够了吗？

目标驱动的本地素材覆盖检查工具：说明想拍出的成片 → 选择本地视频 → 检查必拍内容「还缺什么」→ 给出补拍建议。

> **当前产品只分析用户主动选择的本地普通视角视频。**
> X5 目录探测资料仅作为历史证据保留，不再属于正式运行流程。

## 环境要求

- macOS（开发机为 Apple Silicon，Darwin 27）
- Python ≥ 3.11、[uv](https://docs.astral.sh/uv/)
- Node.js（含 npm）
- `ffmpeg` 与 `ffprobe`（在 PATH 中）

## 安装

```bash
scripts/setup
```

`setup` 会锁定依赖、安装前端包、导出 OpenAPI 契约与前端类型，并构建前端。

## 运行

```bash
scripts/start --simulate   # 本地启动（模拟模型），随后打开 http://127.0.0.1:8765
scripts/stop               # 优雅停止；项目、任务与媒体全部保留
scripts/dev --simulate     # 开发模式，带 Vite 热更新
scripts/check-model        # 不上传视频，验证 Qwen VL 密钥、地域、模型权限和结构化输出
```

`--simulate` 必须显式给出。不给出时需要配置真实模型；未配置或未授权时会返回明确错误，
不会把模拟结果当作真实视觉结论。

真实模型配置：复制 `.env.example` 为 `.env`，填写本机的 `DASHSCOPE_API_KEY`，然后执行
`scripts/check-model`。默认使用北京地域的 `qwen3-vl-flash`；密钥与端点必须属于同一地域。
分析副本会在用户逐项目授权后上传，原片留在本机。单段分析副本限制为 7 MiB，确保 Base64
编码后低于服务端 10 MB 限制；过大的副本会明确失败并提示调整分段参数。

数据默认写入 `./data/`（可用 `BOLD_DATA_DIR` 覆盖）。`data/` 已被 git 忽略。

## 使用流程

1. 创建项目，填写成片目标、目标成片时长与拍摄条件 → 生成分镜草稿。成片可以是教程、探店、Vlog、开箱、产品展示或其他短视频，不需要预先选择固定类型。
2. 修改并**确认锁定**分镜清单（每个分镜有可观察的通过标准）。
3. 确认视频为普通视角后，一次选择一个或多个本地视频。
4. 软件逐文件校验、生成分析副本、调用模型并更新分镜覆盖；之后可继续追加视频。
5. 页面三栏：分镜进度 / 素材与证据 / 当前建议。点击证据在**同一份分析副本**上定位播放。
6. 全部纳入视频分析完成且必要标准覆盖齐全时显示「分镜覆盖完整」；处理中或失败时显示
   「正在分析」及对应恢复入口。

## 测试

| 命令 | 范围 | 依赖 |
|---|---|---|
| `scripts/check` | ruff、单元测试、契约与类型重导出、前端单测、构建 | 无 |
| `scripts/test-integration` | 临时库 + 本地视频的导入、媒体、任务与恢复测试 | FFmpeg |
| `scripts/test-e2e` | 浏览器端完整操作验收（UI01–UI06 / E01–E05） | 一个 Chromium 系浏览器 |
| `scripts/test-e2e-real` | Qwen VL + 实拍视频完整链路（需 `BOLD_E2E_VIDEO_FILES`） | 浏览器、密钥、网络、实拍视频 |
| `scripts/test-live` | 真机 / 真实模型 | **当前不可用，见下** |

`scripts/test-e2e` 优先使用 Playwright 自带的 Chromium，找不到时回退到系统
Chrome/Chromium/Edge。也可以显式指定：

```bash
npm --prefix frontend exec playwright install chromium   # 安装固定版本
BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' scripts/test-e2e
```

要跑真实浏览器验收，必须先安装浏览器：Playwright 的 `chromium` 或系统 Chrome 之一。

`scripts/test-live` 会直接报告未运行并退出 2 —— 这是设计行为，不是缺陷。

## 目录结构

```text
backend/app/      schema、service（事务/规则聚合）、storage、jobs、media、analysis、coverage、api
contracts/        OpenAPI 与 JSON Schema（由 scripts/export-contracts.py 生成）
frontend/         React + TS + Vite 页面；src/ 为源码，e2e/ 为浏览器验收
scripts/          统一入口（setup/check/test-*/dev/start/stop）
tests/            unit（纯规则）与 integration（临时库 + 本地视频）
tools/simulator.py 固定标注的模拟素材生成工具
docs/             设计、测试与验收、交接说明
```

## 文档

- [开发计划](开发计划_初稿.md) — 范围、任务卡、实施顺序
- [架构与接口设计](docs/架构与接口设计.md) — 进程、数据、API、状态语义
- [开发测试与验收流程](docs/开发测试与验收流程.md) — 测试分层与用例矩阵（SY/ME/AI/RU/UI/E/HW）
- [交接说明](docs/交接说明.md) — **接手请先读这份**：已完成/已验证/未验证/下一步

## 历史真机资料

早期 X5 只读探测记录见 [设备探测记录](docs/device-probe.md)。这些脚本和证据不参与正式产品启动、
完成判断或交付验收。
