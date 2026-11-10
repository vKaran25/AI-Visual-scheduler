import pytest

from app.domain.ambiguity import missing_event_details


@pytest.mark.parametrize("hour", ["3", "three"])
def test_event_time_requires_period_even_with_spoken_duration(hour):
    request = f"Create Demo rehearsal on 2027-01-15 at {hour} for thirty minutes"
    assert missing_event_details(request, []) == ["AM or PM for the event time"]
    assert missing_event_details(request, ["Three PM"]) == []
