import { chromium } from 'playwright';
const OUT = process.env.OUT;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });

// Log everything the page paints that might be the orange flash
p.on('console', m => { if (m.type()==='error') console.log('CONSOLE ERROR:', m.text().slice(0,140)); });

await p.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
await p.screenshot({ path: `${OUT}/01-login.png` });

// Sign in
await p.fill('input[type=email]', process.env.EMAIL);
await p.fill('input[type=password]', process.env.PASS);
await Promise.all([
  p.waitForURL(/overview|monitors/, { timeout: 20000 }).catch(()=>{}),
  p.click('button[type=submit]'),
]);
await p.waitForTimeout(2500);
await p.screenshot({ path: `${OUT}/02-overview.png`, fullPage: true });

// Navigate and capture DURING the transition to catch the orange
await p.click('a[href="/monitors"]');
await p.waitForTimeout(120);              // mid-transition
await p.screenshot({ path: `${OUT}/03-transition.png` });
await p.waitForTimeout(2000);
await p.screenshot({ path: `${OUT}/04-monitors.png`, fullPage: true });

await b.close();
