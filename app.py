import streamlit as st
import feedparser
import pandas as pd
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

st.set_page_config(page_title="Crude & Natural Gas News", page_icon="🛢️", layout="wide")

# Streamlit Cloud-compatible 60-second refresh
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

CRUDE_POS = ["opec cut", "production cut", "supply disruption", "outage", "hormuz", "tanker attack", "sanctions", "war", "attack", "iran", "saudi", "inventory draw", "drawdown", "demand rises", "shortage"]
CRUDE_NEG = ["opec increase", "production increase", "supply increase", "inventory build", "builds", "oversupply", "demand falls", "weak demand", "peace deal", "ceasefire", "output rises"]
NG_POS = ["lng demand", "lng export", "gas outage", "pipeline outage", "storage draw", "cold weather", "heat wave", "hurricane", "production falls", "supply disruption"]
NG_NEG = ["storage build", "storage increase", "warm weather", "mild weather", "production rises", "production increase", "weak demand", "lng outage"]


def parse_date(entry):
    for key in ("published", "updated"):
        if getattr(entry, key, None):
            try:
                return parsedate_to_datetime(getattr(entry, key)).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def fetch(feeds):
    rows, seen = [], set()
    for source, url in feeds.items():
        try:
            d = feedparser.parse(url)
            for e in d.entries[:30]:
                title = getattr(e, "title", "").strip()
                link = getattr(e, "link", "")
                key = title.lower()
                if not title or key in seen:
                    continue
                seen.add(key)
                rows.append({"Time": parse_date(e), "Source": source, "Headline": title, "Link": link})
        except Exception:
            continue
    return pd.DataFrame(rows).sort_values("Time", ascending=False) if rows else pd.DataFrame(columns=["Time", "Source", "Headline", "Link"])


def score(text, positive, negative):
    t = text.lower()
    pos = sum(1 for x in positive if x in t)
    neg = sum(1 for x in negative if x in t)
    return pos - neg


def label(s):
    if s >= 6: return "🔥 STRONG BULLISH"
    if s >= 2: return "🟢 BULLISH"
    if s <= -6: return "🔥 STRONG BEARISH"
    if s <= -2: return "🔴 BEARISH"
    return "🟡 NEUTRAL"


def build_news(df, pos, neg):
    if df.empty:
        return 0, df
    df = df.copy()
    df["Score"] = df["Headline"].map(lambda x: score(x, pos, neg))
    # Recent news gets more weight; older headlines fade out.
    now = datetime.now(timezone.utc)
    def weighted(r):
        age_h = max(0.0, (now - r["Time"]).total_seconds() / 3600)
        decay = max(0.15, 1.0 - age_h / 24.0)
        return r["Score"] * decay
    df["Weighted"] = df.apply(weighted, axis=1)
    return int(round(df["Weighted"].sum())), df

st.title("🛢️ Crude Oil & 🔥 Natural Gas — Live News Bias")
st.caption("Free/public RSS news scan • automatic refresh every 60 seconds • news-based bias, not a guaranteed trading signal")

crude = fetch(CRUDE_FEEDS)
ng = fetch(NG_FEEDS)
crude_score, crude = build_news(crude, CRUDE_POS, CRUDE_NEG)
ng_score, ng = build_news(ng, NG_POS, NG_NEG)

c1, c2 = st.columns(2)
with c1:
    st.subheader("🛢️ CRUDE")
    st.metric("News score", crude_score)
    st.success(label(crude_score) if crude_score >= 2 else "") if crude_score >= 2 else st.error(label(crude_score)) if crude_score <= -2 else st.warning(label(crude_score))
with c2:
    st.subheader("🔥 NATURAL GAS")
    st.metric("News score", ng_score)
    st.success(label(ng_score) if ng_score >= 2 else "") if ng_score >= 2 else st.error(label(ng_score)) if ng_score <= -2 else st.warning(label(ng_score))

st.divider()

for name, df, title in [("CRUDE", crude, "📰 Crude-related news"), ("NG", ng, "📰 Natural Gas-related news")]:
    st.subheader(title)
    if df.empty:
        st.info("No feed items returned. The app will retry in 60 seconds.")
        continue
    show = df.head(25).copy()
    show["Time"] = show["Time"].dt.strftime("%d-%b %H:%M UTC")
    show["Bias"] = show["Score"].map(lambda x: "🟢 Bullish" if x > 0 else "🔴 Bearish" if x < 0 else "⚪ Neutral")
    for _, r in show.iterrows():
        st.markdown(f"**{r['Bias']} | {r['Source']} | {r['Time']}** — [{r['Headline']}]({r['Link']})")

st.divider()
st.caption("Last refresh: " + datetime.now().astimezone().strftime("%d-%b-%Y %H:%M:%S %Z"))
