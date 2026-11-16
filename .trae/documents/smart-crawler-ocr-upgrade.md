# Context

现有 DataHarvester 已能在本地 PyCharm 运行，但列表页仍要求用户手填条目选择器和字段映射；国家统计局 2024 年鉴等网站又把统计表发布为 JPG，现有 HTML 解析无法读取其中文字。此次升级目标是：默认只输入链接并点击“开始抓取”，系统自动判断表格、重复列表、正文或图片；同时支持本地图片 OCR，结果继续进入现有任务历史和四种导出。

GitHub 选型已核实：Crawl4AI（unclecode/crawl4ai，约 8.7 万星）提供分层提取策略，但完整引入过重且部分能力依赖 LLM；AutoScraper（alirezamika/autoscraper，约 8 千星）适合样例学习，但零输入场景仍需确定性规则；Trafilatura（adbar/trafilatura，约 7.1 千星）继续作为可选正文增强；PaddleOCR（约 9.2 万星）能力完整但运行时较重。最终借鉴分层提取思想，自行实现轻量自动检测，OCR 采用本地 RapidOCR（RapidAI/RapidOCR，约 8.5 千星）+ ONNX Runtime，不接云服务、不上传用户图片。

## 1. 默认智能识别网页

在 [extractor.py](file:///workspace/crawler-app/app/extractor.py) 新增 `extract_auto()`，保留现有手动 `table/css/article` 函数不变：

1. **HTML 表格**：复用 `parse_tables()` / `extract_table()`，只把至少 2 行、2 列且非空数据充足的表格作为强候选，避免把布局表格当数据表。
2. **重复列表**：在同父容器下寻找至少 3 个同标签、结构相似的 sibling（如 `ul>li`、重复商品卡片）；排除导航、页眉、页脚、表单和隐藏节点。抽样比较 DOM 结构相似度，生成并重新验证可执行的条目 CSS 选择器；从标题、文本叶子、链接、图片、时间等重复子节点推断最多 6 个字段及 `text/href/src` 属性，最终复用 `extract_css()`。
3. **正文**：没有可靠结构化候选时复用 `extract_article()`，保留 trafilatura 可选增强。
4. 按结构证据评分并返回识别模式、置信度、条目选择器和字段规则；低置信度结果必须带警告。空页、frameset、JS 空壳给出可操作提示，不自动遍历框架或整站。
5. `analyze_page()` 增加自动识别摘要，但保留原有返回字段。

在 [jobs.py](file:///workspace/crawler-app/app/jobs.py) 将 `mode` 扩展为默认 `auto`。多页任务在第一页识别成功后冻结表格序号或列表选择器/字段，后续页复用同一规则；后续页失败时保留已完成数据并停止翻页，避免列错位。

## 2. 图片 URL 与本地图片 OCR

新增 [ocr.py](file:///workspace/crawler-app/app/ocr.py) 和 `requirements-ocr.txt`：

- 使用 `rapidocr>=3.10,<4` 与 `onnxruntime`，第三方库仅在 OCR 函数内延迟导入；基础网页抓取在未安装 OCR 依赖时仍可运行。
- 模型懒加载单例，加锁保护初始化与推理；CPU 工作通过 `asyncio.to_thread()` 执行。
- 本地图片由前端 FileReader 转为 data URL，通过现有 JSON `POST /api/jobs` 提交，新增 `source=image`、`image_data`、`image_name`，不引入 multipart。
- Pillow 在内存中校验真实图片，支持 JPEG/PNG/WebP；限制原图 10MB、2000 万像素，拒绝伪造、损坏、SVG 和动画图片，处理 EXIF 方向。
- OCR 结果标准化为按视觉阅读顺序排列的 `页码、行号、文字、置信度、左、上、右、下`；根据检测框 Y 坐标分行、X 坐标排序，明显单元格间隔用 ` | ` 标记。第一阶段交付逐行文字，不承诺复杂表格合并单元格还原。
- 识别元数据保存图片尺寸、文本块数、平均/最低置信度；不保存原图、base64 或模型原始对象。

在 [fetcher.py](file:///workspace/crawler-app/app/fetcher.py) 为 `FetchResult` 增加带默认值的 `kind/body`：HTML 行为不变；自动模式遇到真实图片响应时返回原始字节并进入 OCR。图片下载完整复用 `validate_url()`、robots、逐跳重定向 SSRF 校验、超时和流式大小限制，绝不把 URL 交给 OCR 库自行请求。

在 [jobs.py](file:///workspace/crawler-app/app/jobs.py) 统一编排：URL 可为 HTML 或图片，本地 `source=image` 直接 OCR；`sanitize_params()` 同时剥离 HTML 和 base64，数据库结构不变。

## 3. 前端简化为默认一键操作

修改 [index.html](file:///workspace/crawler-app/static/index.html)、[app.js](file:///workspace/crawler-app/static/app.js) 和必要的 [style.css](file:///workspace/crawler-app/static/style.css)：

- 默认选择“智能识别（推荐）”；原表格/CSS/正文模式保留为高级设置。
- 新增“本地图片”来源和文件选择器；网页链接若直接指向 JPG/PNG/WebP，无需额外选择，点击开始即 OCR。
- 高级折叠区保留分页、请求间隔、浏览器渲染、robots、表格序号和手动字段映射。
- 结果区显示“识别为表格/列表/正文/图片 OCR”、自动规则和置信度警告；本地图片历史标签正确显示。
- “分析页面结构”不再在自动模式下擅自切换到手动表格模式；本地图片禁用页面分析。
- 缺少 OCR 依赖时显示明确命令：`python -m pip install -r requirements-ocr.txt`，安装后重启服务。

[main.py](file:///workspace/crawler-app/app/main.py) 仅做分支适配：本地图片不执行 URL 校验；分析接口遇到图片时提示直接开始 OCR，不重复执行识别。现有认证、CSRF、安全响应头、历史、删除和导出接口保持不变。

## 4. 文档与依赖

新增 `requirements-ocr.txt`，基础 `requirements.txt` 不引入重型 OCR 依赖。更新现有 [README.md](file:///workspace/crawler-app/README.md)：默认一键操作、OCR 安装与首次模型加载说明、支持的图片格式和限制、年鉴 JPG 示例、复杂表格需人工校对，以及安全/隐私说明。

## 5. 验证

1. 新增自动识别单元测试：数据表、布局表排除、无序列表、商品卡片、无 class 列表、链接/图片字段、导航排除、正文回退、frameset 提示、低置信度警告、多页规则冻结。
2. 新增 OCR 测试：假引擎验证坐标分行与置信度；Pillow 验证有效/伪造/损坏/超限图片；base64 不脱敏入库、缺依赖友好错误；直接图片 URL 仍执行 SSRF/robots/大小检查。
3. 运行现有全部测试，确认手动 table/css/article、登录、CSRF、SSRF 和四种导出无回归。
4. 本地端到端验收：quotes.toscrape.com 自动列表、含 HTML 表格页面自动表格、文章页自动正文；上传一张中文图片；直接输入国家统计局 `https://www.stats.gov.cn/sj/ndsj/2024/html/C02-01.jpg` 完成中文 OCR，并重新打开历史、导出 CSV/XLSX/JSON/HTML。
5. 最后用浏览器检查默认页面只需“输入 URL → 开始抓取”，高级模式仍可使用；把更新后的项目和压缩包交付给用户，并给出 PyCharm 中安装依赖、重启和验证的短步骤。

明确不做：云 LLM/云 OCR、完整 PaddleOCR 表格结构识别、自动整站/框架遍历、自动 OCR 页面内所有图片、修改数据库结构或削弱现有安全边界。
