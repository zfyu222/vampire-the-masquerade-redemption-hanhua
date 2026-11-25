# 《吸血鬼：避世之血族－救赎》Crimson Edition 汉化工程

本仓库维护《Vampire: The Masquerade – Redemption》的简体中文译文、Nod 引擎适配器及回填工具。开发和回归测试基线为 **Windows Steam Build 1472805 + VTMR Crimson Edition 1.0 标准 16:9 主模组**。Crimson 由 Cristi 制作，提供宽屏支持、贴图更新，以及仓库和升级入口。本工程在其资源和界面布局上维护汉化。

## 仓库结构

| 位置 | 用途 |
| --- | --- |
| [正文译文](vampire-the-masquerade-redemption_text_translated.csv) 与 [图片译文](vampire-the-masquerade-redemption_images_text_translated.csv) | 单列 CSV，分别维护游戏正文和贴图文字 |
| [正文映射](vampire-the-masquerade-redemption_text.mapping.json)、[场景上下文](vampire-the-masquerade-redemption_text.context.json) 与 [图片映射](vampire-the-masquerade-redemption_images_text.mapping.json) | 源文哈希、字段位置、说话人和图片区域 |
| [TranslateFiles](TranslateFiles/) | 翻译配置、冻结术语、占位符规则及导出验收 |
| [ImagePatch](ImagePatch/) 与 [ImageText](ImageText/) | 界面布局、贴图覆盖清单和图片抽取策略 |
| [scripts/native](scripts/native/) | x86 中文适配器，负责 UTF-8 测宽、换行和 16/32 位绘制 |
| [scripts/release_patch](scripts/release_patch/) | Crimson 字符串合并、回填、差分、安装与升级 |
| [Dispatch](Dispatch/) | 发布渠道配置和封面来源 |

## 开发环境

1. 在 Windows 上准备 [StaticHanHua 工作区](https://github.com/zfyu222/StaticHanHua)，把本仓库克隆到 `Projects/vampire-the-masquerade-redemption`。
2. 让项目的 `Game/` 指向本地 Steam 游戏目录。保留一份未改动的 Steam 归档，并另建隔离副本做回填测试。Crimson 原包请从 [Nexus Mods](https://www.nexusmods.com/vampireredemption/mods/12?tab=files) 获取。
3. Python 工具使用 Pillow 与 fontTools，字库使用 Noto Sans SC。重新编译适配器需要 MSVC x86、MinHook 和 pefile。编译入口与运行时签名见 [原生适配器说明](scripts/native/README.md)。

Steam 游戏文件、Crimson 原始 ZIP、全文英文导出、运行状态与凭据属于本地输入。游戏资源在开发机上提取和校验。

## 修改、构建与验证

1. **定位文本。** 正文记录按资源、行号、字节区间和原文哈希对齐。需要重新提取时，在输出文件尚未生成的隔离副本运行 [extract_text.py](scripts/extract_text.py)，从原版 `Game/Local_Eng.nob` 导出原文和映射。修改译文时保留记录顺序、占位符及冻结术语。
2. **重新验收译文。** 沿用 [翻译工程说明](TranslateFiles/TranslateDoc.md)。润色后的语义复审只派发译文有改动的记录。导出时对全部记录执行结构、术语和占位符校验。回填脚本按验收报告核对原文和译文哈希。
3. **回填 Crimson Edition 资源。** [prepare_crimson_revision.py](scripts/release_patch/prepare_crimson_revision.py) 接收 Crimson 原包、Steam 原版 `Local_Eng.nob`、上一版本已回填的 `Local_Eng.nob`、Noto Sans SC 字体和一个新的输出目录。它复用上一版贴图，更新正文归档，按字符串 ID 合并 Crimson 的松散字符串表，并重建字库。Crimson 松散文件优先于归档内的同名资源，修改 `Game.nls` 或 `System.nls` 时须核对两处输出。
4. **构建差分。** [Build-CrimsonRevision.ps1](scripts/release_patch/Build-CrimsonRevision.ps1) 使用上一版解压载荷、上一版已回填归档、上一版 Crimson 合并资源和本次回填输出。保留这些本地产物以供下一次升级。安装器会按起始哈希选择全新安装或升级路径。
5. **验证交付。** 在隔离副本依次验证全新安装、旧版覆盖升级、重复安装及卸载恢复。运行 [布局回放](scripts/native/verify_layout.cpp) 检查 UTF-8 与断行，再在游戏里检查主菜单、字幕、长文档，以及 Crimson 的仓库和升级界面。

## 发布

原版游戏的独立体验优化补丁已退役。宽屏适配由 Crimson Edition 提供。

玩家安装说明与更新日志见 [GitHub Releases](https://github.com/zfyu222/vampire-the-masquerade-redemption-hanhua/releases/)。
