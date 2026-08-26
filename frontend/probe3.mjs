import { chromium } from 'playwright';
const OUT = process.env.OUT;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
await p.fill('input[type=email]', process.env.EMAIL);
await p.fill('input[type=password]', process.env.PASS);
await p.click('button[type=submit]');
await p.waitForTimeout(3500);

await p.screenshot({ path: `${OUT}/10-branded-light.png` });

// Collapse the rail
await p.click('button[aria-label="Collapse sidebar"]');
await p.waitForTimeout(600);
await p.screenshot({ path: `${OUT}/11-collapsed.png` });

// Expand again, open the org switcher to see the new create flow
await p.click('button[aria-label="Expand sidebar"]');
await p.waitForTimeout(500);
await p.click('button[aria-label^="Organization"]').catch(async () => {
  await p.click('button[aria-label="Choose organization"]');
});
await p.waitForTimeout(500);
await p.screenshot({ path: `${OUT}/12-org-dropdown.png` });
await p.keyboard.press('Escape');

// Dark mode
await p.click('button[aria-label="Switch to dark theme"]').catch(()=>{});
await p.waitForTimeout(700);
await p.screenshot({ path: `${OUT}/13-branded-dark.png` });
await b.close();
