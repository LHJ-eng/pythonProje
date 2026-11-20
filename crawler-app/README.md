# DataHarvester · 自托管网页数据采集系统

输入一个网页链接，系统会自动识别页面里的**表格、列表卡片、正文文章**；输入图片链接或上传本地图片，则使用本地中文 OCR 提取文字。结果可在线预览并导出 **CSV / Excel / JSON / Markdown / HTML 报告**。带**密码门禁**，可完全本地部署，网页数据和图片不会发送给第三方 AI 服务。

> 企业级能力：HTTP 缓存（ETag 条件请求）、同域限速与指数退避重试、同域深度抓取、XPath / CSS 双选择器、可复用的提取 Schema、**可视化点选与规则模板**、缓存与任务指标接口。

> 1.3.0 起进一步强化抽取精度：**合并单元格 / 多行表头还原**、**字段选择器自愈**、**提取质量与置信度评分**、**浏览器网络 JSON 直采**。

> 适合个人或小团队做公开数据采集、竞品价格监控、内容归档、报表取数。
> 请只采集你有权访问的数据，并遵守目标站点服务条款、robots.txt 与当地法律法规。

---

## 一、已实现的功能

| 能力 | 说明 |
| --- | --- |
| 密码门禁 | PBKDF2-SHA256 哈希存储；HMAC 签名会话 Cookie（HttpOnly / SameSite=Lax）；登录失败限流（5 次锁定 5 分钟） |
| 智能识别（默认） | 分层自动识别：HTML 表格 → 重复列表 / 卡片 → 页面结构化数据（JSON-LD、`__NEXT_DATA__`、`window.__INITIAL_STATE__` 等）→ 浏览器网络 JSON → RSS/Atom → 正文文章；自动生成条目选择器与字段，低置信度时会提示核对 |
| 合并单元格还原 | 表格解析按网格还原 `rowspan` / `colspan`，支持多行表头合并（如「成绩 / 数学」），避免跨行跨列导致列错位；可视化点选的表格候选同样生效 |
| 字段选择器自愈 | 站点改版导致 class 变化时，字段为空会自动尝试去掉 class 的等价选择器（仅唯一命中才采用）；链接 / 图片字段在条目内唯一时自动回退，减少整列为空 |
| 提取质量评分 | 每次提取自动计算置信度、字段覆盖率、行完整度与空单元格数；「分析页面」与任务结果都会展示，字段命中率低于 50% 时给出告警 |
| 结构化数据抽取 | 直接解析 JSON-LD `ItemList`、Next.js / Nuxt 等内嵌 JSON，遇到由 JS 注入数据的电商、资讯、招聘等站点时无需浏览器也能取到列表 |
| RSS / Atom 支持 | 直接输入订阅源地址（`.xml` / `.rss` / `feed`）即可解析出条目列表，自动识别标题、链接、日期、摘要字段 |
| 框架页自动跟进 | 遇到 `frameset` 老式目录页（如统计年鉴）时自动尝试 main / content / left 等子框架，选择真正含数据的框架继续提取 |
| 自动浏览器回退 | 静态抓取结果为空、且本机已安装 Playwright 时，自动用浏览器重新渲染一次；前端会提示"已自动切换浏览器渲染" |
| 字段智能清洗 | 自动去掉父子节点重复文本、折叠"标题 标题 标题"式重复、剔除常量列、按语义命名（标题 / 日期 / 链接），一个条目只保留一个链接或图片字段 |
| 主内容清洗 | 内置 readability-lxml（Mozilla Readability 移植），先剥离导航 / 侧栏 / 广告再识别列表与正文，避免周围元素干扰 |
| 高级手动模式 | 保留 HTML 表格、CSS 选择器、正文三种手动模式；条目与字段均支持 **CSS / XPath** 混用，可查看并修改智能识别出的规则 |
| 可视化点选 | 参考 EasySpider / Automa：服务端生成安全快照，在弹窗中直接点击表格或重复列表项，自动生成条目选择器与字段；候选表格会标注「隐藏 / 嵌套」，选中的规则一键套用到表单 |
| 隐藏数据展开 | 快照清洗会移除脚本、事件与外部样式，展开 `display:none` 隐藏元素；浏览器渲染时可自动点击「展开 / 加载更多 / 查看全部」按钮，再滚动整页取数据 |
| 规则模板 | 把表格 / CSS / 正文提取规则保存到 SQLite，支持下拉套用与删除，跨任务复用；可视化点选生成的规则也可保存 |
| 提取 Schema | 「分析页面」会同时输出可复用的提取 Schema（模式、条目选择器、字段、类型）；可通过请求参数 `rule` 直接复用，服务端会校验结构，避免无效规则进入执行环节 |
| 多页采集 | URL 中使用 `{page}` 占位符，最多 20 页；第一页识别后冻结规则，后续页复用，结构异常时保留已抓数据并停止 |
| 深度抓取 | 参考 crawl4ai `DeepCrawlStrategy`：同域 BFS、最大深度 / 页面数、包含 / 排除正则、自动读取 `/sitemap.xml`；每个页面复用首个页面的识别规则，结果新增「来源页面」列 |
| HTTP 缓存 | SQLite 持久化，TTL 内直接复用；过期后携带 ETag / Last-Modified 条件请求，304 时复用本地响应体；支持 `enabled / refresh / bypass` 三种策略与容量上限 |
| 限速与重试 | 同域最小请求间隔 + 随机抖动；429 / 5xx / 网络错误按指数退避重试，自动遵循 `Retry-After` |
| 运行指标 | `/api/metrics` 输出任务状态分布、总行数、缓存命中 / 未命中 / 304 复用次数与关键配置，便于接入监控 |
| 图片文字识别 | 基于 RapidOCR + ONNX Runtime 的本地中文 OCR；支持 JPG / PNG / WebP 图片 URL 与本地上传，逐行输出文字、置信度和坐标 |
| 多种数据来源 | 网页 URL、图片 URL、本地图片、粘贴 HTML、上传本地 `.html` 文件 |
| 页面分析 | 可选步骤：查看智能识别结果、表格数量/行列/表头/预览与正文长度；不分析也可直接开始抓取 |
| 结果预览 | 表格预览前 100 行，显示行数、列数、提取置信度、耗时、抓取页数、告警 |
| 五种导出 | CSV（带 BOM，Excel 打开中文不乱码）、XLSX（带表头样式/冻结/筛选）、JSON、Markdown 表格（便于粘贴到文档 / LLM）、自包含 HTML 报告（含字段完整度统计） |
| 历史任务 | SQLite 持久化，重启后仍可查看与重新导出、删除 |
| SSRF 防护 | 仅 http/https；解析 DNS 后拦截内网/回环/链路本地/元数据地址；每次重定向都重新校验 |
| robots.txt | 默认遵守，可在明确授权时手动忽略 |
| 资源限制 | 响应体大小、超时、页数、行数、并发任务数、排队上限；图片最大 10 MB、2000 万像素并校验真实格式 |
| 浏览器渲染 | 安装 Playwright 后可抓 JS 动态渲染页面；默认拦截图片 / 字体 / 媒体资源加速，可等待指定选择器、滚动整页触发懒加载；智能模式下静态结果为空会自动回退一次；渲染时同步捕获 XHR / fetch 的 JSON 响应，直接解析接口数据，比从渲染后的 DOM 猜结构更准 |
| 正文增强 | 内置 trafilatura 作为基础依赖，正文与元数据抽取质量更高；解析失败时回退内置启发式算法 |
| 部署方式 | Docker Compose 一键部署，或本地 Python 虚拟环境运行 |

---

## 二、参考的 GitHub 开源项目（2026-11-15 星标数据）

选型原则：**高星、活跃、协议宽松、可本地部署**。一期没有直接部署重型平台，而是"薄应用 + 成熟解析库"，原因见下表。

| 项目 | Stars | 定位 | 本项目的取舍 |
| --- | --- | --- | --- |
| [firecrawl](https://github.com/firecrawl/firecrawl) | ~201.9k | AI 友好的爬取/抽取平台 | 未直接自托管：需要 Redis、多服务、API Key、Playwright，资源占用大。借鉴其"URL 进、结构化数据/报告出"的产品形态 |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | ~103.2k | 抗检测抓取框架（Playwright/自适应选择器） | 借鉴自适应选择器与隐身浏览思路；一期用标准 CSS 选择器保证可解释性 |
| [crawl4ai](https://github.com/unclecode/crawl4ai) | ~87.4k | 开源 LLM 爬虫（Apache-2.0） | **本轮重点参考**：落地其 `cache_mode`（enabled / bypass / refresh）+ ETag 条件请求、`DeepCrawlStrategy` 同域 BFS、`RateLimiter` 同域限速、`wait_for` / 整页滚动、Markdown 输出；未直接引入其重型 Playwright 运行时 |
| [Scrapy](https://github.com/scrapy/scrapy) | ~65.4k | 分布式爬虫框架 | 适合百万级抓取；一期单机采集无需引入其工程复杂度 |
| [crawlee-python](https://github.com/apify/crawlee-python) | ~9.7k | Python 爬虫 + 浏览器自动化 | 参考其请求队列/重试设计 |
| [trafilatura](https://github.com/adbar/trafilatura) | ~7.1k | 正文/元数据抽取 | **已接入为基础依赖**，正文与元数据抽取优先使用，失败时回退内置算法 |
| [python-readability](https://github.com/buriy/python-readability) | ~1.6k | Mozilla Readability 的 Python 移植 | **已接入为基础依赖**，用于剥离导航/侧栏/广告后再做列表与正文识别；正文抽取与 trafilatura 并行打分择优 |
| [autoscraper](https://github.com/alirezamika/autoscraper) | ~8.1k | 给样例自动学习规则 | 参考其自动学习思路；当前零输入场景使用确定性的 DOM 结构识别 |
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | ~71.4k | 多平台社媒数据采集 | 借鉴其可配置采集队列与工程化组织方式；按你的要求，本项目**暂不做社媒平台采集** |
| [EasySpider](https://github.com/NaiboWang/EasySpider) | ~44.8k | 可视化点选采集器 | **本轮重点参考**：借鉴「可视化点选 + 工作流」交互，落地服务端安全快照 + 受限 iframe 点击反推 CSS 规则；未引入其 Electron 桌面端 |
| [automa](https://github.com/AutomaApp/automa) | ~10k | 浏览器自动化工作流扩展 | 借鉴「点击元素生成选择器」与工作流编排思路；本项目用网页内弹窗实现，无需安装扩展 |
| [Spider_XHS](https://github.com/cv-cat/Spider_XHS) | ~2k | 小红书数据采集 | 仅参考其字段设计、分页与登录态处理经验；本项目**暂不做社媒采集** |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | ~92.7k | 完整 OCR 与表格结构识别平台 | 能力全面但运行时较重，本次未引入完整 Paddle 运行时 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | ~8.5k | 轻量本地 ONNX OCR | **已接入**，适合中文图片、本地隐私处理与 PyCharm 部署 |

> 说明：星星数以 GitHub 官方 API 实测为准；数字会随时间变化。

**本轮参考 GitHub 落地的增强**：参考 crawl4ai / firecrawl 的"HTML→结构化数据"分层思路，新增 JSON-LD 与内嵌 JSON（`__NEXT_DATA__`、`__INITIAL_STATE__`）抽取；参考 crawl4ai 的 `cache_mode` 落地 SQLite HTTP 缓存与 ETag 条件请求，参考 `DeepCrawlStrategy` 落地同域深度抓取，参考 `RateLimiter` 落地同域限速与 `Retry-After` 退避；参考 Scrapling 的自适应与多策略重试，加入静态失败后的浏览器自动回退与资源拦截；参考 trafilatura 抽取正文；参考 EasySpider / Automa 的"可视化点选"落地安全快照、表格 / 列表候选推断与点击生成规则；并补充 RSS/Atom 解析、`frameset` 子框架自动跟进、XPath 选择器、规则模板与 Markdown 输出。

**1.3.0 精度增强**：参考 crawl4ai / Scrapling 对复杂表格与动态接口的处理方式，新增（1）`rowspan` / `colspan` 网格还原与多行表头合并；（2）字段选择器自愈回退（去 class 唯一命中、唯一链接 / 图片回退）；（3）提取质量评分（置信度、字段覆盖率、行完整度、空单元格）并接入分析与任务结果；（4）浏览器渲染时捕获 XHR / fetch JSON 响应，自动识别接口中的记录列表（`mode: network`），动态页优先采用接口数据。

---

## 三、目录结构

```
crawler-app/
├── app/
│   ├── main.py          # FastAPI 入口、路由、安全响应头
│   ├── config.py        # 环境变量 / .env 配置、密码初始化
│   ├── auth.py          # 密码哈希、签名会话、登录限流
│   ├── security.py      # URL 规范化与 SSRF 防护
│   ├── fetcher.py       # httpx 抓取 + robots + 重定向校验 + 限速重试 + Playwright
│   ├── cache.py         # SQLite HTTP 缓存（TTL / ETag 条件请求 / 容量上限）
│   ├── deep_crawl.py    # 同域 BFS 深度抓取 + sitemap 发现
│   ├── extractor.py     # 智能表格 / 重复列表 / 正文识别 + CSS / XPath + Schema
│   ├── snapshot.py      # 安全快照清洗 + 表格 / 列表候选推断（可视化点选）
│   ├── ocr.py           # RapidOCR 懒加载、图片校验、视觉分行
│   ├── exporter.py      # CSV / XLSX / JSON / Markdown / HTML 报告
│   ├── storage.py       # SQLite 任务存储与统计
│   ├── jobs.py          # 任务参数校验与执行编排（含深度抓取）
│   └── set_password.py  # 生成 PBKDF2 密码哈希
├── static/              # 登录页 + 控制台（原生 JS，无 CDN 依赖）
├── tests/               # 自动化测试（解析、任务、OCR、安全、导出、API）
├── data/                # 运行时生成：SQLite、密钥、初始密码（已 gitignore）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-ocr.txt # 可选本地 OCR 依赖
├── .env.example
└── run.sh
```

---

## 四、快速开始

环境要求：**Python 3.11+（推荐 3.12）**；Docker 方式需要 Docker 24+ 与 Compose v2。

### 方式 A：Docker Compose（推荐，最省事）

```bash
cd crawler-app

# 1. 准备配置：一定要把 APP_PASSWORD 改成你自己的强密码
cp .env.example .env
vi .env

# 2. 准备数据目录（容器内以 UID 1000 运行，需要宿主机目录可写）
mkdir -p data
sudo chown -R 1000:1000 data       # macOS / Windows Docker Desktop 可跳过

# 3. 构建并启动（默认只监听 127.0.0.1:8000）
docker compose up -d --build

# 4. 查看状态与日志
docker compose ps
docker compose logs -f

# 5. 浏览器打开 http://127.0.0.1:8000 ，输入密码登录
```

停止 / 重启 / 升级：

```bash
docker compose down          # 停止（数据在 ./data，不会丢）
docker compose up -d         # 再启动
docker compose up -d --build # 改代码后重建
```

### 方式 B：本地 Python（开发调试）

```bash
cd crawler-app

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # 修改 APP_PASSWORD
# 或者用哈希（推荐）：python -m app.set_password "你的密码"  → 把输出写入 .env 的 APP_PASSWORD_HASH

bash run.sh                        # 等价于 uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Windows 手动启动：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

### 方式 C：PyCharm（新手推荐，每次点绿色三角即可）

1. PyCharm → `File → Open`，选择 `crawler-app` 文件夹。
2. `Settings → Project → Python Interpreter → Add Interpreter → Virtualenv`，新建 `.venv`（Python 3.11/3.12）。
3. 打开底部 Terminal（已自动激活虚拟环境），执行：
   ```powershell
   python -m pip install -r requirements.txt
   python -m pip install -r requirements-ocr.txt
   ```
   第二条用于图片中文 OCR；如果暂时不用图片识别，可以跳过。
4. 在项目根目录新建 `.env` 文件（或复制 `.env.example`），写入：
   ```
   APP_PASSWORD=你的密码
   COOKIE_SECURE=false
   ```
5. 右键 `start.py` → `Run 'start'`。
6. 打开 `http://127.0.0.1:8000`，输入密码使用。
7. 停止：点 PyCharm 运行窗口的红色方块。

以后每次只需：打开项目 → 点顶部绿色三角（运行配置会自动保留）→ 浏览器登录。


**完全不设置密码时**：首次启动会自动生成随机密码，保存到 `data/initial_password.txt`（权限 600），并打印在控制台；之后重启会复用该密码。登录后请尽快在 `.env` 设置自己的 `APP_PASSWORD` 并删除该文件。

### 可选能力

**1）浏览器渲染（抓 JS 动态页面）**

```bash
pip install playwright
python -m playwright install chromium
# Linux 缺系统库时： python -m playwright install --with-deps chromium
```

启用后智能模式会自动处理：等待网络空闲、默认拦截图片 / 字体 / 媒体资源、滚动页面触发懒加载，再提取数据。对于渲染后的列表/卡片页，系统会**优先识别列表数据**而非把整页当成正文，避免抓到一堆导航和页脚文字。若目标数据在某个元素挂载后才出现，可在高级设置填写「等待选择器」（如 `.product-item`）。

Docker 中启用需要在 Dockerfile 增加（镜像会增大约 400MB）：

```dockerfile
RUN pip install playwright && playwright install --with-deps chromium
```

**2）本地中文图片 OCR**

```powershell
python -m pip install -r requirements-ocr.txt
```

OCR 使用 RapidOCR + ONNX Runtime，在本机 CPU 上运行，图片不上传到云端。首次初始化识别引擎可能较慢；识别大量统计表时请逐张提交，避免同时运行过多任务。

Docker 方式如需 OCR，在 `Dockerfile` 中先复制并安装 OCR 依赖（镜像会明显增大）：

```dockerfile
COPY requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements-ocr.txt
```

> 正文抽取库 trafilatura 已写进基础 `requirements.txt`，无需额外安装。

**3）缓存、限速与深度抓取配置（`.env`）**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | 是否启用 HTTP 缓存 |
| `CACHE_MODE` | `enabled` | 全局默认策略：`enabled` / `refresh` / `bypass`；单次任务可在界面覆盖 |
| `CACHE_TTL` | `900` | 缓存有效期（秒） |
| `CACHE_MAX_ENTRIES` / `CACHE_MAX_BYTES` | `500` / `50000000` | 缓存条数与字节上限，超出后从最旧开始淘汰 |
| `HOST_MIN_INTERVAL` / `HOST_JITTER` | `0.5` / `0.3` | 同一域名最小请求间隔与随机抖动（秒） |
| `MAX_RETRIES` / `RETRY_BACKOFF` | `2` / `0.6` | 重试次数与初始退避；自动遵循 `Retry-After` |
| `BROWSER_BLOCK_RESOURCES` | `true` | 浏览器渲染时拦截图片 / 字体 / 媒体资源 |
| `BROWSER_SCROLL_STEPS` | `6` | 整页滚动次数，用于触发懒加载 |
| `BROWSER_EXPAND_CLICKS` | `5` | 浏览器渲染时最多自动点击多少次「展开 / 加载更多 / 查看全部」 |
| `DEEP_MAX_PAGES` | `50` | 深度抓取页数硬上限 |
| `USER_AGENT` | `DataHarvester/1.0` | 建议改成带联系方式的自定义 UA |

---

## 五、使用说明（3 分钟上手）

登录后左侧是任务配置，中间是结果，右侧是历史。

1. **最常用的网页采集（无需设置字段）**：保持「网页 / 图片链接」→ 粘贴 URL → 直接点「开始抓取」。系统会按「数据表 → 重复列表 / 卡片 → 结构化数据（JSON-LD / 内嵌 JSON）→ RSS/Atom → 正文」的顺序自动识别。
   例：`https://quotes.toscrape.com/` 可自动得到 10 条语录及作者、链接、标签等字段。
2. **RSS / Atom 订阅源**：直接粘贴订阅地址（如 `https://www.ruanyifeng.com/blog/atom.xml`），系统按条目列表输出标题、链接、日期、摘要。
3. **识别图片 URL 中的文字**：把 `.jpg`、`.png`、`.webp` 图片地址当作普通链接粘贴，保持智能识别，点击「开始抓取」，系统会自动切换 OCR。
4. **国家统计局 2024 年鉴目录（框架页）示例**：输入
   `https://www.stats.gov.cn/sj/ndsj/2024/indexch.htm`，系统会自动跟进目录框架并提取 727 条章节条目；也可直接输入单张表图片 `https://www.stats.gov.cn/sj/ndsj/2024/html/C02-01.jpg` 做 OCR。
5. **上传本地图片**：来源选择「本地图片识别」→ 选择 JPG / PNG / WebP → 点击「开始识别」。OCR 输出页码、行号、文字、置信度和文字框坐标，可直接导出 Excel / CSV。
6. **分页采集**：展开「高级设置」，URL 写 `https://example.com/list?page={page}`，页数 5，间隔 1.5 秒。多页会复用第一页规则，避免每页字段漂移。
7. **深度抓取**：来源选「网页 URL」、保持智能识别，勾选「深度抓取」，设置最大深度 / 最多页面数，可选包含 / 排除正则（如包含 `/article/`、排除 `/login|/tag/`）。系统会从入口页做同域 BFS，并尝试读取 `/sitemap.xml`；结果新增「来源页面」列。
8. **缓存策略**：高级设置中可选「优先使用缓存（默认）」「强制刷新并校验 ETag」「本次跳过缓存」。相同 URL 在 TTL 内不会重复请求目标站点；缓存库位于 `data/http_cache.db`，可随时删除重建。
9. **XPath 采集**：手动选择器的「条目选择器类型」与每个字段都可独立选 CSS / XPath，例如条目 `//li[@class='row']`、字段 `.//a` + 属性 `href`。
10. **手动修改 / 复用规则**：可先点「分析页面结构」查看智能识别结果与 Schema，再点「在高级设置中查看 / 修改规则」。只有自动结果不准确时才需要手填条目选择器与字段映射。
11. **可视化点选**：点左侧「可视化点选」按钮，系统会生成安全快照并弹出预览窗。直接在预览里点击表格或重复列表项，右侧会自动生成条目选择器与字段；候选区还会列出所有表格（含「隐藏」「嵌套」标记）和列表规则，点一下即可选中。确认后点「套用到表单」或「套用并开始抓取」。
12. **隐藏表格 / 折叠数据**：快照会自动展开 `display:none` 与 `hidden` 元素；如果数据要点击「加载更多 / 展开全部」才出现，请在高级设置勾选「浏览器渲染时自动点击展开按钮」（需安装 Playwright），并设置「等待选择器」。
13. **规则模板**：在高级设置把当前表格 / CSS / 正文规则保存为模板，下次从「规则模板」下拉直接套用；模板只保存规则、不保存数据，可随时删除。
14. **本地 HTML**：来源切「HTML 源码」，粘贴代码或选择 `.html` 文件后开始抓取，全程不联网；同样可以使用可视化点选。

结果区可导出 CSV / Excel / JSON / Markdown / HTML 报告；历史任务随时回看与重新导出。图片 OCR 当前按“视觉行”提取文字，**不会自动还原复杂统计表的行列关系、合并单元格或表头层级**；低置信度文字请对照原图复核。

---

## 六、安全设计与注意事项（重要）

| 风险 | 本项目措施 | 你还需要做什么 |
| --- | --- | --- |
| 未授权访问 | 密码门禁；PBKDF2 26 万次迭代；签名会话 12 小时过期；HttpOnly + SameSite=Lax | 用 16 位以上随机密码；不要多人共用 |
| 暴力破解 | 单 IP 5 次失败锁 5 分钟，失败请求额外延时 | 公网部署务必在 Nginx/Caddy 层再加一层限流与 fail2ban |
| CSRF | 所有写接口要求 `X-CSRF-Token`（与签名会话绑定） | — |
| SSRF（借服务端访问内网） | 仅 http/https；解析所有 A/AAAA 记录并拒绝非公网 IP；拒绝 `file://`/`localhost`/`169.254.169.254`；每次重定向重新校验；URL 禁止携带账号密码 | 云主机建议同时用安全组/网络策略禁止访问元数据地址与内网段 |
| 抓取越权 | 默认遵守 robots.txt；忽略需显式勾选 | 只抓公开、有权访问的数据；不要绕过登录墙/付费墙 |
| 资源耗尽 | 响应体 5MB、超时 25s、单任务 20 页、5 万行、全局并发 2、排队上限 10；HTTP 缓存默认 500 条 / 50MB 自动淘汰 | 按机器配置调整 `MAX_BYTES`/`MAX_CONCURRENT_JOBS`/`CACHE_MAX_ENTRIES` |
| XSS | 前端全部用 `textContent` 渲染；严格 CSP（脚本仅同源）；可视化快照在 `sandbox` iframe（不启用脚本）中渲染，并移除 script / `on*` / `javascript:` / meta refresh | 不要把抓取结果直接贴进其他页面 |
| Cookie 被窃听 | 默认 `COOKIE_SECURE=false` 便于本地 HTTP | 上线 HTTPS 后必须设 `COOKIE_SECURE=true` |
| 明文密码 | 支持 `APP_PASSWORD_HASH` | 生产环境用哈希，不要提交 `.env` 到 Git |

**部署红线**

- **不要**把 8000 端口直接暴露到公网。默认 Compose 仅绑定 `127.0.0.1`；公网访问请用 Nginx/Caddy 反代 + HTTPS + 防火墙白名单。
- 反向代理后需要正确传递客户端 IP（`X-Forwarded-For` / `--proxy-headers` 已开启），否则登录限流可能把所有人当成同一个 IP；同时确认代理层没有被伪造头绕过。
- 本应用是**单进程内存限流**，多实例部署时请改用 Redis 等共享存储。
- 已知限制：
  - 强反爬站点（Cloudflare 人机验证、验证码、指纹校验）不保证成功；
  - 需要登录才能看到的数据不在支持范围；
  - 使用无本地 DNS 的纯代理网络时，SSRF 预解析会失败（这是安全校验的代价）；
  - 处理 `rowspan` 等复杂表格时按行展开，可能出现空单元格；
  - OCR 对模糊、倾斜、低分辨率图片可能误识别；复杂表格仅按视觉行输出，不等于完整表格结构识别；
  - 图片限制为 JPG / PNG / WebP、10 MB、2000 万像素；SVG、动图和伪造图片会被拒绝；
  - DNS 重绑定是高级 SSRF 手法，建议配合出口网络策略防护。

**合规提醒**：采集前确认目标站点条款与 `robots.txt`；涉及个人信息时遵守《个人信息保护法》/GDPR；尊重版权与数据库权利；控制频率，避免影响对方服务。

---

## 七、怎样才算"真正做出来"：验收清单

下面是可复现的验收标准，全部通过即代表系统真实可用（本项目当前状态：**124 个自动化测试全部通过，并用真实站点完成表格 / 重复列表 / 结构化数据 / RSS / frameset 目录 / 正文、缓存命中、深度抓取与五种导出的端到端验证，另用国家统计局 2024 年鉴中文图片完成本地/图片 URL 两条 OCR 链路的实测；可视化点选已用真实浏览器完成登录、快照、表格 / 列表选择与规则套用的 UI 实测**）。

```bash
cd crawler-app
pip install -r requirements-dev.txt
python -m pytest -q          # 预期：124 passed
```

| # | 验收项 | 操作 / 命令 | 通过标准 |
| --- | --- | --- | --- |
| 1 | 服务可启动 | `docker compose up -d` 或 `bash run.sh` | `http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}` |
| 2 | 未登录被拦截 | 浏览器直接访问 `/` | 302 跳转 `/login`；`/api/jobs` 返回 401 |
| 3 | 密码错误 | 输入错误密码 | 401，提示"密码错误" |
| 4 | 防爆破 | 连续输错 5 次 | 第 6 次返回 429 并提示等待 |
| 5 | 正确密码 | 输入 `.env` 中的密码 | 进入控制台，刷新后仍保持登录 |
| 6 | 页面分析 | 输入公开页面 → 「分析页面结构」 | 显示标题、表格列表（行列数/表头/预览）或正文长度 |
| 7 | 表格采集 | 选择表格 → 开始抓取 | 状态"已完成"，行数与页面一致，预览正常 |
| 8 | CSS 采集 | 条目 `div.quote`，字段映射 3 个 | 每张卡片一行，链接为绝对地址 |
| 9 | 正文采集 | 选「正文文章」 | 得到标题 + 正文文本 |
| 10 | 分页 | URL 含 `{page}`，页数 2 | 两页数据合并，`抓取页数=2` |
| 11 | CSV 导出 | 点「导出 CSV」 | 文件带 BOM，Excel 打开中文正常 |
| 12 | Excel 导出 | 点「导出 Excel」 | 可正常打开，表头加粗、首行冻结 |
| 13 | JSON / 报告 | 导出 JSON、HTML 报告 | JSON 可解析；HTML 报告含字段完整度统计 |
| 14 | 历史持久化 | 重启服务后刷新历史 | 任务仍在，可再次导出 |
| 15 | SSRF 防护 | 尝试 `http://127.0.0.1/`、`http://169.254.169.254/` | 被拒绝，提示"内网/保留地址" |
| 16 | robots 遵守 | 目标 robots 禁止的路径 | 任务失败并提示 robots 规则 |
| 17 | 粘贴 HTML | 上传本地 `.html` 文件后采集 | 无需联网即可得到数据 |
| 18 | 一键智能识别 | 只输入 `https://quotes.toscrape.com/` 并开始 | 不填写选择器，自动得到 10 行卡片数据 |
| 19 | 图片 OCR | 上传清晰中文图片或输入年鉴 JPG 地址 | 输出逐行文字与置信度，可导出 Excel / CSV |
| 20 | 结构化数据 | 输入含 JSON-LD / `__NEXT_DATA__` 的页面 | 自动得到条目列表，字段含标题与链接 |
| 21 | RSS / Atom | 输入订阅源地址 | 识别为 `feed` 模式，输出条目标题 / 链接 / 日期 |
| 22 | 框架页目录 | 输入 `https://www.stats.gov.cn/sj/ndsj/2024/indexch.htm` | 自动跟进框架，得到 727 行章节条目 |
| 23 | 动态页回退 | 安装 Playwright 后输入 JS 渲染页面 | 静态为空时自动用浏览器重试并提示"已自动切换浏览器渲染" |
| 24 | HTTP 缓存 | 对同一 URL 连续抓取两次 | 第二次 `via=cache`，缓存库条目增加；切换「本次跳过缓存」后重新请求 |
| 25 | ETag 校验 | 缓存过期后再次抓取 | 服务端返回 304 时复用本地内容，前端显示"ETag 校验复用" |
| 26 | 限速重试 | 目标返回 429 且带 `Retry-After` | 自动等待后重试，不是立即失败；日志/耗时可见 |
| 27 | 深度抓取 | 入口页 + 深度 1 + 最多 5 页 | 自动跟随同域链接，结果含「来源页面」列，可导出 |
| 28 | XPath / Schema | 条目 `//li`、字段 `.//a` + `href` | 正确输出文本与绝对链接；`/api/analyze` 返回 `schema` |
| 29 | Markdown 导出 | 结果区点「导出 Markdown」 | 生成 Markdown 表格，可直接粘贴到文档 |
| 30 | 指标接口 | 登录后访问 `/api/metrics` | 返回任务状态分布、总行数、缓存命中/未命中/304 次数 |
| 31 | 可视化点选 | 粘贴一段含表格和 3 个卡片的 HTML → 「可视化点选」 | 弹窗显示安全快照、表格 / 列表候选；点表格后自动填入条目选择器与「名称 / 价格」字段 |
| 32 | 隐藏表格 | 页面里放一个 `style="display:none"` 的表格 | 候选区标注「隐藏」，快照中已展开，可选择并抓取 |
| 33 | 规则模板 | 保存 CSS 规则 → 刷新页面 → 下拉套用 | 条目选择器、字段、属性完整恢复；删除后下拉不再出现 |

---

## 八、常见问题

**端口被占用**：`PORT=8010 bash run.sh`，或修改 `docker-compose.yml` 左边端口。

**忘记密码**：设置 `.env` 的 `APP_PASSWORD` 后重启即可覆盖；或删除 `data/generated_password.hash` 与 `data/initial_password.txt` 重新生成。

**抓取返回 403 / 空数据**：多数是 JS 渲染或反爬。先在「页面渲染」选「浏览器渲染」并安装 Playwright；仍失败则说明站点有强风控，请勿强行绕过。

**为什么第二次抓取很快就完成**：命中了本地 HTTP 缓存。需要获取最新内容时，在高级设置把缓存策略改为「强制刷新并校验 ETag」或「本次跳过缓存」；也可以删除 `data/http_cache.db`。

**深度抓取为什么没抓满页数**：同域过滤会跳过图片、PDF、CSS/JS 等静态资源；`DEEP_MAX_PAGES` 是服务端硬上限（默认 50），达到上限会在结果提示「已截断」。用包含 / 排除正则可以更精准地圈定内容页。

**中文乱码**：抓取端会按响应头与 meta charset 自动解码（含 gb18030 兜底）；导出 CSV 带 BOM，用 Excel 直接双击打开即可。

**提示未安装 OCR 依赖**：在 PyCharm 底部 Terminal 确认使用的是本项目解释器，然后执行 `python -m pip install -r requirements-ocr.txt`，重启 `start.py`。若第三方镜像提示找不到 RapidOCR 3.10+，改用官方源：`python -m pip install --index-url https://pypi.org/simple -r requirements-ocr.txt`。

**识别图片后不是规范表格**：当前 OCR 输出的是逐行文字和坐标，不做复杂表格结构重建。可以导出 Excel 后二次整理；关键统计数据请对照原图和置信度复核。

**数据会不会丢**：所有任务与结果都在 `data/jobs.db`（SQLite，WAL 模式）。备份该文件即可；Docker 方式已挂载 `./data`。

**能不能多人用**：一期是单密码、单管理员模式，适合个人或小团队内网使用。多用户/权限/API Key 在二期。

---

## 九、二期路线

- 更完整的工作流录制（多步点击、翻页、表单提交）
- 定时任务与增量去重
- 代理池、请求指纹与更强的反爬适配（参考 Scrapling）
- LLM 辅助结构化抽取（参考 Crawl4AI / Firecrawl）
- 多用户、审计日志、任务配额
- 结果直接写入飞书表格 / 数据库

---

## 十、免责声明

本工具仅用于合法的数据采集与技术学习。使用者需自行确保抓取行为符合目标站点的服务条款、robots.txt 以及所在地区的法律法规。因不当使用产生的任何后果由使用者自行承担。
