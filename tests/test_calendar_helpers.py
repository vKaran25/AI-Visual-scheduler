"""Calendar navigation and quick entry run without external model calls."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_calendar_navigation_and_quick_entry():
    if not shutil.which("node"):
        pytest.skip("Node.js is required")
    result = subprocess.run(
        [
            "node",
            "-e",
            r"""
const assert = require('node:assert/strict');
const c = require('./frontend/assets/js/calendar-core.js');
const now = new Date(2026,9,13,15,30);
const selected = new Date(2026,10,1);
const month = c.datesForView(new Date(2026,1,15),'month');
assert.equal(month.length,42);
assert.equal(month[0].getDay(),1);
assert.equal(c.key(month[0]),'2026-01-26');
assert.equal(c.key(month[41]),'2026-03-08');
assert.equal(c.key(c.moveDate(new Date(2024,0,31),'month',1)),'2024-02-29');
assert.equal(c.key(c.moveDate(new Date(2026,11,31),'month',1)),'2027-01-31');
assert.equal(c.key(c.moveDate(new Date(2026,9,13),'week',-1)),'2026-10-06');
assert.equal(c.fromKey('2026-02-30'),null);
const draft = c.parseQuickEntry('i have a meeting at 8 tomroow',now,selected);
assert.equal(draft.label,'Meeting');
assert.equal(draft.date,'2026-10-14');
assert.equal(draft.hour,8);
assert.equal(draft.period,'');
assert.equal(draft.duration,'');
assert.throws(()=>c.quickPayload(draft),/AM or PM/);
assert.throws(()=>c.quickPayload({...draft,period:'PM'}),/duration/);
const payload = c.quickPayload({...draft,period:'PM',duration:'45'});
assert.equal(payload.start,'20:00'); assert.equal(payload.end,'20:45');
const explicit = c.parseQuickEntry('Lunch tomorrow at 12 pm for 1.5 hours',now,selected);
assert.equal(explicit.period,'PM'); assert.equal(explicit.duration,90); assert.equal(explicit.label,'Lunch');
assert.equal(c.quickPayload(explicit).start,'12:00');
assert.equal(c.parseQuickEntry('Call at 20:15 on Friday',now,selected).date,'2026-10-16');
assert.equal(c.parseQuickEntry('Call next Monday at 8',now,selected).date,'2026-10-19');
assert.equal(c.parseQuickEntry('Call on 21 October at 10 am',now,selected).date,'2026-10-21');
assert.equal(c.parseQuickEntry('Call October 21, 2026 at 10 am',now,selected).date,'2026-10-21');
assert.equal(c.parseQuickEntry('Call on 10/11 at 8',now,selected).date,'');
assert.equal(c.parseQuickEntry('Call on 2026-02-30 at 8',now,selected).date,'');
assert.equal(c.parseQuickEntry('Call at 8',now,selected).date,'2026-11-01');
assert.equal(c.parseQuickEntry('Call in 3 days at 8',now,selected).date,'');
assert.equal(c.parseQuickEntry('Call at 25:00',now,selected).hour,'');
assert.equal(c.parseQuickEntry('Call at midnight',now,selected).period,'AM');
assert.throws(()=>c.quickPayload({...draft,hour:11,period:'PM',duration:90}),/midnight/);
assert.equal(c.quickPayload({...draft,hour:11,period:'PM',duration:60}).end,'24:00');
assert.throws(()=>c.quickPayload({...draft,period:'AM',duration:30,date:'2026-02-30'}),/date/);
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
