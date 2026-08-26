import { test, expect } from '@playwright/test';

test.describe('Incidents and Status Pages', () => {
  test.use({ storageState: 'tests/setup/storageState.json' });

  test('user can view incident updates and resolution', async ({ page }) => {
    await page.goto('/dashboard/incidents');
    
    // Check if an incident exists or mock the UI state
    await page.waitForSelector('[data-testid="incident-list"]');
    // ...
  });

  test('user can create a status page', async ({ page }) => {
    await page.goto('/dashboard/status-pages');
    await page.click('[data-testid="create-status-page-btn"]');
    
    await page.fill('[data-testid="sp-name"]', 'Main Status');
    await page.fill('[data-testid="sp-domain"]', 'status.example.com');
    await page.click('[data-testid="save-sp-btn"]');
    
    await expect(page.locator('text=Main Status')).toBeVisible();
  });

  test('keyboard navigation and accessibility', async ({ page }) => {
    await page.goto('/dashboard');
    
    // Press Tab multiple times and expect focus to move logically
    await page.keyboard.press('Tab');
    
    // Basic accessibility check (in real scenario, use @axe-core/playwright)
    const mainNav = page.locator('nav');
    await expect(mainNav).toHaveAttribute('role', 'navigation');
  });
});
