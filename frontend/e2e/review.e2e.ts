import { expect, test } from '@playwright/test'

test('saves speaker edits and requires transcript approval before generating voices', async ({ page }) => {
  let savedSpeaker = ''
  let approved = false
  const job = {
    id: 'review-fixture', display_name: 'generated-review.mp4', status: 'awaiting_transcript_review',
    stage: 'awaiting_transcript_review', progress: 62.5, created_at: '2026-10-24T00:00:00Z',
    updated_at: '2026-10-24T00:00:00Z', options: { subtitle_mode: 'balanced' }, logs: [], speakers: [],
    stages: [{ name: 'translate', status: 'completed', progress: 100 }],
    transcript: [{ id: 's1', start: 1, end: 3, source_text: '你好', translated_text: 'Hello.', speaker_id: 'speaker_1' }],
  }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = {}
    if (path.endsWith('/health')) body = { status: 'ok' }
    else if (path.endsWith('/diagnostics')) body = { cpu_count: 8, data_free_bytes: 10e9, offline_inference: true }
    else if (path.endsWith('/models')) body = { packs: [], operations: {} }
    else if (path.endsWith('/inbox')) body = { files: [] }
    else if (path.endsWith('/voices')) body = { voices: [] }
    else if (path.endsWith('/transcript')) {
      job.transcript = route.request().postDataJSON()
      savedSpeaker = job.transcript[0].speaker_id
      body = job
    } else if (path.endsWith('/approve-transcript')) {
      approved = true
      body = { id: job.id, status: 'queued' }
    } else if (path === '/api/v1/jobs') body = { jobs: [{ id:job.id,display_name:job.display_name,status:job.status,stage:job.stage,progress:job.progress,created_at:job.created_at,updated_at:job.updated_at }] }
    else body = job
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /generated-review.mp4/ }).click()
  await expect(page.getByRole('heading', { name: 'Review dialogue and speakers' })).toBeVisible()
  await page.getByLabel('Speaker', { exact: true }).fill('speaker_2')
  await page.getByLabel('Short translation', {exact:true}).fill('Hi.')
  await page.getByRole('button', { name: 'Save dialogue' }).click()
  await expect.poll(() => savedSpeaker).toBe('speaker_2')
  expect((job.transcript[0] as unknown as {short_translation:string}).short_translation).toBe('Hi.')
  expect(approved).toBe(false)
  await page.getByRole('button', { name: /Generate English voices/ }).click()
  await expect.poll(() => approved).toBe(true)
})
