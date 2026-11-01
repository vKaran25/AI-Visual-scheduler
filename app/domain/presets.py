"""Built-in calendar templates."""

BUILTIN_PRESETS = [
    {
        "id": "blank",
        "name": "Blank",
        "description": "Start with an empty schedule.",
        "blocks": [],
    },
    {
        "id": "student",
        "name": "Student",
        "description": "Classes, homework, and sleep blocks for a typical weekday student routine.",
        "blocks": [
            {
                "label": "Sleep",
                "start": "00:00",
                "end": "06:30",
                "repeatDays": [0, 1, 2, 3, 4, 5, 6],
                "color": "#4527a0",
            },
            {
                "label": "Classes",
                "start": "08:30",
                "end": "13:30",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#2e7d32",
            },
            {
                "label": "Homework",
                "start": "19:00",
                "end": "20:30",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#0277bd",
            },
        ],
    },
    {
        "id": "exam_prep",
        "name": "Exam Prep",
        "description": "Focused study blocks with review and rest time.",
        "blocks": [
            {
                "label": "Deep Study",
                "start": "09:00",
                "end": "11:00",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#7c6aff",
            },
            {
                "label": "Practice Problems",
                "start": "16:00",
                "end": "17:30",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#f9a825",
            },
            {
                "label": "Review",
                "start": "20:00",
                "end": "21:00",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#00695c",
            },
        ],
    },
    {
        "id": "working_professional",
        "name": "Working Professional",
        "description": "Workday structure with evening learning time.",
        "blocks": [
            {
                "label": "Work",
                "start": "09:00",
                "end": "17:00",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#37474f",
            },
            {
                "label": "Commute / Reset",
                "start": "17:30",
                "end": "18:30",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#e65100",
            },
            {
                "label": "Skill Building",
                "start": "20:00",
                "end": "21:00",
                "repeatDays": [1, 3],
                "color": "#7c6aff",
            },
        ],
    },
    {
        "id": "fitness_study",
        "name": "Fitness + Study",
        "description": "Balances exercise, study, and recovery.",
        "blocks": [
            {
                "label": "Workout",
                "start": "06:30",
                "end": "07:30",
                "repeatDays": [0, 2, 4],
                "color": "#d81b60",
            },
            {
                "label": "Study",
                "start": "19:00",
                "end": "20:30",
                "repeatDays": [0, 1, 2, 3, 4],
                "color": "#0277bd",
            },
            {
                "label": "Wind Down",
                "start": "22:00",
                "end": "22:30",
                "repeatDays": [0, 1, 2, 3, 4, 5, 6],
                "color": "#00695c",
            },
        ],
    },
]
