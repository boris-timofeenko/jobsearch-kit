const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

async function bundled(path) {
  try { const r = await fetch(api.runtime.getURL(path)); return r.ok ? r : null; } catch (e) { return null; }
}

// status line: optional green tick + plain text (no innerHTML)
function status(el, ok, text) {
  el.textContent = '';
  if (ok) { const t = document.createElement('span'); t.className = 'ok'; t.textContent = '✓ '; el.append(t); }
  el.append(text);
}

function describe(p) {
  const e = p.experience && p.experience[0];
  return [
    `${p.person.full_name} · ${p.person.email} · ${p.person.phone.international}`,
    `${p.location.display}${p.location.address ? ', ' + p.location.address : ''}`,
    e ? `Сейчас: ${e.title}, ${e.company}` : '',
    `Опыт: ${(p.experience || []).length} мест, образование: ${(p.education || []).length}`,
    `Зарплата: ${(p.answers.salary || {}).text || '—'} · уведомление: ${p.answers.notice_period || '— (не задано)'}`,
    p.generated ? `Собран: ${p.generated}` : '',
  ].filter(Boolean).join('\n');
}

async function render() {
  const { profile, cv, attachCv } = await api.storage.local.get(['profile', 'cv', 'attachCv']);
  let p = profile, src = 'импортирован';
  if (!p) { const r = await bundled('profile.json'); p = r ? await r.json() : null; src = 'встроенный profile.json'; }
  status($('profileStatus'), !!p, p ? src : 'Профиля нет: импортируйте profile.json.');
  $('profilePreview').textContent = p ? describe(p) : '';
  $('profileReset').disabled = !profile;

  if (cv && cv.data) status($('cvStatus'), true, `${cv.name} (${Math.round(cv.data.length * 0.75 / 1024)} КБ, выбран здесь)`);
  else {
    const r = await bundled((p && p.cv_file) || 'cv.pdf');
    status($('cvStatus'), !!r, r ? `встроенный: ${(p && p.cv_name) || 'cv.pdf'}` : 'CV нет: выберите PDF.');
  }
  $('cvReset').disabled = !(cv && cv.data);
  $('attachCv').checked = attachCv !== false;
}

function readFile(file, as) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    as === 'text' ? fr.readAsText(file) : fr.readAsDataURL(file);
  });
}

$('profileFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const p = JSON.parse(await readFile(f, 'text'));
    if (!p.person || !p.person.email) throw new Error('нет person.email');
    await api.storage.local.set({ profile: p });
  } catch (err) {
    alert('Не похоже на profile.json: ' + err.message);
  }
  e.target.value = '';
  render();
});

$('cvFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const url = await readFile(f, 'dataurl');
  await api.storage.local.set({ cv: { name: f.name, type: f.type || 'application/pdf', data: url.split(',')[1] } });
  e.target.value = '';
  render();
});

$('profileReset').addEventListener('click', async () => { await api.storage.local.remove('profile'); render(); });
$('cvReset').addEventListener('click', async () => { await api.storage.local.remove('cv'); render(); });
$('attachCv').addEventListener('change', async (e) => { await api.storage.local.set({ attachCv: e.target.checked }); });

render();
