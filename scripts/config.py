"""The knobs. Change a rule here, not in check.py."""

# Alaska companion fare: $99 + taxes/fees from about $23.
COMPANION_COST = 122

# Airline names Google Flights uses for Alaska-operated flights.
ALASKA_NAMES = ("Alaska", "Horizon")

# BUY rules
LAST_MINUTE_DAYS = 14      # inside this many days of departure: BUY
DEADLINE_DAYS = 10         # inside this many days of a book-by date: BUY
BUY_NEAR_LOW = 0.03        # within 3% of the lowest price seen: BUY
MIN_OBS_FOR_LOW = 7        # need this many price points before trusting "lowest seen"

# Nearby-dates grid: shift both dates by these offsets. Refreshed weekly.
GRID_OFFSETS = (-3, -2, -1, 1, 2, 3)
GRID_WEEKDAY = 0           # Monday
