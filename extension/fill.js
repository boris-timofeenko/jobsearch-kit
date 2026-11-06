// Job Autofill: fills a job application form from profile.json. Injected by background.js into every frame of the
// active tab on toolbar click, then called as __jobAutofill.run(profile, cv). Only empty fields are touched, nothing
// is submitted; filled fields get a green outline, answers worth a second look (salary, yes/no, years) orange,
// fields left empty blue.
(() => {
  if (globalThis.__jobAutofill) return;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const MARK = 'data-job-autofill';
  const COLORS = { filled: '#2e9d4e', review: '#e08a00', missed: '#3b82f6' };

  // ---------------------------------------------------------------- text helpers
  const fold = (s) => (s || '').toString().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const squash = (s) => fold(s).replace(/[*✱:]+/g, ' ').replace(/\((required|optional|verplicht|pflicht)\)/g, ' ')
    .replace(/\s+/g, ' ').trim();
  const humanize = (s) => fold((s || '').replace(/([a-z])([A-Z])/g, '$1 $2')).replace(/[_\-[\]./:#]+/g, ' ')
    .replace(/\s+/g, ' ').trim();

  const SKIP_TEXT = new Set(['SCRIPT', 'STYLE', 'SELECT', 'OPTION', 'TEXTAREA', 'NOSCRIPT', 'svg']);

  function textExcluding(node, excluded = []) {
    let out = '';
    const walk = (n) => {
      if (n.nodeType === 3) { out += n.nodeValue + ' '; return; }
      if (n.nodeType !== 1 || SKIP_TEXT.has(n.tagName) || excluded.some((x) => x === n)) return;
      if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return;
      for (const c of n.childNodes) walk(c);
    };
    walk(node);
    return out.replace(/\s+/g, ' ').trim();
  }

  const byId = (el, id) => (el.getRootNode().getElementById ? el.getRootNode().getElementById(id) : null)
    || document.getElementById(id);

  // ---------------------------------------------------------------- DOM traversal (open and, in Firefox, closed shadow roots)
  function deepAll(root, sel, out = []) {
    for (const el of root.querySelectorAll(sel)) out.push(el);
    for (const el of root.querySelectorAll('*')) {
      const sr = el.openOrClosedShadowRoot || el.shadowRoot;
      if (sr) deepAll(sr, sel, out);
    }
    return out;
  }

  const visible = (el) => {
    if (!el.isConnected || el.closest('[' + MARK + '-ui]')) return false;
    const r = el.getClientRects();
    if (!r.length) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none';
  };

  // ---------------------------------------------------------------- controls
  const TEXT_TYPES = new Set(['', 'text', 'email', 'tel', 'url', 'number', 'search', 'date', 'month']);
  const CONTROL_SEL = 'input, select, textarea, [role=combobox]:not(input), button[aria-haspopup=listbox], '
    + '[role=radiogroup], [role=radio]';

  function isControl(el) {
    if (el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
    if (el.tagName === 'INPUT') {
      const t = (el.type || '').toLowerCase();
      if (t === 'file') return true;
      if (el.readOnly && el.getAttribute('role') !== 'combobox') return false;
      if (el.tabIndex === -1 && getComputedStyle(el).opacity === '0') return false;   // react-select's required shadow
      if (!(TEXT_TYPES.has(t) || t === 'radio' || t === 'checkbox')) return false;
    }
    if (el.tagName === 'TEXTAREA' && (el.readOnly || /recaptcha/i.test(el.name || el.id))) return false;
    if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
      // native radios are often visually hidden behind a styled label
      const lab = el.labels && el.labels[0];
      return visible(el) || (lab && visible(lab));
    }
    return visible(el);
  }

  // Everything other controls in `root` might conflict with: to decide how far up a question's text may be looked for.
  function otherControls(root, group) {
    return [...root.querySelectorAll('input, select, textarea, [role=combobox]:not(input)')]
      .filter((e) => !group.includes(e) && e.type !== 'hidden' && !(e.tabIndex === -1 && e.getAttribute('aria-hidden')))
      .filter((e) => e.getAttribute('aria-hidden') !== 'true').length;
  }

  // Text of the question around a control when no <label> points at it: climb while the ancestor holds no other field.
  function questionText(first, group, excluded) {
    let a = first.parentElement;
    for (let depth = 0; a && depth < 7; depth++, a = a.parentElement) {
      if (a === document.body || a.tagName === 'FORM') break;
      if (otherControls(a, group) > 0) break;
      const t = textExcluding(a, excluded);
      if (t.length >= 2) return t.slice(0, 400);
    }
    return '';
  }

  const DATE_PART = /^(month|year|day|mm|yyyy|jjjj|maand|jaar|monat|jahr|mois|annee)$/;

  function labelOf(el, group = [el], excluded = group) {
    const parts = [];
    const lb = el.getAttribute('aria-labelledby');
    if (lb) for (const id of lb.split(/\s+/)) { const n = byId(el, id); if (n && n !== el) parts.push(textExcluding(n, excluded)); }
    if (el.labels) for (const l of el.labels) parts.push(textExcluding(l, excluded));
    if (el.getAttribute('aria-label')) parts.push(el.getAttribute('aria-label'));
    let label = squash(parts.join(' '));
    if (!label) label = squash(questionText(el, group, excluded));
    // "Month" / "Year" alone say nothing about which date: add the text of the small group around the date parts
    if (DATE_PART.test(label)) {
      let a = el.parentElement;
      for (let d = 0; a && d < 6; d++, a = a.parentElement) {
        const ctrls = [...a.querySelectorAll('input, select')].filter((x) => x.type !== 'hidden');
        if (ctrls.length > 3) break;
        const q = squash(textExcluding(a, ctrls)).replace(/\b(month|year|day|mm|yyyy|dd|jjjj|maand|jaar|monat|jahr|mois|annee)\b/g, '').trim();
        if (q.length >= 2) { label = q + ' ' + label; break; }
      }
    }
    return label;
  }

  function attrsOf(el) {
    const bits = [el.name, el.id, el.placeholder, el.getAttribute('autocomplete'), el.title,
      el.getAttribute('data-automation-id'), el.getAttribute('data-qa'), el.getAttribute('data-testid'),
      el.getAttribute('data-ui'), el.getAttribute('data-field')];
    let a = el.parentElement;
    for (let i = 0; a && i < 4; i++, a = a.parentElement) bits.push(a.getAttribute('data-automation-id'), a.id);
    return humanize(bits.filter(Boolean).join(' '));
  }

  const EDU = /educat|school|universit|academic|degree|opleiding|ausbildung|studium|\bformation\b|\betudes\b/;
  const EXP = /experience|employment|work history|job history|career history|werkervaring|berufserfahrung|experience professionnelle/;

  function headingsIndex() {
    // section titles, not questions: a legend "Do you have 3 years of experience...?" must not open an experience block
    return deepAll(document, 'h1, h2, h3, h4, h5, h6, [role=heading]')
      .map((h) => ({ h, t: squash(h.textContent) }))
      .filter((x) => x.t && x.t.length <= 40 && !/\?/.test(x.t));
  }

  function sectionOf(el, heads) {
    const form = el.closest('form');
    let a = el;
    for (let i = 0; a && i < 10; i++, a = a.parentElement) {
      const s = humanize([a.id, a.getAttribute && a.getAttribute('data-automation-id'), a.getAttribute && a.getAttribute('aria-label')]
        .filter(Boolean).join(' '));
      if (EDU.test(s)) return 'edu';
      if (EXP.test(s)) return 'exp';
    }
    let last = null;
    for (const x of heads) {
      if (!(x.h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
      if (!form || form.contains(x.h)) last = x;
    }
    if (last) { if (EDU.test(last.t)) return 'edu'; if (EXP.test(last.t)) return 'exp'; }
    return '';
  }

  const isCombo = (el) => el.tagName === 'INPUT' && (el.getAttribute('role') === 'combobox'
    || el.getAttribute('aria-haspopup') === 'listbox' || /list|both/.test(el.getAttribute('aria-autocomplete') || ''));

  // Groups the page into fields: {kind, el | els, label, attrs, section, options}
  function collectFields() {
    const heads = headingsIndex();
    const fields = [];
    const seen = new Set();
    const all = deepAll(document, CONTROL_SEL).filter((el) => !seen.has(el));
    for (const el of all) {
      if (seen.has(el)) continue;
      if (el.getAttribute('role') === 'radiogroup') {
        const radios = [...el.querySelectorAll('[role=radio], input[type=radio]')];
        radios.forEach((r) => seen.add(r));
        seen.add(el);
        if (!radios.length) continue;
        const opts = radios.map((r) => ({ el: r, text: squash(r.getAttribute('aria-label') || textExcluding(r) || (r.labels && r.labels[0] ? r.labels[0].textContent : '')) }));
        fields.push({ kind: 'radio', els: radios, options: opts, label: labelOf(el, [el, ...radios], [...radios, ...radios.map((r) => r.closest('label')).filter(Boolean)]), attrs: attrsOf(el), section: sectionOf(el, heads) });
        continue;
      }
      if (!isControl(el)) continue;
      const tag = el.tagName;
      const type = (el.type || '').toLowerCase();
      if (tag === 'INPUT' && type === 'radio' || el.getAttribute('role') === 'radio') {
        const root = el.getRootNode();
        const radios = el.name ? [...root.querySelectorAll('input[type=radio]')].filter((r) => r.name === el.name) : [el];
        radios.forEach((r) => seen.add(r));
        const labels = radios.map((r) => (r.labels && r.labels[0]) || r.closest('label')).filter(Boolean);
        const opts = radios.map((r) => ({ el: r, text: squash(((r.labels && r.labels[0]) || r.closest('label') || {}).textContent || r.getAttribute('aria-label') || r.value) }));
        const fs = el.closest('fieldset');
        let label = fs && fs.querySelector('legend') ? squash(textExcluding(fs.querySelector('legend'))) : '';
        if (!label) label = squash(questionText(radios[0], radios, [...radios, ...labels]));
        fields.push({ kind: 'radio', els: radios, options: opts, label, attrs: attrsOf(el), section: sectionOf(el, heads) });
        continue;
      }
      seen.add(el);
      let kind;
      if (tag === 'SELECT') kind = 'select';
      else if (tag === 'TEXTAREA') kind = 'textarea';
      else if (tag === 'INPUT' && type === 'file') kind = 'file';
      else if (tag === 'INPUT' && type === 'checkbox') kind = 'checkbox';
      else if (tag === 'INPUT') kind = isCombo(el) ? 'combo' : 'text';
      else kind = 'dropdown';                                  // Workday-style button / div opening a listbox
      const f = { kind, el, label: labelOf(el), attrs: attrsOf(el), section: sectionOf(el, heads) };
      if (kind === 'file' && !f.label) f.label = squash(questionText(el, [el], [el]));
      if (kind === 'select') f.options = [...el.options].map((o) => ({ el: o, text: squash(o.textContent), value: o.value }));
      fields.push(f);
    }
    fields.push(...buttonGroups(heads, seen));
    return fields;
  }

  // Ashby-style yes/no: two buttons next to each other instead of radios
  function buttonGroups(heads, seen) {
    const out = [];
    const done = new Set();
    for (const b of deepAll(document, 'button, [role=button]')) {
      if (done.has(b) || !visible(b) || !/^(yes|no|ja|nee|nein|oui|non)$/.test(squash(b.textContent))) continue;
      const box = b.parentElement;
      const btns = [...box.querySelectorAll('button, [role=button]')].filter((x) => /^(yes|no|ja|nee|nein|oui|non)$/.test(squash(x.textContent)));
      btns.forEach((x) => done.add(x));
      if (btns.length < 2) continue;
      const hidden = [...box.parentElement.querySelectorAll('input[type=checkbox]')];
      hidden.forEach((x) => seen.add(x));
      const label = squash(questionText(box, [...btns, ...hidden], btns));
      out.push({ kind: 'buttons', els: btns, options: btns.map((x) => ({ el: x, text: squash(x.textContent) })), label, attrs: '', section: sectionOf(b, heads) });
    }
    return out;
  }

  // ---------------------------------------------------------------- current state
  function comboHasValue(el) {
    const box = el.closest('[class*=control], [class*=Control], [class*=container]') || el.parentElement;
    return !!(box && box.querySelector('[class*=single-value], [class*=singleValue], [class*=multi-value], [class*=multiValue], '
      + '[data-automation-id=selectedItem], [data-automation-id=selectedItemList] li'))
      || (el.value || '').trim() !== '';
  }

  function hasValue(f) {
    const el = f.el;
    switch (f.kind) {
      case 'text': case 'textarea': return (el.value || '').trim() !== '';
      case 'select': {
        const o = el.options[el.selectedIndex];
        return !!o && o.value !== '' && !/^(select|choose|please|kies|bitte|--|-|selecteer|wahlen)/.test(squash(o.textContent));
      }
      case 'combo': return comboHasValue(el);
      case 'dropdown': { const t = squash(el.textContent); return t !== '' && !/^(select|choose|kies|bitte|selecteer)/.test(t); }
      case 'radio': return f.els.some((r) => r.checked || r.getAttribute('aria-checked') === 'true');
      case 'buttons': return f.els.some((b) => b.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(b.className));
      case 'file': return !!(el.files && el.files.length);
      case 'checkbox': return el.checked;
    }
    return false;
  }

  // ---------------------------------------------------------------- answers
  const YES_RE = /^(yes|ja|oui|si|da|y)\b/;
  const NO_RE = /^(no|nee|nein|non|n)\b/;
  const yes = () => ({ text: 'Yes', opts: [YES_RE], review: true });
  const no = () => ({ text: 'No', opts: [NO_RE], review: true });
  const DECLINE = [/decline|prefer not|rather not|not (to )?(say|disclose|answer|specify)|don'?t wish|do not wish|choose not|wish not|not wish/];
  const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const textOpts = (t) => { const n = squash(t); return [new RegExp('^' + esc(n) + '$'), new RegExp('^' + esc(n) + '\\b'), new RegExp('\\b' + esc(n) + '\\b')]; };

  function monthsSince(d, now = new Date()) {
    return (now.getFullYear() - d.year) * 12 + (now.getMonth() + 1 - (d.month || 1));
  }

  function yearsOf(p) {
    const ex = p.experience || [];
    const starts = (pred) => ex.filter(pred).map((e) => e.start).filter(Boolean);
    const since = (list) => list.length ? Math.round(Math.max(...list.map((d) => monthsSince(d))) / 12) : null;
    const y = p.years || {};
    return {
      total: y.total ?? since(starts(() => true)),
      qa: y.qa ?? since(starts((e) => /\b(qa|sdet|test|quality)/i.test(e.title))),
      lead: y.lead ?? since(starts((e) => /\b(lead|head|manager)\b/i.test(e.title))),
      skills: y.skills || {},
    };
  }

  function skillsSet(p) {
    return (p.skills || []).flatMap((s) => [s, ...s.split(/[/(),]/)]).map(squash).filter((s) => s.length > 1);
  }

  // Number the question asks for ("5+ years", "at least 3 years") or null
  const askedYears = (l) => { const m = l.match(/(\d{1,2})\s*\+?\s*(years|yrs|jaar|jahre|ans)/); return m ? +m[1] : null; };

  function yearsAnswer(f, p, l) {
    const y = yearsOf(p);
    let n = null;
    for (const [k, v] of Object.entries(y.skills)) if (new RegExp('\\b' + esc(fold(k)) + '\\b').test(l)) { n = v; break; }
    if (n == null && !mentionsTool(l)) {
      if (/\b(lead|leadership|management|managing|people manager)\b/.test(l)) n = y.lead;
      else if (/\b(qa|quality|test|testing|automation|sdet)\b/.test(l)) n = y.qa;
      else if (/\b(professional|work|working|software|industry|relevant|total|overall|it)\b/.test(l)) n = y.total;
    }
    if (n == null) return null;
    const need = askedYears(l);
    if (need != null && (f.kind === 'radio' || f.kind === 'buttons' || /^(do|have|are)\b/.test(l))) return n >= need ? yes() : no();
    return { text: String(n), opts: [(t) => rangeHas(t, n)], review: true };
  }

  // "3-5 years", "5+", "more than 10", "0-2" contain n?
  function rangeHas(t, n) {
    let m = t.match(/(\d+)\s*(?:-|–|to|tot|bis|a)\s*(\d+)/);
    if (m) return n >= +m[1] && n <= +m[2];
    m = t.match(/(\d+)\s*\+|(?:more than|over|meer dan|mehr als|plus de)\s*(\d+)/);
    if (m) return n >= +(m[1] || m[2]) + (m[2] ? 1 : 0);
    m = t.match(/(?:less than|under|minder dan|weniger als|moins de)\s*(\d+)/);
    if (m) return n < +m[1];
    return new RegExp('^' + n + '\\b').test(t);
  }

  // Tools the profile does not list (Java, Cypress...) must not be answered from the generic numbers
  const TOOL_WORDS = /\b(java|c#|\.net|kotlin|swift|golang|ruby|php|scala|rust|c\+\+|cypress|testcafe|webdriverio|detox|espresso|xcuitest|robot framework|katalon|tosca|ranorex|uft|loadrunner|gatling|locust|playwright|selenium|appium|flutter|python|typescript|javascript|pytest|postman|k6|jmeter)\b/;
  const mentionsTool = (l) => TOOL_WORDS.test(l);

  function experienceWith(l, p) {
    const m = l.match(/(?:experience|worked|familiar|proficient|hands-on|knowledge|skilled)\s+(?:with|in|of|using)\s+(.+)/);
    if (!m) return null;
    const asked = m[1].replace(/\?.*$/, '');
    const have = skillsSet(p);
    const hit = have.find((s) => s.length > 2 && new RegExp('\\b' + esc(s) + '\\b').test(asked));
    return hit ? yes() : null;
  }

  // month and year of one date are two fields: each keeps its own count of blocks
  const datePart = (f) => {
    const l = f.label + ' ' + f.attrs;
    const m = /\bmonth|\bmm\b|maand|monat|mois/.test(l), y = /\byear|yyyy|jaar|jahr|annee/.test(l);
    return m && !y ? 'month' : y && !m ? 'year' : 'full';
  };

  function dateAnswer(entry, part, f, p) {
    const d = entry && entry[part];
    if (!d) return null;
    const l = f.label + ' ' + f.attrs;
    const mm = String(d.month || 1).padStart(2, '0');
    if (/\bmonth|\bmm\b|maand|monat|mois/.test(l) && !/year|yyyy|jaar|jahr|annee/.test(l)) {
      if (!d.month) return null;
      return { text: mm, opts: [new RegExp('^' + MONTHS[d.month - 1]), new RegExp('^' + MONTHS[d.month - 1].slice(0, 3) + '\\b'), new RegExp('^0?' + d.month + '$')] };
    }
    if (/\byear|yyyy|jaar|jahr|annee/.test(l) && !/month|mm\b/.test(l)) return { text: String(d.year), opts: [new RegExp('^' + d.year + '$')] };
    if (f.el && f.el.type === 'month') return { text: `${d.year}-${mm}` };
    if (f.el && f.el.type === 'date') return { text: `${d.year}-${mm}-01` };
    if (/mm\s*\/\s*yyyy|mm\s*yyyy/.test(fold(f.el && f.el.placeholder))) return { text: `${mm}/${d.year}` };
    if (/mm\s*\/\s*dd/.test(fold(f.el && f.el.placeholder))) return null;
    return { text: d.month ? `${mm}/${d.year}` : String(d.year) };
  }

  const any = (f) => f.label + ' | ' + f.attrs;
  const CHOICE = new Set(['select', 'radio', 'buttons', 'combo', 'dropdown']);

  // Ordered: the first rule that matches decides. `re` is tested on the visible label, `are` on the name/id/placeholder
  // attributes, `not` on both. `max` caps the label length for identity fields so long questions do not match them.
  const RULES = [
    { id: 'cover', re: /cover ?letter|motivation|anschreiben|lettre|motivatie|begeleidende/, are: /cover ?letter/, value: () => null },
    { id: 'referral', re: /\breferr|\breferee|who referred|recommended by|reference (name|contact|email)|emergency/, value: () => null },
    { id: 'resume', kinds: ['file'], re: /resume|\bcv\b|curriculum|lebenslauf|levensloop|resum|document|attach|upload|file|bestand|datei/, are: /resume|\bcv\b|curriculum|document|attach|upload|file/,
      not: /cover|motivation|anschreiben|lettre|photo|picture|avatar|image|portfolio|transcript|certificat|diploma|id card|passport/, value: () => ({ file: true }) },
    { id: 'first_name', max: 60, re: /\bfirst ?name|given name|forename|voornaam|vorname|prenom|^first$/, are: /first ?name|given name|fname|legal name first/, value: (p) => ({ text: p.person.first_name }) },
    { id: 'last_name', max: 60, re: /\blast ?name|surname|family name|achternaam|nachname|nom de famille|^last$/, are: /last ?name|family name|lname|surname/, value: (p) => ({ text: p.person.last_name }) },
    { id: 'middle_name', max: 60, re: /middle name|tussenvoegsel/, value: () => null },
    { id: 'preferred_name', max: 60, re: /preferred (first )?name|nick ?name|roepnaam/, value: (p) => ({ text: p.person.first_name }) },
    { id: 'full_name', max: 50, re: /^(full |legal |your |candidate |complete |volledige )?(name|naam|nom|vor- und nachname|name und vorname)$|^(full|legal) name\b/,
      are: /(^|\s)(full ?name|systemfield name|candidate name|^name)(\s|$)/, not: /company|employer|school|universit|user ?name|file/, value: (p) => ({ text: p.person.full_name }) },
    { id: 'email', max: 80, re: /e-?mail/, are: /e-?mail/, value: (p) => ({ text: p.person.email }) },
    { id: 'phone_code', max: 80, re: /country code|dial(ing)? code|phone code|calling code|landcode|landnummer|vorwahl|indicatif|phone country|country phone|prefix/, are: /country ?phone ?code|phone ?code|dial ?code|country code|calling code/,
      value: (p) => ({ text: p.person.phone.country_code, search: p.location.country, opts: [new RegExp('\\+\\s?' + p.person.phone.country_code.replace('+', '') + '\\b'), ...textOpts(p.location.country)] }) },
    { id: 'phone_type', max: 60, re: /phone (device )?type|device type|type of phone/, are: /phone ?device ?type|phone ?type/, value: () => ({ text: 'Mobile', opts: [/^mobile|^cell|^mobiel|^handy/] }) },
    { id: 'phone', max: 80, re: /phone|mobile|mobiel|\btel\b|telefoon|telefon|telephone|cell/, are: /phone|mobile|\btel\b/, not: /extension|\bext\b|type|code/,
      value: (p, c) => ({ text: c.hasDialCode ? p.person.phone.national : p.person.phone.international }) },
    { id: 'linkedin', re: /linked ?in/, are: /linked ?in/, value: (p) => p.person.linkedin && ({ text: p.person.linkedin }) },
    { id: 'github', re: /git ?hub/, are: /git ?hub/, value: (p) => p.person.github && ({ text: p.person.github }) },
    { id: 'telegram', re: /telegram/, are: /telegram/, value: (p) => p.person.telegram && ({ text: p.person.telegram }) },
    { id: 'social', max: 60, re: /twitter|\bx\.com|facebook|instagram|dribbble|behance|stack ?overflow|medium/, value: () => null },
    { id: 'website', max: 80, re: /portfolio|website|web site|personal (site|page|url)|homepage|\bblog\b|\burls?\b|other links?|online profile/, are: /portfolio|website|\burls?\b/,
      value: (p) => (p.person.website || p.person.github) && ({ text: p.person.website || p.person.github }) },
    { id: 'heard', re: /how did you (hear|find|learn|come across)|where did you (hear|find|see|learn)|how you heard|hoe (heb|ben) je|wie (sind|haben) sie|comment avez-vous|source of (application|candidacy)|^source$/,
      value: (p) => ({ text: p.answers.heard_about, opts: [new RegExp('^' + esc(fold(p.answers.heard_about))), new RegExp('\\b' + esc(fold(p.answers.heard_about)))], review: true }) },
    { id: 'salary', re: /salary|compensation|remuneration|pay expectation|expected pay|desired pay|gehalt|salaris|loon|salaire|remuneration|wage|rate expectation|ctc\b/,
      value: (p, c, f) => salaryAnswer(p, f) },
    { id: 'notice', re: /notice period|opzegtermijn|kundigungsfrist|preavis|when can you start|earliest (possible )?start|available (to start|from)|availability|start date|beschikbaar|verfugbar|eintrittsdatum|date de disponibilite/,
      when: (f) => f.section === '', value: (p, c, f) => noticeAnswer(p, f) },
    // yes/no questions: before location and experience rules, whose words they contain
    { id: 'yn_no_sponsor', re: /without (the )?(need (for|of) )?(any )?(visa |work permit |employer )?sponsor|without requiring (visa |a )?sponsor|not (need|require) (visa )?sponsor/, value: () => no() },
    { id: 'yn_sponsor', re: /(require|need|necessit)\w*.{0,60}(sponsor|visa|work permit|permit to work)|sponsorship|visa support|werkvergunning nodig|visum/, value: () => yes() },
    { id: 'yn_authorized', re: /(authori[sz]ed|eligible|legally (able|allowed|entitled|permitted)|entitled|right|permitted|allowed|permission) to (work|live and work)|work (authori[sz]ation|permit|eligibility)|right to work|arbeitserlaubnis|werkvergunning|autorisation de travail/,
      value: (p) => p.answers.work_authorized ? yes() : no() },
    { id: 'yn_citizen', re: /(eu|eea|european union|european|swiss|uk|british|dutch|german|french|belgian) (citizen|national|passport)|citizen of (the )?(eu|european|eea)|(eu|eea) nationality/, value: () => no() },
    { id: 'yn_relocate', re: /relocat|verhuiz|umzug|umziehen|demenag/, value: () => yes() },
    { id: 'yn_fulltime', re: /full[- ]time|40 hours|fulltime|voltijd|vollzeit|temps plein/, value: () => yes() },
    { id: 'yn_onsite', re: /(hybrid|on-?site|in (the )?office|office[- ]based|commut|days? (a|per) week|from (the|our) office|required location|work from .{0,40}(office|location)|reisbereidheid)/, value: () => yes() },
    { id: 'yn_adult', re: /18 (years|or older)|over (the age of )?18|at least 18|legal (working )?age|volljahrig/, value: () => yes() },
    { id: 'yn_other_lang', re: /(speak|fluent|proficien|command|knowledge|beheers|spreek|sprechen|parlez).{0,40}\b(dutch|nederlands|german|deutsch|french|francais|spanish|espanol|italian|portuguese|polish|swedish|danish|norwegian|finnish|czech)\b/, when: (f) => f.kind !== 'text' && f.kind !== 'textarea' || /^(do|are|can|is)\b/.test(f.label), value: () => no() },
    { id: 'yn_english', re: /(speak|fluent|proficien|command|comfortable).{0,40}\benglish\b/, when: (f) => f.kind !== 'text' && f.kind !== 'textarea' || /^(do|are|can|is)\b/.test(f.label), value: () => yes() },
    { id: 'yn_located', re: /(currently|already) (live|living|reside|residing|based|located)|do you (currently )?(live|reside)|are you (currently )?(based|located|living|residing) in|resident of/,
      when: (f) => CHOICE.has(f.kind) || /^(do|are)\b/.test(f.label),
      value: (p, c, f) => new RegExp('\\b(' + [p.location.city, p.location.country, 'europe', 'cet', 'emea', 'balkans'].map((s) => esc(fold(s))).join('|') + ')\\b').test(f.label) ? yes() : no() },
    { id: 'yn_employee', re: /(previously|ever|already) (worked|been employed|employed) (for|at|by|with)|former employee|(are you )?a current employee|currently employed (by|at) /, value: () => no() },
    { id: 'yn_experience', re: /(do|have) you (have )?(any |hands-on |professional |practical )?(experience|worked|familiar|knowledge)/, when: (f) => CHOICE.has(f.kind), value: (p, c, f) => experienceWith(f.label, p) },
    { id: 'consent', re: /consent|agree|privacy|terms|gdpr|data (processing|retention|protection)|toestemming|einwilligung|datenschutz|acknowledge|confirm that/, value: () => null },
    // education block (sequential: the n-th school field gets the n-th entry)
    { id: 'school', seq: 'edu', re: /school|universit|institution|college|hochschule|ecole|onderwijsinstelling|place of study/, are: /school|universit|institution/, not: /high school diploma|degree/, when: (f) => f.section !== 'exp',
      value: (p, c) => { const e = p.education[c.i]; return e && { text: e.school, search: e.school_search || e.school, opts: textOpts(e.school), autocomplete: true }; } },
    { id: 'degree', seq: 'edu', re: /degree|qualification|diploma|abschluss|diplome|opleidingsniveau|(level|highest) (of )?education|education level|highest level/, are: /degree/,
      value: (p, c) => { const e = p.education[c.i]; return e && { text: e.degree_full || e.degree, opts: degreeOpts(e) }; } },
    { id: 'field_of_study', seq: 'edu', re: /field of study|discipline|major|speciali[sz]ation|studierichting|studiengang|fachrichtung|area of study|subject|course of study|programme|program\b/, are: /discipline|field of study|major/,
      value: (p, c) => { const e = p.education[c.i]; return e && { text: e.field, opts: textOpts(e.field) }; } },
    { id: 'grade', re: /\bgpa\b|grade|cijfer|note\b|abschlussnote/, when: (f) => f.section === 'edu', value: () => null },
    // work experience block
    { id: 'current_company', max: 60, re: /current (company|employer|organi[sz]ation)|present employer|most recent (company|employer)|^org(ani[sz]ation)?$|huidige werkgever|aktueller arbeitgeber/, are: /^org$|current company/, value: (p) => p.experience[0] && ({ text: p.experience[0].company }) },
    { id: 'current_title', max: 60, re: /current (job )?(title|role|position)|present (title|position)|most recent (title|position|role)|huidige functie|aktuelle position/, value: (p) => p.experience[0] && ({ text: p.experience[0].title }) },
    { id: 'company', seq: 'exp', max: 60, re: /company|employer|organi[sz]ation|werkgever|arbeitgeber|unternehmen|entreprise|bedrijf/, are: /company|employer/, when: (f) => f.section !== 'edu',
      value: (p, c) => { const e = p.experience[c.i]; return e && { text: e.company }; } },
    { id: 'job_title', seq: 'exp', max: 60, re: /job title|position title|^title$|^role$|^position$|^functie|berufsbezeichnung|jobtitel|intitule|^poste$|job title/, are: /job ?title|position ?title/, when: (f) => f.section === 'exp' || /job|position/.test(f.label + f.attrs),
      value: (p, c) => { const e = p.experience[c.i]; return e && { text: e.title }; } },
    { id: 'exp_location', seq: 'exp', max: 60, re: /location|city|plaats|ort\b|lieu/, when: (f) => f.section === 'exp', value: (p, c) => { const e = p.experience[c.i]; return e && e.location && { text: e.location }; } },
    { id: 'exp_description', seq: 'exp', kinds: ['textarea'], re: /description|responsibilit|achievement|duties|tasks|what did you do|taken|aufgaben|role description/, when: (f) => f.section === 'exp',
      value: (p, c) => { const e = p.experience[c.i]; return e && e.description && { text: e.description }; } },
    { id: 'currently_here', kinds: ['checkbox'], re: /current(ly)? (work|working|employed|role|position)|i (currently )?work here|still (work|employed)|present|tot heden|bis heute/, when: (f) => f.section !== 'edu',
      value: (p, c) => c.nth('currently_here') === 0 && p.experience[0] && p.experience[0].current ? { check: true } : null },
    { id: 'start', seq: 'date', max: 40, kinds: ['text', 'select', 'combo', 'dropdown'], re: /\b(start|from|begin|since|van|von|debut|vanaf)\b|start date/, are: /start ?date|from|start/, when: (f) => f.section !== '',
      value: (p, c, f) => dateAnswer(block(p, f)[c.i], 'start', f, p) },
    { id: 'end', seq: 'date', max: 40, kinds: ['text', 'select', 'combo', 'dropdown'], re: /\b(end|to|until|finish|tot|bis|fin|graduation|graduated)\b|end date/, are: /end ?date|\bto\b|end/, when: (f) => f.section !== '',
      value: (p, c, f) => dateAnswer(block(p, f)[c.i], 'end', f, p) },
    // numbers and levels
    { id: 'years', re: /years? of (\w+ ){0,3}experience|how many years|years experience|experience \(years\)|jaar ervaring|jaren ervaring|jahre berufserfahrung|annees d.experience|\byoe\b/, value: (p, c, f) => yearsAnswer(f, p, f.label) },
    { id: 'english_level', re: /english/, when: (f) => /level|proficien|fluen|skill|niveau|kenntnis/.test(f.label) || CHOICE.has(f.kind),
      value: (p) => langAnswer(p, 'english') },
    { id: 'other_lang_level', re: /\b(dutch|nederlands|german|deutsch|french|francais)\b/, when: (f) => CHOICE.has(f.kind),
      value: () => ({ opts: [/^(none|no|geen|keine|aucun|not|beginner|basic)\b/], review: true }) },
    { id: 'languages', max: 80, re: /^languages?( spoken)?$|which languages|talen|sprachkenntnisse|langues/, kinds: ['text', 'textarea'],
      value: (p) => ({ text: (p.languages || []).map((l) => `${l.name} (${l.level})`).join(', ') }) },
    { id: 'nationality', max: 80, re: /nationality|citizenship|nationaliteit|staatsangehorigkeit|nationalite/, are: /nationality|citizenship/,
      value: (p) => p.person.nationality && ({ text: p.person.nationality, search: p.person.citizenship_country || p.person.nationality, opts: [...textOpts(p.person.nationality), ...(p.person.citizenship_country ? textOpts(p.person.citizenship_country) : [])], review: true }) },
    { id: 'dob', max: 60, re: /date of birth|birth ?date|birthday|geboortedatum|geburtsdatum|date de naissance/, are: /birth/, value: (p) => p.person.date_of_birth && ({ text: p.person.date_of_birth, review: true }) },
    // address and location
    { id: 'address2', max: 60, re: /address (line )?2|address 2|apartment|suite|\bapt\b|toevoeging|adresszusatz/, are: /address ?line ?2|address2/, value: () => null },
    { id: 'address', max: 60, re: /street|address( line)?( 1)?$|^address\b|home address|postal address|straat|adres|strasse|anschrift|adresse/, are: /address ?line ?1|street|^address/, not: /e-?mail|web|ip address/,
      value: (p) => p.location.address && ({ text: p.location.address }) },
    { id: 'postal', max: 60, re: /postal|post ?code|zip|\bplz\b|code postal|postcode/, are: /postal|zip|post ?code/, value: (p) => p.location.postal_code && ({ text: p.location.postal_code }) },
    { id: 'region', max: 60, re: /\bstate\b|province|region|county|provincie|bundesland|departement/, are: /\bstate\b|province|region/, value: () => null },
    { id: 'city', max: 60, re: /\bcity\b|\btown\b|woonplaats|\bplaats\b|\bstadt\b|\bort\b|\bville\b|municipality|gemeente/, are: /\bcity\b|town|locality/, not: /location/,
      value: (p) => ({ text: p.location.city, opts: textOpts(p.location.city), autocomplete: true }) },
    { id: 'country', max: 80, re: /\bcountry\b|\bland\b|\bpays\b|country of residence|country\/region|where do you (currently )?live|wohnland/, are: /country/, not: /code|phone|citizen|nationality|birth|visa/,
      value: (p) => ({ text: p.location.country, opts: [...textOpts(p.location.country), ...(p.location.country_aliases || []).flatMap(textOpts)] }) },
    { id: 'location', max: 120, re: /location|where are you (currently )?(based|located)|based in|current(ly)? (city|residence)|place of residence|residence|wohnort|standort|localisation|lieu de residence|woonplaats/, are: /location/,
      not: /preferred|desired|willing|relocat|office|work location/,
      value: (p, c, f) => f.kind === 'select'
        ? { text: p.location.country, opts: [...textOpts(p.location.display), ...textOpts(p.location.city), ...textOpts(p.location.country)] }
        : { text: p.location.display, search: p.location.city, opts: [new RegExp('\\b' + esc(fold(p.location.city))), ...textOpts(p.location.country)], autocomplete: true } },
    // equal-opportunity questions: the "prefer not to say" option when there is one, unless the profile answers
    { id: 'gender', re: /\bgender\b|\bsex\b|geslacht|geschlecht|genre\b|identify (my|your) gender/, value: (p) => p.answers.gender ? { text: p.answers.gender, opts: textOpts(p.answers.gender), review: true } : { opts: DECLINE, review: true } },
    { id: 'pronouns', re: /pronoun/, value: () => ({ opts: DECLINE, review: true }) },
    { id: 'eeo', re: /ethnic|\brace\b|racial|hispanic|latino|veteran|disabilit|sexual orientation|transgender|lgbt|heritage/, kinds: ['select', 'radio', 'combo', 'dropdown', 'buttons'], value: () => ({ opts: DECLINE, review: true }) },
    // free text about the candidate
    { id: 'headline', max: 60, re: /headline|professional title|desired (job )?title/, kinds: ['text'], value: (p) => ({ text: p.headline }) },
    { id: 'summary', kinds: ['textarea'], re: /summary|about (you|yourself|me)|profile|introduce yourself|\bbio\b|over jezelf|uber (sie|dich)|a propos/, value: (p) => p.summary && ({ text: p.summary, review: true }) },
  ];

  // yes/no rules answer free-text fields only when the label is phrased as a question
  const QUESTION = /^(are|do|does|will|would|can|could|is|have|has|did)\b/;
  for (const r of RULES) {
    if (!r.id.startsWith('yn_')) continue;
    const own = r.when || (() => true);
    r.when = (f) => (CHOICE.has(f.kind) || QUESTION.test(f.label)) && own(f);
  }

  const block = (p, f) => (f.section === 'edu' ? p.education : p.experience) || [];

  function degreeOpts(e) {
    const d = fold(e.degree);
    if (/^m|master/.test(d)) return [/master'?s?\b.*(science|degree)?|^m\.?sc|^msc|^ma\b|master/, /post ?graduate|graduate/];
    if (/^b|bachelor/.test(d)) return [/bachelor|^b\.?sc|^bsc|^ba\b/, /undergraduate/];
    if (/^ph|doctor/.test(d)) return [/doctor|ph\.?d/];
    return textOpts(e.degree);
  }

  function langAnswer(p, name) {
    const l = (p.languages || []).find((x) => fold(x.name) === name);
    if (!l) return null;
    const lv = fold(l.level);
    const opts = /native|mother/.test(lv) ? [/native|mother|bilingual|c2/]
      : /c2/.test(lv) ? [/\bc2\b|proficient|native|bilingual|fluent/]
        : /c1/.test(lv) ? [/\bc1\b/, /fluent|advanced|full professional|professional working|proficient/]
          : /b2/.test(lv) ? [/\bb2\b/, /upper.?intermediate|professional working/] : textOpts(l.level);
    return { text: l.level, opts, review: true };
  }

  function salaryAnswer(p, f) {
    const s = p.answers.salary || {};
    const l = any(f);
    const yearly = /annual|year|yearly|per annum|p\.?a\.?|jaar|jahr|annuel/.test(l);
    const monthly = /month|monthly|maand|monat|mensuel/.test(l);
    const num = yearly ? s.annual : monthly ? s.monthly : (f.el && f.el.type === 'number' ? (s.annual && /k\b|000/.test(l) ? s.annual : s.monthly) : null);
    if (f.kind === 'text' && f.el.type === 'number') return num && { text: String(num), review: true };
    if (CHOICE.has(f.kind)) return num && { opts: [(t) => rangeHas(t.replace(/[.,](?=\d{3})/g, '').replace(/(\d+)\s*k\b/g, (m, a) => a + '000'), num)], review: true };
    if (yearly && s.annual) return { text: String(s.annual), review: true };
    if (monthly && s.monthly) return { text: String(s.monthly), review: true };
    return s.text && { text: s.text, review: true };
  }

  function noticeAnswer(p, f) {
    const a = p.answers;
    const l = any(f);
    if (/notice|opzeg|kundigung|preavis/.test(l)) return a.notice_period && { text: a.notice_period, opts: textOpts(a.notice_period), review: true };
    // date pickers take a date, not "1 month"
    if (f.el && (f.el.type === 'date' || /\b(date|dd|mm|yyyy|jjjj)\b/.test(humanize(f.el.placeholder)))) {
      if (!a.available_from) return null;
      if (f.el.type === 'date') return { text: a.available_from, review: true };
      const [y, m, d] = a.available_from.split('-');
      const ph = fold(f.el.placeholder);
      return { text: /mm\s*\/\s*dd/.test(ph) ? `${m}/${d}/${y}` : /dd\s*[./-]\s*mm/.test(ph) ? `${d}/${m}/${y}` : a.available_from, review: true };
    }
    const t = a.available_text || a.notice_period;
    return t && { text: t, opts: textOpts(t), review: true };
  }

  // yes/no answers only fit a choice that offers yes and no; menus not opened yet may
  function offersYesNo(f) {
    if (!f.options) return true;
    return f.options.some((o) => YES_RE.test(o.text)) && f.options.some((o) => NO_RE.test(o.text));
  }

  // The visible label decides first; name/id/placeholder attributes only when no rule knows the label
  function match(f) {
    const label = f.label, attrs = f.attrs, both = label + ' | ' + attrs;
    const usable = (r) => {
      if (r.kinds && !r.kinds.includes(f.kind)) return false;
      if (!r.kinds && f.kind === 'file' && r.id !== 'cover') return false;
      if (f.kind === 'checkbox' && !(r.kinds || []).includes('checkbox') && r.id !== 'consent') return false;
      if (r.id.startsWith('yn_') && !offersYesNo(f)) return false;
      return !(r.not && r.not.test(both)) && !(r.when && !r.when(f));
    };
    for (const r of RULES) if (r.re && r.re.test(label) && (!r.max || label.length <= r.max) && usable(r)) return r;
    for (const r of RULES) if (r.are && r.are.test(attrs) && (!r.max || label.length <= r.max || !label) && usable(r)) return r;
    return null;
  }

  // ---------------------------------------------------------------- writing values
  const protoOf = (el) => el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
    : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;

  function setValue(el, v) {
    const d = Object.getOwnPropertyDescriptor(protoOf(el), 'value');
    if (d && d.set) d.set.call(el, v); else el.value = v;
  }

  const fire = (el, type, init = {}) => el.dispatchEvent(new Event(type, { bubbles: true, composed: true, ...init }));
  const key = (el, k, code) => ['keydown', 'keyup'].forEach((t) => el.dispatchEvent(new KeyboardEvent(t, { key: k, code: k, keyCode: code, which: code, bubbles: true, cancelable: true, composed: true })));

  // A click on a <button> inside a <form> can submit it. Never let our clicks do that.
  function safeClick(el) {
    const stop = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };
    window.addEventListener('submit', stop, true);
    try {
      const o = { bubbles: true, cancelable: true, composed: true, button: 0 };
      el.dispatchEvent(new MouseEvent('mousedown', o));
      el.dispatchEvent(new MouseEvent('mouseup', o));
      el.click();
    } finally {
      window.removeEventListener('submit', stop, true);
    }
  }

  function typeText(el, text) {
    el.focus({ preventScroll: true });
    setValue(el, text);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'insertText', data: text }));
    fire(el, 'change');
  }

  function fillText(el, text) {
    if (el.type === 'number' && !/^-?\d+(\.\d+)?$/.test(text)) return false;
    if (el.type === 'email' && !/@/.test(text)) return false;
    if (el.maxLength > 0 && text.length > el.maxLength) text = text.slice(0, el.maxLength);
    typeText(el, text);
    el.blur();
    return true;
  }

  function pick(options, ans) {
    const usable = options.filter((o) => o.text && !/^(select|choose|please|kies|bitte|selecteer|--)/.test(o.text));
    const tests = ans.opts || (ans.text ? textOpts(ans.text) : []);
    for (const t of tests) {
      const hit = usable.find((o) => (typeof t === 'function' ? t(o.text) : t.test(o.text)));
      if (hit) return hit;
    }
    return null;
  }

  function fillSelect(el, options, ans) {
    const o = pick(options, ans);
    if (!o) return false;
    setValue(el, o.value);
    o.el.selected = true;
    fire(el, 'input');
    fire(el, 'change');
    return true;
  }

  function fillChoice(f, ans) {
    const o = pick(f.options, ans);
    if (!o) return false;
    const target = o.el.tagName === 'INPUT' && o.el.labels && o.el.labels[0] && !visible(o.el) ? o.el.labels[0] : o.el;
    safeClick(target);
    if (o.el.tagName === 'INPUT' && !o.el.checked) { o.el.checked = true; fire(o.el, 'change'); }
    return true;
  }

  const OPTION_SEL = '[role=option], [data-automation-id=promptOption], .pac-item, .dropdown-location, .autocomplete-suggestion, li[id*=option], [class*=suggestion] li';

  function visibleOptions(el) {
    const ids = [el.getAttribute('aria-controls'), el.getAttribute('aria-owns')].filter(Boolean);
    for (const id of ids) {
      const box = byId(el, id);
      if (box) { const o = [...box.querySelectorAll(OPTION_SEL)].filter(visible); if (o.length) return o; }
    }
    return deepAll(document, OPTION_SEL).filter(visible);
  }

  async function waitOptions(el, ans, ms) {
    const t0 = Date.now();
    let last = [];
    while (Date.now() - t0 < ms) {
      last = visibleOptions(el);
      const o = pick(last.map((x) => ({ el: x, text: squash(x.textContent) })), ans);
      if (o) return o.el;
      await sleep(120);
    }
    return null;
  }

  function openCombo(el) {
    el.focus({ preventScroll: true });
    const ctl = el.closest('[class*=control], [class*=Control]');
    const md = { bubbles: true, cancelable: true, composed: true, button: 0, buttons: 1 };
    (ctl || el).dispatchEvent(new MouseEvent('mousedown', md));
    if (el.getAttribute('aria-expanded') !== 'true' && ctl) ctl.dispatchEvent(new Event('touchend', { bubbles: true, cancelable: true }));
    if (el.getAttribute('aria-expanded') !== 'true') key(el, 'ArrowDown', 40);
  }

  async function fillCombo(el, ans) {
    openCombo(el);
    await sleep(150);
    let o = await waitOptions(el, ans, 400);            // short list already open (Yes/No, gender...)
    if (!o && (ans.search || ans.text)) {
      typeText(el, ans.search || ans.text);
      o = await waitOptions(el, ans, 2500);             // async search (location, school)
      if (!o) { key(el, 'Enter', 13); o = await waitOptions(el, ans, 1200); }   // Workday prompt: search on Enter
    }
    if (o) { safeClick(o); await sleep(120); return true; }
    if (ans.search || ans.text) { setValue(el, ''); fire(el, 'input'); }
    key(el, 'Escape', 27);
    el.blur();
    return false;
  }

  async function fillDropdown(el, ans) {
    safeClick(el);
    await sleep(250);
    const o = await waitOptions(el, ans, 1500);
    if (o) { safeClick(o); await sleep(150); return true; }
    key(el, 'Escape', 27);
    key(document.activeElement || el, 'Escape', 27);
    return false;
  }

  // Plain text inputs with a suggestion list (Lever location, Google Places): type, then take the suggestion if one shows
  async function fillAutocomplete(el, ans) {
    const before = new Set(visibleOptions(el));
    typeText(el, ans.search || ans.text);
    const t0 = Date.now();
    while (Date.now() - t0 < 1500) {
      const fresh = visibleOptions(el).filter((x) => !before.has(x));
      const o = pick(fresh.map((x) => ({ el: x, text: squash(x.textContent) })), ans);
      if (o) { safeClick(o.el); await sleep(150); if (!(el.value || '').trim()) setValue(el, ans.text); return true; }
      await sleep(150);
    }
    if (ans.search && ans.search !== ans.text) { setValue(el, ans.text); fire(el, 'input'); fire(el, 'change'); }
    return true;
  }

  function b64ToFile(cv) {
    const bin = atob(cv.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], cv.name, { type: cv.type || 'application/pdf', lastModified: Date.now() });
  }

  function fillFile(el, cv) {
    const accept = fold(el.accept || '');
    if (accept && !/pdf|application|\*/.test(accept)) return false;
    const dt = new DataTransfer();
    dt.items.add(b64ToFile(cv));
    el.files = dt.files;
    fire(el, 'input');
    fire(el, 'change');
    return true;
  }

  // ---------------------------------------------------------------- marking
  function outline(el, color) {
    if (!el) return;
    el.setAttribute(MARK, color);
    el.style.setProperty('outline', `2px solid ${color}`, 'important');
    el.style.setProperty('outline-offset', '1px', 'important');
    const clear = () => { el.style.removeProperty('outline'); el.style.removeProperty('outline-offset'); el.removeAttribute(MARK); };
    el.addEventListener('focus', clear, { once: true });
  }

  function markField(f, state) {
    const color = COLORS[state];
    if (f.kind === 'radio' || f.kind === 'buttons') {
      const box = commonAncestor(f.els);
      outline(box, color);
    } else if (f.kind === 'file') {
      outline(visible(f.el) ? f.el : f.el.closest('[class*=upload], [class*=file], [class*=drop], [class*=attach], div'), color);
    } else if (f.kind === 'combo') {
      outline(f.el.closest('[class*=control], [class*=Control]') || f.el, color);
    } else outline(f.el, color);
  }

  function commonAncestor(els) {
    let a = els[0].parentElement;
    while (a && !els.every((e) => a.contains(e))) a = a.parentElement;
    return a;
  }

  // ---------------------------------------------------------------- main
  async function run(profile, cv) {
    const p = profile;
    const res = { filled: 0, review: 0, missed: 0, kept: 0, cv: false, fields: [] };
    const fields = collectFields();
    const counters = {};
    const nth = (k) => (counters['n:' + k] = (counters['n:' + k] ?? -1) + 1);
    const matched = fields.map((f) => ({ f, r: match(f) }));
    const hasDialCode = matched.some((m) => m.r && m.r.id === 'phone_code');

    // CV: one file input per form, preferring the one that is not an "autofill from resume" helper
    const fileFields = matched.filter((m) => m.r && m.r.id === 'resume');
    const plain = fileFields.filter((m) => !/autofill|auto-fill|parse|import/.test(m.f.label + m.f.attrs));
    const cvTarget = (plain[0] || fileFields[0] || {}).f;

    const queue = [];
    for (const { f, r } of matched) {
      if (f.kind === 'file') {
        if (f !== cvTarget) continue;
        if (hasValue(f)) { res.kept++; continue; }
        if (cv && fillFile(f.el, cv)) { res.cv = true; res.filled++; markField(f, 'filled'); }
        else { res.missed++; markField(f, 'missed'); }
        continue;
      }
      const seqKey = r && r.seq ? (r.seq === 'date' ? `${f.section}:${r.id}:${datePart(f)}` : r.seq + ':' + r.id) : null;
      const i = seqKey ? nth(seqKey) : 0;
      if (hasValue(f)) { res.kept++; continue; }
      if (!r) { if (f.kind !== 'checkbox') { res.missed++; markField(f, 'missed'); } continue; }
      let ans = null;
      try { ans = r.value(p, { i, hasDialCode, nth }, f); } catch (e) { ans = null; }
      if (!ans) { if (f.kind !== 'checkbox') { res.missed++; markField(f, 'missed'); } continue; }
      queue.push({ f, r, ans });
    }

    // synchronous writes first, then the ones that open menus one at a time
    const later = [];
    for (const q of queue) {
      const { f, ans } = q;
      let ok = null;
      if (f.kind === 'text' || f.kind === 'textarea') {
        if (ans.text == null) ok = false;
        else if (ans.autocomplete && f.kind === 'text') { later.push(q); continue; }
        else ok = fillText(f.el, ans.text);
      } else if (f.kind === 'select') ok = fillSelect(f.el, f.options, ans);
      else if (f.kind === 'radio' || f.kind === 'buttons') ok = fillChoice(f, ans);
      else if (f.kind === 'checkbox') { if (ans.check && !f.el.checked) safeClick(f.el); ok = f.el.checked; }
      else { later.push(q); continue; }
      done(q, ok);
    }
    for (const q of later) {
      let ok = false;
      try {
        if (q.f.kind === 'combo') ok = await fillCombo(q.f.el, q.ans);
        else if (q.f.kind === 'dropdown') ok = await fillDropdown(q.f.el, q.ans);
        else ok = await fillAutocomplete(q.f.el, q.ans);
      } catch (e) { ok = false; }
      done(q, ok);
    }

    function done({ f, r, ans }, ok) {
      if (ok) {
        const state = ans.review ? 'review' : 'filled';
        res[state === 'review' ? 'review' : 'filled']++;
        markField(f, state);
        res.fields.push(`${r.id}: ${(ans.text || '').toString().slice(0, 40)}`);
      } else { res.missed++; markField(f, 'missed'); }
    }
    return res;
  }

  // ---------------------------------------------------------------- toast
  function toast(text, ms = 9000) {
    const old = document.querySelector('[' + MARK + '-ui]');
    if (old) old.remove();
    const host = document.createElement('div');
    host.setAttribute(MARK + '-ui', '');
    host.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:380px';
    const sr = host.attachShadow({ mode: 'closed' });
    const box = document.createElement('div');
    box.style.cssText = 'font:13px/1.45 -apple-system,system-ui,sans-serif;background:#1f2328;color:#f6f8fa;'
      + 'padding:12px 14px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.25);cursor:pointer;white-space:pre-line';
    box.textContent = text;
    box.title = 'Закрыть';
    box.addEventListener('click', () => host.remove());
    sr.appendChild(box);
    (document.body || document.documentElement).appendChild(host);
    setTimeout(() => host.remove(), ms);
  }

  globalThis.__jobAutofill = { run, toast, _collect: collectFields, _match: match, _rules: RULES };
})();
