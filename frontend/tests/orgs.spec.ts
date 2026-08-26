import { test, expect } from '@playwright/test';

test.describe('Organization Boundaries', () => {
  // Use the authenticated storage state by default
  test.use({ storageState: 'tests/setup/storageState.json' });

  test('user can switch between their organizations', async ({ page }) => {
    await page.goto('/dashboard');
    
    // Open org switcher
    await page.click('[data-testid="org-switcher"]');
    
    // Select second org
    await page.click('[data-testid="org-item-2"]');
    
    // Verify URL or context changes
    await expect(page).toHaveURL(/.*\/dashboard\?org=\w+/);
    await expect(page.locator('[data-testid="current-org-name"]')).toBeVisible();
  });

  test('user is blocked from accessing unauthorized organization', async ({ page, request }) => {
    // Attempt to directly navigate to an org we don't own (assuming org ID 9999)
    const response = await page.goto('/dashboard?org=9999');
    
    // Should be redirected or show forbidden
    await expect(page.locator('[data-testid="forbidden-error"]')).toBeVisible();
    
    // API validation: Try to fetch data from that org
    const apiRes = await request.get('/api/v1/orgs/9999/monitors/');
    expect(apiRes.status()).toBe(403);
  });
});
