#!/usr/bin/env python3
"""
Synthetic data generator for the Meridian Cycle Co. reference lakehouse.

Meridian Cycle Co. is a FICTIONAL, multi-location bicycle retail and service
business. Every row produced here is fake and generated deterministically from
a fixed random seed, so a clean clone always reproduces the same warehouse.

It emits four CSV "source system" extracts into data/raw/ :

  pos_orders.csv    - point-of-sale retail transactions
  workshop_jobs.csv - service / repair work orders
  ad_spend.csv      - marketing spend by channel, store, and day
  crm_leads.csv     - inbound leads with source channel and outcome

These four files stand in for four independent operational systems that a
finance-data platform has to reconcile into one trustworthy picture.
"""

import csv
import os
import random
from datetime import date, datetime, timedelta

SEED = 42
START = date(2024, 1, 1)
DAYS = 730  # two years of daily history
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")

STORES = {
    1: "Riverside",
    2: "Highland Park",
    3: "Oakmont",
    4: "Lakeside",
}

# Conformed marketing channels. Some carry paid media, some do not; the
# contrast is what makes "burdened cost per sale" interesting.
PAID_CHANNELS = ["paid_search", "paid_social", "email"]
FREE_CHANNELS = ["organic_search", "referral", "walk_in"]
ALL_CHANNELS = PAID_CHANNELS + FREE_CHANNELS

# How channels are *written* by each messy upstream system. Silver conforms
# these back to the canonical names above.
CHANNEL_ALIASES = {
    "paid_search": ["Paid Search", "paid-search", "PPC", "google_ads"],
    "paid_social": ["Paid Social", "paid-social", "Meta", "social_paid"],
    "email": ["Email", "email_blast", "newsletter"],
    "organic_search": ["Organic Search", "organic", "SEO"],
    "referral": ["Referral", "word_of_mouth", "ref"],
    "walk_in": ["Walk-in", "walk in", "walkin", "WALK_IN"],
}

# Relative share of demand by channel (unnormalized weights).
CHANNEL_WEIGHT = {
    "paid_search": 0.22,
    "paid_social": 0.16,
    "email": 0.10,
    "organic_search": 0.20,
    "referral": 0.14,
    "walk_in": 0.18,
}

rng = random.Random(SEED)


def messy_channel(canonical: str) -> str:
    """Return a realistically-inconsistent spelling of a channel."""
    return rng.choice(CHANNEL_ALIASES[canonical])


def seasonality(d: date) -> float:
    """Spring/summer cycling peak, winter trough, plus mild year-2 growth."""
    import math

    day_of_year = d.timetuple().tm_yday
    season = 1.0 + 0.35 * math.sin((day_of_year - 80) / 365.0 * 2 * math.pi)
    growth = 1.0 + 0.12 * ((d - START).days / DAYS)
    return season * growth


def pick_channel() -> str:
    channels = list(CHANNEL_WEIGHT.keys())
    weights = [CHANNEL_WEIGHT[c] for c in channels]
    return rng.choices(channels, weights=weights, k=1)[0]


def ts(d: date) -> str:
    return datetime(d.year, d.month, d.day, rng.randint(8, 19), rng.randint(0, 59)).isoformat(sep=" ")


def main() -> None:
    os.makedirs(RAW_DIR, exist_ok=True)

    pos_rows = []
    workshop_rows = []
    lead_rows = []
    adspend_rows = []

    order_seq = 100000
    job_seq = 500000
    lead_seq = 900000
    customer_pool = 6000

    for day_offset in range(DAYS):
        d = START + timedelta(days=day_offset)
        s = seasonality(d)
        weekday_boost = 1.25 if d.weekday() >= 5 else 1.0

        # ---- point-of-sale retail orders ----
        n_orders = max(0, int(rng.gauss(9 * s * weekday_boost, 3)))
        for _ in range(n_orders):
            order_seq += 1
            store_id = rng.choice(list(STORES))
            channel = pick_channel()
            gross = round(rng.choice([45, 85, 120, 350, 650, 1200, 2400]) * rng.uniform(0.85, 1.2), 2)
            discount = round(gross * rng.choice([0, 0, 0, 0.05, 0.1, 0.15]), 2)
            cogs = round((gross - discount) * rng.uniform(0.52, 0.68), 2)
            pos_rows.append(
                [
                    f"ORD-{order_seq}",
                    ts(d),
                    store_id,
                    messy_channel(channel),
                    f"CUST-{rng.randint(1, customer_pool)}",
                    f"{gross:.2f}",
                    f"{discount:.2f}",
                    f"{cogs:.2f}",
                ]
            )

        # ---- workshop service jobs ----
        n_jobs = max(0, int(rng.gauss(4 * s, 1.6)))
        for _ in range(n_jobs):
            job_seq += 1
            store_id = rng.choice(list(STORES))
            channel = pick_channel()
            labor_hours = round(rng.choice([0.5, 1.0, 1.5, 2.0, 3.0, 4.0]) * rng.uniform(0.9, 1.1), 2)
            labor_rate = rng.choice([75, 85, 95])  # rate billed to the customer
            parts_cost = round(rng.choice([0, 15, 40, 90, 160]) * rng.uniform(0.8, 1.2), 2)
            invoice = round(labor_hours * labor_rate + parts_cost * 1.4, 2)
            status = rng.choices(["completed", "completed", "completed", "cancelled"], k=1)[0]
            completed = ts(d + timedelta(days=rng.randint(0, 3))) if status == "completed" else ""
            workshop_rows.append(
                [
                    f"JOB-{job_seq}",
                    ts(d),
                    completed,
                    store_id,
                    messy_channel(channel),
                    f"CUST-{rng.randint(1, customer_pool)}",
                    f"{labor_hours:.2f}",
                    labor_rate,
                    f"{parts_cost:.2f}",
                    f"{invoice:.2f}",
                    status,
                ]
            )

        # ---- marketing spend (paid channels only) ----
        for channel in PAID_CHANNELS:
            for store_id in STORES:
                if rng.random() < 0.15:
                    continue  # some store/day/channel combos have no spend
                base = {"paid_search": 65, "paid_social": 48, "email": 12}[channel]
                spend = round(base * s * rng.uniform(0.7, 1.3), 2)
                impressions = int(spend * rng.uniform(80, 160))
                clicks = int(impressions * rng.uniform(0.02, 0.06))
                adspend_rows.append(
                    [
                        d.isoformat(),
                        store_id,
                        messy_channel(channel),
                        f"{spend:.2f}",
                        impressions,
                        clicks,
                    ]
                )

        # ---- inbound CRM leads ----
        n_leads = max(0, int(rng.gauss(6 * s, 2)))
        for _ in range(n_leads):
            lead_seq += 1
            store_id = rng.choice(list(STORES))
            channel = pick_channel()
            won = rng.random() < {
                "paid_search": 0.34,
                "paid_social": 0.22,
                "email": 0.40,
                "organic_search": 0.30,
                "referral": 0.46,
                "walk_in": 0.55,
            }[channel]
            status = "won" if won else rng.choice(["new", "contacted", "lost", "lost"])
            converted = f"ORD-{rng.randint(100001, order_seq)}" if won else ""
            lead_rows.append(
                [
                    f"LEAD-{lead_seq}",
                    ts(d),
                    store_id,
                    messy_channel(channel),
                    status,
                    converted,
                ]
            )

    _write("pos_orders.csv", ["order_id", "order_ts", "store_id", "channel", "customer_id", "gross_amount", "discount_amount", "cogs"], pos_rows)
    _write("workshop_jobs.csv", ["job_id", "created_ts", "completed_ts", "store_id", "channel", "customer_id", "labor_hours", "labor_rate", "parts_cost", "invoice_amount", "status"], workshop_rows)
    _write("ad_spend.csv", ["spend_date", "store_id", "channel", "spend", "impressions", "clicks"], adspend_rows)
    _write("crm_leads.csv", ["lead_id", "created_ts", "store_id", "channel", "status", "converted_sale_id"], lead_rows)

    print("Synthetic source extracts written to", RAW_DIR)
    print(f"  pos_orders.csv     {len(pos_rows):>7,} rows")
    print(f"  workshop_jobs.csv  {len(workshop_rows):>7,} rows")
    print(f"  ad_spend.csv       {len(adspend_rows):>7,} rows")
    print(f"  crm_leads.csv      {len(lead_rows):>7,} rows")


def _write(name: str, header, rows) -> None:
    path = os.path.join(RAW_DIR, name)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    main()
