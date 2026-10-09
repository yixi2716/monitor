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
    if (!ds.length) {
      toolbar.innerHTML = '<span style="color:var(--muted)">暂无历史存档' + (unsaved() ? '' : '（每晚 0 点自动生成，或点"重新生成"后手动存入）') + '</span>' + saveBtn + '<span id="ai-arch-msg" style="color:var(--muted)"></span>';
    } else {
      const opts = ds.map(d => '<option value="' + d + '">' + d + '</option>').join('');
      const def = (cfg.dataDate && archive[cfg.dataDate]) ? cfg.dataDate : ds[0];
      toolbar.innerHTML = '历史存档 <select id="ai-arch-date" style="background:#161d26;color:inherit;border:1px solid #30363d;border-radius:4px;padding:2px 6px">'
        + opts + '</select><span style="color:var(--muted)">共 ' + ds.length + ' 天</span>'
        + saveBtn + '<span id="ai-arch-msg" style="color:var(--muted)"></span>';
      const sel = toolbar.querySelector('#ai-arch-date');
      sel.value = def;
      sel.onchange = () => show(sel.value);
      show(def, true);
    }
    const sv = toolbar.querySelector('#ai-arch-save');
    if (sv) sv.onclick = save;
  }

  function show(date, silent) {
    const el = display();
    if (!el || !archive[date]) return;
    el.textContent = archive[date].text;
    if (!silent) setMsg('');
  }

  function setMsg(t, isErr) {
    const m = toolbar && toolbar.querySelector('#ai-arch-msg');
    if (m) { m.textContent = t; m.style.color = isErr ? '#f85149' : 'var(--muted)'; }
  }

  /* 页面"重新生成"成功后调用：登记当前文本，允许存入档案 */
  function setCurrent(text) {
    currentText = (text || '').trim();
    refresh();
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

  async function save() {
    if (!currentText) { setMsg('请先生成分析', true); return; }
    const pat = await getPat();
    if (!pat) return;
    const path = 'site/data/' + (cfg.commodity ? cfg.commodity + '/' : '') + 'ai_history.json';
    const api = 'https://api.github.com/repos/' + REPO + '/contents/' + path;
    setMsg('保存中...');
    try {
      let sha = null;
      let content = {};
      const g = await fetch(api, { headers: { 'Authorization': 'token ' + pat, 'Accept': 'application/vnd.github+json' } });
      if (g.ok) {
        const gj = await g.json();
        sha = gj.sha;
        content = JSON.parse(decodeURIComponent(escape(atob(gj.content.replace(/\n/g, '')))));
      } else if (g.status !== 404) {
        throw new Error('读取档案失败 HTTP ' + g.status);
      }
      content[cfg.dataDate] = { text: currentText, ts: new Date().toISOString() };
      const payload = {
        message: 'ai: ' + (cfg.commodity || 'pig') + ' ' + cfg.dataDate,
        content: btoa(unescape(encodeURIComponent(JSON.stringify(content, null, 2)))),
        sha: sha
      };
      const p = await fetch(api, {
        method: 'PUT',
        headers: { 'Authorization': 'token ' + pat, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github+json' },
        body: JSON.stringify(payload)
      });
      if (!p.ok) {
        const pj = await p.json().catch(() => ({}));
        throw new Error(pj.message || ('HTTP ' + p.status));
      }
      archive = content;
      setMsg('已保存（Pages 部署约 1 分钟后生效）');
      refresh();
    } catch (e) {
      if (/401|403|Bad credentials/i.test(String(e.message))) {
        localStorage.removeItem('gh_pat');
        setMsg('Token 无效/权限不足，已清除请重试', true);
      } else {
        setMsg('保存失败：' + e.message, true);
      }
    }
  }

  return { init, setCurrent, save, refresh };
})();
