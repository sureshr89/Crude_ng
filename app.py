import streamlit as st
import feedparser
import pandas as pd
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

st.set_page_config(page_title="Crude & Natural Gas News", page_icon="🛢️", layout="wide")

# Refresh the whole dashboard every 60 seconds.
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

CRUDE_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "OilPrice": "https://oilprice.com/rss/main",
    "Rigzone": "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
}

NG_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "Rigzone": "https://www.rigzone.com/news/rss/naturalgas_latest.aspx",
}

# Keyword scoring is deliberately transparent: no fake AI certainty.
CRUDE_POS = [
    "opec cut", "production cut", "supply disruption", "supply outage", "oil outage",
    "hormuz", "strait of hormuz", "tanker attack", "tanker disruption", "sanctions",
    "war", "attack", "iran", "saudi", "saudi arabia", "inventory draw", "drawdown",
    "demand rises", "strong demand", "shortage", "refinery outage", "refinery shutdown",
    "export halt", "exports fall", "production falls", "oil prices rise", "brent rises",
    "wti rises"
]
CRUDE_NEG = [
    "opec increase", "production increase", "supply increase", "inventory build", "builds",
    "oversupply", "demand falls", "weak demand", "peace deal", "ceasefire", "output rises",
    "production rises", "exports rise", "oil prices fall", "brent falls", "wti falls",
    "refinery restart", "supply glut"
]

NG_POS = [
    "natural gas", "lng", "lng demand", "lng export", "lng exports", "gas outage",
    "pipeline outage", "storage draw", "storage withdrawal", "cold weather", "heat wave",
    "hurricane", "production falls", "gas production falls", "supply disruption",
    "export terminal outage", "pipeline disruption", "power demand rises"
]
NG_NEG = [
    "natural gas", "storage build", "storage injection", "storage increase", "warm weather",
    "mild weather", "production rises", "production increase", "weak demand", "lng outage",
    "lng terminal outage", "supply increase", "gas production rises", "power demand falls"
]

# Terms used to decide whether a headline belongs in each market.
CRUDE_TOPIC = [
    "crude", "oil", "brent", "wti", "opec", "petroleum", "refinery", "gasoline", "diesel",
    "hormuz", "tanker", "saudi", "iran", "iraq", "russia", "venezuela", "oilprice"
]
NG_TOPIC = [
    "natural gas", "natgas", "lng", "henry hub", "gas storage", "gas production", "pipeline",
    "freeport", "sabine pass", "louisiana gas", "ercot", "hurricane", "weather"
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
            for entry in feed.entries[:50]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "")
                if not title:
                    continue
                key = title.lower().strip()
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "Time": parse_date(entry),
                    "Source": source,
                    "Headline": title,
                    "Link": link,
                })
        except Exception:
            continue

    columns = ["Time", "Source", "Headline", "Link"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("Time", ascending=False).reset_index(drop=True)


def relevant(headline, topic_terms):
    text = headline.lower()
    return any(term in text for term in topic_terms)


def score_headline(text, positive, negative):
    t = text.lower()
    pos_hits = [term for term in positive if term in t]
    neg_hits = [term for term in negative if term in t]
    raw = len(pos_hits) - len(neg_hits)
    # Keep a single headline from dominating the complete score.
    return max(-3, min(3, raw)), pos_hits, neg_hits


def label(value):
    if value >= 6:
        return "🔥 STRONG BULLISH"
    if value >= 2:
        return "🟢 BULLISH"
    if value <= -6:
        return "🔥 STRONG BEARISH"
    if value <= -2:
        return "🔴 BEARISH"
    return "🟡 NEUTRAL"


def build_market_news(df, topic_terms, positive, negative):
    if df.empty:
        return 0, df

    df = df[df["Headline"].map(lambda x: relevant(x, topic_terms))].copy()
    if df.empty:
        return 0, df

    now = datetime.now(timezone.utc)
    scores, weights, explanations = [], [], []

    for _, row in df.iterrows():
        raw_score, pos_hits, neg_hits = score_headline(row["Headline"], positive, negative)
        age_hours = max(0.0, (now - row["Time"]).total_seconds() / 3600.0)
        # 0-24h: strong recency decay; after 24h retain only 15%.
        weight = max(0.15, 1.0 - age_hours / 24.0)
        scores.append(raw_score)
        weights.append(weight)
        explanations.append(", ".join(pos_hits[:3]) if pos_hits else (", ".join(neg_hits[:3]) if neg_hits else "No direct score keyword"))

    df["Score"] = scores
    df["Weighted"] = [s * w for s, w in zip(scores, weights)]
    df["Reason"] = explanations

    total = int(round(df["Weighted"].sum()))
    return total, df.sort_values(["Time", "Weighted"], ascending=[False, False]).reset_index(drop=True)


def show_bias(value):
    # IMPORTANT: don't put st.success/st.warning/st.error calls inside a
    # conditional expression. Streamlit renders the returned DeltaGenerator
    # otherwise, which caused the ugly DeltaGenerator output seen previously.
    if value >= 2:
        st.success(label(value))
    elif value <= -2:
        st.error(label(value))
    else:
        st.warning(label(value))


st.title("🛢️ Crude Oil & 🔥 Natural Gas — Live News Bias")
st.caption("Free/public RSS scan • automatic refresh every 60 seconds • transparent news scoring, not a guaranteed trading signal")

raw_crude = fetch(CRUDE_FEEDS)
raw_ng = fetch(NG_FEEDS)

crude_score, crude = build_market_news(raw_crude, CRUDE_TOPIC, CRUDE_POS, CRUDE_NEG)
ng_score, ng = build_market_news(raw_ng, NG_TOPIC, NG_POS, NG_NEG)

c1, c2 = st.columns(2)
with c1:
    st.subheader("🛢️ CRUDE")
    st.metric("News score", crude_score)
    show_bias(crude_score)
    st.caption(f"Relevant headlines: {len(crude)}")

with c2:
    st.subheader("🔥 NATURAL GAS")
    st.metric("News score", ng_score)
    show_bias(ng_score)
    st.caption(f"Relevant headlines: {len(ng)}")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("📰 Crude-related news")
    if crude.empty:
        st.info("No relevant Crude headlines returned. The app will retry in 60 seconds.")
    else:
        for _, row in crude.head(30).iterrows():
            bias = "🟢 Bullish" if row["Score"] > 0 else "🔴 Bearish" if row["Score"] < 0 else "⚪ Neutral"
            time_text = row["Time"].strftime("%d-%b %H:%M UTC")
            reason = row["Reason"]
            st.markdown(
                f"**{bias} | {row['Source']} | {time_text}** — "
                f"[{row['Headline']}]({row['Link']})  \n"
                f"`Score {row['Score']:+d}` • {reason}"
            )

with col2:
    st.subheader("📰 Natural Gas-related news")
    if ng.empty:
        st.info("No relevant Natural Gas headlines returned. The app will retry in 60 seconds.")
    else:
        for _, row in ng.head(30).iterrows():
            bias = "🟢 Bullish" if row["Score"] > 0 else "🔴 Bearish" if row["Score"] < 0 else "⚪ Neutral"
            time_text = row["Time"].strftime("%d-%b %H:%M UTC")
            reason = row["Reason"]
            st.markdown(
                f"**{bias} | {row['Source']} | {time_text}** — "
                f"[{row['Headline']}]({row['Link']})  \n"
                f"`Score {row['Score']:+d}` • {reason}"
            )

st.divider()

with st.expander("📊 Scoring method", expanded=False):
    st.write(
        "Each headline receives a transparent keyword score from -3 to +3. "
        "News becomes less influential as it ages, with a minimum 15% weight after 24 hours. "
        "Crude and Natural Gas use separate topic and scoring dictionaries, so unrelated petroleum headlines "
        "are not counted as Natural Gas news."
    )

st.caption("Last refresh: " + datetime.now().astimezone().strftime("%d-%b-%Y %H:%M:%S %Z"))
