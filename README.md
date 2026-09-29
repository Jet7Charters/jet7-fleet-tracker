# Jet7 fleet tracker

Hourly map and summary of the Jet7 fleet, using free live ADS-B data from the
OpenSky Network.

**Aircraft:** N936AM, N511AB, N577XW, N560PA, N560WV, N50XY, N156RE
(edit `TAILS` at the top of `tracker.py` to change the list; transponder codes are
worked out automatically).

## What it shows

- **In the air:** the live position, altitude and speed, and the track actually
  flown since takeoff, with the departure airport.
- **On the ground and transmitting:** the live position, labelled with the nearest
  airport.
- **Not transmitting** (parked with avionics off, or out of receiver range): the
  last place the tracker saw it and when. It remembers this between runs.

OpenSky doesn't carry flight plans, so destinations aren't shown.

Every hour, the map page is rebuilt and the same summary goes out by email and text.

## Setup

1. **OpenSky account (free):** Register at opensky-network.org. In your account
   page, create API client credentials and note the client ID and client secret.
   The tracker also works without an account, but with much tighter limits, and
   cloud servers like GitHub's are sometimes refused anonymous access.
2. **GitHub:** Create a free account and a new repository, then upload everything
   in this folder, including the hidden `.github` folder.
3. **Map page:** Go to Settings → Pages. Set Source to "Deploy from a branch,"
   choose `main`, then choose `/docs`. Copy the page URL. On GitHub's free plan,
   the repo must be public for this to work. No keys are stored in the code.
4. **Email (optional):** Use your mail provider's SMTP details. For Google
   Workspace, use `smtp.gmail.com`, port 587, and an app password.
5. **Text (optional):** Create a Twilio account and buy a number.
6. **Secrets:** Go to Settings → Secrets and variables → Actions and add:

| Secret | Value |
|---|---|
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | From OpenSky |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | Your mail server |
| `EMAIL_FROM`, `EMAIL_TO` | Sender and recipient |
| `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` | From Twilio |
| `SMS_TO` | Your mobile, as +1XXXXXXXXXX |
| `PAGE_URL` | The Pages URL from step 3 |
| `LOCAL_TZ` | Optional, e.g. `America/Chicago` (default is Eastern) |

   Any piece you leave out is simply skipped.
7. **Test:** Open the Actions tab, select "Jet7 fleet hourly update," and click
   "Run workflow." When it finishes, open the page URL. The first run takes a
   little longer because it downloads the airport list once.

## Checking accuracy

Compare against each aircraft's page on flightaware.com. Small differences are
normal because the page is a snapshot from the top of the hour.

## Good to know

- OpenSky's free service is intended for non-commercial use. Review their terms
  before relying on it long term.
- Coverage depends on volunteer receivers, so some areas, especially at low
  altitude near small airports, may have gaps.
- Tails in the FAA's LADD or PIA privacy programs may still appear here even when
  hidden on FlightAware.
- Airport data comes from OurAirports (public domain).
