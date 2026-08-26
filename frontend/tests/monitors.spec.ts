import { test, expect } from '@playwright/test';

test.describe('Monitors', () => {
  test.use({ storageState: 'tests/setup/storageState.json' });

  test('user can create a new monitor', async ({ page }) => {
    await page.goto('/dashboard/monitors');
    await page.click('[data-testid="create-monitor-btn"]');
    
    await page.fill('[data-testid="monitor-name"]', 'Production API');
    await page.fill('[data-testid="monitor-url"]', 'https://api.example.com/health');
    await page.click('[data-testid="save-monitor-btn"]');
    
    await expect(page.locator('text=Production API')).toBeVisible();
  });

  test('user can edit and pause a monitor', async ({ page }) => {
    await page.goto('/dashboard/monitors');
    // Assuming the first monitor in the list
    await page.click('[data-testid="monitor-list-item-0"]');
    await page.click('[data-testid="edit-monitor-btn"]');
    
    await page.fill('[data-testid="monitor-name"]', 'Production API - Edited');
    await page.click('[data-testid="save-monitor-btn"]');
    await expect(page.locator('text=Production API - Edited')).toBeVisible();

    await page.click('[data-testid="pause-monitor-btn"]');
    await expect(page.locator('[data-testid="status-badge-paused"]')).toBeVisible();
  });
});
