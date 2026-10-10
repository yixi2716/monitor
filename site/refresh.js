/* 刷新数据按钮：网页上直接触发 GitHub Actions 重新抓数，不用打开 GitHub。
 *
 * 原理：workflow 已支持 workflow_dispatch；这里用浏览器里的 PAT
 * （与 AI 存档共用 localStorage 的 gh_pat）调 GitHub API 派发并轮询状态。
 *
 * PAT 权限要求（fine-grained，仅本仓库 yixi2716/monitor）：
 *   Contents: Read and write（存 AI 档案用）+ Actions: Read and write（触发刷新用）
 * Token 只保存在本浏览器 localStorage，不进仓库。
 *
 * 用法：页面加 <script src="refresh.js?v=1"></script>
 */
(function () {
  "use strict";
  var REPO = 'yixi2716/monitor';
  var WORKFLOW = 'update.yml';
  var POLL_INTERVAL = 8000, POLL_MAX = 40; // 8s × 40 = 约5分半

  function getPat() {
    var pat = localStorage.getItem('gh_pat');
    if (!pat) {
      pat = prompt('首次刷新需要 GitHub Personal Access Token\n'
        + '（github.com/settings/pat 生成 fine-grained token，本仓库勾选：\n'
        + ' Contents: Read/write + Actions: Read/write；\n'
        + ' 与"存入档案"共用同一个 token，只存在本浏览器）');
      if (!pat) return null;
      localStorage.setItem('gh_pat', pat.trim());
    }
    return pat.trim();
  }

  function api(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({
      'Authorization': 'token ' + getPat(),
      'Accept': 'application/vnd.github+json'
    }, opts.headers || {});
    return fetch(url, opts).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        localStorage.removeItem('gh_pat');
        throw new Error('Token 无效或权限不足（需 Actions: Read/write），已清除，请重试');
      }
      if (!r.ok) throw new Error('GitHub API HTTP ' + r.status);
      return r.status === 204 ? {} : r.json();
    });
  }

  function toast() {
    var el = document.getElementById('refresh-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'refresh-toast';
      el.style.cssText = 'position:fixed;right:76px;bottom:20px;z-index:9999;max-width:300px;'
        + 'background:#161d26;border:1px solid #30363d;border-radius:8px;padding:10px 14px;'
        + 'font-size:12px;color:#c9d1d9;box-shadow:0 4px 16px rgba(0,0,0,.5);display:none;line-height:1.6';
      document.body.appendChild(el);
    }
    return el;
  }

  function setStatus(t, isErr) {
    var el = toast();
    el.style.display = 'block';
    el.innerHTML = t;
    el.style.borderColor = isErr ? '#f85149' : '#30363d';
    if (isErr) el.style.color = '#f85149';
  }

  function dispatch() {
    return api('https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main' })
    });
  }

  function pollRun(done) {
    var n = 0;
    var timer = setInterval(function () {
      n++;
      api('https://api.github.com/repos/' + REPO + '/actions/runs?per_page=1')
        .then(function (d) {
          var run = d.workflow_runs && d.workflow_runs[0];
          if (!run) return;
          var st = run.status === 'completed'
            ? (run.conclusion === 'success' ? '✅ 完成' : '⚠️ 结束(' + run.conclusion + ')')
            : '⏳ ' + (run.status === 'in_progress' ? '运行中' : run.status) + '…';
          setStatus('正在刷新数据（ Actions 全量重跑约 2-4 分钟）<br>' + st
            + '<br><span style="color:#6e7681">' + (run.created_at || '').replace('T', ' ').slice(0, 16) + ' UTC</span>');
          if (run.status === 'completed') {
            clearInterval(timer);
            setStatus(st + '，正在重新加载页面…');
            setTimeout(function () { location.reload(); }, 1500);
          }
        })
        .catch(function (e) {
          clearInterval(timer);
          setStatus('状态查询失败：' + e.message, true);
        });
      if (n >= POLL_MAX) {
        clearInterval(timer);
        setStatus('等待超时，去 GitHub Actions 页面看结果吧。<br>数据提交后 Pages 部署约 1 分钟生效。', true);
      }
    }, POLL_INTERVAL);
  }

  function refresh() {
    try {
      setStatus('正在触发 GitHub Actions…');
      dispatch().then(function () {
        setStatus('已触发，等待排队…');
        setTimeout(function () { pollRun(); }, 5000);
      }).catch(function (e) {
        setStatus('触发失败：' + e.message, true);
      });
    } catch (e) {
      setStatus('失败：' + e.message, true);
    }
  }

  function build() {
    if (document.getElementById('refresh-btn')) return;
    var b = document.createElement('button');
    b.id = 'refresh-btn';
    b.textContent = '⟳ 刷新数据';
    b.title = '触发 GitHub Actions 重新抓取全部板块数据（约2-4分钟）';
    b.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;'
      + 'padding:8px 14px;background:#238636;color:#fff;border:none;border-radius:20px;'
      + 'cursor:pointer;font-size:13px;box-shadow:0 2px 10px rgba(0,0,0,.5)';
    b.onclick = refresh;
    document.body.appendChild(b);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
