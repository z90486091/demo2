const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');

chromium.use(stealth());

async function checkPWAHealth() {
    const pwaUrl = process.env.PWA_URL || 'https://foo.bar';
    // const successSelector = '#app-root, app-root, [data-testid="main-dashboard"]'; 
    const successSelector = '#fail"]'; 

    console.log(`Starting stealth PWA health check for: ${pwaUrl}`);

    // Launch real system Chrome (or bundled chromium with heavy stealth args)
    const browser = await chromium.launch({ 
        headless: true, // Set to false if you want to watch it run locally
        args: [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-infobars',
            '--window-size=1920,1080',
            '--start-maximized',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-gpu'
        ]
    });

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const harPath = `wsod-failure-${timestamp}.har`;

    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 1,
        locale: 'en-US',
        timezoneId: 'America/New_York',
        recordHar: {
            path: harPath,
            content: 'embed' 
        }
    });

    const page = await context.newPage();
    const consoleLogs = [];
    
    page.on('console', msg => {
        consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    try {
        // Use 'domcontentloaded' or 'load' instead of 'networkidle' to avoid hanging on background sockets
        await page.goto(pwaUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        
        // Give it a few seconds to evaluate WAF challenge or render scripts
        await page.waitForTimeout(5000);

        const pageContent = await page.content();
        const pageTitle = await page.title();

        if (pageContent.includes('The request is blocked') || pageTitle === 'Service unavailable') {
            throw new Error('WAF / AFD blocked the request with a "Service unavailable" page.');
        }

        // Wait for the app root element
        await page.waitForSelector(successSelector, { timeout: 15000 });

        console.log('SUCCESS: PWA booted and rendered successfully.');
        
        await context.close();
        await browser.close();
        
        if (fs.existsSync(harPath)) {
            fs.unlinkSync(harPath);
        }
        
        process.exit(0);

    } catch (error) {
        console.error('FAILURE: WSOD or WAF block detected!', error.message);
        
        const screenshotPath = `wsod-failure-${timestamp}.png`;
        await page.screenshot({ path: screenshotPath, fullPage: true });
        console.log(`Saved failure screenshot to: ${screenshotPath}`);

        await context.close();
        await browser.close();

        console.log(`Saved failure HAR file to: ${harPath}`);
        console.log('--- Browser Console Logs ---');
        consoleLogs.forEach(log => console.log(log));
        
        process.exit(1);
    }
}

checkPWAHealth();
