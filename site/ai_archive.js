/* AI 分析档案：按日期保存 / 翻阅 / 手动存入 GitHub
 *
 * 用法（每个监测页）：
 *   AIArchive.init({
 *     commodity: 'gold',          // 存档文件 data/<commodity>/ai_history.json（pig 用 '' 即 data/ 根）
 *     baseDir: 'data/gold/',      // 该品种数据目录
 *     displayEl: 'ai-content',    // 分析正文元素 id
 *     dataDate: L.date            // 当前数据日期
 *   });
 * 重新生成成功后调用 AIArchive.setCurrent(text) 激活"存入档案"按钮。
 * GitHub token 只存浏览器 localStorage，不进入仓库。
 */
const AIArchive = (function () {
  const REPO = 'yixi2716/monitor';
  let archive = {};            // date -> {text, ts}
  let cfg = null;              // {commodity, baseDir, displayEl, dataDate}
  let toolbar = null;
  let currentText = '';        // 本次会话刚生成的分析（未保存）

  async function init(options) {
    cfg = options;
    currentText = '';
    try {
      const r = await fetch(cfg.baseDir + 'ai_history.json', { cache: 'no-store' });
      if (r.ok) archive = await r.json() || {};
    } catch (e) { archive = {}; }
    buildToolbar();
    refresh();
    return archive;
  }

  function dates() { return Object.keys(archive).sort().reverse(); }

  function display() { return document.getElementById(cfg.displayEl); }

  function buildToolbar() {
    const el = display();
    if (!el) return;
    toolbar = document.createElement('div');
    toolbar.id = 'ai-arch-toolbar';
    toolbar.style.cssText = 'margin:0 0 8px;font-size:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap';
    el.parentNode.insertBefore(toolbar, el);
  }

  function unsaved() {
    return !!currentText && archive[cfg.dataDate] && archive[cfg.dataDate].text === currentText ? false : !!currentText;
  }

  function refresh() {
    if (!toolbar) return;
    const ds = dates();
    const saveBtn = unsaved()
      ? '<button id="ai-arch-save" style="padding:2px 10px;background:#238636;color:#fff;border:none;border-radius:4px;cursor:pointer">存入档案（覆盖当天）</button>'
      : '';
    // 本地草稿：生成过但还没存进 GitHub 档案（如上次保存失败/断网），提供一键恢复
    const draft = (!unsaved() && loadDraft() && (!archive[cfg.dataDate] || archive[cfg.dataDate].text !== loadDraft().text))
      ? '<button id="ai-arch-restore" style="padding:2px 10px;background:#9e6a03;color:#fff;border:none;border-radius:4px;cursor:pointer">恢复本地草稿（' + loadDraft().date + ' 未保存）</button>'
      : '';
    if (!ds.length) {
      toolbar.innerHTML = '<span style="color:var(--muted)">暂无历史存档' + (unsaved() ? '' : '（点"重新生成"后可手动存入档案）') + '</span>' + saveBtn + draft + '<span id="ai-arch-msg" style="color:var(--muted)"></span>';
    } else {
      // 始终提供"今天"这个选项：没存档就标注未生成，选中后正文显示提示而不是塞旧的存档
      const todayOpt = (cfg.dataDate && !archive[cfg.dataDate])
        ? '<option value="' + cfg.dataDate + '">' + cfg.dataDate + '（未生成）</option>'
        : '';
      const opts = todayOpt + ds.map(d => '<option value="' + d + '">' + d + '</option>').join('');
      toolbar.innerHTML = '历史存档 <select id="ai-arch-date" style="background:#161d26;color:inherit;border:1px solid #30363d;border-radius:4px;padding:2px 6px">'
        + opts + '</select><span style="color:var(--muted)">共 ' + ds.length + ' 天</span>'
        + saveBtn + draft + '<span id="ai-arch-msg" style="color:var(--muted)"></span>';
      const sel = toolbar.querySelector('#ai-arch-date');
      sel.value = cfg.dataDate || ds[0];   // 默认选今天：有存档显示存档，没有则显示"未生成"提示
      sel.onchange = () => show(sel.value);
      show(sel.value, true);
    }
    const sv = toolbar.querySelector('#ai-arch-save');
    if (sv) sv.onclick = save;
    const rs = toolbar.querySelector('#ai-arch-restore');
    if (rs) rs.onclick = () => {
      const d = loadDraft();
      if (!d) return;
      currentText = d.text;
      cfg.dataDate = d.date;
      display().textContent = d.text;
      setMsg('已恢复 ' + d.date + ' 草稿，点"存入档案"即可保存');
      refresh();
    };
  }

  function show(date, silent) {
    const el = display();
    if (!el) return;
    if (archive[date]) {
      el.textContent = archive[date].text;
      el.style.color = '';
    } else if (date === cfg.dataDate) {
      // 今天的存档为空：明确提示未生成，不把旧存档伪装成今日分析
      el.textContent = '今日（' + date + '）的 AI 分析尚未生成。\n点上方"重新生成"按钮生成，生成后点"存入档案"保存当天；当天不生成则存档留空，随时可在下拉框翻阅历史存档。';
      el.style.color = 'var(--muted)';
    } else {
      return;
    }
    if (!silent) setMsg('');
  }

  function setMsg(t, isErr) {
    const m = toolbar && toolbar.querySelector('#ai-arch-msg');
    if (m) { m.textContent = t; m.style.color = isErr ? '#f85149' : 'var(--muted)'; }
  }

  /* 页面"重新生成"成功后调用：登记当前文本，允许存入档案 */
  function setCurrent(text) {
    currentText = (text || '').trim();
    // 本地草稿备份：即使保存到 GitHub 失败，刷新/重进页面也能找回
    try { localStorage.setItem(draftKey(), JSON.stringify({ date: cfg.dataDate, text: currentText })); } catch (e) {}
    refresh();
  }

  function draftKey() { return 'ai_draft_' + (cfg.commodity || 'pig'); }

  function loadDraft() {
    try {
      const d = JSON.parse(localStorage.getItem(draftKey()) || 'null');
      return d && d.text ? d : null;
    } catch (e) { return null; }
  }

  /* 带超时的 fetch：国内直连 api.github.com 可能挂起，绝不无限等 */
  async function fetchT(url, options, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || 20000);
    try {
      return await fetch(url, Object.assign({}, options, { signal: ctrl.signal }));
    } finally {
      clearTimeout(timer);
    }
  }

  async function getPat() {
    let pat = localStorage.getItem('gh_pat');
    if (!pat) {
      pat = prompt('首次保存需要 GitHub Personal Access Token\n'
        + '（github.com/settings/tokens 生成，只需勾选 repo 或 Contents 读写权限；\n'
        + 'Token 只保存在本浏览器 localStorage，不会进入仓库代码）');
      if (!pat) return null;
      localStorage.setItem('gh_pat', pat.trim());
    }
    return pat.trim();
  }

  async function getContentAndSha(pat, api) {
    const g = await fetchT(api, { headers: { 'Authorization': 'token ' + pat, 'Accept': 'application/vnd.github+json' } });
    if (g.ok) {
      const gj = await g.json();
      return { sha: gj.sha, content: JSON.parse(decodeURIComponent(escape(atob(gj.content.replace(/\n/g, ''))))) };
    }
    if (g.status === 404) return { sha: null, content: {} };
    throw new Error('读取档案失败 HTTP ' + g.status);
  }

  async function save() {
    if (!currentText) { setMsg('请先生成分析', true); return; }
    const pat = await getPat();
    if (!pat) return;
    const path = 'site/data/' + (cfg.commodity ? cfg.commodity + '/' : '') + 'ai_history.json';
    const api = 'https://api.github.com/repos/' + REPO + '/contents/' + path;
    setMsg('保存中...（最长等 20 秒）');
    try {
      let { sha, content } = await getContentAndSha(pat, api);
      content[cfg.dataDate] = { text: currentText, ts: new Date().toISOString() };
      const body = (s) => JSON.stringify({
        message: 'ai: ' + (cfg.commodity || 'pig') + ' ' + cfg.dataDate,
        content: btoa(unescape(encodeURIComponent(JSON.stringify(content, null, 2)))),
        sha: s
      });
      let p = await fetchT(api, {
        method: 'PUT',
        headers: { 'Authorization': 'token ' + pat, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github+json' },
        body: body(sha)
      });
      if (p.status === 422) {
        // sha 过期（Actions 或别的设备刚提交过）：重取最新 sha 再试一次，避免覆盖他人新增的存档
        const fresh = await getContentAndSha(pat, api);
        sha = fresh.sha; content = fresh.content;
        content[cfg.dataDate] = { text: currentText, ts: new Date().toISOString() };
        p = await fetchT(api, {
          method: 'PUT',
          headers: { 'Authorization': 'token ' + pat, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github+json' },
          body: body(sha)
        });
      }
      if (!p.ok) {
        const pj = await p.json().catch(() => ({}));
        throw new Error(pj.message || ('HTTP ' + p.status));
      }
      archive = content;
      try { localStorage.removeItem(draftKey()); } catch (e) {}
      setMsg('已保存（Pages 部署约 1 分钟后生效）');
      refresh();
    } catch (e) {
      if (e.name === 'AbortError' || /Failed to fetch|NetworkError/i.test(String(e.message))) {
        setMsg('连不上 api.github.com（网络问题，开代理后重试即可，分析已存本地草稿不会丢）', true);
      } else if (/401|403|Bad credentials/i.test(String(e.message))) {
        localStorage.removeItem('gh_pat');
        setMsg('Token 无效/权限不足，已清除请重试', true);
      } else {
        setMsg('保存失败：' + e.message + '（分析已存本地草稿，可重试）', true);
      }
    }
  }

  return { init, setCurrent, save, refresh };
})();
/* 显式挂到 window：顶层 const 不会成为 window 属性，页面里用 window.AIArchive 判断 */
window.AIArchive = AIArchive;
