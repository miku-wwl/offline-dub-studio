import { expect, test } from '@playwright/test'

test('loads the local conversion dashboard in a browser', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    let body: unknown = {}
    if (url.pathname.endsWith('/health')) body = { status: 'ok' }
    else if (url.pathname.endsWith('/diagnostics')) body = { cpu_count: 8, data_free_bytes: 20_000_000_000, offline_inference: false }
    else if (url.pathname.endsWith('/models')) body = { packs: [
      { id: 'asr-small', name: 'Faster-Whisper Small (Balanced)', kind: 'asr', ready: true, approx_size: '500 MB', license: 'MIT', access: 'public' },
      { id: 'translation-zh-en', name: 'Argos Chinese to English', kind: 'translation', ready: true, approx_size: '50-200 MB', license: 'package metadata', access: 'public' },
      { id: 'tts-kokoro-en', name: 'Kokoro 82M English voices', kind: 'tts', ready: true, approx_size: '363 MB', license: 'Apache-2.0', access: 'public' },
      { id: 'separation-htdemucs', name: 'Demucs htdemucs vocals split', kind: 'separation', ready: true, approx_size: '80-300 MB', license: 'MIT', access: 'public' },
    ], operations: {} }
    else if (url.pathname.endsWith('/jobs')) body = { jobs: [] }
    else if (url.pathname.endsWith('/inbox')) body = { files: [] }
    else if (url.pathname.endsWith('/voices')) body = { voices: [{ id: 'af_heart', label: 'Heart · American English' }] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Start with a video' })).toBeVisible()
  await expect(page.getByText('Model readiness')).toBeVisible()
  await expect(page.getByText(/8 CPU threads/)).toBeVisible()
  await page.getByLabel('Processing profile').selectOption('cpu-lite')
  await expect(page.getByRole('button', { name: /Models required/ })).toBeDisabled()
  await page.getByText('Subtitle and audio settings').click()
  await expect(page.getByLabel(/Subtitle size/)).toBeVisible()
  await expect(page.getByLabel(/Original background gain/)).toBeVisible()
})
