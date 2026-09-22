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
