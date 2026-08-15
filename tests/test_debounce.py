from scare_node.debounce import Cooldown


def test_first_call_is_always_ready():
    cooldown = Cooldown(10, clock=lambda: 0.0)
    assert cooldown.ready() is True


def test_second_call_too_soon_is_not_ready():
    times = iter([0.0, 1.0])
    cooldown = Cooldown(10, clock=lambda: next(times))
    assert cooldown.ready() is True
    assert cooldown.ready() is False


def test_call_after_cooldown_is_ready_again():
    times = iter([0.0, 15.0])
    cooldown = Cooldown(10, clock=lambda: next(times))
    assert cooldown.ready() is True
    assert cooldown.ready() is True
