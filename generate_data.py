import csv, math, os, random
from datetime import date, timedelta

rng = random.Random(42)
RAW, POL = os.path.join("data", "raw"), os.path.join("data", "policies")
os.makedirs(RAW, exist_ok=True); os.makedirs(POL, exist_ok=True)

SNAP = date(2026, 3, 31)                      # observation window ends here; churn is measured in April 2026
PLANS = [("P01", "Basic Lite", 199, 0, 80), ("P02", "Basic", 299, 0, 140), ("P03", "Standard", 449, 0, 220),
         ("P04", "Standard HD", 599, 1, 260), ("P05", "Premium", 799, 1, 320), ("P06", "Premium Plus", 999, 1, 380)]
PRICE = {p[0]: p[2] for p in PLANS}
CITIES = ["Chennai", "Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Pune", "Kolkata"]
CITY_ALT = {"Chennai": ["chennai", "Madras"], "Mumbai": ["mumbai", "Bombay"], "Bengaluru": ["bengaluru", "Bangalore", "BENGALURU "],
            "Delhi": ["delhi", "New Delhi"], "Hyderabad": ["hyderabad", "Hyd"], "Pune": ["pune", "PUNE"],
            "Kolkata": ["kolkata", "Calcutta"]}
ARCH = {  # weight, plan weights P01..P06, tenure range, weekly hours (mean, sd), max add-on packs
    "binge":  (0.20, [0, 0, 0.05, 0.15, 0.45, 0.35], (12, 60), (34, 5), 3),
    "family": (0.33, [0.03, 0.10, 0.45, 0.30, 0.10, 0.02], (6, 48), (21, 4), 2),
    "budget": (0.28, [0.35, 0.50, 0.12, 0.03, 0, 0], (3, 40), (7, 2), 1),
    "newbie": (0.19, [0.10, 0.25, 0.30, 0.20, 0.10, 0.05], (0, 6), (13, 3), 1),
}
N = 2400

def clip(x, lo, hi):
    return max(lo, min(hi, x))

# ---------------------------------------------------------------- plans
with open(os.path.join(RAW, "plans.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["plan_id", "plan_name", "monthly_price_inr", "hd_included", "channel_count"])
    w.writerows(PLANS)

# ---------------------------------------------------------------- subscribers + recharges
subs, rech, rid = [], [], 0
for i in range(1, N + 1):
    sid = f"TP{i:05d}"
    a = rng.choices(list(ARCH), weights=[v[0] for v in ARCH.values()])[0]
    _, pw, (t0, t1), (hmu, hsd), addmax = ARCH[a]
    plan = rng.choices([p[0] for p in PLANS], weights=pw)[0]
    tenure = rng.randint(t0, t1)
    city = rng.choices(CITIES, weights=[16, 20, 18, 17, 12, 10, 7])[0]
    age = int(clip(round(rng.gauss(38, 11)), 18, 70))
    hours = round(clip(rng.gauss(hmu, hsd), 2, 60), 1)
    hd = round(clip(0.70 * hours + rng.gauss(0, 1.6), 0, 60), 1)
    sports = round(clip(0.45 * hours + rng.gauss(0, 1.6), 0, 40), 1)
    channels = int(clip(round(0.38 * hours + rng.gauss(0, 1.5)), 3, 30))
    addons = rng.randint(0, addmax)
    monthly = PRICE[plan] + 49 * addons
    pay = rng.choices(["UPI", "Card", "NetBanking", "Cash"], weights=[50, 20, 10, 20])[0]
    auto = "Yes" if rng.random() < {"UPI": 0.55, "Card": 0.70, "NetBanking": 0.50, "Cash": 0.0}[pay] else "No"
    calls = rng.choices([0, 1, 2, 3, 4, 5, 6], weights=[30, 25, 18, 12, 8, 5, 2])[0]
    pf = clip(0.04 + 0.04 * calls, 0, 0.45)             # chance that a recharge attempt fails
    cycles = min(6, tenure)                              # monthly cycles Oct 2025 .. Mar 2026 that exist for this subscriber
    anchor = rng.randint(1, 26)
    nfail, last_succ = 0, None
    for c in range(cycles):
        m = 3 - (cycles - 1 - c)
        y, mo = (2026, m) if m >= 1 else (2025, m + 12)
        d = date(y, mo, clip(anchor + rng.randint(-2, 2), 1, 28))
        r = rng.random()
        st = "failed" if r < pf else ("pending" if r < pf + 0.01 else "success")
        if st == "failed": nfail += 1
        if st == "success": last_succ = d
        rid += 1
        amt = f"INR {monthly}" if rng.random() < 0.03 else str(monthly)     # a few amounts arrive as text
        stv = {"success": rng.choice(["success", "success", "success", "SUCCESS", "Success"]),
               "failed": rng.choice(["failed", "failed", "FAILED"]), "pending": "pending"}[st]
        rech.append([f"R{rid:06d}", sid, d.isoformat(), amt, stv, rng.choice(["app", "app", "web", "retail"])])
    recency = (SNAP - last_succ).days if last_succ else None
    z = (-2.2 + 0.40 * calls + 1.00 * (auto == "No") + 0.60 * (pay == "Cash") - 0.085 * min(tenure, 24)
         + 0.70 * nfail + 0.022 * (recency if recency is not None else 40) - 0.040 * hours
         + 1.2 * (calls >= 4 and auto == "No"))
    churned = 1 if rng.random() < 1 / (1 + math.exp(-z)) else 0
    nxt = "" if churned else round(monthly + 4 * hd + 5 * sports + rng.gauss(0, 25), 2)   # known only after the next cycle
    closure = "Yes" if rng.random() < (0.96 if churned else 0.02) else "No"             # logged while a subscriber is leaving
    # ---- raw-data mess
    cv = city if rng.random() < 0.62 else rng.choice(CITY_ALT[city])
    av = auto if rng.random() < 0.7 else {"Yes": rng.choice(["Y", "yes"]), "No": rng.choice(["N", "no"])}[auto]
    agev = "" if rng.random() < 0.04 else age
    payv = "" if rng.random() < 0.05 else pay
    subs.append([sid, cv, plan, tenure, agev, payv, av, addons, monthly, hours, hd, sports, channels, calls, closure, nxt, churned])

for k in rng.sample(range(len(subs)), 6):                # impossible ages
    subs[k][4] = rng.choice([0, -1, 150, 999, 0, 150])
dups = [list(subs[k]) for k in rng.sample(range(len(subs)), 15)]     # exact duplicate subscriber rows
subs = subs + dups
rng.shuffle(subs)
with open(os.path.join(RAW, "subscribers.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["subscriber_id", "city", "plan_id", "tenure_months", "age", "payment_mode", "auto_renew", "add_on_count",
                "monthly_recharge_inr", "hours_watched_per_week", "hd_hours_per_week", "sports_hours_per_week",
                "channels_watched", "support_calls_90d", "closure_request_logged", "next_cycle_recharge_inr", "churned"])
    w.writerows(subs)

for k in range(10):                                      # recharge rows that belong to no subscriber
    rid += 1
    rech.append([f"R{rid:06d}", f"TP{9000 + k:05d}", (SNAP - timedelta(days=rng.randint(5, 150))).isoformat(), "499", "success", "app"])
rech += [list(rech[k]) for k in rng.sample(range(len(rech)), 60)]     # exact duplicate recharge rows
rng.shuffle(rech)
with open(os.path.join(RAW, "recharges.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["recharge_id", "subscriber_id", "recharge_date", "amount_inr", "status", "channel"])
    w.writerows(rech)

# ---------------------------------------------------------------- tickets
SUBJ = {
    "billing": ["My recharge of INR {amt} failed but the money was deducted from my {pay}.",
                "I was charged twice for the {mon} recharge, please return the extra amount.",
                "The bill shows an extra add-on pack that I never asked for.",
                "Payment was made yesterday but the subscription is still off.",
                "Auto renew took money from my account but the connection is not active."],
    "signal": ["The picture keeps freezing on every channel since this morning.",
               "There is no signal on my set top box after the rain.",
               "Channels show pixelation every evening and this is the third time I am calling.",
               "Set top box shows error E{n} and nothing plays.",
               "Sound is fine but the screen goes black on sports channels."],
    "plan_change": ["I want to upgrade to the {plan} plan from my next cycle.",
                    "Please remove the add-on pack, I do not use it.",
                    "How can I switch to a cheaper plan?",
                    "Can I get HD channels on my current pack?",
                    "Please add a regional language pack to my plan."],
    "cancellation": ["I want to close my connection from next month.",
                     "Please cancel my subscription, I am shifting abroad.",
                     "I am closing the account because the price is too high.",
                     "I am planning to stop the service, what is the process?",
                     "Kindly disconnect my set top box permanently."],
}
MIXED = {  # real intent first, a second topic mentioned in passing
    "cancellation": "I want to cancel my subscription because the picture keeps freezing.",
    "plan_change": "My last recharge went through fine, now I want to move to the {plan} plan.",
    "billing": "The picture is fine but I was charged twice this month and want a refund.",
    "signal": "I do not want to cancel, but there is no signal since last night.",
}
MONTHS = ["January", "February", "March"]
EXAMPLES = [("billing", "Money was debited for my recharge but the balance did not update."),
            ("billing", "I see two charges for one recharge and need a refund."),
            ("billing", "The bill has an extra add-on pack charge that I did not order."),
            ("billing", "Payment went through yesterday but the connection is still off."),
            ("signal", "The screen shows no signal and the box keeps restarting."),
            ("signal", "Pixelation and freezing on all channels in the evening."),
            ("signal", "The picture goes black on the sports channels."),
            ("plan_change", "I would like to upgrade my pack to the Premium plan."),
            ("plan_change", "Please remove the add-on pack from my plan next month."),
            ("plan_change", "Can I get the HD channels on my current plan?"),
            ("cancellation", "Please close my account, I am moving to another city."),
            ("cancellation", "I want to cancel the subscription and return the box."),
            ("cancellation", "Kindly stop the service and disconnect the connection.")]
tickets = []
for i in range(1, 151):
    cat = rng.choices(list(SUBJ), weights=[34, 28, 22, 16])[0]
    sid = f"TP{rng.randint(1, N):05d}"
    if rng.random() < 0.13:
        t = MIXED[cat]
    else:
        t = rng.choice(SUBJ[cat])
    t = t.format(amt=rng.choice([299, 449, 599, 799, 999]), pay=rng.choice(["UPI account", "card", "bank account"]),
                 mon=rng.choice(MONTHS), n=rng.randint(10, 99), plan=rng.choice(["Premium", "Standard HD", "Premium Plus"]))
    if rng.random() < 0.45:
        t = f"Subscriber ID {sid}. " + t
    if rng.random() < 0.25:
        t += rng.choice([" Please help.", " This is urgent.", " Need a fix immediately.", " Thanks."])
    tickets.append([f"T{i:04d}", sid, t, cat])
for k in (17, 58, 103, 140):                            # unreadable tickets
    tickets[k][2] = "..."
with open(os.path.join(RAW, "tickets.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["ticket_id", "subscriber_id", "text", "true_category"]); w.writerows(tickets)
with open(os.path.join(RAW, "few_shot_examples.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["text", "label"]); w.writerows([[t, c] for c, t in EXAMPLES])

# ---------------------------------------------------------------- policies
POLICIES = {
"recharge_and_refund_policy.txt": (
    "Recharge and Refund Policy. A recharge is marked successful only after the payment gateway confirms the debit and the "
    "subscription is extended. If the amount is debited but the recharge fails, the amount is returned to the original payment "
    "method within 5 working days. Refunds for cash recharges made at retail partners are paid to the subscriber's bank account "
    "after verification, within 10 working days. A recharge made on the wrong subscriber ID can be transferred to the correct ID "
    "only within 24 hours of the payment and only if the amount has not been used. Duplicate recharges for the same cycle are "
    "refunded in full within 7 working days after the subscriber reports them with the payment reference. Recharge amounts are "
    "not refunded once the cycle has started, except for service outages longer than 72 continuous hours, which are credited as "
    "free days. Auto-renew failures are retried automatically twice, 24 hours apart, before the subscription is suspended."),
"plan_change_policy.txt": (
    "Plan Change Policy. A subscriber may upgrade the plan at any time and the new plan starts immediately; the unused balance of "
    "the old plan is adjusted against the new price. A downgrade takes effect from the next billing cycle and can be requested "
    "only once in every 90 days. Add-on packs cost INR 49 per month each and can be added or removed at the start of a cycle. "
    "A subscriber can hold a maximum of 3 add-on packs at a time. Moving from a standard definition plan to an HD plan needs an "
    "HD-capable set top box; the box swap is free for Premium plans and costs INR 250 for all other plans. Plan changes requested "
    "after the 25th of the month are applied from the cycle after next. Regional language packs can be paused for up to 60 days "
    "once a year."),
"retention_offers_policy.txt": (
    "Retention Offers Policy. Retention offers are made only to subscribers whose churn risk band is High or who have requested "
    "closure. A High risk subscriber with a tenure of 12 months or more is eligible for a loyalty discount of 15 percent on the "
    "next three recharges. A High risk subscriber with a tenure below 12 months is eligible for a free add-on pack for 2 months. "
    "A High risk subscriber with 3 or more failed recharges in the last six months receives an auto-renew setup call and a 7 day "
    "grace extension instead of a discount. Only one retention offer can be active on a subscriber at a time, and an offer cannot be "
    "combined with a coupon. Offers are approved by the retention desk and must be logged with the subscriber ID, the offer type "
    "and the reason. A subscriber who accepted an offer in the last 180 days is not eligible for another one."),
"technical_support_policy.txt": (
    "Technical Support Policy. Signal loss and pixelation complaints are first handled by a remote refresh of the set top box, "
    "attempted within 2 hours of the call. If the problem continues, a technician visit is scheduled within 48 hours, or within "
    "24 hours for Premium and Premium Plus subscribers. The first technician visit in a cycle is free; each additional visit in "
    "the same cycle costs INR 150 unless the fault is on the company side. If a fault on the company side lasts longer than 72 "
    "hours, the subscriber is credited for the lost days. A replacement remote costs INR 120 and a replacement cable costs INR 90. "
    "Complaints about app or channel buffering are logged as app issues and answered within 1 working day."),
"cancellation_policy.txt": (
    "Cancellation Policy. A subscriber can request closure through the app, the call centre or a retail partner. Closure takes "
    "effect at the end of the current paid cycle and no refund is paid for the unused days. The retention desk shares any "
    "applicable offer once; the subscriber may decline and the closure then proceeds without further calls. A closed account can "
    "be reopened with the same subscriber ID within 90 days, after any pending balance is cleared. After 90 days the account is "
    "archived and a new connection with a new subscriber ID is needed. The set top box must be returned within 15 days of "
    "closure, otherwise a non-return charge of INR 1,000 applies."),
}
for name, text in POLICIES.items():
    with open(os.path.join(POL, name), "w") as f:
        f.write(text + "\n")

EVAL = [  # question, file that holds the answer, short fact the answer must contain ("" = not answered by any document)
    ("My top-up money was deducted but the recharge did not go through. When will I get it back?", "recharge_and_refund_policy.txt", "5 working days"),
    ("I paid cash at a shop and need my money returned. How long does that take?", "recharge_and_refund_policy.txt", "10 working days"),
    ("I topped up the wrong customer ID by mistake. Can the payment be moved?", "recharge_and_refund_policy.txt", "24 hours"),
    ("What happens if my automatic payment does not go through?", "recharge_and_refund_policy.txt", "twice"),
    ("Can I switch to a cheaper pack right away?", "plan_change_policy.txt", "next billing cycle"),
    ("How many extra channel packs can I keep at once?", "plan_change_policy.txt", "maximum of 3"),
    ("What does it cost to get an HD capable box if I am on a Standard plan?", "plan_change_policy.txt", "INR 250"),
    ("Which discount does a long-term subscriber who is likely to leave get?", "retention_offers_policy.txt", "15 percent"),
    ("Can a customer take two offers back to back?", "retention_offers_policy.txt", "180 days"),
    ("My picture keeps breaking up and freezing. What will the company do first?", "technical_support_policy.txt", "2 hours"),
    ("How soon does an engineer visit a Premium customer's home?", "technical_support_policy.txt", "24 hours"),
    ("What is the fee for not sending the set top box back after closing the account?", "cancellation_policy.txt", "INR 1,000"),
    ("Who won the cricket world cup final?", "", ""),
    ("Give me a recipe for paneer butter masala.", "", ""),
    ("Does the company offer a student discount?", "", ""),
    ("Is international roaming available on the mobile app?", "", ""),
]
with open(os.path.join(RAW, "policy_eval.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["question", "expected_file", "expected_fact"]); w.writerows(EVAL)

print(f"generated: subscribers={len(subs)} recharges_raw={len(rech)} tickets={len(tickets)} policy_files={len(POLICIES)}")
