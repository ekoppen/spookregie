def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def current_tier(now, escalation_time):
    """None als er geen omslagtijd is ingesteld (= geen filtering op
    intensiteit, huidig gedrag). Anders 'subtle' vóór de omslagtijd,
    'full' erna."""
    if not escalation_time:
        return None
    return "full" if _to_minutes(now) >= _to_minutes(escalation_time) else "subtle"


def filter_by_tier(hashes, intensity_by_hash, tier):
    """Laat een hash door als hij geen intensiteit heeft (geldt altijd)
    of als zijn intensiteit overeenkomt met de huidige fase.
    tier=None (geen omslagtijd ingesteld) laat alles door."""
    if tier is None:
        return list(hashes)
    return [h for h in hashes if not intensity_by_hash.get(h) or intensity_by_hash.get(h) == tier]


def read_intensity_by_hash(db):
    return {row[0]: row[1] for row in db.execute("SELECT hash, intensity FROM media")}


def read_escalation_time(db):
    row = db.execute("SELECT scare_escalation_time FROM app_settings WHERE id = 1").fetchone()
    return row[0] if row is not None else ""
