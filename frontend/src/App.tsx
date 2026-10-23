import { ChangeEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, Diagnostics, Job, MediaAsset, ModelPack, Segment, Voice } from './api'

const required = ['translation-zh-en', 'tts-kokoro-en', 'separation-htdemucs']
const stageNames: Record<string, string> = {
  inspect: 'Inspect media', extract: 'Extract audio', separate: 'Separate audio', transcribe: 'Recognize speech',
  translate: 'Translate dialogue', synthesize: 'Generate voices', subtitle_processing: 'Process subtitles', render: 'Export MP4',
}
const prettyBytes = (value: number) => value > 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${(value / 1024 ** 2).toFixed(0)} MB`
const prettyDuration = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
const prettyElapsed = (value?: number | null) => {
  if (value == null) return '—'
  const total = Math.floor(value)
  return total >= 3600 ? `${Math.floor(total / 3600)}h ${String(Math.floor(total % 3600 / 60)).padStart(2, '0')}m` : `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`
}
const prettyFreeSpace = (value: number) => value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB free` : `${(value / 1024 ** 2).toFixed(0)} MB free`
const active = (status: string) => ['queued', 'running', 'cancelling'].includes(status)

export default function App() {
  const [packs, setPacks] = useState<ModelPack[]>([])
  const [operations, setOperations] = useState<Record<string, { status: string; error?: string }>>({})
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Job | null>(null)
  const [inbox, setInbox] = useState<{ filename: string; bytes: number }[]>([])
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [profile, setProfile] = useState('balanced')
  const [subtitleMode, setSubtitleMode] = useState('fast')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [editSegments, setEditSegments] = useState<Segment[]>([])
  const [voiceChoices, setVoiceChoices] = useState<Voice[]>([])
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [serviceStatus, setServiceStatus] = useState('checking')
  const [subtitleFontSize, setSubtitleFontSize] = useState(44)
  const [subtitleMarginV, setSubtitleMarginV] = useState(44)
  const [dialogueGainDb, setDialogueGainDb] = useState(-1)
  const [backgroundGainDb, setBackgroundGainDb] = useState(-10)
  const [voiceEdits, setVoiceEdits] = useState<Record<string, string>>({})
  const [savingTranscript, setSavingTranscript] = useState(false)
  const [regions, setRegions] = useState<[number,number,number,number][]>([])
  const [selection, setSelection] = useState<[number,number,number,number] | null>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const dragStart = useRef<[number,number] | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [modelData, jobData, inboxData, voiceData] = await Promise.all([api.models(), api.jobs(), api.inbox(), api.voices()])
      setPacks(modelData.packs); setOperations(modelData.operations); setJobs(jobData.jobs); setInbox(inboxData.files); setVoiceChoices(voiceData.voices)
      const [healthResult, diagnosticResult] = await Promise.allSettled([api.health(), api.diagnostics()])
      setServiceStatus(healthResult.status === 'fulfilled' ? healthResult.value.status : 'unavailable')
      setDiagnostics(diagnosticResult.status === 'fulfilled' ? diagnosticResult.value : null)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not connect to the local service.') }
  }, [])
  useEffect(() => { void refresh(); const id = window.setInterval(() => void refresh(), 2500); return () => window.clearInterval(id) }, [refresh])
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    let alive = true
    const load = async () => { try { const job = await api.job(selectedId); if (alive) setDetail(job) } catch { /* list refresh reports connectivity */ } }
    void load(); const id = window.setInterval(() => void load(), 1800)
    return () => { alive = false; window.clearInterval(id) }
  }, [selectedId])
  const transcriptSignature = JSON.stringify(detail?.transcript ?? [])
  const regionSignature = JSON.stringify(detail?.subtitle_report?.regions ?? [])
  const speakerSignature = JSON.stringify(detail?.speakers ?? [])
  useEffect(() => { setEditSegments(detail?.transcript ?? []) }, [detail?.id, transcriptSignature])
  useEffect(() => {
    const next: Record<string, string> = {}
    for (const speaker of detail?.speakers ?? []) next[speaker.speaker_id] = speaker.voice_id
    setVoiceEdits(next)
  }, [detail?.id, speakerSignature])
  useEffect(() => { setRegions(detail?.subtitle_report?.regions ?? []); setSelection(null) }, [detail?.id, regionSignature])

  const allRequired = useMemo(() => {
    const asrId = profile === 'cpu-lite' ? 'asr-tiny' : 'asr-small'
    return [asrId, ...required].every(id => packs.find(p => p.id === id)?.ready)
  }, [packs, profile])
  const selectedJob = detail ?? jobs.find(j => j.id === selectedId) ?? null

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusy(label); setError('')
    try { await action(); await refresh() } catch (e) { setError(e instanceof Error ? e.message : 'Action failed.') }
    finally { setBusy('') }
  }
  async function onUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''
    if (!file) return
    setBusy('Uploading video'); setError(''); setAsset(null)
    try { const media = await api.upload(file); setAsset(media) }
    catch (e) { setError(e instanceof Error ? e.message : 'Upload failed.') }
    finally { setBusy('') }
  }
  async function importFromInbox(filename: string) {
    await runAction('Importing mounted video', async () => { setAsset(await api.importInbox(filename)) })
  }
  async function startJob() {
    if (!asset) return
    await runAction('Creating conversion', async () => {
      const result = await api.createJob(asset.id, {
        source_language: 'zh', target_language: 'en', profile,
        subtitle_mode: subtitleMode, manual_speaker_assignment: true,
        voice_assignments: { 'speaker_1': 'af_heart' },
        subtitle_font_size: subtitleFontSize, subtitle_margin_v: subtitleMarginV,
        dialogue_gain_db: dialogueGainDb, background_gain_db: backgroundGainDb,
      })
      setSelectedId(result.id); setAsset(null)
    })
  }
  async function initializePack(id: string) { await runAction('Starting model initialization', () => api.initializeModel(id)) }
  async function saveTranscript() {
    if (!selectedJob) return
    setSavingTranscript(true); setError('')
    try { const updated = await api.editTranscript(selectedJob.id, editSegments); setDetail(updated) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save transcript.') }
    finally { setSavingTranscript(false) }
  }
  async function saveVoices() {
    if (!selectedJob) return
    const assignments = Object.fromEntries(Object.entries(voiceEdits).map(([key, voice_id]) => [key, { voice_id }]))
    await runAction('Saving speaker voices', () => api.editSpeakers(selectedJob.id, assignments))
  }
  function regionPoint(event: ReactPointerEvent<HTMLDivElement>): [number,number] | null {
    const image = imageRef.current
    if (!image) return null
    const rect = image.getBoundingClientRect()
    return [Math.round((event.clientX-rect.left)/rect.width*image.naturalWidth),
      Math.round((event.clientY-rect.top)/rect.height*image.naturalHeight)]
  }
  function startRegion(event: ReactPointerEvent<HTMLDivElement>) {
    const point=regionPoint(event); if (!point) return
    dragStart.current=point; setSelection(null)
  }
  function finishRegion(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragStart.current) return
    const point=regionPoint(event); if (!point) return
    const [x0,y0]=dragStart.current; const [x1,y1]=point; dragStart.current=null
    const region:[number,number,number,number]=[Math.min(x0,x1),Math.min(y0,y1),Math.abs(x1-x0),Math.abs(y1-y0)]
    if (region[2]>2 && region[3]>2) setSelection(region)
  }
  async function applyRegions() {
    if (!selectedJob) return
    const next=selection ? [...regions,selection] : regions
    await runAction('Rebuilding subtitle preview', async () => { await api.updateRegions(selectedJob.id,next); setRegions(next); setSelection(null) })
  }

  return <main className="shell">
    <header className="topbar">
      <a className="brand" href="#home" onClick={() => setSelectedId(null)} aria-label="Offline Dub Studio home">
        <span className="brand-mark">OD</span><span><strong>Offline Dub Studio</strong><small>LOCAL VIDEO WORKFLOW</small></span>
      </a>
      <div className="top-status"><i className={`dot ${serviceStatus === 'ok' ? '' : 'status-offline'}`} /> {serviceStatus === 'ok' ? 'Local service ready' : serviceStatus === 'checking' ? 'Checking local service' : 'Local service unavailable'} <span className="divider" /> {diagnostics ? `${diagnostics.cpu_count} CPU threads · ${prettyFreeSpace(diagnostics.data_free_bytes)}` : 'CPU status unavailable'}</div>
    </header>

    <section className="hero-row">
      <div><p className="eyebrow">YOUR MEDIA STAYS HERE</p><h1>Give every story<br /><em>a new voice.</em></h1>
        <p className="hero-copy">Translate Mandarin dialogue, build speaker voices, and export a subtitled MP4 on your own machine.</p></div>
      <div className="hero-note"><span className="note-icon">◉</span><div><b>Private by design</b><p>Once the local model packs are ready, inference runs inside this container. No cloud API fallback.</p></div></div>
    </section>

    {error && <div className="alert" role="alert"><span>!</span><div>{error}</div><button onClick={() => setError('')} aria-label="Dismiss">×</button></div>}

    <div className="dashboard-grid">
      <section className="card conversion-card">
        <div className="section-heading"><div><p className="eyebrow">NEW CONVERSION</p><h2>Start with a video</h2></div><span className="step-badge">01</span></div>
        <div className="upload-zone">
          <div className="upload-symbol">↑</div><b>Drop in an MP4 to begin</b><p>MP4, MOV, MKV or WebM · file is stored in local app data</p>
          <label className="button primary upload-button">Choose a video<input type="file" accept="video/mp4,video/*,.mkv,.m4v" onChange={onUpload} /></label>
        </div>
        {inbox.length > 0 && <div className="inbox-list"><div className="list-label">OR SELECT FROM YOUR MOUNTED INBOX</div>
          {inbox.slice(0, 5).map(item => <button className="inbox-item" key={item.filename} onClick={() => void importFromInbox(item.filename)}>
            <span className="file-icon">▶</span><span className="file-name">{item.filename}<small>{prettyBytes(item.bytes)}</small></span><span>Import ↗</span></button>)}
        </div>}
        {asset && <div className="asset-preview"><div><b>{asset.display_name}</b><span>{prettyDuration(asset.duration)} · {asset.width} × {asset.height} · {asset.has_audio ? 'audio found' : 'no audio'}</span></div><button className="text-button" onClick={() => setAsset(null)}>Remove</button></div>}
        <div className="settings-row">
          <label>Processing profile<select value={profile} onChange={e => setProfile(e.target.value)}><option value="cpu-lite">CPU Lite · smallest ASR pack</option><option value="balanced">Balanced · small ASR pack</option></select></label>
          <label>Chinese subtitle handling<select value={subtitleMode} onChange={e => setSubtitleMode(e.target.value)}><option value="fast">Fast · OpenCV inpainting</option><option value="balanced">Balanced · OpenCV inpainting</option><option value="none">Leave hard subtitles</option></select></label>
        </div>
        <details className="output-settings"><summary>Subtitle and audio settings</summary><div className="settings-row">
          <label>Subtitle size · {subtitleFontSize}px<input type="range" min="18" max="96" step="2" value={subtitleFontSize} onChange={e => setSubtitleFontSize(Number(e.target.value))} /></label>
          <label>Subtitle height · {subtitleMarginV}px from bottom<input type="range" min="0" max="300" step="4" value={subtitleMarginV} onChange={e => setSubtitleMarginV(Number(e.target.value))} /></label>
          <label>English dialogue gain · {dialogueGainDb} dB<input type="range" min="-18" max="6" step="1" value={dialogueGainDb} onChange={e => setDialogueGainDb(Number(e.target.value))} /></label>
          <label>Original background gain · {backgroundGainDb} dB<input type="range" min="-30" max="6" step="1" value={backgroundGainDb} onChange={e => setBackgroundGainDb(Number(e.target.value))} /></label>
        </div></details>
        <div className="language-route"><span>中文</span><i>→</i><span>English</span><small>Chinese → English</small></div>
        {!allRequired && <div className="inline-hint">Initialize the required local model packs below to enable conversion.</div>}
        <button className="button dark start-button" disabled={!asset || !allRequired || Boolean(busy)} onClick={() => void startJob()}>{busy || (allRequired ? 'Start conversion' : 'Models required')} <span>→</span></button>
        <small className="fineprint">The first run requires model downloads. Later inference can run offline.</small>
      </section>

      <div className="right-stack">
        <section className="card readiness-card">
          <div className="section-heading compact"><div><p className="eyebrow">LOCAL RUNTIME</p><h2>Model readiness</h2></div><span className="ready-count">{packs.filter(p => p.ready).length}/{packs.length}</span></div>
          <p className="muted small">Each pack is downloaded to persistent model storage.</p>
          <div className="model-list">{packs.map(pack => {
            const operation = operations[pack.id]
            return <div className="model-row" key={pack.id}>
              <span className={`model-state ${pack.ready ? 'is-ready' : operation?.status === 'running' ? 'is-loading' : ''}`}>{pack.ready ? '✓' : operation?.status === 'running' ? '…' : '○'}</span>
              <div className="model-info"><b>{pack.name}</b><span>{pack.approx_size} · {pack.license}</span>{pack.note && <small>{pack.note}</small>}{operation?.error && <small className="model-error">{operation.error}</small>}</div>
              {!pack.ready && <button className="text-button" disabled={operation?.status === 'running' || Boolean(busy)} onClick={() => void initializePack(pack.id)}>{operation?.status === 'running' ? 'Working…' : 'Initialize'}</button>}
            </div>
          })}</div>
          <div className="separator-note"><span>i</span> CPU-only processing. Demucs separates music vocals, not film dialogue; review the audio mix.</div>
        </section>
        <section className="card storage-card">
          <div className="section-heading compact"><div><p className="eyebrow">PERSISTENT STORAGE</p><h2>Bring a full movie</h2></div><span className="folder-icon">▱</span></div>
          <p>Place large files in the mounted <code>/data/inbox</code> folder to avoid uploading through the browser.</p>
          <div className="storage-foot"><span>{inbox.length} video{inbox.length === 1 ? '' : 's'} available</span><button onClick={() => void refresh()}>Refresh list ↻</button></div>
        </section>
      </div>
    </div>

    {selectedJob && <section className="card job-detail" id="job-detail">
      <div className="section-heading"><div><p className="eyebrow">CONVERSION WORKSPACE</p><h2>{selectedJob.display_name}</h2></div><div className="job-actions">
        {active(selectedJob.status) && <button className="button outline" onClick={() => void runAction('Requesting cancellation', () => api.cancel(selectedJob.id))}>Cancel</button>}
        {['interrupted','failed','cancelled'].includes(selectedJob.status) && <button className="button outline" onClick={() => void runAction('Resuming conversion', () => api.resume(selectedJob.id))}>Resume</button>}
        <button className="text-button" onClick={() => setSelectedId(null)}>Close ×</button></div></div>
      <div className="job-overview"><StatusPill status={selectedJob.status} /><span>{stageNames[selectedJob.stage] ?? selectedJob.stage}</span><span className="elapsed-display">Elapsed {prettyElapsed(selectedJob.elapsed_seconds)}</span><span className="elapsed-display">This stage {prettyElapsed(selectedJob.current_stage_elapsed_seconds)}</span><b>{Math.round(selectedJob.progress)}%</b></div>
      <div className="progress-track"><div style={{ width: `${Math.max(0,Math.min(100,selectedJob.progress))}%` }} /></div>
      <div className="stage-grid">{selectedJob.stages.map(stage => <div className={`stage-chip ${stage.status}`} key={stage.name}><i />{stageNames[stage.name] ?? stage.name}</div>)}</div>
      {selectedJob.error && <div className="alert compact-alert"><span>!</span>{selectedJob.error}</div>}
      {selectedJob.stages.some(stage => stage.name==='subtitle_processing' && stage.status==='completed') && selectedJob.options.subtitle_mode!=='none' && <section className="subtitle-review">
        <div className="review-heading"><div><p className="eyebrow">REVIEW BEFORE EXPORT</p><h3>Check subtitle removal</h3><p>Drag over any missed hardcoded subtitle on the source frame. Adjusted regions are reprocessed before you approve the final MP4.</p></div>
          {selectedJob.status==='awaiting_review' && <button className="button dark" disabled={Boolean(busy)} onClick={() => void runAction('Approving export',() => api.approveSubtitles(selectedJob.id))}>Looks good · export MP4 <span>→</span></button>}
        </div>
        <div className="review-grid"><figure><div className="image-select" onPointerDown={startRegion} onPointerUp={finishRegion}>
          <img ref={imageRef} src={`/api/v1/jobs/${selectedJob.id}/preview/subtitle-original.png`} alt="Source video frame. Drag to select another subtitle region." />
          {regions.map(([x,y,w,h],i)=><span key={i} className="region-box" style={{left:`${(x/(imageRef.current?.naturalWidth||1))*100}%`,top:`${(y/(imageRef.current?.naturalHeight||1))*100}%`,width:`${(w/(imageRef.current?.naturalWidth||1))*100}%`,height:`${(h/(imageRef.current?.naturalHeight||1))*100}%`}} />)}
          {selection && <span className="region-box selected-region" style={{left:`${(selection[0]/(imageRef.current?.naturalWidth||1))*100}%`,top:`${(selection[1]/(imageRef.current?.naturalHeight||1))*100}%`,width:`${(selection[2]/(imageRef.current?.naturalWidth||1))*100}%`,height:`${(selection[3]/(imageRef.current?.naturalHeight||1))*100}%`}} />}
        </div><figcaption>Source frame · drag to add a removal region</figcaption></figure>
          {['subtitle-mask.png','subtitle-repaired.png','english-subtitle.png'].map((name,i)=><figure key={name}><img className="review-image" src={`/api/v1/jobs/${selectedJob.id}/preview/${name}`} onError={e=>{e.currentTarget.style.display='none'}} alt={name} /><figcaption>{['Detected mask','Inpainted background','English subtitle preview'][i]}</figcaption></figure>)}
        </div>
        <div className="region-controls"><span>{regions.length} removal region{regions.length===1?'':'s'} · {selectedJob.media_info?.width} × {selectedJob.media_info?.height}px</span>
          {selection && <button className="text-button" onClick={()=>setSelection(null)}>Discard selection</button>}
          <button className="button outline" disabled={active(selectedJob.status) || Boolean(busy) || (!selection && selectedJob.status!=='awaiting_review')} onClick={()=>void applyRegions()}>{selection?'Add region and rebuild preview':'Rebuild preview'}</button>
        </div>
        {selectedJob.subtitle_report?.warnings?.map(w=><div className="warning" key={w}>Review: {w}</div>)}
      </section>}
      {selectedJob.stages.some(stage => stage.name==='subtitle_processing' && stage.status==='completed') && selectedJob.options.subtitle_mode==='none' && <section className="subtitle-review">
        <div className="review-heading"><div><p className="eyebrow">REVIEW BEFORE EXPORT</p><h3>English subtitle preview</h3><p>Original hardcoded subtitles are left in the picture. Embedded soft subtitle streams are excluded.</p></div>
          {selectedJob.status==='awaiting_review' && <button className="button dark" disabled={Boolean(busy)} onClick={() => void runAction('Approving export',() => api.approveSubtitles(selectedJob.id))}>Looks good · export MP4 <span>→</span></button>}
        </div>
        <div className="preview-pair"><figure><img className="review-image" src={`/api/v1/jobs/${selectedJob.id}/preview/subtitle-original.png`} alt="Source video frame" /><figcaption>Source frame</figcaption></figure><figure><img className="review-image" src={`/api/v1/jobs/${selectedJob.id}/preview/english-subtitle.png`} alt="English subtitles over video" /><figcaption>English subtitle preview</figcaption></figure></div>
      </section>}
      {selectedJob.status.startsWith('completed') && selectedJob.download_url && <div className="output-grid">
        <div className="video-comparison"><figure><video controls preload="metadata" src={`/api/v1/jobs/${selectedJob.id}/artifacts/original`} /><figcaption>Original source</figcaption></figure><figure><video controls preload="metadata" src={selectedJob.download_url} /><figcaption>English dub · burned-in subtitles</figcaption></figure></div>
        <div className="output-side"><h3>Export ready</h3><p>Review the dub and burned-in English subtitles. Listen for separation artifacts and timing issues.</p>
          <a className="button primary" href={selectedJob.download_url}>Download MP4 ↓</a><audio controls src={`/api/v1/jobs/${selectedJob.id}/artifacts/audio`} />
          {selectedJob.subtitle_report?.warnings?.map(w => <div className="warning" key={w}>Review: {w}</div>)}
          <div className="preview-pair">{['subtitle-mask.png','subtitle-repaired.png'].map(name => <figure key={name}><img src={`/api/v1/jobs/${selectedJob.id}/preview/${name}`} onError={e => { e.currentTarget.style.display='none' }} /><figcaption>{name === 'subtitle-mask.png' ? 'Detected mask preview' : 'Inpainting preview'}</figcaption></figure>)}</div>
        </div>
      </div>}
      {selectedJob.transcript.length > 0 && <div className="editor-layout">
        <section><div className="editor-head"><div><h3>Dialogue and subtitle editor</h3><p>Correct translations and speaker IDs. Saving re-runs only TTS and later stages.</p></div><button className="button primary" disabled={savingTranscript || active(selectedJob.status)} onClick={() => void saveTranscript()}>{savingTranscript ? 'Saving…' : 'Save dialogue'}</button></div>
          <div className="segment-list">{editSegments.map((segment,index) => <div className="segment-row" key={segment.id}>
            <div className="segment-index"><span>{String(index+1).padStart(2,'0')}</span><div className="segment-times"><label>In<input aria-label={`Segment ${index+1} start time`} type="number" min="0" step="0.1" value={segment.start} onChange={e => setEditSegments(rows => rows.map(s => s.id===segment.id ? {...s,start:Number(e.target.value)}:s))} /></label><label>Out<input aria-label={`Segment ${index+1} end time`} type="number" min="0" step="0.1" value={segment.end} onChange={e => setEditSegments(rows => rows.map(s => s.id===segment.id ? {...s,end:Number(e.target.value)}:s))} /></label></div></div>
            <div className="segment-fields"><label>Mandarin source<textarea value={segment.source_text} onChange={e => setEditSegments(rows => rows.map(s => s.id===segment.id ? {...s,source_text:e.target.value}:s))} /></label><label>English dub and subtitle<textarea value={segment.translated_text} onChange={e => setEditSegments(rows => rows.map(s => s.id===segment.id ? {...s,translated_text:e.target.value}:s))} /></label></div>
            <label className="speaker-field">Speaker<input value={segment.speaker_id} onChange={e => setEditSegments(rows => rows.map(s => s.id===segment.id ? {...s,speaker_id:e.target.value}:s))} /></label>
          </div>)}</div>
        </section>
        <aside className="voice-panel"><h3>Speaker voice mapping</h3><p>Manual assignment is active. Assign different stable voices, then save.</p>
          {selectedJob.speakers.map(speaker => <label key={speaker.speaker_id}>{speaker.speaker_id}<select value={voiceEdits[speaker.speaker_id] ?? speaker.voice_id} onChange={e => setVoiceEdits(v => ({...v,[speaker.speaker_id]:e.target.value}))}>{voiceChoices.map(v => <option key={v.id} value={v.id}>{v.label}</option>)}</select></label>)}
          <button className="button outline full" disabled={active(selectedJob.status)} onClick={() => void saveVoices()}>Save voice mapping</button><div className="manual-note">Speaker separation and automatic diarization are not enabled. Correct speaker IDs in the dialogue list.</div>
        </aside>
      </div>}
      <details className="logs"><summary>Processing log · {selectedJob.logs.length} entries</summary><div>{selectedJob.logs.map((line,i) => <p key={`${line.timestamp}-${i}`}><time>{new Date(line.timestamp).toLocaleTimeString()}</time><b className={`log-${line.level}`}>{line.level}</b>{line.message}</p>)}</div></details>
    </section>}

    <section className="recent-section"><div className="section-heading"><div><p className="eyebrow">YOUR WORKSPACE</p><h2>Recent conversions</h2></div><span className="recent-count">{jobs.length} saved</span></div>
      {jobs.length ? <div className="recent-list">{jobs.map(job => <button className={`recent-row ${selectedId===job.id?'selected':''}`} key={job.id} onClick={() => setSelectedId(job.id)}><span className="video-icon">▶</span><span className="recent-name"><b>{job.display_name}</b><small>{new Date(job.created_at).toLocaleString()}</small></span><span className="recent-stage">{stageNames[job.stage] ?? job.stage}</span><StatusPill status={job.status} /><span className="recent-progress">{Math.round(job.progress)}%</span></button>)}</div> : <div className="empty-state"><span>▣</span><b>Your conversions will appear here</b><p>Jobs and stage checkpoints persist across container restarts.</p></div>}
    </section>

    <footer><span>Offline Dub Studio <b>·</b> local-first</span><span>First-time setup needs internet. Model inference has no cloud fallback.</span></footer>
  </main>
}

function StatusPill({ status }: { status: string }) {
  const title = status.replaceAll('_',' ')
  return <span className={`status-pill ${status}`}><i />{title}</span>
}
