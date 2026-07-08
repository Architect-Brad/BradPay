"""Shared input validation used by both storage backends (models.py /
firestore_db.py) so security rules can't drift between them."""

WEAK_PINS = {
    "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888",
    "9999", "1234", "4321", "1212", "0123",
}


def validate_pin(pin):
    """Raise ValueError if the PIN is missing, non-numeric, too short, or a
    commonly guessed sequence. Returns the normalized PIN string otherwise."""
    if pin is None:
        raise ValueError("PIN is required")
    pin_str = str(pin)
    if not pin_str.isdigit():
        raise ValueError("PIN must contain only digits")
    if len(pin_str) < 4:
        raise ValueError("PIN must be at least 4 digits")
    if pin_str in WEAK_PINS:
        raise ValueError("PIN is too common, choose a less predictable PIN")
    return pin_str
