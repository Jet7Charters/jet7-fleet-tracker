"""Convert US N-numbers to ICAO24 (Mode S) hex codes.

US registrations map deterministically onto A00001-ADF7C7, so no lookup is needed.
"""

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O
DIGITS = "0123456789"
SUFFIX_SIZE = 1 + len(LETTERS) * (1 + len(LETTERS))   # 601
BUCKET4 = 1 + len(LETTERS) + len(DIGITS)               # 35
BUCKET3 = len(DIGITS) * BUCKET4 + SUFFIX_SIZE          # 951
BUCKET2 = len(DIGITS) * BUCKET3 + SUFFIX_SIZE          # 10111
BUCKET1 = len(DIGITS) * BUCKET2 + SUFFIX_SIZE          # 101711


def _suffix_offset(s):
    if not s:
        return 0
    if len(s) > 2 or any(c not in LETTERS for c in s):
        raise ValueError(f"bad letter suffix: {s}")
    off = LETTERS.index(s[0]) * (len(LETTERS) + 1) + 1
    if len(s) == 2:
        off += LETTERS.index(s[1]) + 1
    return off


def n_to_icao24(tail):
    t = tail.upper().strip()
    if t.startswith("N"):
        t = t[1:]
    if not t or t[0] not in "123456789" or len(t) > 5:
        raise ValueError(f"not a valid US N-number: {tail}")
    out = 0xA00001 + (int(t[0]) - 1) * BUCKET1
    rest = t[1:]
    for bucket in (BUCKET2, BUCKET3, BUCKET4):
        if not rest:
            return f"{out:06x}"
        c = rest[0]
        if c in LETTERS:
            return f"{out + _suffix_offset(rest):06x}"
        out += SUFFIX_SIZE + int(c) * bucket
        rest = rest[1:]
    if rest:
        if len(rest) > 1:
            raise ValueError(f"not a valid US N-number: {tail}")
        c = rest[0]
        out += 1 + LETTERS.index(c) if c in LETTERS else 1 + len(LETTERS) + int(c)
    return f"{out:06x}"
