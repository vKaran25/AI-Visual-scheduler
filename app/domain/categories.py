"""Typical lengths for common student events, so simple requests need no follow-up questions.

The assistant shows every assumption in the draft, and nothing is saved until the student approves,
so a sensible default is better than another question.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    name: str
    minutes: int
    color: str


# Checked in order; the first category with a matching keyword wins.
CATEGORIES = [
    Category("Exam", 120, "#d81b60"),
    Category("Lab", 120, "#7c6aff"),
    Category("Class", 60, "#0277bd"),
    Category("Study", 60, "#2e7d32"),
    Category("Standup", 15, "#e65100"),
    Category("Call", 30, "#e65100"),
    Category("Meeting", 60, "#e65100"),
    Category("Exercise", 60, "#00695c"),
    Category("Meal", 45, "#546e7a"),
    Category("Break", 15, "#546e7a"),
    Category("Appointment", 60, "#37474f"),
]
KEYWORDS = {
    "Exam": "exam|midterm|final exam|test|viva",
    "Lab": "lab|practical",
    "Class": "class|lecture|tutorial|seminar|course|lesson",
    "Study": "study|revise|revision|homework|assignment|practice|reading|read|prep|prepare|notes|project work",
    "Standup": "standup|stand-up|check-in|check in",
    "Call": "call|phone|ring",
    "Meeting": "meeting|meet|review|discussion|sync|interview|presentation|group|team|mentor|office hours",
    "Exercise": "gym|workout|run|running|jog|yoga|sport|football|cricket|swim|walk",
    "Meal": "breakfast|lunch|dinner|meal|coffee|brunch",
    "Break": "break|rest|nap",
    "Appointment": "doctor|dentist|appointment|bank|errand|shopping|haircut",
}
DEFAULT = Category("Event", 60, "#397969")


def classify(text: str) -> Category:
    lowered = (text or "").lower()
    for category in CATEGORIES:
        if re.search(rf"\b(?:{KEYWORDS[category.name]})\b", lowered):
            return category
    return DEFAULT


def prompt_table() -> dict[str, int]:
    """Category -> default minutes, given to the model as context."""
    return {category.name.lower(): category.minutes for category in CATEGORIES} | {"other": DEFAULT.minutes}


def plus_minutes(clock: str, minutes: int) -> str:
    """'HH:MM' + minutes, capped at the end of the day (events cannot cross midnight)."""
    hour, minute = map(int, clock.split(":"))
    total = min(hour * 60 + minute + minutes, 24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"
