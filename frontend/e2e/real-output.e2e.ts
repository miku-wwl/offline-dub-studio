import { expect, test } from '@playwright/test'

test('plays the completed private acceptance output through the production UI', async ({ page, request }) => {
  const url=process.env.LIVE_APP_URL
  const id=process.env.LIVE_ACCEPTANCE_JOB_ID
  test.skip(!url || !id,'The real private video and local models are not committed to CI.')
  const response=await request.get(`${url}/api/v1/jobs/${id}`)
  expect(response.ok()).toBe(true)
  const job=await response.json()
  expect(job.status).toMatch(/^completed/)
  await page.goto(url!)
  await page.locator('.recent-row').filter({ hasText:job.display_name }).first().click()
  await expect(page.getByRole('heading',{name:'Export ready'})).toBeVisible()
  const output=page.locator('.video-comparison video').nth(1)
  await expect.poll(() => output.evaluate((element: HTMLVideoElement) => element.readyState),{timeout:30000}).toBeGreaterThanOrEqual(2)
  await output.evaluate(async (element: HTMLVideoElement) => { element.muted=true; await element.play() })
  await expect.poll(() => output.evaluate((element: HTMLVideoElement) => element.currentTime),{timeout:10000}).toBeGreaterThan(.5)
  expect(await output.evaluate((element: HTMLVideoElement) => element.error)).toBeNull()
  // Muted playback proves decoding/progress, never human audio approval.
})
