"""NPI check digit.

An NPI is 9 digits plus a Luhn check digit. The Luhn sum is computed as if the
number had the prefix 80840 in front (the ISO card-issuer prefix for US health),
which is why plain Luhn on the 10 digits alone gives the wrong answer.
"""

NPI_PREFIX = "80840"


def luhn_check_digit(payload: str) -> int:
    """Check digit that makes payload + digit pass Luhn."""
    total = 0
    # Walk right to left. The digit next to where the check digit will go gets doubled,
    # then every other one after that.
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def npi_check_digit(first_nine: str) -> int:
    return luhn_check_digit(NPI_PREFIX + first_nine)


def is_valid_npi(npi: str | None) -> bool:
    if not npi or len(npi) != 10 or not npi.isdigit():
        return False
    return npi_check_digit(npi[:9]) == int(npi[9])
