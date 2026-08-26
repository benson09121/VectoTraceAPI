import { chromium } from 'playwright';
const OUT = process.env.OUT;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
await p.fill('input[type=email]', process.env.EMAIL);
await p.fill('input[type=password]', process.env.PASS);
await p.click('button[type=submit]');
await p.waitForTimeout(3000);

// Open a Select (the health filter) and hover an option — this is the shadcn
// path that paints bg-accent.
await p.click('button[aria-label="Health"]').catch(()=>{});
await p.waitForTimeout(500);
await p.screenshot({ path: `${OUT}/05-select-open.png` });

// Also open the account dropdown
await p.keyboard.press('Escape');
await p.click('button[aria-label="Account menu"]');
await p.waitForTimeout(400);
await p.hover('text=Profile settings').catch(()=>{});
await p.waitForTimeout(300);
await p.screenshot({ path: `${OUT}/06-dropdown-hover.png` });
await b.close();
