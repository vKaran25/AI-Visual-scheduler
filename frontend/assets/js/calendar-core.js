/* Pure calendar helpers. Local dates deliberately avoid UTC conversion. */
(function (root) {
  'use strict';
  const pad = n => String(n).padStart(2, '0');
  const key = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const fromKey = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
    const d = new Date(`${value}T00:00:00`);
    return !Number.isNaN(d.getTime()) && key(d) === value ? d : null;
  };
  const addDays = (d, n) => { const result = new Date(d); result.setDate(result.getDate() + n); return result; };
  const monday = d => addDays(d, -((d.getDay() + 6) % 7));
  function datesForView(date, view) {
    const start = view === 'month' ? monday(new Date(date.getFullYear(), date.getMonth(), 1)) : view === 'week' ? monday(date) : new Date(date);
    const length = view === 'month' ? 42 : view === 'week' ? 7 : 1;
    return Array.from({length}, (_, i) => addDays(start, i));
  }
  function moveDate(date, view, direction) {
    if (view !== 'month') return addDays(date, direction * (view === 'week' ? 7 : 1));
    const first = new Date(date.getFullYear(), date.getMonth() + direction, 1);
    const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    first.setDate(Math.min(date.getDate(), last));
    return first;
  }

  // Parse common single-event phrases without sending personal text to a provider.
  // Every result is reviewed in a form; an omitted period/duration stays unset.
  function parseQuickEntry(text, now = new Date(), selected = now) {
    let rest = text.trim().replace(/\btom(?:m?orow|mor?row|roow)\b/gi, 'tomorrow');
    const notes = [];
    let date = key(selected), dateFound = false, hour = '', minute = 0, period = '', duration = '';
    const remove = match => { rest = rest.replace(match[0], ' '); };
    const relative = rest.match(/\b(day after tomorrow|tomorrow|today|tonight)\b/i);
    if (relative) {
      date = key(addDays(now, /day after/i.test(relative[0]) ? 2 : /tomorrow/i.test(relative[0]) ? 1 : 0));
      dateFound = true;
      if (/tonight/i.test(relative[0])) period = 'PM';
      remove(relative);
    }
    const iso = rest.match(/\b\d{4}-\d{2}-\d{2}\b/);
    if (iso) {
      date = fromKey(iso[0]) ? iso[0] : '';
      dateFound = true;
      if (!date) notes.push('The date was not valid. Please choose a date.');
      remove(iso);
    }
    const months = ['january','february','march','april','may','june','july','august','september','october','november','december'];
    const named = rest.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(\d{4}))?\b/i) || rest.match(/\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b/i);
    if (named) {
      const dayFirst = /^\d/.test(named[1]);
      const day = Number(named[dayFirst ? 1 : 2]);
      const month = months.findIndex(m => m.startsWith(named[dayFirst ? 2 : 1].toLowerCase().slice(0,3)));
      let year = Number(named[3] || now.getFullYear());
      let d = new Date(year, month, day);
      if (!named[3] && key(d) < key(now)) d = new Date(++year, month, day);
      date = d.getMonth() === month && d.getDate() === day ? key(d) : '';
      dateFound = true;
      if (!date) notes.push('Please choose a valid date.');
      remove(named);
    }
    const weekday = rest.match(/\b(?:(next|this)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i);
    if (weekday && !dateFound) {
      const day = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'].indexOf(weekday[2].toLowerCase());
      let offset = (day - now.getDay() + 7) % 7;
      if (weekday[1]?.toLowerCase() === 'next') {
        date = key(addDays(monday(now), 7 + ((day + 6) % 7)));
      } else {
        if (!offset) offset = 7;
        date = key(addDays(now, offset));
      }
      dateFound = true;
      remove(weekday);
    }
    const numericDate = rest.match(/\b\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?\b/);
    if (numericDate) {
      date = '';
      dateFound = true;
      notes.push('Please choose the date for this numeric date format.');
      remove(numericDate);
    }
    const durationMatch = rest.match(/\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b/i);
    if (durationMatch) {
      duration = Number(durationMatch[1]) * (/^h/i.test(durationMatch[2]) ? 60 : 1);
      remove(durationMatch);
    }
    const time = rest.match(/\b(?:at\s+)(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b/i) || rest.match(/\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b/i) || rest.match(/\b(\d{1,2}):(\d{2})\b/);
    if (time) {
      const raw = Number(time[1]);
      minute = Number(time[2] || 0);
      if (raw <= 23 && minute < 60 && (!time[3] || (raw >= 1 && raw <= 12))) {
        hour = raw % 12 || 12;
        if (time[3]) period = time[3].replace(/\./g, '').toUpperCase();
        else if (raw > 12 || raw === 0) period = raw >= 12 ? 'PM' : 'AM';
      } else { hour = ''; minute = 0; notes.push('Please choose a valid time.'); }
      remove(time);
    } else {
      const noon = rest.match(/\b(?:at\s+)?(noon|midnight)\b/i);
      if (noon) { hour = 12; period = /noon/i.test(noon[1]) ? 'PM' : 'AM'; remove(noon); }
    }
    const partOfDay = rest.match(/\b(?:in the\s+)?(morning|afternoon|evening|night)\b/i);
    if (partOfDay) { if (!period) period = /morning/i.test(partOfDay[1]) ? 'AM' : 'PM'; remove(partOfDay); }
    if (/\b(every|daily|weekly|repeat|until|to\s+\d|next month|next week|in\s+\d+\s+days?)\b/i.test(rest)) {
      notes.push('Some timing or repeat details need manual review. This will create one event; use Schedule tools for recurring blocks.');
      if (!dateFound) date = '';
    } else if (!dateFound) notes.push('No date mentioned; the selected calendar date is filled in.');
    rest = rest.replace(/^(?:please\s+)?(?:remind me to|remind me about|i have|i've got|add|schedule|create)\s+/i, '').replace(/^(?:an?|my)\s+/i, '').replace(/\b(?:on|at|for)\s*$/i, '').replace(/\s+/g, ' ').replace(/^[\s,.-]+|[\s,.-]+$/g, '');
    return {label: rest ? rest[0].toUpperCase() + rest.slice(1) : '', date, hour, minute, period, duration, notes};
  }

  function quickPayload(values) {
    if (!fromKey(values.date)) throw new Error('Choose a valid date.');
    const hour = Number(values.hour), minute = Number(values.minute), duration = Number(values.duration);
    if (!Number.isInteger(hour) || hour < 1 || hour > 12 || values.minute === '' || !Number.isInteger(minute) || minute < 0 || minute > 59) throw new Error('Choose an hour from 1 to 12 and a minute from 0 to 59.');
    if (!['AM','PM'].includes(values.period)) throw new Error('Choose AM or PM.');
    if (!Number.isInteger(duration) || duration < 1 || duration > 1440) throw new Error('Enter a duration in minutes.');
    const start = (hour % 12 + (values.period === 'PM' ? 12 : 0)) * 60 + minute;
    if (start + duration > 1440) throw new Error('This event crosses midnight. Add separate blocks for each date using Schedule tools.');
    const label = values.label.trim();
    if (!label) throw new Error('Give your event a name.');
    const format = n => `${pad(Math.floor(n / 60))}:${pad(n % 60)}`;
    return {date: values.date, start: format(start), end: format(start + duration), label, color: '#397969', repeatDays: []};
  }
  const api = {key, fromKey, addDays, monday, datesForView, moveDate, parseQuickEntry, quickPayload};
  root.CalendarCore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
