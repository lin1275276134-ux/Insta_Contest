# 拍够了吗？

本地拍摄覆盖检查工具：连接相机 → 发现素材 → 分析 → 判断教程分镜「还缺什么」→ 给出补拍建议。

> **当前状态：模拟验收通过，真机验收未开始。**
> 已跑通的是「模拟相机 + 固定标注模型」下的完整程序流程。它**不能**识别真实画面，
> 也**没有**验证过 X5 的自动同步协议。真机门槛（G0/G1）尚未验证，详见
> [交接说明](docs/交接说明.md)。

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
scripts/start --simulate   # 正式本地启动（模拟模式），随后打开 http://127.0.0.1:8765
scripts/stop               # 优雅停止；项目、任务与媒体全部保留
scripts/dev --simulate     # 开发模式，带 Vite 热更新
```

`--simulate` 必须显式给出。不给出时，涉及真实设备与真实模型的接口会返回
`CAPABILITY_UNVERIFIED`，而不是假装成功。

数据默认写入 `./data/`（可用 `BOLD_DATA_DIR` 覆盖）。`data/` 已被 git 忽略。

## 使用流程

1. 创建项目，填写教程主题、目标成片时长与拍摄条件 → 生成分镜草稿。
2. 修改并**确认锁定**分镜清单（每个分镜有可观察的通过标准）。
3. 「连接并浏览素材」→ 勾选本项目已有片段，或只接收之后的新片段。
4. 在相机上录制。软件轮询目录、发现新素材、下载、转码、分析、更新分镜覆盖。
5. 页面三栏：分镜进度 / 素材与证据 / 当前建议。点击证据在**同一份分析副本**上定位播放。
6. 覆盖齐全且扫描新鲜时显示「已拍够」；暂停、断连或有未完成处理时保留进度但降级为
   「覆盖齐全 · 最新素材未核验」。

## 测试

| 命令 | 范围 | 依赖 |
|---|---|---|
| `scripts/check` | ruff、单元测试、契约与类型重导出、前端单测、构建 | 无 |
| `scripts/test-integration` | 临时库 + 假相机的服务集成测试（SY/ME/AI/RU/API 语义） | 无 |
| `scripts/test-e2e` | 浏览器端完整操作验收（UI01–UI06 / E01–E05） | 一个 Chromium 系浏览器 |
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
backend/app/      schema、service（事务/规则聚合）、storage、jobs、camera、media、analysis、coverage、api
contracts/        OpenAPI 与 JSON Schema（由 scripts/export-contracts.py 生成）
frontend/         React + TS + Vite 页面；src/ 为源码，e2e/ 为浏览器验收
scripts/          统一入口（setup/check/test-*/dev/start/stop）
tests/            unit（纯规则）与 integration（临时库 + 假相机）
tools/simulator.py 固定标注的模拟素材目录工具
docs/             设计、测试与验收、交接说明
```

## 文档

- [开发计划](开发计划_初稿.md) — 范围、任务卡、实施顺序
- [架构与接口设计](docs/架构与接口设计.md) — 进程、数据、API、状态语义
- [开发测试与验收流程](docs/开发测试与验收流程.md) — 测试分层与用例矩阵（SY/ME/AI/RU/UI/E/HW）
- [交接说明](docs/交接说明.md) — **接手请先读这份**：已完成/已验证/未验证/下一步
