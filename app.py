import re
import streamlit as st
import feedparser
import pandas as pd
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

st.set_page_config(page_title="Crude & Natural Gas News", page_icon="🛢️", layout="wide")
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Free/public sources.  The engine deliberately separates market-impact news
# from generic energy headlines.  It is a decision-support screen, not a
# guaranteed trading system.
# -----------------------------------------------------------------------------
CRUDE_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "OilPrice": "https://oilprice.com/rss/main",
    "Rigzone": "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
}

NG_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "Rigzone": "https://www.rigzone.com/news/rss/naturalgas_latest.aspx",
}

SOURCE_WEIGHT = {
    "EIA": 1.40,
    "OPEC": 1.45,
    "IEA": 1.45,
    "Rigzone": 0.95,
    "OilPrice": 0.90,
}

CRUDE_TOPIC = [
    "crude oil", "crude", "brent", "wti", "opec", "petroleum", "refinery",
    "oil supply", "oil production", "oil exports", "oil inventory", "oil prices",
    "hormuz", "tanker", "saudi", "iran", "iraq", "russia", "venezuela",
]

NG_TOPIC = [
    "natural gas", "natgas", "lng", "henry hub", "gas storage", "gas production",
    "gas supply", "gas demand", "gas prices", "pipeline", "freeport", "sabine pass",
    "louisiana gas", "ercot", "hurricane", "weather",
]

# Rules are written as MARKET IMPACT, not generic sentiment.
# Each rule has a phrase, direction, impact points and an event group.
CRUDE_RULES = [
    (r"production (?:cut|cuts|cutback|reduction)|output (?:cut|cuts|reduction)", 2, "OPEC/supply cut", "supply"),
    (r"supply (?:disruption|disrupted|outage|shortage)|oil outage|export halt|exports (?:halt|stopped)", 3, "Supply disruption", "supply"),
    (r"strait of hormuz|hormuz (?:standoff|closure|blocked|attack)|tanker (?:attack|disruption)", 3, "Hormuz/shipping risk", "geopolitics"),
    (r"refinery (?:outage|shutdown|shut down)", 2, "Refinery outage", "refinery"),
    (r"crude (?:inventory|inventories).{0,30}(?:draw|fell|fall)|inventory draw|drawdown", 2, "Inventory draw", "inventory"),
    (r"demand (?:rises|rose|increase|increases|strong)|strong oil demand|china buying more oil", 1, "Demand strength", "demand"),
    (r"sanctions|iran.{0,40}(?:oil exports|oil production)|oil exports.{0,40}(?:iran|sanctions)", 1, "Sanctions/supply risk", "geopolitics"),
    (r"attack(?:s|ed)?.{0,40}(?:refiner|oil|pipeline|energy|facility)|oil.{0,30}attack", 2, "Energy infrastructure attack", "geopolitics"),
    (r"production (?:increase|increases|rises|rose)|output (?:increase|increases|rises|rose)", -2, "Production increase", "supply"),
    (r"supply (?:increase|increases|rises)|oversupply|supply glut", -3, "Supply increase/glut", "supply"),
    (r"inventory (?:build|builds|increase|increases)|crude inventories.{0,30}(?:build|rose|rise)", -2, "Inventory build", "inventory"),
    (r"demand (?:falls|fell|weak|weakness)|weak oil demand", -2, "Demand weakness", "demand"),
    (r"refinery (?:restart|restarts|resumes|resume)", -1, "Refinery restart", "refinery"),
    (r"ceasefire|peace deal|de-escalation", -1, "Geopolitical de-escalation", "geopolitics"),
]

NG_RULES = [
    (r"storage (?:draw|withdrawal|withdrawals)|storage.{0,30}(?:fell|decline|declined)", 3, "Gas storage draw", "storage"),
    (r"storage (?:build|injection|injections|increase|increases)|storage.{0,30}(?:rose|rise|build)", -3, "Gas storage build", "storage"),
    (r"lng (?:exports|export|demand).{0,50}(?:rise|rose|increase|increased|higher)", 2, "LNG demand/exports strength", "lng"),
    (r"lng (?:outage|terminal outage|shutdown|disruption)|export terminal outage", -2, "LNG outage", "lng"),
    (r"pipeline (?:outage|disruption|shutdown|rupture)", 3, "Gas pipeline disruption", "supply"),
    (r"gas (?:supply|production).{0,40}(?:disruption|outage|shortage|falls|fell|decline)", 3, "Gas supply reduction", "supply"),
    (r"gas (?:production|supply).{0,40}(?:increase|increases|rises|rose|record)", -2, "Gas supply increase", "supply"),
    (r"cold weather|heat wave|extreme heat|hurricane", 1, "Weather/power demand risk", "weather"),
    (r"warm weather|mild weather", -2, "Weather demand weakness", "weather"),
    (r"gas demand.{0,30}(?:rises|rose|increase|increased|higher)|power demand.{0,30}(?:rises|rose|increase|increased|higher)", 2, "Gas/power demand strength", "demand"),
    (r"gas demand.{0,30}(?:falls|fell|weak|lower)|power demand.{0,30}(?:falls|fell|weak|lower)", -2, "Gas/power demand weakness", "demand"),
]


def parse_date(entry):
    for key in ("published", "updated"):
        value = getattr(entry, key, None)
        if value:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def fetch(feeds):
    rows, seen = [], set()
    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:60]:
                title = getattr(entry, "title", "").strip()
                summary = re.sub(r"<[^>]+>", " ", getattr(entry, "summary", "")).strip()
                link = getattr(entry, "link", "")
                if not title:
                    continue
                key = re.sub(r"\W+", " ", title.lower()).strip()
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "Time": parse_date(entry),
                    "Source": source,
                    "Headline": title,
                    "Summary": summary,
                    "Link": link,
                })
        except Exception:
            continue

    columns = ["Time", "Source", "Headline", "Summary", "Link"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("Time", ascending=False).reset_index(drop=True)


def relevant(row, topic_terms):
    text = f"{row['Headline']} {row['Summary']}".lower()
    return any(term in text for term in topic_terms)


def classify(text, rules):
    text = text.lower()
    hits = []
    used_groups = set()
    score = 0
    for pattern, points, reason, group in rules:
        if re.search(pattern, text, flags=re.I):
            # One event group should not be counted repeatedly from overlapping phrases.
            if group not in used_groups:
                score += points
                used_groups.add(group)
            hits.append((points, reason, group))
    return max(-4, min(4, score)), hits


def age_weight(dt):
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    # Fast decay: a 12-hour-old event is materially less useful than a fresh one.
    return max(0.10, 2 ** (-age_hours / 12.0))


def build_market_news(df, topic_terms, rules):
    if df.empty:
        return 0.0, 0, df, 0.0, []

    df = df[df.apply(lambda r: relevant(r, topic_terms), axis=1)].copy()
    if df.empty:
        return 0.0, 0, df, 0.0, []

    scores, weights, reasons, groups = [], [], [], []
    for _, row in df.iterrows():
        text = f"{row['Headline']} {row['Summary']}"
        score, hits = classify(text, rules)
        weight = age_weight(row["Time"]) * SOURCE_WEIGHT.get(row["Source"], 0.8)
        scores.append(score)
        weights.append(weight)
        reasons.append("; ".join(h[1] for h in hits[:3]) if hits else "No material market-impact rule")
        groups.append(sorted(set(h[2] for h in hits)))

    df["Impact"] = scores
    df["Weight"] = weights
    df["Weighted"] = df["Impact"] * df["Weight"]
    df["Reason"] = reasons
    df["Groups"] = groups

    # Only recent material events drive the headline bias. Old neutral articles
    # are retained for display but cannot create a false signal.
    material = df[(df["Impact"] != 0) & (df["Time"] >= datetime.now(timezone.utc) - pd.Timedelta(hours=48))].copy()
    raw_total = float(material["Weighted"].sum()) if not material.empty else 0.0

    # Independent-source corroboration: repeated reports of the same event from
    # different publishers increase confidence, but never double the score.
    corroborated = 0
    event_sources = {}
    for _, row in material.iterrows():
        for group in row["Groups"]:
            event_sources.setdefault(group, set()).add(row["Source"])
    for sources in event_sources.values():
        if len(sources) >= 2:
            corroborated += 1

    # Confidence combines freshness, source quality, number of material events,
    # and independent corroboration. It is intentionally capped below certainty.
    fresh = material[material["Time"] >= datetime.now(timezone.utc) - pd.Timedelta(hours=12)] if not material.empty else material
    fresh_count = len(fresh)
    source_count = len(set(material["Source"])) if not material.empty else 0
    confidence = 25 + min(25, fresh_count * 8) + min(20, source_count * 7) + min(20, corroborated * 10)
    if not material.empty and (material["Impact"] > 0).any() and (material["Impact"] < 0).any():
        confidence -= 15  # conflicting evidence -> lower confidence
    confidence = max(0.0, min(85.0, confidence))

    score = max(-10.0, min(10.0, raw_total))
    df = df.sort_values(["Time", "Weighted"], ascending=[False, False]).reset_index(drop=True)
    return score, int(round(score)), df, confidence, sorted(event_sources.items())


def bias_label(score):
    if score >= 5:
        return "🔥 STRONG BULLISH"
    if score >= 2:
        return "🟢 BULLISH"
    if score <= -5:
        return "🔥 STRONG BEARISH"
    if score <= -2:
        return "🔴 BEARISH"
    return "🟡 NEUTRAL"


def trade_gate(score, confidence, df):
    """News-only gate. It is deliberately hard to pass."""
    if df.empty:
        return "⛔ NO TRADE", "No material recent evidence"
    recent_material = df[(df["Impact"] != 0) & (df["Time"] >= datetime.now(timezone.utc) - pd.Timedelta(hours=12))]
    high_impact = recent_material[recent_material["Impact"].abs() >= 3]
    if confidence < 65:
        return "⛔ NO TRADE", f"Confidence only {confidence:.0f}%"
    if len(high_impact) == 0:
        return "⛔ NO TRADE", "No fresh high-impact event"
    if score >= 5:
        return "🟢 NEWS LONG BIAS", "Fresh high-impact bullish evidence"
    if score <= -5:
        return "🔴 NEWS SHORT BIAS", "Fresh high-impact bearish evidence"
    return "⛔ NO TRADE", "Bias is not strong enough"


def show_market(title, score, rounded, confidence, df):
    st.subheader(title)
    st.metric("News impact score", f"{rounded:+d}")
    st.write(bias_label(score))
    action, why = trade_gate(score, confidence, df)
    st.metric("News-only trade gate", action)
    st.caption(f"Confidence: {confidence:.0f}% • {why} • Material headlines: {len(df[df['Impact'] != 0]) if not df.empty else 0}")


st.title("🛢️ Crude Oil & 🔥 Natural Gas — News Decision Engine")
st.caption("Free/public RSS • refreshes every 60 seconds • event-based market-impact scoring • news-only gate is deliberately conservative")

raw_crude = fetch(CRUDE_FEEDS)
raw_ng = fetch(NG_FEEDS)

crude_score, crude_round, crude, crude_conf, crude_events = build_market_news(raw_crude, CRUDE_TOPIC, CRUDE_RULES)
ng_score, ng_round, ng, ng_conf, ng_events = build_market_news(raw_ng, NG_TOPIC, NG_RULES)

c1, c2 = st.columns(2)
with c1:
    show_market("🛢️ CRUDE", crude_score, crude_round, crude_conf, crude)
with c2:
    show_market("🔥 NATURAL GAS", ng_score, ng_round, ng_conf, ng)

st.divider()

col1, col2 = st.columns(2)


def render_news(df):
    if df.empty:
        st.info("No relevant headlines returned. The app will retry in 60 seconds.")
        return
    for _, row in df.head(30).iterrows():
        impact = row["Impact"]
        bias = "🟢 Bullish" if impact > 0 else "🔴 Bearish" if impact < 0 else "⚪ Neutral"
        time_text = row["Time"].strftime("%d-%b %H:%M UTC")
        st.markdown(
            f"**{bias} | {row['Source']} | {time_text}** — [{row['Headline']}]({row['Link']})  \n"
            f"`Impact {impact:+d}` • {row['Reason']}"
        )

with col1:
    st.subheader("📰 Crude-related news")
    render_news(crude)

with col2:
    st.subheader("📰 Natural Gas-related news")
    render_news(ng)

st.divider()

with st.expander("🎯 Why this is safer than the old score", expanded=False):
    st.write(
        "The old version rewarded isolated words such as 'Iran' or 'Saudi'. This version scores specific market-impact events: supply disruption, inventories, OPEC/output changes, refinery outages, LNG/storage, weather and demand. "
        "It applies source quality and recency, avoids counting overlapping rules from the same event, lowers confidence when evidence conflicts, and requires fresh high-impact evidence before showing a news-only LONG/SHORT bias."
    )
    st.warning(
        "IMPORTANT: A news-only signal is not sufficient for a reliable MCX trade. Before entering a trade, confirm the live MCX price trend, breakout/breakdown, volume/open interest where available, and a defined stop-loss."
    )

st.caption("Last refresh: " + datetime.now().astimezone().strftime("%d-%b-%Y %H:%M:%S %Z"))
