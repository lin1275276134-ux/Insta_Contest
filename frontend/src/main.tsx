import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, prefix, acceptSnapshot, waitJob, withResync } from './api';
import type { Snapshot, Project, Shot, Job, Catalog, Evidence } from './api';
import './style.css';

const names: Record<string, string> = {
  pending: '待拍', covered: '已覆盖', reshoot: '需补拍', uncertain: '待确认',
  watching: '正在同步', awaiting_scope: '等待范围确认', paused: '已暂停', disconnected: '连接断开', closed: '已结束', error: '同步异常',
  awaiting_ready: '等待文件完整', queued: '排队中', downloading: '下载中', preparing: '处理视频', analyzing: '分析中',
  analyzed: '分析完成', failed: '失败', blocked_format: '格式待处理', excluded: '已排除', retry_wait: '等待重试',
};
const readiness: Record<string, string> = {not_ready: '还差一些镜头', checking: '正在核验新素材', unverified: '覆盖齐全 · 最新素材未核验', ready: '已拍够'};

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState(localStorage.getItem('bold.project') ?? '');
  const pidRef = useRef(pid); pidRef.current = pid;
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const latest = useRef<Snapshot | null>(null);
  const [mode, setMode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState('');
  const [conditions, setConditions] = useState('');
  const [seconds, setSeconds] = useState(45);
  const [creating, setCreating] = useState(!pid);
  const [draft, setDraft] = useState<Shot[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [playing, setPlaying] = useState<{rid: string; start: number; title: string} | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const confirmedVersion = useRef('');
  const [ordinary, setOrdinary] = useState(false);

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
    api<{camera_mode: string}>('/health').then(h => setMode(h.camera_mode)).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    localStorage.setItem('bold.project', pid);
    latest.current = null;
    setSnap(null); setCatalog(null); setSelected([]); setPlaying(null); confirmedVersion.current = '';
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
  async function scanCatalog() {
    const connect = await api<Job>('/devices:connect', 'POST', {profile_id: 'simulator'});
    await waitJob(connect.id);
    const job = await api<Job>('/devices/camera_demo/scans', 'POST', {});
    const result = await waitJob(job.id);
    const sid = (result.result as {id: string}).id;
    let next: string | null = null;
    let all: Catalog | null = null;
    do {
      const page: Catalog = await api(`/devices/camera_demo/catalog?snapshot_id=${sid}${next ? '&cursor=' + next : ''}`);
      all = all ? {...page, groups: [...all.groups, ...page.groups]} : page;
      next = page.next_cursor ?? null;
    } while (next);
    setCatalog(all); setSelected([]);
  }
  function toggle(id: string) { setSelected(items => items.includes(id) ? items.filter(x => x !== id) : [...items, id]); }
  const active = snap?.sync && snap.sync.state !== 'closed';
  const covered = snap?.shots.filter(s => s.required && s.state === 'covered').length ?? 0;
  const required = snap?.shots.filter(s => s.required).length ?? 0;

  return <div className="app">
    <header><a className="brand" href="/">拍够了吗<span>？</span></a><span className="tag">拍摄工作台</span>
      <div className="header-right"><span className="mode">{mode === 'simulator' ? '模拟相机 · 模拟模型' : '真实设备 / 模型尚未配置'}</span>
      <button className="quiet" onClick={() => setCreating(true)}>＋ 新建项目</button></div></header>
    <div className="statusbar"><span><i className={active && snap?.sync?.state === 'watching' ? 'dot green' : 'dot'}/>{snap?.sync ? names[snap.sync.state] : '尚未连接相机'}</span>
      <span>下载 / 分析：{snap ? `${snap.pipeline.running} 处理中 · ${snap.pipeline.waiting} 等待 · ${snap.pipeline.failed} 失败` : '—'}</span>
      <span>模型：{mode === 'simulator' ? '固定标注，仅验证程序流程' : '待配置'}</span></div>
    {error && <div className="error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}
    {creating ? <main className="creation"><div className="eyebrow">开始一次有准备的拍摄</div><h1>先说清楚，你想教会什么。</h1><p className="muted">把目标拆成可以看见、可以检查的镜头。拍摄过程中，我们帮你检查还缺什么。</p>
      <form onSubmit={e => {e.preventDefault(); const key = crypto.randomUUID(); act(async () => {
        // Reusing the key across a retry keeps it from creating a second project.
        const p = await api<Project>('/projects', 'POST', {goal, target_seconds: seconds, conditions}, key);
        pidRef.current = p.id; setPid(p.id); setCreating(false);
        const job = await api<Job>(`/projects/${p.id}/plan:generate`, 'POST', {expected_revision:p.revision});
        await waitJob(job.id);
      });}}>
        <label>教程主题<input required maxLength={2000} placeholder="例如：在自行车上安装手机支架" value={goal} onChange={e => setGoal(e.target.value)}/></label>
        <div className="formrow"><label>目标成片时长<select value={seconds} onChange={e => setSeconds(Number(e.target.value))}><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
        <label className="grow">拍摄条件<input maxLength={2000} placeholder="例如：一个人拍摄，室内桌面" value={conditions} onChange={e => setConditions(e.target.value)}/></label></div>
        <button className="primary" disabled={busy || !goal.trim()}>{busy ? '正在生成…' : '创建项目并生成分镜 →'}</button>
        {projects.length > 0 && <button type="button" className="quiet" onClick={() => {setCreating(false); if (!pid) setPid(projects[0].id);}}>返回已有项目</button>}
      </form><div className="note">{mode === 'simulator' ? '当前为模拟演示：生成通用分镜草稿，素材观察使用固定测试标注，不进行真实视觉识别。' : '请先配置真实模型，或按 README 显式启动模拟模式。'}</div>
    </main> : snap ? <>
      <section className="projectbar"><div><div className="eyebrow">拍摄项目 / {snap.project.target_seconds} 秒</div><h1>{snap.project.goal}</h1></div>
        <select aria-label="选择项目" value={pid} onChange={e => setPid(e.target.value)}>{projects.map(p => <option value={p.id} key={p.id}>{p.goal}</option>)}</select>
      </section>
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
        {!active && <section className="connect panel"><div><h2>选择这次拍摄的素材范围</h2><p className="muted">只导入选中的已有片段，此后自动接收新片段。</p></div>
          <button className="primary" disabled={busy} onClick={() => act(scanCatalog)}>连接并浏览素材</button></section>}
        {catalog && !active && <section className="catalog panel"><h2>已有素材 · {catalog.groups.length} 组</h2><p className="muted">未勾选的历史素材不会在后续同步中自动导入。</p>
          {catalog.groups.map(g => <label className="check" key={g.id}><input type="checkbox" checked={selected.includes(g.id)} onChange={() => toggle(g.id)}/><span>{g.name}</span><small>{(g.sizes.reduce((a,b) => a+b,0)/1024).toFixed(0)} KB · {g.complete ? '文件组完整' : '仍在写入'}</small></label>)}
          <button disabled={busy} className="primary" onClick={() => act(async () => {
            await api(`/projects/${pid}/sync-sessions`, 'POST', {device_id:catalog.device_id, snapshot_id:catalog.id, selected_group_ids:selected, expected_revision:rev()}); setCatalog(null);
          })}>{selected.length ? `导入 ${selected.length} 组并开始同步` : '只接收之后的新片段'}</button>
        </section>}
        {snap.sync?.state === 'awaiting_scope' && <section className="panel scope"><h2>重连后，先确认新增素材归属</h2><p>发现 {snap.pending_scope_count} 组待确认素材。它们尚未自动加入本项目。</p>
          {Object.entries(snap.sync.membership).filter(([,v]) => v === 'pending_confirmation').map(([key]) => <label className="check" key={key}><input type="checkbox" checked={selected.includes(key)} onChange={() => toggle(key)}/><span>{key}</span></label>)}
          <button disabled={busy} className="primary" onClick={() => act(async () => {
            const pending = Object.entries(snap.sync!.membership).filter(([,v]) => v === 'pending_confirmation').map(([k]) => k);
            await api(`/sync-sessions/${snap.sync!.id}/scope:confirm`, 'POST', {expected_revision:rev(), snapshot_id:latest.current!.sync!.snapshot_id, include_group_ids:pending.filter(k => selected.includes(k)), exclude_group_ids:pending.filter(k => !selected.includes(k))}); setSelected([]);
          })}>纳入勾选素材，排除其余并继续</button></section>}
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
            <div className="cliplist">{snap.clips.length === 0 ? <p className="muted emptylist">等待第一段素材。你可以先选择相机中的已有片段。</p> : snap.clips.map(c => <div className={`clip ${!c.active ? 'inactive' : ''}`} key={c.id}>
              <button className="clipmain" disabled={!c.rendition_id} onClick={() => setPlaying({rid:c.rendition_id!,start:0,title:c.name})}><span className="thumbnail">▷</span><span><strong>{c.name}</strong><small>{names[c.state]}{c.duration ? ` · ${c.duration.toFixed(1)} 秒` : ''}</small></span></button>
              <button className="quiet small" disabled={busy} onClick={() => act(async () => {await api(`/projects/${pid}/clips/${c.id}/membership`, 'PATCH', {expected_revision:rev(), membership:c.active ? 'excluded' : 'included', reason:'用户调整素材归属'});})}>{c.active ? '排除' : '重新纳入'}</button>
              {c.error && <div className="cliperror">{c.error.message}{c.job_id && <button disabled={busy} onClick={() => act(async () => {
                const j=await api<Job>(`/jobs/${c.job_id}`); await api(`/jobs/${j.id}/retry`, 'POST', {expected_attempt:j.attempt});
              })}>重试</button>}</div>}
            </div>)}</div>
            <details className="import"><summary>备用入口：本地视频导入</summary><p className="muted">此入口不替代 X5 自动同步验收。模拟模式不会识别上传视频的真实内容。</p>
              <label className="check"><input type="checkbox" checked={ordinary} onChange={e => setOrdinary(e.target.checked)}/>我已确认这是普通视角视频，不是全景或双鱼眼原片</label>
              <input type="file" accept="video/*,.insv" disabled={busy} aria-label="导入本地视频" onChange={e => {const file=e.target.files?.[0]; if(!file)return; act(async () => {
                const form = new FormData(); form.set('file',file); form.set('expected_revision', String(rev())); form.set('projection', ordinary ? 'rectilinear' : 'unknown');
                const r = await fetch(`${prefix}/projects/${pid}/imports`, {method:'POST', body:form, headers:{'Idempotency-Key':crypto.randomUUID()}}); const result=await r.json(); if(!r.ok)throw new Error(result.error?.message ?? '导入失败');
              }); e.target.value='';}}/>
            </details>
          </section>
          <aside><section className={`advice panel ${snap.readiness === 'ready' ? 'ready' : ''}`}><div className="eyebrow">当前建议</div><div className="readiness">{readiness[snap.readiness]}</div>
            {snap.next_action ? <><h2>{snap.next_action.what}</h2><p>{snap.next_action.how}</p><div className="why"><strong>为什么</strong><p>{snap.next_action.why}</p></div></> : <p>{snap.readiness === 'ready' ? '所有必要分镜已有合格证据，本次可见素材已核验。' : '已有分镜覆盖保留，待完成同步与素材处理后再核验。'}</p>}
            {snap.checked_at && <small>检查时间：{new Date(snap.checked_at * 1000).toLocaleTimeString()}<br/>仅针对截至本次扫描已可见的素材。</small>}
            {mode === 'simulator' && <p className="simulation-note">模拟结果，仅用于演示流程。</p>}
          </section>
          <section className="session panel"><h3>同步会话</h3><p className="muted">在相机上录制。软件负责发现素材、分析并更新清单。</p>
            {active && <div className="actions"><button disabled={busy} onClick={() => act(async () => {
              const action=snap.sync!.state === 'watching' ? 'pause' : 'resume';
              const result=await api<Job>(`/sync-sessions/${snap.sync!.id}/${action}`, 'POST', {expected_revision:rev()});
              if(action === 'resume')await waitJob(result.id);
            })}>{snap.sync?.state === 'watching' ? '暂停同步' : '重新扫描并恢复'}</button>
            <button className="quiet" disabled={busy} onClick={() => act(async () => {await api(`/sync-sessions/${snap.sync!.id}/close`, 'POST', {expected_revision:rev()});})}>结束会话</button></div>}
            <small>最近完整扫描：{snap.sync?.last_complete_scan_at ? new Date(snap.sync.last_complete_scan_at*1000).toLocaleTimeString() : '尚未扫描'}</small>
          </section></aside>
        </main>
      </>}
    </> : <main className="creation"><h2>正在打开项目…</h2><button onClick={() => setCreating(true)}>新建项目</button></main>}
    <footer>拍够了吗？ <span>本地项目 · 原片保留 · 证据可回看</span></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
