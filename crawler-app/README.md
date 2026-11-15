# DataHarvester · 自托管网页数据采集系统

输入一个网页链接（或直接粘贴 / 上传 HTML），把页面里的**表格、列表卡片、正文文章**抽取成结构化数据，在线预览并导出 **CSV / Excel / JSON / HTML 报告**。带**密码门禁**，可完全本地部署，数据不经过任何第三方服务。

> 适合个人或小团队做公开数据采集、竞品价格监控、内容归档、报表取数。
> 请只采集你有权访问的数据，并遵守目标站点服务条款、robots.txt 与当地法律法规。

---

## 一、已实现的功能（一期）

| 能力 | 说明 |
| --- | --- |
| 密码门禁 | PBKDF2-SHA256 哈希存储；HMAC 签名会话 Cookie（HttpOnly / SameSite=Lax）；登录失败限流（5 次锁定 5 分钟） |
| 三种提取模式 | ① 自动识别 HTML 表格 ② CSS 选择器（列表 / 卡片） ③ 正文文章抽取 |
| 多页采集 | URL 中使用 `{page}` 占位符，最多 20 页，页间可设延时 |
| 多种数据来源 | 网页 URL、粘贴 HTML、上传本地 `.html` 文件 |
| 页面分析 | 抓取前先分析：页面标题、检测到的表格数量/行列/表头/预览、正文长度，点选表格即可采集 |
| 结果预览 | 表格预览前 100 行，显示行数、列数、耗时、抓取页数、告警 |
| 四种导出 | CSV（带 BOM，Excel 打开中文不乱码）、XLSX（带表头样式/冻结/筛选）、JSON、自包含 HTML 报告（含字段完整度统计） |
| 历史任务 | SQLite 持久化，重启后仍可查看与重新导出、删除 |
| SSRF 防护 | 仅 http/https；解析 DNS 后拦截内网/回环/链路本地/元数据地址；每次重定向都重新校验 |
| robots.txt | 默认遵守，可在明确授权时手动忽略 |
| 资源限制 | 响应体大小、超时、页数、行数、并发任务数、排队上限 |
| 可选浏览器渲染 | 安装 Playwright 后可抓 JS 动态渲染页面 |
| 可选正文增强 | 安装 trafilatura 后正文抽取质量更高（未安装时使用内置启发式算法） |
| 部署方式 | Docker Compose 一键部署，或本地 Python 虚拟环境运行 |

---

## 二、参考的 GitHub 开源项目（2026-11-15 星标数据）

选型原则：**高星、活跃、协议宽松、可本地部署**。一期没有直接部署重型平台，而是"薄应用 + 成熟解析库"，原因见下表。

| 项目 | Stars | 定位 | 本项目的取舍 |
| --- | --- | --- | --- |
| [firecrawl](https://github.com/firecrawl/firecrawl) | ~201.9k | AI 友好的爬取/抽取平台 | 未直接自托管：需要 Redis、多服务、API Key、Playwright，资源占用大。借鉴其"URL 进、结构化数据/报告出"的产品形态 |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | ~103.2k | 抗检测抓取框架（Playwright/自适应选择器） | 借鉴自适应选择器与隐身浏览思路；一期用标准 CSS 选择器保证可解释性 |
| [crawl4ai](https://github.com/unclecode/crawl4ai) | ~87.4k | 开源 LLM 爬虫（Apache-2.0） | 借鉴本地部署与 Markdown/结构化输出；作为二期 LLM 抽取的候选 |
| [Scrapy](https://github.com/scrapy/scrapy) | ~65.4k | 分布式爬虫框架 | 适合百万级抓取；一期单机采集无需引入其工程复杂度 |
| [crawlee-python](https://github.com/apify/crawlee-python) | ~9.7k | Python 爬虫 + 浏览器自动化 | 参考其请求队列/重试设计 |
| [trafilatura](https://github.com/adbar/trafilatura) | ~7.1k | 正文/元数据抽取 | **已接入为可选依赖**，未安装时使用内置正文算法 |
| [autoscraper](https://github.com/alirezamika/autoscraper) | ~8.1k | 给样例自动学习规则 | 二期做"点选式选择器"的参考 |

> 说明：星星数以 GitHub 官方 API 实测为准；数字会随时间变化。

---

## 三、目录结构

```
crawler-app/
├── app/
│   ├── main.py          # FastAPI 入口、路由、安全响应头
│   ├── config.py        # 环境变量 / .env 配置、密码初始化
│   ├── auth.py          # 密码哈希、签名会话、登录限流
│   ├── security.py      # URL 规范化与 SSRF 防护
│   ├── fetcher.py       # httpx 抓取 + robots + 重定向校验 + Playwright
│   ├── extractor.py     # 表格 / CSS / 正文三种解析
│   ├── exporter.py      # CSV / XLSX / JSON / HTML 报告
│   ├── storage.py       # SQLite 任务存储
│   ├── jobs.py          # 任务参数校验与执行编排
│   └── set_password.py  # 生成 PBKDF2 密码哈希
├── static/              # 登录页 + 控制台（原生 JS，无 CDN 依赖）
├── tests/               # 40 个自动化测试
├── data/                # 运行时生成：SQLite、密钥、初始密码（已 gitignore）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
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

**完全不设置密码时**：首次启动会自动生成随机密码，保存到 `data/initial_password.txt`（权限 600），并打印在控制台；之后重启会复用该密码。登录后请尽快在 `.env` 设置自己的 `APP_PASSWORD` 并删除该文件。

### 可选能力

**1）浏览器渲染（抓 JS 动态页面）**

```bash
pip install playwright
python -m playwright install chromium
# Linux 缺系统库时： python -m playwright install --with-deps chromium
```

Docker 中启用需要在 Dockerfile 增加（镜像会增大约 400MB）：

```dockerfile
RUN pip install playwright && playwright install --with-deps chromium
```

**2）更好的正文抽取**

```bash
pip install trafilatura
```

---

## 五、使用说明（3 分钟上手）

登录后左侧是任务配置，中间是结果，右侧是历史。

1. **表格采集**：粘贴页面 URL → 点「分析页面结构」→ 在检测结果里点选表格 → 「开始抓取」。
   例：`https://www.w3schools.com/html/html_tables.asp`
2. **列表/卡片采集**：提取方式选「CSS 选择器」。
   例：`https://quotes.toscrape.com/`
   - 条目选择器：`div.quote`
   - 字段：`语录` → `.text`；`作者` → `.author`；`链接` → `a`，属性 `href`
3. **正文采集**：选「正文文章」，输出标题、作者、日期、摘要、来源、正文一行。
4. **分页采集**：URL 写 `https://example.com/list?page={page}`，页数 5，间隔 1.5 秒。
5. **本地文件**：来源切「粘贴 / 上传 HTML」，选文件后点分析/抓取，全程不联网。

结果区可导出 CSV / Excel / JSON / HTML 报告；历史任务随时回看与重新导出。

---

## 六、安全设计与注意事项（重要）

| 风险 | 本项目措施 | 你还需要做什么 |
| --- | --- | --- |
| 未授权访问 | 密码门禁；PBKDF2 26 万次迭代；签名会话 12 小时过期；HttpOnly + SameSite=Lax | 用 16 位以上随机密码；不要多人共用 |
| 暴力破解 | 单 IP 5 次失败锁 5 分钟，失败请求额外延时 | 公网部署务必在 Nginx/Caddy 层再加一层限流与 fail2ban |
| CSRF | 所有写接口要求 `X-CSRF-Token`（与签名会话绑定） | — |
| SSRF（借服务端访问内网） | 仅 http/https；解析所有 A/AAAA 记录并拒绝非公网 IP；拒绝 `file://`/`localhost`/`169.254.169.254`；每次重定向重新校验；URL 禁止携带账号密码 | 云主机建议同时用安全组/网络策略禁止访问元数据地址与内网段 |
| 抓取越权 | 默认遵守 robots.txt；忽略需显式勾选 | 只抓公开、有权访问的数据；不要绕过登录墙/付费墙 |
| 资源耗尽 | 响应体 5MB、超时 25s、单任务 20 页、5 万行、全局并发 2、排队上限 10 | 按机器配置调整 `MAX_BYTES`/`MAX_CONCURRENT_JOBS` |
| XSS | 前端全部用 `textContent` 渲染；严格 CSP（禁止内联脚本与外链资源） | 不要把抓取结果直接贴进其他页面 |
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
  - DNS 重绑定是高级 SSRF 手法，建议配合出口网络策略防护。

**合规提醒**：采集前确认目标站点条款与 `robots.txt`；涉及个人信息时遵守《个人信息保护法》/GDPR；尊重版权与数据库权利；控制频率，避免影响对方服务。

---

## 七、怎样才算"真正做出来"：验收清单

下面是可复现的验收标准，全部通过即代表系统真实可用（本项目当前状态：**40 个自动化测试全部通过，并用本地站点完成三种模式与四种导出的端到端验证**）。

```bash
cd crawler-app
pip install -r requirements-dev.txt
python -m pytest -q          # 预期：40 passed
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

---

## 八、常见问题

**端口被占用**：`PORT=8010 bash run.sh`，或修改 `docker-compose.yml` 左边端口。

**忘记密码**：设置 `.env` 的 `APP_PASSWORD` 后重启即可覆盖；或删除 `data/generated_password.hash` 与 `data/initial_password.txt` 重新生成。

**抓取返回 403 / 空数据**：多数是 JS 渲染或反爬。先在「页面渲染」选「浏览器渲染」并安装 Playwright；仍失败则说明站点有强风控，请勿强行绕过。

**中文乱码**：抓取端会按响应头与 meta charset 自动解码（含 gb18030 兜底）；导出 CSV 带 BOM，用 Excel 直接双击打开即可。

**数据会不会丢**：所有任务与结果都在 `data/jobs.db`（SQLite，WAL 模式）。备份该文件即可；Docker 方式已挂载 `./data`。

**能不能多人用**：一期是单密码、单管理员模式，适合个人或小团队内网使用。多用户/权限/API Key 在二期。

---

## 九、二期路线

- 可视化点选选择器（浏览器里点元素自动生成规则）
- 定时任务与增量去重
- 代理池、请求指纹与更强的反爬适配（参考 Scrapling）
- LLM 辅助结构化抽取（参考 Crawl4AI / Firecrawl）
- 多用户、审计日志、任务配额
- 结果直接写入飞书表格 / 数据库

---

## 十、免责声明

本工具仅用于合法的数据采集与技术学习。使用者需自行确保抓取行为符合目标站点的服务条款、robots.txt 以及所在地区的法律法规。因不当使用产生的任何后果由使用者自行承担。
