// fill.js against local copies of typical ATS forms. Run: npm test (in extension/), Playwright's Chromium.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const PROFILE = JSON.parse(fs.readFileSync(path.join(ROOT, 'profile.example.json'), 'utf8'));
const CV = { name: 'Alex_Example_CV.pdf', type: 'application/pdf', data: Buffer.from('%PDF-1.4\n%%EOF\n').toString('base64') };

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function filled(fixture) {
  const page = await browser.newPage();
  await page.goto('file://' + path.join(__dirname, 'fixtures', fixture));
  await page.addScriptTag({ path: path.join(ROOT, 'fill.js') });
  const res = await page.evaluate(([p, cv]) => globalThis.__jobAutofill.run(p, cv), [PROFILE, CV]);
  return { page, res };
}

const val = (page, sel) => page.$eval(sel, (e) => e.value);
const checked = (page, name) => page.$eval(`input[name="${name}"]:checked`, (e) => e.value).catch(() => null);
const optText = (page, sel) => page.$eval(sel, (e) => e.options[e.selectedIndex].textContent.trim());

test('generic form: identity, links, choices, numbers', async () => {
  const { page, res } = await filled('generic.html');
  assert.equal(await val(page, '#fn'), 'Alex');
  assert.equal(await val(page, '#ln'), 'Example');
  assert.equal(await val(page, '#em'), 'alex@example.com');
  assert.equal(await val(page, '#ph'), '+381 60 123 4567');
  assert.equal(await val(page, '#loc'), 'Belgrade, Serbia');
  assert.equal(await val(page, '#li'), 'https://www.linkedin.com/in/alex-example');
  assert.equal(await val(page, '#web'), 'https://github.com/alex-example');
  assert.equal(await val(page, '#gh'), 'https://github.com/alex-example');
  assert.equal(await val(page, '#already'), 'Sasha', 'a field with a value is left alone');
  assert.equal(await optText(page, '#ctry'), 'Serbia', 'exact option beats a longer one');
  assert.equal(await optText(page, '#heard'), 'LinkedIn');
  assert.equal(await checked(page, 'sp'), '1', 'sponsorship needed');
  assert.equal(await checked(page, 'auth'), '0', 'not authorised to work in NL');
  assert.equal(await checked(page, 'rel'), 'y');
  assert.equal(await checked(page, 'y3'), 'y', '5 years of QA >= 3');
  assert.equal(await optText(page, '#gender'), "I don't wish to answer");
  assert.equal(await optText(page, '#vet'), 'I prefer not to say');
  assert.match(await val(page, '#sal'), /5,000-5,500/);
  assert.equal(await val(page, '#salnum'), '66000');
  assert.equal(await val(page, '#notice'), '1 month');
  assert.equal(await val(page, '#yrs'), '8');
  assert.equal(await val(page, '#yrsqa'), '5');
  assert.equal(await val(page, '#yrspw'), '4', 'per-skill years from the profile');
  assert.equal(await val(page, '#yrscy'), '', 'no years for a tool the CV does not have');
  assert.equal(await optText(page, '#eng'), 'Fluent');
  assert.equal(await val(page, '#curco'), 'Acme Pay');
  assert.equal(await val(page, '#curti'), 'QA Tech Lead');
  assert.equal(await val(page, '#refname'), '', 'referrer is not the candidate');
  assert.equal(await val(page, '#addinfo'), '');
  assert.match(await val(page, '#summary'), /^Senior SDET/);
  assert.equal(await page.$eval('#gdpr', (e) => e.checked), false, 'consent stays with the user');
  assert.equal(await page.$eval('#cv', (e) => e.files.length && e.files[0].name), 'Alex_Example_CV.pdf');
  assert.equal(await page.$eval('#cl', (e) => e.files.length), 0, 'cover letter is not the CV');
  assert.equal(res.cv, true);
  assert.equal(await page.evaluate(() => window.submitted), undefined);
  await page.close();
});

test('lever: questions without for=, radios, location suggestion', async () => {
  const { page } = await filled('lever.html');
  assert.equal(await val(page, 'input[name=name]'), 'Alex Example');
  assert.equal(await val(page, 'input[name=email]'), 'alex@example.com');
  assert.equal(await val(page, 'input[name=org]'), 'Acme Pay');
  assert.equal(await val(page, 'input[name="urls[LinkedIn]"]'), 'https://www.linkedin.com/in/alex-example');
  assert.equal(await page.evaluate(() => window.pickedLocation), 'Belgrade, Central Serbia, Serbia');
  assert.equal(await optText(page, 'select'), 'Serbia');
  assert.equal(await checked(page, 'cards[b][field0]'), 'Yes, sponsorship is required');
  assert.equal(await checked(page, 'cards[c][field0]'), '2', 'LinkedIn job posting');
  assert.equal(await checked(page, 'cards[d][field0]'), 'y', 'Appium is in the CV');
  assert.equal(await checked(page, 'cards[e][field0]'), null, 'Kotlin is not: left for the user');
  assert.equal(await page.$eval('#resume-upload-input', (e) => e.files.length), 1);
  await page.close();
});

test('ashby: yes/no buttons do not submit the form, combobox picks an option', async () => {
  const { page } = await filled('ashby.html');
  assert.equal(await val(page, '#_systemfield_name'), 'Alex Example');
  assert.equal(await val(page, '#p1'), '+381 60 123 4567');
  assert.equal(await page.evaluate(() => window.answer), 'Yes');
  assert.equal(await page.evaluate(() => window.pickedLocation), 'Belgrade, Serbia');
  assert.equal(await page.$eval('#_systemfield_resume', (e) => e.files.length), 1);
  assert.equal(await page.evaluate(() => window.submitted), undefined, 'clicking a button without type= must not submit');
  await page.close();
});

test('workday: blocks in order, dates, dropdown buttons, dial code', async () => {
  const { page } = await filled('workday.html');
  assert.equal(await val(page, '#n1'), 'Alex');
  assert.equal(await val(page, '#n2'), 'Example');
  assert.equal(await val(page, '#a1'), 'Example street 1');
  assert.equal(await val(page, '#c1'), 'Belgrade');
  assert.equal(await val(page, '#z1'), '11000');
  assert.equal(await page.textContent('#countryBtn'), 'Serbia');
  assert.equal(await page.textContent('#ptBtn'), 'Mobile');
  assert.equal(await optText(page, '#pc'), 'Serbia (+381)');
  assert.equal(await val(page, '#pn'), '60 123 4567', 'national number next to a dial-code field');
  assert.equal(await val(page, '#t1'), 'QA Tech Lead');
  assert.equal(await val(page, '#co1'), 'Acme Pay');
  assert.equal(await val(page, '#l1'), 'Johannesburg, South Africa');
  assert.equal(await page.$eval('#cur1', (e) => e.checked), true);
  assert.equal(await page.$eval('#cur2', (e) => e.checked), false);
  assert.equal(await val(page, '#s1m'), '11');
  assert.equal(await val(page, '#s1y'), '2025');
  assert.equal(await val(page, '#e1m'), '', 'current role has no end');
  assert.equal(await val(page, '#t2'), 'Senior QA Engineer');
  assert.equal(await val(page, '#co2'), 'Travel Soft');
  assert.equal(await val(page, '#s2m'), '09');
  assert.equal(await val(page, '#e2y'), '2025');
  assert.match(await val(page, '#d1'), /450 scenarios/);
  assert.equal(await val(page, '#sch1'), 'ITMO University');
  assert.equal(await page.textContent('#degBtn'), "Master's Degree");
  assert.equal(await val(page, '#fos1'), 'Big Data and Machine Learning');
  assert.equal(await val(page, '#ey1'), '2020');
  assert.equal(await val(page, '#ey2'), '2022');
  assert.equal(await checked(page, 'prev'), '0');
  assert.equal(await page.evaluate(() => window.submitted), undefined);
  await page.close();
});

test('second click changes nothing', async () => {
  const { page, res } = await filled('generic.html');
  const again = await page.evaluate(([p, cv]) => globalThis.__jobAutofill.run(p, cv), [PROFILE, CV]);
  assert.equal(again.filled + again.review, 0);
  assert.ok(again.kept >= res.filled + res.review);
  await page.close();
});
