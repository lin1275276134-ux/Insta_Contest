# 2026-09-22 真机证据（脱敏副本）

这些 JSON 来自本轮实际 X5 只读请求和本地 FFmpeg 检查。设备序列号/URL 等字段已脱敏，
媒体准备报告中的本机绝对路径改为仓库相对路径。无视频、截图、模型输出或凭据。
不是模拟 fixtures；本轮自动测试不依赖相机或这些私有原片。

- device-connected-001：info/state，设备型号及固件。
- catalog-experiment-001：两小页实验，totalEntries 非整卡总数。
- catalog-after-recording-full-002：106 条完整扫描基线。
- catalog-second-recording-001/002、button-recording-comparison-001：078 新增和稳定复扫。
- media-078-report：全景 INSV/LRV 技术元数据/hash；投影需结合文档的抽帧检查。
- catalog-before-single-lens-001：108 条基线。
- catalog-single-lens-after-001/002、single-lens-comparison：079 新增与复扫。
- media-single-lens-report、single-lens-preparation-report：079 元数据/hash、现有 prepare 的产物信息。

原 JSON 保留采集时的 gate_status=unverified，不将后续人工判断写回原响应。
完整成功扫描只证明当次读到空页，不能证明录制中所有文件均已落盘。
原片位置与限制见 [交接说明](../../交接说明.md)；新电脑 clone 后需另行取得原片。
