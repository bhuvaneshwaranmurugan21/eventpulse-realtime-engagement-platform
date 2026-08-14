from eventpulse.simulator import simulate


def test_simulation_is_deterministic() -> None:
    assert simulate() == simulate()
    evidence = simulate()
    assert evidence["result"] == "PASS"
    assert evidence["metrics"]["checks_total"] == evidence["metrics"]["checks_passed"]
    assert evidence["production_claim"] is False

