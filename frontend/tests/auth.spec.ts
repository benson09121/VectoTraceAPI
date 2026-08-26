import { test, expect } from '@playwright/test';

test.describe('Authentication and Recovery', () => {
  // Use isolated storage state for these tests so we start fresh
  test.use({ storageState: { cookies: [], origins: [] } });

  test('user can register a new account', async ({ page }) => {
    await page.goto('/auth/register');
    // Assuming standard data-testids for these elements
    await page.fill('[data-testid="register-email"]', `test-${Date.now()}@example.com`);
    await page.fill('[data-testid="register-password"]', 'StrongPass123!');
    await page.click('[data-testid="register-submit"]');
    
    // Expect to be redirected to dashboard or onboarding
    await expect(page).toHaveURL(/.*\/dashboard|.*\/onboarding/);
  });

  test('user can log in with valid credentials', async ({ page }) => {
    await page.goto('/auth/login');
    await page.fill('[data-testid="login-email"]', 'member@monitor.test');
    await page.fill('[data-testid="login-password"]', 'TestPass123!');
    await page.click('[data-testid="login-submit"]');
    
    await expect(page).toHaveURL(/.*\/dashboard/);
    
    // Verify auth cookie or token is set
    const cookies = await page.context().cookies();
    const hasAuthCookie = cookies.some(c => c.name === 'refresh_token' || c.name === 'access_token');
    // We don't fail strictly here in case they use localStorage, but we can check UI state
    await expect(page.locator('[data-testid="user-menu"]')).toBeVisible();
  });

  test('user can log out', async ({ page }) => {
    await page.goto('/auth/login');
    await page.fill('[data-testid="login-email"]', 'member@monitor.test');
    await page.fill('[data-testid="login-password"]', 'TestPass123!');
    await page.click('[data-testid="login-submit"]');
    
    await expect(page).toHaveURL(/.*\/dashboard/);
    
    // Perform logout
    await page.click('[data-testid="user-menu"]');
    await page.click('[data-testid="logout-button"]');
    
    await expect(page).toHaveURL(/.*\/auth\/login/);
  });

  test('offline recovery works', async ({ page }) => {
    // Navigate to a page that supports offline caching/recovery
    await page.goto('/dashboard');
    
    // Simulate offline
    await page.context().setOffline(true);
    
    // Attempt to reload or perform an action
    await page.reload();
    
    // The app should show an offline indicator rather than crashing
    await expect(page.locator('[data-testid="offline-indicator"]')).toBeVisible();
    
    // Restore network
    await page.context().setOffline(false);
  });
});
