# 图像生成、快速预览与完整图片版契约

## 1. 共同输入与运行方式

每次生成前准备：

- `SLIDE_COUNT=N` 与唯一的 `content-spec.txt`。
- 参考风格图及其版式、配色、字体、留白、图表和视觉母题分析。
- 禁止改变的结论、数据、术语、引用和品牌元素。
- 16:9 画布与当前设计令牌。

优先使用 Codex 内置图像工具，不因缺少本地 `OPENAI_API_KEY` 而暂停。只有用户明确要求本地 CLI、API 可复现生成或具体本地模型参数时，才按系统 `imagegen` 技能检查 CLI、密钥和 Python 包。记录实际运行方式；不要声称无法验证的模型版本。

## 2. 默认代表页预览

默认每套风格只展示 4 个代表页，不完整覆盖全稿。

### 代表页选择

从 `content-spec.txt` 语义选择：

1. Cover：封面或总览。
2. Context：背景、科学问题、知识缺口或比较。
3. Method：方法、流程、实验设计或机制。
4. Result：关键结果、数据图表或验证。

优先选择最能暴露排版差异、图表语言和视觉风险的页面。少于 4 页时使用全部页面；缺少某类时选择最接近的页面。四套必须使用同一页码集合。

保存：

```json
{
  "slide_count": 32,
  "preview_pages": [1, 4, 10, 23],
  "roles": ["cover", "context", "method", "result"],
  "reasons": ["...", "...", "...", "..."]
}
```

运行计划验证：

```bash
python3 <skill-dir>/scripts/plan_contact_sheets.py "$SLIDE_COUNT" \
  --mode representative --pages "1,4,10,23" --json
```

每套生成一张 2×2 contact sheet，共输出 A、B、C、D 四张图。每张必须：

- 精确包含相同的 4 个代表页，不缺页、不重复、不换序。
- 标明套系、主题名、页码与 4–6 个色板色值。
- 让封面、信息页、方法页和数据页明显不同但属于同一视觉系统。
- 只用短标题；准确标签和页码优先确定性合成。

预览阶段图像调用数固定为 4。不要根据 `SLIDE_COUNT` 增加预览图数量。

## 3. 全稿缩略预览（仅用户明确要求）

用户明确要求“每套完整展示所有页面”时运行：

```bash
python3 <skill-dir>/scripts/plan_contact_sheets.py "$SLIDE_COUNT" \
  --mode full --json
```

每张 contact sheet 最多 12 页。脚本会把 N 页均衡分组，并使用以下网格：

| 页数 | 网格 |
|---:|---:|
| 1 | 1×1 |
| 2 | 2×1 |
| 3–4 | 2×2 |
| 5–6 | 3×2 |
| 7–9 | 3×3 |
| 10–12 | 4×3 |

为四套使用相同分组、页序和全局页码。全稿预览是可选的高成本模式，不得作为默认流程。

## 4. 四套风格差异

四套不能只换色。至少在以下项目中的两项有明显差异：

- 栅格：分栏、卡片、全幅视觉、编辑式排版。
- 留白：高留白、密集证据、非对称或居中聚焦。
- 图表：细线、实心色块、半透明层或论文式重点色。
- 母题：学科形态、路径节点、数据切片或微观纹理。
- 字体气质：现代无衬线、理性几何、轻编辑感或克制衬线。

四套都保持专业、学术和清洁，避免霓虹、商务模板、无关 3D 装饰和过度渐变。

## 5. 完整图片版逐页生成

只在 `execution_mode=fidelity` 时执行。

1. 不把 contact sheet 裁切放大为页面。
2. 为第 01 页至第 N 页独立生成 16:9 页面，使用相同已选预览、设计令牌、页眉页脚、网格和安全区。
3. 只给模型本页必需的内容，避免长提示词与跨页事实污染。
4. 让模型负责构图、复杂背景和视觉资产；准确文字、公式、真实图表、DOI、单位和统计符号由确定性步骤合成。
5. 有数据时用可重复工具绘图。无法反推时只允许视觉近似，并在页面或报告标注“数据为视觉近似”。
6. 文件名使用宽度 `W=max(2,len(str(N)))` 的零填充格式：`slide-{i:0W}.png`。
7. 同步保存 `page-object-manifest.json`、`complex-asset-manifest.json` 和 artifact-tool `.mjs`，供可编辑还原复用。

## 6. 可恢复任务队列

用 `scripts/image_job_manifest.py` 管理逐页生成：

```bash
python3 <skill-dir>/scripts/image_job_manifest.py init manifest.json \
  --slide-count "$SLIDE_COUNT" --out-dir ./page-images

python3 <skill-dir>/scripts/image_job_manifest.py pending manifest.json

python3 <skill-dir>/scripts/image_job_manifest.py mark manifest.json 7 \
  --status completed --path ./page-images/slide-07.png

python3 <skill-dir>/scripts/image_job_manifest.py summary manifest.json
```

执行规则：

- 并发数保持 2–3。
- 每页成功并写入文件后立即标记完成。
- 单页失败不终止整批；不要使用未捕获错误的 `Promise.all`。
- 超时、临时错误和限流使用指数退避重试。
- 医学图片被安全过滤时，把真实手术照片降级为非血腥示意图、仿体或器械图。
- 重启时跳过状态为 `completed` 且文件存在的页；文件缺失时自动恢复为 `pending`。

## 7. 提示词模板

### 代表页 contact sheet

```text
Create one professional 2-by-2 academic presentation style-preview contact
sheet. Show exactly the four specified representative 16:9 slides in order:
{COVER_PAGE}, {CONTEXT_PAGE}, {METHOD_PAGE}, {RESULT_PAGE}.

The four thumbnails belong to one visual system. Preserve their scientific
roles and short titles. Style variant: {A/B/C/D and tokens}. Reference-image
traits: {layout, palette, typography, spacing, chart language, motifs}.

Keep the result clean, research-grade, bilingual Chinese-English, and suitable
for a formal lab meeting. Do not invent data, citations, mechanisms, page
numbers, or extra slides. No missing or repeated thumbnail.
```

### 独立页面

```text
Create slide {CURRENT_PAGE} of {SLIDE_COUNT} as one complete 16:9 academic
presentation page using the approved visual system.

Slide function: {FUNCTION}
One-sentence takeaway: {TAKEAWAY}
Required visual structure: {VISUAL_PLAN}
Reserved exact-text/data regions: {DETERMINISTIC_REGIONS}
Allowed complex visual assets: {ASSETS}

Do not invent data, citations, mechanisms, formulas, or labels. Produce one
polished page, not a contact-sheet crop or a generic corporate template.
```

## 8. 图片版验收

- 实际页数恰好等于 N，全部页面为 16:9 且尺寸一致。
- 页面图无拉伸、黑边、错位和异常裁切。
- 所有关键文字、数字、单位、公式、图轴和引用经过来源对照。
- PPTX 重新渲染后与页面 PNG 基本一致。
- 运行 `pptx_audit.py --profile image --expect-slides "$SLIDE_COUNT"`；解决所有错误并人工确认警告。
