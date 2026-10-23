import { expect, test } from '@playwright/test'

test('shows the dashboard served by the running container', async ({ page }) => {
  const url=process.env.LIVE_APP_URL
  test.skip(!url,'Set LIVE_APP_URL when the production container is running.')
  await page.goto(url!)
  await expect(page.getByRole('heading',{name:'Start with a video'})).toBeVisible()
  await expect(page.getByText('Model readiness')).toBeVisible()
  await expect(page.getByText('CPU-only processing')).toBeVisible()
})
