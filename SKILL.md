---
name: ppt-generate
description: "Create variable-length, 16:9 Chinese-English academic presentations from literature, source decks, data, and visual references. Default to a fast workflow with four style previews that each show only four representative slides, then build a hybrid editable PPTX using native text/charts and image generation only for complex visuals. Preserve an optional high-fidelity workflow that generates a full image-based deck before editable reconstruction. Use when the user says ppt-generate, 三步法PPT, 学术PPT, 组会汇报, 文献做PPT, 四套风格预览, 图片版PPT, 可编辑还原, or asks to reuse this method for any slide count."
---

# PPT Generate 学术演示工作流

把本技能作为总编排器。先锁定事实、页数和内容骨架，再进行风格选型与 PPTX 构建。默认走快速路径，避免为风格预览生成整套缩略页，也避免先做全页图片再重复拆解。

## 开始前

1. 读取用户提供的文献、源 PPTX、数据和参考图；保留原文件，不移动、不覆盖。
2. 建立来源清单，记录页码、图表编号、引用和可信度。按“原始来源 > 用户明确修订 > 生成页面 > OCR”解决冲突。
3. 确定 `SLIDE_COUNT`：
   - 用户给出页数或范围时严格遵循。
   - 用户授权自动决定时，根据时长、模块和证据量直接确定。
   - 用户未指定且未授权时，先给出推荐值并等待确认。
   - 不使用固定默认页数。
4. 默认采用 16:9、中英文混排。中文承担叙事，英文只用于必要副标题、术语、图轴和引用。
5. 读取 [references/academic-slide-structure.md](references/academic-slide-structure.md)，形成唯一的 `content-spec.txt`，逐页记录功能、核心结论、事实来源和视觉需求。

## 执行模式

在 `workflow_state.json` 中记录 `execution_mode`。

- `fast`：默认模式。四套代表页预览 → 用户选风格 → 直接构建混合可编辑 PPTX。只为封面主视觉、复杂机制、装置合成和其他高复杂视觉调用图像模型。
- `fidelity`：仅在用户明确要求“先做完整图片版”“整页 Image 2”“最高视觉保真”或坚持原三阶段法时使用。四套代表页预览 → 完整图片版 PPTX → 用户确认 → 混合可编辑还原。

若用户只说“制作 PPT”或“使用 ppt-generate”，选择 `fast`。不要因为旧任务曾使用图片版而自动选择 `fidelity`。

## 工具路由

- 图像生成：加载系统 `imagegen` 技能。优先使用 Codex 内置图像工具；不要把本地 `OPENAI_API_KEY` 缺失当作内置模式的阻塞条件。只有用户明确要求本地 CLI、API 可复现调用或指定本地模型参数时，才检查 CLI、密钥和 Python 包。记录实际运行方式，不虚构无法验证的模型版本。
- PPTX、原生对象和渲染：加载 `Presentations` 技能并使用 `@oai/artifact-tool` JavaScript 链路。不要使用 `python-pptx`，也不要在同一 PPTX 中混用导出后端。
- PDF、DOCX、XLSX：按来源类型加载相应文档技能。只读原文件，不执行移动来源的参数。

## 状态机

允许从已有产物恢复，但必须验证状态、来源哈希和用户选择。

```text
INPUT_READY
  -> PAGE_COUNT_SET
  -> PREVIEW_READY
  -> STYLE_SELECTED
  -> FAST_EDITABLE_READY -> QA_PASSED
  or
  -> IMAGE_DECK_READY -> IMAGE_DECK_APPROVED -> EDITABLE_READY -> QA_PASSED
```

`workflow_state.json` 至少记录：状态、执行模式、页数与依据、来源哈希、内容规范哈希、四套风格、四个代表页、用户选择、页面原型、素材清单、任务清单、输出路径和未解决问题。

## 阶段 1：四套快速风格预览

1. 完成全部 `SLIDE_COUNT` 页的内容骨架，但每套风格只预览最多 4 个代表页。
2. 按语义选择代表页，不按固定页码机械抽样：
   - 封面/总览页；
   - 背景、科学问题或比较页；
   - 方法、流程或机制页；
   - 关键结果、数据图表或验证页。
3. 少于 4 页时使用全部页面；缺少某类页面时选择最接近的内容功能。四套必须使用同一组代表页。
4. 保存 `selected-preview-pages.json`，包含页码、页面角色和选择理由。
5. 每套生成一张 2×2 contact sheet，共严格输出 4 张预览图。不要默认完整覆盖全稿，不按总页数增加预览张数。
6. 运行以下命令验证计划：

   ```bash
   python3 <skill-dir>/scripts/plan_contact_sheets.py "$SLIDE_COUNT" \
     --mode representative --pages "1,4,9,18" --json
   ```

7. 除配色外，让四套在栅格、留白、图表语言或视觉母题上至少有两项实质差异。准确的 A–D 标签、页码、主题名和色板用确定性排版补齐。
8. 首次图像调用前告诉用户预览后回复 A/B/C/D。到达 `PREVIEW_READY` 后停止，等待明确选型。

只有用户明确要求“每套查看全稿缩略图”时，才运行 `--mode full` 并按动态页数生成多张 contact sheets。详细规则见 [references/image-generation-contract.md](references/image-generation-contract.md)。

## 快速路径：直接构建混合可编辑 PPTX

进入条件：用户选择风格，且 `execution_mode=fast`。

1. 冻结设计令牌到 `selected-style-spec.txt`：颜色、字体、层级、网格、边距、圆角、图表、页码和引用格式。
2. 从来源中一次性提取并缓存论文图、实验照片、Logo、二维码、图表数据和引用，生成 `source-asset-manifest.json`。优先复用真实素材，不让图像模型重画已有数据图。
3. 把全部页面映射到 6–8 种原型并保存 `page-archetype-map.json`：Cover、Background/Question、Comparison、Methods/Workflow、Mechanism、Key Result、Validation、Summary。
4. 用原生对象构建标题、正文、数字、简单形状、箭头、表格和数据图表。只对复杂背景、封面主视觉、复杂机制图、装置合成或缺失的非数据插图调用图像模型；通常控制在 4–8 个复杂资产，按实际需要调整，不以牺牲质量凑调用次数。
5. 禁止图像模型生成精确数字、公式、DOI、统计符号或长文本。真实图表由数据确定性绘制；无法反推的数据标注“数据为视觉近似”。
6. 生成 `page-object-manifest.json`、`complex-asset-manifest.json` 和可重复执行的 artifact-tool `.mjs` 源文件。
7. 渲染全稿，先检查四个代表页和所有高风险页，再检查完整浏览图、文本溢出和页数。运行 `pptx_audit.py --profile editable`。
8. 直接交付混合可编辑 PPTX、浏览图和编辑性报告，不再先制作整页图片版。

## 高保真路径：完整图片版后还原

进入条件：`execution_mode=fidelity`。

1. 读取 [references/image-generation-contract.md](references/image-generation-contract.md)，按选定风格逐页生成高清视觉稿；不要放大预览缩略图。
2. 运行可恢复的图片任务队列。每页成功后立即保存并更新 `image-job-manifest.json`；失败页不得终止整批。
3. 并发保持 2–3。设置单页超时；超时后单页重试。医学图片触发安全过滤时，自动改用非血腥示意图、仿体或装置图。
4. 把准确文字、公式、真实数据图和引用确定性合成到页面图中。逐页核对标题、数字、单位、图轴、统计符号和引用。
5. 用 `@oai/artifact-tool` 把页面图无拉伸地铺入同页数 16:9 PPTX；渲染并运行 `pptx_audit.py --profile image`。
6. 到达 `IMAGE_DECK_READY` 后等待用户确认，除非用户已预授权直接继续。
7. 图片版确认后读取 [references/hybrid-reconstruction-and-qa.md](references/hybrid-reconstruction-and-qa.md)，复用阶段中保存的对象与资产清单进行混合可编辑还原，不依赖盲目 OCR。

## 断点续作与失败隔离

- 使用 `scripts/image_job_manifest.py` 初始化、查询和更新图片任务状态。
- 写入成功文件后再标记 `completed`；重启时跳过已完成且文件存在的任务。
- 把 `moderation_blocked`、`timeout`、`transient` 和 `content_error` 分开记录。
- 单页失败时继续处理其他页；最后只重试失败页。
- 不用一个未捕获的 `Promise.all` 错误终止整个生成批次。

## 最终 QA 与交付

1. 使用 `render_slides.py`、`slides_test.py` 和浏览图检查页数、比例、溢出、裁切、节奏和跨页一致性。
2. 抽查所有准确性高风险页：数据、公式、方法参数、引用、联系方式和二维码。
3. 最终报告按页说明：可编辑文字、原生形状/箭头/表格/图表、复用或裁切图片、复杂视觉图片、视觉近似数据、字体替代和剩余限制。
4. 只有内容核对、渲染对照和可编辑性审计通过后，才标记 `QA_PASSED`。
