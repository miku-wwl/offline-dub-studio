export type Stage = { name: string; status: string; progress: number; started_at?: string | null; finished_at?: string | null; error?: string | null }
export type Segment = {
  id: string; start: number; end: number; source_text: string; translated_text: string;
  speaker_id: string; asr_quality?: number | null
  short_translation?: string | null; translation_provenance?: Record<string,unknown>
}
export type Speaker = { speaker_id: string; voice_id: string; label?: string }
export type Job = {
  id: string; display_name: string; status: string; stage: string; progress: number;
  created_at: string; updated_at: string; error?: string | null; options: Record<string, unknown>;
  stages: Stage[]; transcript: Segment[]; speakers: Speaker[];
  logs: { timestamp: string; level: string; message: string }[]; download_url?: string | null;
  elapsed_seconds?: number | null; current_stage_elapsed_seconds?: number | null
  subtitle_report?: { warnings?: string[]; hard_subtitles_processed?: boolean; mask_applied?: boolean; caption_placement_note?: string; manual_search_regions?: [number,number,number,number][]; regions?: { start: number; end: number; boxes: [number,number,number,number][] }[] } | null
  media_info?: { width: number; height: number; duration: number } | null
}
export type ModelPack = {
  id: string; name: string; kind: string; ready: boolean; approx_size: string; license: string;
  access: string; note?: string | null
}
export type JobSummary = Pick<Job,'id'|'display_name'|'status'|'stage'|'progress'|'created_at'|'updated_at'|'error'|'download_url'>
export type MediaAsset = {
  id: string; display_name: string; bytes: number; duration: number;
  width: number; height: number; has_audio: boolean; subtitle_streams: number
}
export type Voice = { id: string; label: string }
export type TemporalMask = { start_time:number; end_time:number; x:number; y:number; width:number; height:number }
export type Diagnostics = { cpu_count: number; data_free_bytes: number; offline_inference: boolean }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try { message = (await response.json()).detail ?? message } catch { /* retain HTTP message */ }
    throw new Error(message)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}
const json = (method: string, body?: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const api = {
  health: () => request<{ status: string }>('/api/v1/health'),
  diagnostics: () => request<Diagnostics>('/api/v1/diagnostics'),
  models: () => request<{ packs: ModelPack[]; operations: Record<string, { status: string; error?: string }> }>('/api/v1/models'),
  initializeModel: (id: string) => request(`/api/v1/models/${id}/initialize`, { method: 'POST' }),
  jobs: () => request<{ jobs: JobSummary[] }>('/api/v1/jobs'),
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  upload: async (file: File) => {
    const form = new FormData(); form.append('file', file)
    return request<MediaAsset>('/api/v1/media/upload', { method: 'POST', body: form })
  },
  inbox: () => request<{ files: { filename: string; bytes: number }[] }>('/api/v1/media/inbox'),
  importInbox: (filename: string) => request<MediaAsset>('/api/v1/media/import', json('POST', { filename })),
  createJob: (asset_id: string, options: unknown) => request<{ id: string }>('/api/v1/jobs', json('POST', { asset_id, options })),
  cancel: (id: string) => request(`/api/v1/jobs/${id}/cancel`, { method: 'POST' }),
  resume: (id: string) => request(`/api/v1/jobs/${id}/resume`, { method: 'POST' }),
  approveSubtitles: (id: string) => request(`/api/v1/jobs/${id}/approve-subtitles`, { method: 'POST' }),
  approveTranscript: (id: string) => request(`/api/v1/jobs/${id}/approve-transcript`, { method: 'POST' }),
  updateRegions: (id: string, regions: [number,number,number,number][]) => request(`/api/v1/jobs/${id}/subtitle-regions`, json('PUT', { regions })),
  updateTemporalMasks: (id:string,masks:TemporalMask[]) => request(`/api/v1/jobs/${id}/temporal-masks`,json('PUT',{masks})),
  projectTranslation: () => request<{glossary:Record<string,string>}>('/api/v1/project/translation'),
  saveProjectTranslation: (glossary:Record<string,string>) => request('/api/v1/project/translation',json('PUT',{glossary})),
  editTranscript: (id: string, segments: unknown) => request<Job>(`/api/v1/jobs/${id}/transcript`, json('PUT', segments)),
  editSpeakers: (id: string, assignments: unknown) => request<Job>(`/api/v1/jobs/${id}/speakers`, json('PUT', { assignments })),
  voices: () => request<{ voices: Voice[] }>('/api/v1/voices'),
}
