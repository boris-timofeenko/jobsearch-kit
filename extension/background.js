// Toolbar click (or Alt+Shift+J): inject fill.js into every frame of the tab, run it with the profile, show a summary.
// Profile and CV come from storage.local (imported on the options page) or, failing that, from profile.json / the CV
// file bundled next to this script by `python -m jobsearch autofill`.
const api = globalThis.browser ?? globalThis.chrome;

async function bundled(path, as) {
  try {
    const r = await fetch(api.runtime.getURL(path));
    if (!r.ok) return null;
    return as === 'json' ? await r.json() : await r.arrayBuffer();
  } catch (e) {
    return null;
  }
}

function toB64(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

async function loadProfile() {
  const { profile } = await api.storage.local.get('profile');
  return profile || bundled('profile.json', 'json');
}

async function loadCv(profile) {
  const { cv, attachCv } = await api.storage.local.get(['cv', 'attachCv']);
  if (attachCv === false) return null;
  if (cv && cv.data) return cv;
  const file = (profile && profile.cv_file) || 'cv.pdf';
  const buf = await bundled(file.replace(/^.*\//, ''), 'bin') || await bundled('cv.pdf', 'bin');
  return buf ? { name: (profile && profile.cv_name) || 'CV.pdf', type: 'application/pdf', data: toB64(buf) } : null;
}

async function toast(tabId, text) {
  try {
    await api.scripting.executeScript({ target: { tabId, frameIds: [0] }, files: ['fill.js'] });
    await api.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: (t) => globalThis.__jobAutofill.toast(t), args: [text] });
  } catch (e) { /* page that does not allow scripts (about:, addons store) */ }
}

async function fill(tab) {
  const profile = await loadProfile();
  if (!profile) {
    await toast(tab.id, 'Job Autofill: профиль не загружен. Открываю настройки: импортируйте profile.json.');
    api.runtime.openOptionsPage();
    return;
  }
  const cv = await loadCv(profile);
  let results;
  const run = async (target) => {
    await api.scripting.executeScript({ target, files: ['fill.js'] });
    return api.scripting.executeScript({ target, func: (p, c) => globalThis.__jobAutofill.run(p, c), args: [profile, cv] });
  };
  try {
    results = await run({ tabId: tab.id, allFrames: true });
  } catch (e) {
    // a frame we may not touch fails the whole call in some browsers: fall back to the page itself
    try { results = await run({ tabId: tab.id }); } catch (e2) {
      await api.action.setBadgeText({ tabId: tab.id, text: '!' });
      console.error('job autofill', e2);
      return;
    }
  }
  const sum = { filled: 0, review: 0, missed: 0, kept: 0, cv: false };
  for (const r of results || []) {
    const v = r && r.result;
    if (!v) continue;
    for (const k of ['filled', 'review', 'missed', 'kept']) sum[k] += v[k] || 0;
    sum.cv = sum.cv || v.cv;
  }
  const total = sum.filled + sum.review;
  await api.action.setBadgeBackgroundColor({ tabId: tab.id, color: total ? '#2e9d4e' : '#888' });
  await api.action.setBadgeText({ tabId: tab.id, text: total ? String(total) : '0' });
  const lines = total || sum.missed || sum.kept
    ? [`Job Autofill: заполнено ${total}` + (sum.cv ? ', CV прикреплён' : ''),
      sum.review ? `🟧 проверить: ${sum.review} (зарплата, да/нет, стаж)` : '',
      sum.missed ? `🟦 не заполнено: ${sum.missed}` : '',
      sum.kept ? `уже было заполнено: ${sum.kept}` : '',
      'Отправка формы — вручную.']
    : ['Job Autofill: полей формы на странице не нашёл.'];
  await toast(tab.id, lines.filter(Boolean).join('\n'));
}

api.action.onClicked.addListener((tab) => {
  // host access lets the script reach application forms embedded from another domain (Greenhouse iframes);
  // Firefox asks once, the request must happen before any await to count as a user action
  const perm = api.permissions && api.permissions.request
    ? api.permissions.request({ origins: ['<all_urls>'] }).catch(() => false)
    : Promise.resolve(true);
  perm.then(() => fill(tab));
});
