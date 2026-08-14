# SportsDataIO pre-sale questions — DRAFT, NOT SENT

Status: **draft only**. No email has been sent by any automated session.
This exists so the repository owner can review, edit, and send it manually
through SportsDataIO's own sales channel — sending a commercial inquiry as
this repository is out of scope for an automated agent.

Purpose: resolve `SOURCE_REQUIRES_HUMAN_DECISION` for SportsDataIO against
the decision contract frozen in `docs/PAST_ATTEMPT_LEDGER.md`, for trial
`G1-F1-market-h2h-sportsdataio-diligence` (`data/trials.json`). Every
question is closed-ended (yes/no or a specific value) on purpose — the goal
is a verifiable answer, not a sales pitch.

Suggested recipient: SportsDataIO sales (see `sportsdata.io` contact page for
current address). Suggested subject: "Pre-sale technical questions — F1 race
head-to-head odds, historical".

---

Hello,

We're evaluating SportsDataIO as a licensed data source for a research
project analyzing historical Formula 1 head-to-head market odds. Before any
commercial discussion, we need factual yes/no answers to the following, since
our research protocol requires each item to be confirmed before a licence is
considered:

1. Does your **Odds API / Historical Odds** product (not the free F1 stats
   API) include Formula 1 as a covered sport? If yes, since when?
2. If F1 is covered, does it include a **race head-to-head** market
   specifically (odds on which of two named drivers finishes ahead), as
   distinct from race winner / podium / qualifying / sprint markets?
3. For that market, do you provide **both opening and closing prices**, each
   with a **distinct UTC timestamp**?
4. Are odds provided for **both sides** of each head-to-head pairing (both
   drivers), from an identified **bookmaker**?
5. Is a **market margin** (vig) either provided directly or computable from
   the data you export?
6. Do you publish a **versioned settlement rule** for this market — in
   particular, how a DNF, DNS, DSQ, cancelled race, or post-race result
   correction is settled?
7. What is the **historical date range** for F1 head-to-head odds, if
   covered, and how many distinct races/bookmakers does that represent?
8. What is the **export mechanism** (REST API, bulk file, warehouse query)
   and is it reproducible on demand — i.e., can we re-request the exact same
   historical batch later and get byte-identical results?
9. Does your standard research/commercial licence permit **storage for
   research purposes** and **publication of derived results** (not the raw
   odds themselves, but statistics computed from them)?
10. Is race and driver **identity** provided via stable IDs that can be
    cross-referenced to a third-party source (e.g., official F1 timing data
    or Jolpica/Ergast driver IDs), rather than free-text names only?
11. What is the indicative **price** for historical F1 head-to-head odds
    access, and is a small **sample export** available for technical
    validation before a full licence is signed?

We are not looking for marketing material — a direct "not covered" or "yes,
covered since <date>" answer to each item is exactly what we need to decide
whether to proceed.

Thank you,
[repository owner name]

---

## Internal note (not part of the email)

Answers should be recorded verbatim (with date and respondent) as a follow-up
to this file or as a new dated `docs/DILIGENCIA_ODDS_YYYY-MM-DD.md`, and cross-
referenced from `data/trials.json`'s `G1-F1-market-h2h-sportsdataio-diligence`
notes. A "yes" to items 1–2 does not by itself flip
`market_h2h_feasibility.json`'s SportsDataIO status to `SOURCE_ACCEPTED` — all
eleven items must be confirmed, and moving the status is a separate, explicit
human decision, same as every other step on this track.
