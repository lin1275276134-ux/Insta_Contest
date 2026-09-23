import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, prefix, acceptSnapshot, waitJob, withResync, requestKey, uploadLocalFiles } from './api';
import type { Snapshot, Project, Shot, Job, Evidence } from './api';
import './style.css';
import './home.css';

const names: Record<string, string> = {
  pending: '待拍', covered: '已覆盖', reshoot: '需补拍', uncertain: '待确认',
  awaiting_ready: '等待处理', queued: '排队中', downloading: '校验导入', preparing: '处理视频', analyzing: '分析中',
  analyzed: '分析完成', failed: '失败', blocked_format: '格式待处理', excluded: '已排除', retry_wait: '等待重试',
};
const readiness: Record<string, string> = {not_ready: '还缺一些镜头', checking: '正在分析', ready: '分镜覆盖完整'};

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState(localStorage.getItem('bold.project') ?? '');
  const pidRef = useRef(pid); pidRef.current = pid;
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const latest = useRef<Snapshot | null>(null);
  const [modelMode, setModelMode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState('');
  const [conditions, setConditions] = useState('');
  const [seconds, setSeconds] = useState(45);
  const [home, setHome] = useState(true);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [draft, setDraft] = useState<Shot[]>([]);
  const [playing, setPlaying] = useState<{rid: string; start: number; title: string} | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const confirmedVersion = useRef('');
  const [ordinary, setOrdinary] = useState(false);
  const [modelConsent, setModelConsent] = useState(false);

  // The server bumps revision whenever freshness changes, so the snapshot a user is
  // looking at can be stale before they click. Writes must send the latest revision.
  async function refresh(target = pidRef.current) {
    if (!target) return;
    const incoming = await api<Snapshot>(`/projects/${target}/snapshot`);
    if (pidRef.current !== target) return;
    const next = acceptSnapshot(latest.current, incoming);
    latest.current = next;
    setSnap(next);
  }
  async function listProjects() {
    const page = await api<{items: Project[]}>('/projects');
    setProjects(page.items);
  }
  const rev = () => latest.current?.revision ?? snap?.revision ?? 0;
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try {
      await withResync(fn, refresh);
      await refresh(); await listProjects();
    }
    catch (e) { setError((e as Error).message); await refresh().catch(() => {}); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    listProjects().catch(e => setError(e.message));
    api<{model_mode: string}>('/health').then(h => setModelMode(h.model_mode)).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (home) listProjects().catch(e => setError(e.message));
  }, [home]);
  useEffect(() => {
    localStorage.setItem('bold.project', pid);
    latest.current = null;
    setSnap(null); setPlaying(null); confirmedVersion.current = '';
    refresh(pid).catch(e => setError(e.message));
    const interval = setInterval(() => refresh(pid).catch(e => setError(e.message)), 1500);
    return () => clearInterval(interval);
  }, [pid]);
  useEffect(() => {
    if (!snap) return;
    const version = `${snap.project_id}:${snap.plan_version}`;
    if (version !== confirmedVersion.current) { setDraft(snap.project.shots); confirmedVersion.current = version; }
  }, [snap]);
  function play(e: Evidence) {
    setPlaying({rid: e.rendition_id, start: e.start, title: e.reason});
    if (video.current && playing?.rid === e.rendition_id) { video.current.currentTime = e.start; video.current.play().catch(() => {}); }
  }
  const covered = snap?.shots.filter(s => s.required && s.state === 'covered').length ?? 0;
  const required = snap?.shots.filter(s => s.required).length ?? 0;

  function openProject(id: string) {
    setError(''); setHome(false); setCreating(false); setPid(id);
  }
  async function deleteProject(project: Project) {
    setBusy(true); setError('');
    try {
      await api(`/projects/${project.id}`, 'DELETE', {expected_revision: project.revision});
      if (pidRef.current === project.id) {
        pidRef.current = ''; setPid(''); localStorage.removeItem('bold.project');
      }
      setDeleting(null);
      await listProjects();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="app">
    <header><a className="brand" href="/" onClick={e => {e.preventDefault(); setHome(true); setCreating(false);}}>拍够了吗<span>？</span></a><span className="tag">拍摄工作台</span>
      <div className="header-right"><span className="mode">{modelMode === 'simulator' ? '本地视频 · 模拟模型' : modelMode === 'qwen' ? '本地视频 · 千问视觉模型' : '本地视频 · 模型待配置'}</span>
      <button className="quiet" onClick={() => {setHome(false); setCreating(true);}}>＋ 新建项目</button></div></header>
    <div className="statusbar"><span><i className="dot green"/>本地视频工作区</span>
      <span>{home ? `项目：${projects.length} 个` : `处理 / 分析：${snap ? `${snap.pipeline.running} 处理中 · ${snap.pipeline.waiting} 等待 · ${snap.pipeline.failed} 失败` : '—'}`}</span>
      <span>模型：{modelMode === 'simulator' ? '固定标注，仅验证程序流程' : modelMode === 'qwen' ? '千问视觉模型' : '待配置'}</span></div>
    {error && <div className="error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}
    {home ? <main className="project-home">
      <section className="home-hero"><div><div className="eyebrow">你的拍摄空间</div><h1>今天想拍点什么？</h1><p className="muted">从一个清晰的目标开始，或者继续完善已有项目。</p></div>
        <button className="primary new-project" onClick={() => {setHome(false); setCreating(true);}}><span>＋</span><span><strong>新建项目</strong><small>生成一份新的拍摄清单</small></span></button>
      </section>
      <section className="project-section"><div className="project-section-title"><div><h2>已有项目</h2><p>{projects.length ? `共 ${projects.length} 个项目` : '还没有项目，从第一个拍摄目标开始吧'}</p></div></div>
        {projects.length ? <div className="project-grid">{projects.map(project => {
          const stage = project.confirmed ? '拍摄进行中' : project.shots.length ? '待确认分镜' : '正在准备';
          return <article className="project-card" key={project.id}>
            <button className="project-open" onClick={() => openProject(project.id)} aria-label={`进入项目：${project.goal}`}>
              <div className="project-card-top"><span className={`project-state ${project.confirmed ? 'active' : ''}`}>{stage}</span><span className="arrow">↗</span></div>
              <h3>{project.goal}</h3><p>{project.conditions || '暂无拍摄条件说明'}</p>
              <div className="project-meta"><span>{project.target_seconds} 秒成片</span><span>{project.shots.length} 个分镜</span><span>{new Date(project.created_at * 1000).toLocaleDateString('zh-CN')}</span></div>
            </button>
            <div className="project-card-actions"><button onClick={() => openProject(project.id)}>进入项目</button><button className="danger-quiet" onClick={() => setDeleting(project)} aria-label={`删除项目：${project.goal}`}>删除</button></div>
          </article>;
        })}</div> : <div className="projects-empty"><div className="empty-mark">◎</div><h3>还没有拍摄项目</h3><p>创建项目后，你可以在这里随时继续、管理或删除。</p><button className="primary" onClick={() => {setHome(false); setCreating(true);}}>创建第一个项目</button></div>}
      </section>
    </main> : creating ? <main className="creation"><button className="back-link" onClick={() => {setHome(true); setCreating(false);}}>← 返回项目首页</button><div className="eyebrow">开始一次有准备的拍摄</div><h1>你想拍出一条什么样的视频？</h1><p className="muted">说清成片目标，我们把它拆成可以看见、可以检查的必拍内容，帮你发现还缺什么。</p>
      <form onSubmit={e => {e.preventDefault(); const key = requestKey(); act(async () => {
        // Reusing the key across a retry keeps it from creating a second project.
        const p = await api<Project>('/projects', 'POST', {goal, target_seconds: seconds, conditions, model_upload_consent:modelConsent}, key);
        pidRef.current = p.id; setPid(p.id); setCreating(false); setHome(false);
        const job = await api<Job>(`/projects/${p.id}/plan:generate`, 'POST', {expected_revision:p.revision});
        await waitJob(job.id);
      });}}>
        <label>成片目标<input required maxLength={2000} placeholder="例如：展示一家咖啡馆的环境和招牌饮品" value={goal} onChange={e => setGoal(e.target.value)}/></label>
        <div className="formrow"><label>目标成片时长<select value={seconds} onChange={e => setSeconds(Number(e.target.value))}><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
        <label className="grow">拍摄条件<input maxLength={2000} placeholder="例如：一个人拍摄，室内桌面" value={conditions} onChange={e => setConditions(e.target.value)}/></label></div>
        {modelMode !== 'simulator' && <label className="check"><input type="checkbox" checked={modelConsent} onChange={e => setModelConsent(e.target.checked)}/>允许将本项目纳入的素材分析副本发送至千问模型服务，会消耗模型额度。原片保留在本机。</label>}
        <button className="primary" disabled={busy || !goal.trim()}>{busy ? '正在生成…' : '创建项目并生成分镜 →'}</button>
        <button type="button" className="quiet" onClick={() => {setCreating(false); setHome(true);}}>取消</button>
      </form><div className="note">{modelMode === 'simulator' ? '当前为模拟演示：生成通用分镜草稿，素材观察使用固定测试标注，不进行真实视觉识别。' : modelMode === 'qwen' ? '真实模型将分析上传的普通视角视频，生成结果需你确认。' : '请先配置真实模型，或按 README 显式启动模拟模式。'}</div>
    </main> : snap ? <>
      <section className="projectbar"><div><button className="back-link" onClick={() => setHome(true)}>← 全部项目</button><div className="eyebrow">拍摄项目 / {snap.project.target_seconds} 秒</div><h1>{snap.project.goal}</h1></div>
        <button className="danger-quiet" onClick={() => setDeleting(snap.project)}>删除项目</button>
      </section>
      {modelMode !== 'simulator' && !snap.project.model_upload_consent && <section className="panel"><p>视频已保留在本地。启用视觉分析后，本项目纳入的素材副本将发送至千问模型服务并消耗额度。</p><button disabled={busy} onClick={() => act(async () => {await api(`/projects/${pid}/analysis:authorize`, 'POST', {expected_revision:rev()});})}>允许本项目上传分析副本</button></section>}
      {!snap.project.confirmed ? <section className="plan panel"><div className="eyebrow">01 / 确认拍摄清单</div><h2>每个镜头，都有明确的通过标准。</h2><p className="muted">修改分镜与标准后确认。锁定后将按照这份清单检查素材。</p>
        {draft.map((s, i) => <div className="draftshot" key={s.id}><span className="number">0{i+1}</span><div className="grow"><label>分镜标题<input value={s.title} onChange={e => setDraft(d => d.map(x => x.id === s.id ? {...x, title:e.target.value} : x))}/></label>
          {s.criteria.map(c => <label key={c.id}>通过标准<input value={c.description} onChange={e => setDraft(d => d.map(x => x.id === s.id ? {...x, criteria:x.criteria.map(k => k.id === c.id ? {...k, description:e.target.value} : k)} : x))}/></label>)}
          <span className="muted">{s.criteria.some(c => c.continuous) ? '需要连续动作证据' : '需要清晰可见的画面'}</span></div></div>)}
        <div className="actions"><button disabled={busy || !draft.length} className="primary" onClick={() => act(async () => {
          const edited = await api<Project>(`/projects/${pid}/plan`, 'PATCH', {expected_revision:rev(), shots:draft});
          await api(`/projects/${pid}/plan:confirm`, 'POST', {expected_revision:edited.revision});
        })}>确认并锁定清单 →</button><button disabled={busy} onClick={() => act(async () => {
          const job = await api<Job>(`/projects/${pid}/plan:generate`, 'POST', {expected_revision:rev()}); await waitJob(job.id);
        })}>重新生成</button></div>
      </section> : <>
        <section className="connect panel"><div><h2>导入本地视频</h2><p className="muted">可一次选择多个普通视角视频；每段素材会独立校验、处理和分析。</p></div>
          <div><label className="check"><input type="checkbox" checked={ordinary} onChange={e => setOrdinary(e.target.checked)}/>我确认所选文件是普通视角视频</label>
          <input type="file" multiple accept="video/*" disabled={busy || !ordinary} aria-label="导入本地视频" onChange={e => {
            const input = e.currentTarget;
            const files = Array.from(input.files ?? []);
            if (!files.length) return;
            act(async () => { await uploadLocalFiles(pidRef.current, rev(), files); })
              .finally(() => { input.value = ''; });
          }}/></div></section>
        <main className="workspace">
          <section className="panel shots"><div className="sectiontitle"><h2>分镜进度</h2><span>{covered} / {required}</span></div><div className="progress"><div style={{width:`${required ? covered/required*100 : 0}%`}}/></div>
            {snap.shots.map((s,i) => <article className={`shot ${s.state}`} key={s.id}><div className="shothead"><span className="number">0{i+1}</span><span className="badge">{names[s.state]}</span></div><h3>{s.title}</h3>
              <p>{s.missing.length ? s.missing.join('；') : '必要标准已获得合格证据'}</p>
              {snap.evidence.filter(e => e.shot_id === s.id).map(e => <button className="evidence" key={e.id} onClick={() => play(e)}>▶ {e.start.toFixed(1)}–{e.end.toFixed(1)} 秒 · {e.verdict === 'supports' ? '支持证据' : e.verdict === 'defect' ? '缺陷证据' : '待确认'}</button>)}
            </article>)}
          </section>
          <section className="media panel"><div className="sectiontitle"><h2>素材与证据</h2><span>{snap.clips.length} 段</span></div>
            <div className="player">{playing ? <video ref={video} controls src={`${prefix}/renditions/${playing.rid}/content`} onLoadedMetadata={() => {if(video.current) video.current.currentTime=playing.start;}}/> : <div className="empty"><span className="playicon">▷</span><p>选择素材或点击证据播放</p><small>播放器使用分析时的同一份视频副本</small></div>}</div>
            {playing && <p className="caption">{playing.title}</p>}
            <div className="cliplist">{snap.clips.length === 0 ? <p className="muted emptylist">请选择一个或多个本地视频开始分析。</p> : snap.clips.map(c => <div className={`clip ${!c.active ? 'inactive' : ''}`} key={c.id}>
              <button className="clipmain" disabled={!c.rendition_id} onClick={() => setPlaying({rid:c.rendition_id!,start:0,title:c.name})}><span className="thumbnail">▷</span><span><strong>{c.name}</strong><small>{names[c.state]}{c.duration ? ` · ${c.duration.toFixed(1)} 秒` : ''}</small></span></button>
              <button className="quiet small" disabled={busy} onClick={() => act(async () => {await api(`/projects/${pid}/clips/${c.id}/membership`, 'PATCH', {expected_revision:rev(), membership:c.active ? 'excluded' : 'included', reason:'用户调整素材归属'});})}>{c.active ? '排除' : '重新纳入'}</button>
              {c.error && <div className="cliperror">{c.error.message}{c.job_id && <button disabled={busy} onClick={() => act(async () => {
                const j=await api<Job>(`/jobs/${c.job_id}`); await api(`/jobs/${j.id}/retry`, 'POST', {expected_attempt:j.attempt});
              })}>重试</button>}</div>}
            </div>)}</div>
          </section>
          <aside><section className={`advice panel ${snap.readiness === 'ready' ? 'ready' : ''}`}><div className="eyebrow">当前建议</div><div className="readiness">{readiness[snap.readiness]}</div>
            {snap.next_action ? <><h2>{snap.next_action.what}</h2><p>{snap.next_action.how}</p><div className="why"><strong>为什么</strong><p>{snap.next_action.why}</p></div></> : <p>{snap.readiness === 'ready' ? '所有必要分镜已有合格证据，本次可见素材已核验。' : '已有分镜覆盖保留，待完成同步与素材处理后再核验。'}</p>}
            {snap.checked_at && <small>完成时间：{new Date(snap.checked_at * 1000).toLocaleTimeString()}<br/>结论仅针对当前纳入的本地素材。</small>}
            {modelMode === 'simulator' && <p className="simulation-note">模拟结果，仅用于演示流程。</p>}
          </section>
          </aside>
        </main>
      </>}
    </> : <main className="creation"><h2>正在打开项目…</h2><button onClick={() => {setHome(true); setCreating(false);}}>返回项目首页</button></main>}
    {deleting && <div className="modal-backdrop" role="presentation" onMouseDown={e => {if (e.target === e.currentTarget) setDeleting(null);}}><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title"><div className="delete-icon">×</div><h2 id="delete-title">删除这个项目？</h2><p>“{deleting.goal}”及其本地导入素材和分析结果将被永久删除，此操作无法撤销。</p><div className="dialog-actions"><button onClick={() => setDeleting(null)} disabled={busy}>取消</button><button className="danger" onClick={() => deleteProject(deleting)} disabled={busy}>{busy ? '正在删除…' : '确认删除'}</button></div></div></div>}
    <footer>拍够了吗？ <span>本地项目 · 原片保留 · 证据可回看</span></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
