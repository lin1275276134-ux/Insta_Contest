# T00 设备与媒体探测记录

截至 2026-09-22 冻结：X5 信息读取、多页枚举、两段按钮录制新增对比和下载已实测；
079 单镜头样本通过现有媒体模块。G0/G1 整体验收未完成，真实模型未配置。
当前交接状态以 [交接说明](交接说明.md) 为准；以下按探测阶段记录历史与限制。
已入库的脱敏证据见 [证据目录](evidence/2026-09-22/README.md)，原片仅留本地。

## 已知信息与依据

交接提供：X5 固件 v1.11.6、MCU v1.2.5、硬件 523；其中固件已通过本轮 info 响应复核，MCU 信息未独立读取。
[官方 OSC 接口文档](https://insta360develop.github.io/Insta360-Developer_Docs/ch/x/osc/api/)
（2026-09-22 查阅）描述 GET `/osc/info` 和 POST `/osc/state`，建议各不超过每秒一次。
本工具单次各请求一次，不发送录制、设置或删除命令，不探测未证实的视频列表参数。
设备信息成功仅证明这两个请求可读，不能证明历史视频分页与按钮录制后新增发现。

## 采集命令

先按 README 安装依赖。在项目根目录执行，设备地址替换成实际连接地址：

```bash
.venv/bin/python -m tools.probes.inspect_device --output data/probes/device-001.json device --base-url http://DEVICE_IP
.venv/bin/python -m tools.probes.inspect_device --output data/probes/media-001.json media /absolute/path/clip.insv
```

`--timeout` 在子命令之前指定，默认每个请求/ffprobe 30 秒。每次使用新输出名，拒绝覆盖已有报告。
媒体可提供多个同组成员路径，但工具不会由文件名推断组完整性。输出含 SHA-256、文件大小、
编码、尺寸、帧率与容器时长；不转码、不更改原片。元数据读取成功记为 `metadata_only`，
投影与组完整性仍为 `unknown`，不代表全片可解码或普通视角可用。

设备报告保留请求方法、路径、HTTP 状态及递归脱敏后的 JSON；常见凭据/序列号键与 URL 被隐藏，
不保存非 JSON 错误正文。非标准字段仍需人工检查后才能分享。媒体只保存技术字段，不保留容器标签
和绝对路径。采集请求失败退出 1；参数错误退出 2；退出 0 仅代表采集成功。HTTP 重定向不跟随，
系统代理不用于设备请求。报告默认放在被 Git 忽略的 data/ 下。

## 真机验收清单

| 用例 | 必需证据 | 当前状态 |
|---|---|---|
| HW01 | 超过一页的历史视频目录、实际协议参数、各页响应、总数与相机对照 | 部分：已多页到空页，待相机端数量对照 |
| HW02 | 相机按钮连续录制至少 5 段，逐段结束时间与发现记录 | 部分：严格前后对比 2 段，尚未完成连续至少 5 段 |
| HW03 | 录制中枚举/读取结果及文件增长、组成员到齐情况 | 未运行 |
| HW04 | 原片模式、完整成员/hash、全片解码、投影确认、分析副本及证据定位 | 部分：079 解码/副本通过，播放器/模型待验收 |
| HW05 | 相机网络与模型外网并存情况，或切网及队列恢复记录 | 未运行 |
| HW06 | 断连期间新增清单、重连补扫、归属确认及去重记录 | 未运行 |

能力表：history_video_listing、listing_during_recording、download_during_recording、
group_metadata、readiness_signal 当前均为 `unknown`。真实 CameraAdapter 仍未冻结。

## 探测起点（历史计划，当前下一步见交接说明）

连接设备后先采集 info/state 并复核固件，取得支持历史视频枚举的可读协议依据，再实现目录采集。
不能将当前工具当作已完成 HW01/HW02。拿到真实原片后采集媒体报告，再验证完整解码、投影与
自动处理路径。真实模型仍待服务配置和冻结评估集；`scripts/test-live` 保持未运行出口。

## 首次真机连接结果（以下为阶段记录，后续章节更新结论）（2026-09-22 07:44 UTC）

后续用户连接 X5 后完成实测，更新此前“未连接”的状态：

- info/state 均 HTTP 200，设备 Insta360 X5，固件 A3_1.11.6.523_build1，卡状态 pass，电量 25%。
- 实际 Mac：Darwin 25.5.0 / arm64，与原交接机器环境不同。
- `camera.listFiles` 采用 Google OSC level 2 标准的 video/startPosition/entryCount/maxThumbSize
  参数实验，startPosition 0 和 2、entryCount 2 返回不同的两条记录；两页 totalEntries 均为 2。
  因此不能采用标准总数字段语义终止分页，也不能声称完整枚举通过。
- 一次 entryCount 20 请求返回 15 条文件记录，含 MP4/LRV；这是文件数而非已确认的录制组数。
  探测脚本遇短页标记 short_page_needs_followup，后续需边界页与相机端数量核对。
- 证据：data/probes/device-connected-001.json、catalog-experiment-001.json、catalog-baseline-001.json。
- 新增实验入口：`.venv/bin/python -m tools.probes.catalog_probe --output data/probes/catalog-next.json`。
  固定访问已连接设备 192.168.42.1，仅枚举目录，不下载视频。输出完整性始终为 unverified。
- 已补官方要求的 Accept / X-XSRF-Protected 请求头，相关测试 4 passed，Ruff 通过。

HW01 部分实测、尚未通过；HW02 等待相机按钮录制后的对比；HW03–HW06 尚未完成。
G0/G1 仍未通过。目录中的 isProcessed 或尺寸元数据不证明视频已拼接或适合视觉分析。
标准参数依据：https://developers.google.com/streetview/open-spherical-camera/reference/camera/listfiles

## 按钮录制后扫描与分页修正

用户回复“拍好了”后，第一页仍为原 15 条。修正 catalog_probe：按实际返回数量推进
startPosition，短页继续翻页，直到空页。两次独立扫描均获得 106 条，文件路径及大小完全一致；
偏移为 0/15/30/45/60/75/90/105/106，最后一页为空。实测请求 entryCount=20 每页最多返回 15 条。
新增回归测试模拟 15+15+1+0，证明不依赖短页或 totalEntries 提前结束，5 项相关测试通过，Ruff 通过。

目录末尾有 VID_20260922_154624_00_077.insv（157208926 字节）及
LRV_20260922_154624_01_077.lrv（27185496 字节），时间与本次录制相符，但此前基线
只有第一页，因此不能严格证明该组由本次操作新增。两次大小稳定也不证明文件完整或投影可用。
尚未下载/分析。现在以全目录第二次扫描为新基线，下一次按钮录制后进行严格集合差异验证。
HW01 已有多页至空页的重复扫描证据，仍待与相机端组数核对；HW02 尚未满足连续 5 段标准。
证据：data/probes/catalog-after-recording-001.json、catalog-after-recording-full-001.json、
catalog-after-recording-full-002.json。G0/G1 保持未验证。

## 第二段按钮录制：严格新增对比与下载（2026-09-22）

以 catalog-after-recording-full-002.json 为基线，两次新扫描均到空页，106 → 108 条。
新增且仅新增：VID_20260922_155056_00_078.insv（162713950 字节）与
LRV_20260922_155056_01_078.lrv（27447640 字节）；无移除、无旧条目变化，复扫完全一致。
未发出开始/停止录制命令。此为 1 段具有完整前后目录证据的按钮录制发现，尚未满足 HW02 至少 5 段。

两文件已通过设备 HTTP 下载至 data/probes/media-078/，落盘前逐一核对目录大小。
media-078-report.json 保存 SHA-256 和 ffprobe 结果：INSV 时长 12.529183 秒，两路
1920×1920 HEVC 视频轨；LRV 时长 12.545867 秒，1664×832 H.264 视频轨。
FFmpeg 使用 -xerror、-map 0:v 全视频轨解码检查，无错误输出；LRV 第 2 秒抽帧目视明确为
左右双鱼眼，而非普通视角或已拼接全景。目录声称 6080×3040、isProcessed=true，与实际轨道
和画面用途不符，不能用目录字段判定媒体 ready。

G1 尚未通过：当前拍摄模式需要验证自动去畸变/拼接与视角输出方案，或另验证相机可输出普通
视角的模式。不得仅转封装或直接把双鱼眼交给模型宣布通过。未调用任何真实模型。
证据：catalog-second-recording-001/002.json、button-recording-comparison-001.json、
media-078-report.json；下载原片均留在被忽略的 data/ 下。

## 单镜头普通录像：真实样本处理通过（079）

用户接受单镜头或全景两种路线，优先验证单镜头普通录像。拍摄前完整目录 108 条，拍摄后
两次扫描均为 110 条且到空页；仅新增 079 MP4/LRV，旧条目不变，复扫一致。
两文件已下载到 data/probes/media-single-lens/，字节数均与目录一致：

- VID_20260922_155953_00_079.mp4：71142538 字节；HEVC 1920×1080，30000/1001 fps，12.345667 秒。
- LRV_20260922_155953_01_079.lrv：12684426 字节；H.264 1280×720，时长相同。

原片第 3 秒抽帧目视确认为普通单视角桌面画面。以此样本人工验证投影，调用现有
backend.app.media.service.prepare，仅输入原 MP4（LRV 是同次录制预览，不能拼接成后续时段）。
完成原片全片解码、H.264/yuv420p/faststart 分析副本生成和副本全片解码；输出时长
12.345667 秒，与源文件一致，source_start=0、group_start=0；副本第 3 秒抽帧与原片内容一致。

此结果证明该真实单镜头样本可走现有自动转码模块，无需 Studio 手工导出；尚未验证产品播放器
实播、模型证据定位、其他模式/长片及可靠模式识别，不能据此宣布 G1 总体验收完成。
模式确认仍来自用户操作和目视抽帧，真实适配器不得仅凭 .mp4 后缀或相机目录 width/isProcessed 放行。
HW02 具有完整前后目录对比的片段目前 2 段（078、079；模式不同），未达到连续至少 5 段验收。

报告：catalog-before-single-lens-001.json、catalog-single-lens-after-001/002.json、
single-lens-comparison.json、media-single-lens-report.json、single-lens-preparation-report.json，
均在 data/probes/。下一步将真实设备枚举/下载接入业务服务，并配置真实模型；全景自动处理仍未通过。
