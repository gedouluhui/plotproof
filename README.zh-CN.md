# PlotProof 中文快速开始

[English](README.md)

## 快速开始与支持状态

### 问题
通过结合保存时绘制意图和受限 PDF 字符框证据，检测 Matplotlib PDF 导出的静默缺陷。

### 安装
```sh
python -m pip install -e ".[dev]"
```

### 成功命令
```sh
python -m plotproof demo --output plotproof-demo
```
预期：干净图通过，故意裁切图失败；演示验证两个对照后退出码 0。

### 故意失败命令
```sh
python -m plotproof check does-not-exist.py --json missing-report.json --html missing-report.html
```
预期：缺失的 figure 模块被拒绝，退出码 2，且不声称成功。

### 证据与覆盖边界
证据包括 356 项测试，覆盖确定性核心、受限 PDF 读取器、CA1 采集和一个端到端装配。没有保留集结果、准确率数字或字体 cmap 证据，D4_missing_glyph 未评估。PASS 仅表示在已评估类别中且覆盖足够时未发现受支持的缺陷。

### 支持状态
版本 0.1.0a2 是面向 Python 3.12 和 Matplotlib 3.10.8 的 B1 工程预览。PDF worker 路径仅在 Windows 上验证。它不是认证检测器，也没有准确率声明。维护为尽力而为，不提供 SLA。

### 限制
不支持旋转文字、数学公式、TeX、自动换行/栅格化文字、路径效果、任意/多页/旋转 PDF，也不做语义或美学判断。当图像或集合导致绘制清单不完整时，D2 会被跳过。
