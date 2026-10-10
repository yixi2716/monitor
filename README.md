# 猪周期监测网站（pig-cycle-monitor）

自动更新的猪周期监测站：定时抓取猪价/期货/产能数据，规则引擎跟踪拐点确认信号，前端仪表盘渲染。

- **技术栈**：Python 3.11 + akshare（结构化数据）+ DeepSeek API（公告文本提取）+ GitHub Actions（定时调度）+ GitHub Pages（静态托管）+ ECharts（前端图表）
- **成本**：DeepSeek API 约 0.5 元/月，GitHub Actions/Pages 免费
- **分工原则**：价格/期货走确定性代码；公告/月报走 DeepSeek 文本提取；AI 只做提取不做判断；信号灯规则由代码确定性执行。LLM 提取结果带 `need_review` 标记，人工复核后才进入正式信号计算。

## 架构

```
GitHub Actions cron 定时触发
 ├─ fetch_daily.py    每日 16:30（北京）：期货 LH/C/M、现货猪价、猪粮比、LH期限结构
 ├─ fetch_monthly.py  每月 15 日：农业农村部公告 → 正则/DeepSeek 提取能繁母猪存栏
 ├─ fetch_reports.py  每月 10 日：巨潮猪企月报 + 期货公司周报 → DeepSeek 提取
 └─ signals.py        规则引擎：合并全部数据 → 拐点信号灯判断 → signals.json
        ↓ git commit & push
 data/*.json ──→ GitHub Pages 静态网站（index.html 读取 JSON 渲染仪表盘）
```

## 目录结构

```
pig-cycle-monitor/
├── .github/workflows/update.yml    # 定时任务 + Pages 自动部署
├── requirements.txt
├── config/
│   ├── rules.json                  # 信号灯规则配置（阈值可改）
│   └── prices.json                 # 玉米现货价兜底等参数
├── scripts/
│   ├── fetch_daily.py              # 每日：期货+现货+猪粮比+期限结构
│   ├── fetch_monthly.py            # 每月：能繁母猪（正则→DeepSeek）
│   ├── fetch_reports.py            # 每月：猪企月报+周报提取
│   ├── signals.py                  # 规则引擎
│   └── util.py                     # 共用工具（git提交、JSON读写）
├── data/                           # 脚本写入（latest/history/manual/signals.json）
├── site/
│   ├── index.html                  # 仪表盘主页
│   └── app.js                      # 渲染逻辑（ECharts CDN）
└── README.md
```

## 本地运行

```bash
pip install -r requirements.txt
python scripts/fetch_daily.py     # 生成 data/latest.json、history.json
python scripts/signals.py         # 生成 data/signals.json
python -m http.server 8000        # 在仓库根目录启动
# 浏览器打开 http://localhost:8000/site/index.html
```

> 本地直接双击 index.html（file://）时浏览器会拒绝 fetch JSON；届时可把
> data/*.json 内容填入 site/index.html 顶部 `window.__PIG_DATA__` 后刷新查看，
> GitHub Pages 部署环境无需此操作。

## 部署步骤（按序执行）

1. 创建 GitHub 仓库 `pig-cycle-monitor`，上传全部文件（含 `.github/`）。
2. Settings → Secrets and variables → Actions 添加 `DEEPSEEK_API_KEY`
   （https://platform.deepseek.com 申请，每月仅 0.5 元量级）。
3. Settings → Pages：Source 选 **GitHub Actions**（workflow 已内置部署步骤，
   会自动把最新 data/ 打包进 site/ 后发布，无需手动选分支目录）。
4. 仓库 Actions 页手动触发一次 `workflow_dispatch` 验证全链路：
   `data/latest.json` 有值、`data/signals.json` 生成、Pages 站点可访问。
5. 每月 15 日 workflow 运行后，检查 `data/manual.json` 中 `sow.need_review` 记录，
   人工核对农业农村部原文后把 `need_review` 改为 `false` 并 push
   （复核后 signals 才计入产能类信号）。

## 验收标准

- [ ] Actions 每日运行成功，`data/history.json` 随时间累积且无缺日（数据源故障日除外，需有日志）。
- [ ] `data/signals.json` 每日更新，score/verdict 随规则正确变化（`scripts/selftest_signals.py` 可验证规则分支）。
- [ ] LLM 提取结果均带 `need_review: true`；越界值（能繁母猪不在 3000~4500 万头）不进入信号计算。
- [ ] 前端仪表盘 5 个区块渲染正常，灰态（数据缺失）不报错。
- [ ] DeepSeek 月调用成本 < 1 元（Actions 日志中统计 token 用量抽查）。

## 已知限制与后续迭代

- **akshare 接口稳定性**：新浪/生意社接口变动会导致抓取失败，脚本已做容错（跳过+日志），
  需要人工定期维护接口。本地验证时若 `fetch_spot_pig` 两个候选接口都失效，现货记为 gap。
- **冻品库容/出栏体重/二育**：依赖免费周报文本质量（`WEEKLY_REPORT_URLS` 需人工配置稳定链接），
  解析准确率需人工抽查；若长期不稳定，改为前端提供手动录入表单。
- **能繁母猪公告**：农业农村部页面结构可能变化，`fetch_moa_announcement` 已实现
  栏目列表页检索 + 正文解析，失败时返回空串并记日志，可改为人工补录。
- **猪企月报正文**：cninfo 公告为 PDF，当前只记录公告标题供人工查阅；
  如需自动提取，可安装 pdfplumber 后补充 PDF 解析（TODO）。
- **后续迭代**：拐点确认后的微信/Telegram 推送（Actions 调 webhook）；多历史周期对比图；猪企个股联动面板。

## 光伏看板（solar.html · 2026-10 上线）

与医药看板同构的四层监测：**位置（左侧）× 时机（右侧）× 政策 × 产业**。
信号计算纯函数在 `scripts/solar_core.js`（前端与 `scripts/test_solar_replay.js`
node 回放测试共用同一文件，回放测试是上线生死线）。

### 指标数据源与维护频率表

| 模块 | 指标 | 数据源 | 频率 | 维护方式 |
|---|---|---|---|---|
| 行情矩阵 | 光伏ETF 515790 / 新能源ETF 516160 / 储能ETF 159566 / 沪深300 | Tushare fund_daily/index_daily | 日频自动 | 自动（Actions） |
| 行情矩阵 | 个股（隆基/捷佳/通威/阳光/福莱特等7只代表股） | Tushare daily | 日频自动 | 自动 |
| 宏观卡片 | 10Y美债 / 美元人民币 | 复用医药页 history.json（同源共享，不重复抓取） | 日频 | 自动 |
| 灯⑥ 估值位置 | 光伏池 PB<1 家数 ÷ 总数（池约30只，见 fetch_solar.py SOLAR_POOL） | Tushare daily_basic | 日频自动 | 自动；**成分池约季度人工核对一次** |
| 灯⑦ 成交占比 | 光伏池 Σ成交额 ÷ 全市场 Σ成交额，分位逐日积累（满30个交易日出分位） | Tushare daily | 日频自动 | 自动 |
| 灯⑧ 政策日历 | 宏观事件（与医药页同源）+ 硅业分会每周三报价 / 能源局月度装机 / 事件型节点（预估） | site/data/solar/calendar.json | — | **手工季度维护** |
| ① 商品价格 | 多晶硅/组件/玻璃/硅片/电池 周度价 | config/solar_manual.json（硅业分会周三报价 > InfoLink/隆众/SMM 周报） | 周频 | **手工，建议每月至少核对一次**；价格序列须保留≥5周①号灯才可算 |
| 公司先行指标 | 捷佳伟创合同负债 / 隆基出货均价+减亏 / 行业季度亏损总额 | config/solar_manual.json（季报） | 季度 | **手工，季报披露后更新** |
| 新闻 | Google News RSS（光伏/多晶硅/硅料/组件/硅片） | 免费 RSS | 日频 | 自动 |
| AI 综合分析 | DeepSeek（浏览器端手动生成 + 存档） | 用户自带 API Key | 手动 | 手动 |

### 组合状态真值表（scripts/solar_core.js combineState）

🔵底部区（⑥⑦全亮且时机≤2灯、无临近事件）/ 🟡埋伏区（同上但 level≥4 事件≤14天）/
🟢趋势确认（时机≥4灯）/ 🔴规避（位置≤1亮、无事件、时机≤1灯）/ ⚪中性 / ⚫过热区
（光伏ETF 距前高回撤<15% 且 灯④广度满格，强制覆盖）。

### 回放测试

```bash
node scripts/test_solar_replay.js
# 测试A：2024-08 底部 → 🔵底部区；测试B：2026-02 捷佳独涨顶部 → 非🟢且④灭；测试C：过热覆盖 → ⚫
```
