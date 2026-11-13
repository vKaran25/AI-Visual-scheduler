# 0002: Category defaults instead of follow-up questions

- **Status:** accepted (2026-11-14)
- **Context:** "schedule 9 am review of project" produced a list of questions (length, date, dates, availability)
  or failed outright, because the model treated it as a flexible study plan. Students expect a calendar to fill in
  the obvious.

## Decision

- Fill details students rarely state, and **show every assumption on the draft**; nothing is saved until approval.
  - Event length comes from its category (`app/domain/categories.py`): meeting/review 1h, call 30 min, class 1h,
    lab 2h, exam 2h, study 1h, exercise 1h, meal 45 min, break 15 min, other 1h.
  - Named days come from a weekday-to-date table given to the model, so it never computes dates.
  - Plans need only the total study time. Missing dates become today to 6 days later, sessions are 1 hour,
    free time is 8 AM to 9 PM around existing events, and sessions are spread over separate days.
- Still asked: a clock time without AM/PM ("at 3"), a missing start time, which event to change, and genuinely
  unknown content (for example which subject).
- A request containing a clock time is treated as one event, even if the model labels it a plan, unless it
  clearly asks for a plan or an amount of study.

## Consequences

- Fewer questions and faster drafts; the student corrects assumptions by replying ("make it 30 minutes").
- Defaults are opinions; the table is easy to change and is covered by tests.
