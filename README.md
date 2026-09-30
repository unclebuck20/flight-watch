# Flight Watch

Tells us when to buy our flights. Once a day a GitHub Action checks Google Flights prices (via SerpApi) for every saved trip, logs them, and marks each trip **BUY** or **WAIT**. When a trip flips to BUY, we get a text.

**Page:** https://unclebuck20.github.io/flight-watch/

## Add a trip
Page → **+ Add trip** (or Issues → New → Add trip). Fill in the form and submit. The trip is checked within about a minute and the issue closes itself. Only the repo owner and collaborators can add trips.

## How the verdict works (`scripts/config.py` holds the numbers)
The tracked price is the Alaska fare on companion-fare trips, otherwise the cheapest fare. It's **BUY** when any of these is true:
1. Departure is 14 days or less away.
2. A book-by deadline is 10 days or less away.
3. The price is below Google's typical range, or Google calls it "low".
4. With 7+ price points, the price is within 3% of the lowest seen.

Otherwise **WAIT**, with the reason. This is a set of rules, not a forecast.

## Money math
Companion trips: Alaska fare + $122 (the $99 companion fare plus taxes). Others: 2 × the cheapest fare.

## Secrets (Settings → Secrets and variables → Actions)
| Name | What |
|---|---|
| `SERPAPI_KEY` | Required. SerpApi private key. |
| `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` | Text alerts (Twilio). |
| `ALERT_TO` | Phone numbers, comma-separated, e.g. `+12065551234,+12065555678`. |
| `NTFY_TOPIC` | Optional free push alerts via the ntfy app, until texting is approved. |

## Quota
One search per trip per day, plus 6 per trip each Monday for the nearby-dates grid. SerpApi's free plan (250/month) covers about 5–6 trips.

## Files
- `scripts/check.py`: daily check, verdict, alerts; writes `docs/data.json`
- `scripts/add_trip.py`: turns an Add-trip issue into a row in `data/trips.json`
- `scripts/config.py`: the rule thresholds
- `data/trips.json`: saved trips (set `active` to false to stop watching one)
- `data/prices.json`: our price log; `data/raw/` holds the latest raw response per trip
- `docs/index.html`: the page
