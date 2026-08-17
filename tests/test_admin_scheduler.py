from admin.app.scheduler import should_be_sleeping


def test_should_be_sleeping_within_window_is_awake():
    assert should_be_sleeping("19:00", "18:00", "22:00") is False


def test_should_be_sleeping_before_window_is_asleep():
    assert should_be_sleeping("10:00", "18:00", "22:00") is True


def test_should_be_sleeping_after_window_is_asleep():
    assert should_be_sleeping("23:00", "18:00", "22:00") is True


def test_should_be_sleeping_at_exact_on_time_is_awake():
    assert should_be_sleeping("18:00", "18:00", "22:00") is False


def test_should_be_sleeping_at_exact_off_time_is_asleep():
    assert should_be_sleeping("22:00", "18:00", "22:00") is True


def test_should_be_sleeping_handles_overnight_window():
    # bijv. aan om 22:00, uit om 02:00 (loopt over middernacht)
    assert should_be_sleeping("23:30", "22:00", "02:00") is False
    assert should_be_sleeping("03:00", "22:00", "02:00") is True
