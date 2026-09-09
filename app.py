import re
import html
import streamlit as st
import feedparser
import pandas as pd
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

st.set_page_config(page_title="Crude & Natural Gas News", page_icon="🛢️", layout="wide")
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

NEWS_WINDOW_HOURS = 24
TOP_NEWS = 10

# -----------------------------------------------------------------------------
# INTERNATIONAL NEWS COVERAGE
# Official energy sources + broad international Google News RSS feeds.
# Google News RSS is used only as a public news-discovery layer; every headline
# keeps its original publisher link. Failed feeds are ignored automatically.
# -----------------------------------------------------------------------------
CRUDE_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "OPEC": "https://www.opec.org/assets/assetdb/opec_rss.xml",
    "IEA": "https://www.iea.org/rss/news.xml",
    "OilPrice": "https://oilprice.com/rss/main",
    "Rigzone": "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
}

NG_FEEDS = {
    "EIA": "https://www.eia.gov/rss/todayinenergy.xml",
    "IEA": "https://www.iea.org/rss/news.xml",
    "Rigzone": "https://www.rigzone.com/news/rss/naturalgas_latest.aspx",
}

# Country/region-specific searches.  These deliberately cover producers,
# exporters, transit points, major consumers and weather/LNG hubs.
COUNTRY_TAGS = {
    "Middle East": ["Saudi Arabia", "Iran", "Iraq", "UAE", "Qatar", "Kuwait", "Oman", "Israel"],
    "Russia/CIS": ["Russia", "Kazakhstan", "Azerbaijan", "Caspian"],
    "North America": ["United States", "Canada", "Gulf of Mexico", "Texas", "Alaska"],
    "Latin America": ["Brazil", "Venezuela", "Mexico", "Guyana", "Colombia"],
    "Europe": ["Norway", "UK", "Germany", "France", "Italy", "Netherlands", "EU"],
    "Asia": ["China", "India", "Japan", "South Korea", "Taiwan", "Singapore"],
    "Africa": ["Nigeria", "Libya", "Algeria", "Angola", "Egypt"],
    "Oceania": ["Australia"],
}

# Search themes are intentionally explicit so the engine captures each major
# market-moving tag rather than treating a country name as bullish/bearish.
CRUDE_TAGS = [
    "crude oil", "Brent", "WTI", "OPEC", "OPEC+", "oil supply", "oil production",
    "oil exports", "oil imports", "oil inventory", "refinery", "refining",
    "SPR", "strategic petroleum reserve", "oil tanker", "tanker rates", "shipping",
    "Strait of Hormuz", "Red Sea", "Bab el-Mandeb", "sanctions", "pipeline",
    "oil demand", "China oil demand", "India oil demand", "US oil production",
]

NG_TAGS = [
    "natural gas", "natgas", "LNG", "Henry Hub", "gas storage", "gas production",
    "gas supply", "gas demand", "gas prices", "pipeline", "LNG exports", "LNG imports",
    "LNG terminal", "Freeport LNG", "Sabine Pass", "Europe gas", "TTF gas", "JKM LNG",
    "hurricane", "cold weather", "heat wave", "power demand", "gas outage",
]

SOURCE_WEIGHT = {
    "EIA": 1.45, "OPEC": 1.50, "IEA": 1.50, "Rigzone": 1.00, "OilPrice": 0.90,
}

CRUDE_RULES = [
    (r"production (?:cut|cuts|cutback|reduction)|output (?:cut|cuts|reduction)", 2, "Production cut", "supply"),
    (r"supply (?:disruption|disrupted|outage|shortage)|oil outage|export halt|exports (?:halt|stopped)", 3, "Oil supply disruption", "supply"),
    (r"strait of hormuz|hormuz (?:standoff|closure|blocked|attack)|tanker (?:attack|disruption)", 3, "Hormuz/shipping risk", "geopolitics"),
    (r"red sea|bab el[- ]mandeb|shipping disruption|shipping risk", 2, "Shipping/geopolitical risk", "geopolitics"),
    (r"refinery (?:outage|shutdown|shut down)|refinery .*offline", 2, "Refinery outage", "refinery"),
    (r"crude (?:inventory|inventories).{0,40}(?:draw|fell|fall)|inventory draw|drawdown", 2, "Crude inventory draw", "inventory"),
    (r"demand (?:rises|rose|increase|increases|strong|higher)|strong oil demand|china buying more oil", 1, "Oil demand strength", "demand"),
    (r"sanctions|iran.{0,50}(?:oil exports|oil production)|oil exports.{0,50}(?:iran|sanctions)", 1, "Sanctions/supply risk", "geopolitics"),
    (r"attack(?:s|ed)?.{0,50}(?:refiner|oil|pipeline|energy|facility)|oil.{0,30}attack", 2, "Energy infrastructure attack", "geopolitics"),
    (r"production (?:increase|increases|rises|rose)|output (?:increase|increases|rises|rose)", -2, "Production increase", "supply"),
    (r"supply (?:increase|increases|rises)|oversupply|supply glut", -3, "Supply increase/glut", "supply"),
    (r"inventory (?:build|builds|increase|increases)|crude inventories.{0,40}(?:build|rose|rise)", -2, "Crude inventory build", "inventory"),
    (r"demand (?:falls|fell|weak|weakness|lower)|weak oil demand", -2, "Oil demand weakness", "demand"),
    (r"refinery (?:restart|restarts|resumes|resume)", -1, "Refinery restart", "refinery"),
    (r"ceasefire|peace deal|de-escalation", -1, "Geopolitical de-escalation", "geopolitics"),
]

NG_RULES = [
    (r"storage (?:draw|withdrawal|withdrawals)|storage.{0,30}(?:fell|decline|declined)", 3, "Gas storage draw", "storage"),
    (r"storage (?:build|injection|injections|increase|increases)|storage.{0,30}(?:rose|rise|build)", -3, "Gas storage build", "storage"),
    (r"lng (?:exports|export|demand).{0,50}(?:rise|rose|increase|increased|higher)", 2, "LNG demand/exports strength", "lng"),
    (r"lng (?:outage|terminal outage|shutdown|disruption)|export terminal outage", -2, "LNG terminal outage", "lng"),
    (r"pipeline (?:outage|disruption|shutdown|rupture)", 3, "Gas pipeline disruption", "supply"),
    (r"gas (?:supply|production).{0,40}(?:disruption|outage|shortage|falls|fell|decline)", 3, "Gas supply reduction", "supply"),
    (r"gas (?:production|supply).{0,40}(?:increase|increases|rises|rose|record)", -2, "Gas supply increase", "supply"),
    (r"cold weather|heat wave|extreme heat|hurricane", 1, "Weather/power demand risk", "weather"),
    (r"warm weather|mild weather", -2, "Weather demand weakness", "weather"),
    (r"gas demand.{0,30}(?:rises|rose|increase|increased|higher)|power demand.{0,30}(?:rises|rose|increase|increased|higher)", 2, "Gas/power demand strength", "demand"),
    (r"gas demand.{0,30}(?:falls|fell|weak|lower)|power demand.{0,30}(?:falls|fell|weak|lower)", -2, "Gas/power demand weakness", "demand"),
]


def google_news_url(query, country="US"):
    return "https://news.google.com/rss/search?q=" + query.replace(" ", "+") + f"&hl=en-{country}&gl={country}&ceid={country}:en"


def build_international_feeds(product):
    feeds = {}
    tags = CRUDE_TAGS if product == "crude" else NG_TAGS
    # Product-wide global searches catch stories that may not mention a country.
    feeds["Global"] = google_news_url(" OR ".join(tags[:10]))
    feeds["Global Energy"] = google_news_url("(" + " OR ".join(tags) + ") oil gas energy")

    for region, countries in COUNTRY_TAGS.items():
        for country in countries:
            country_terms = " OR ".join(f'"{x}"' for x in tags[:8])
            query = f'({country_terms}) AND "{country}"'
            feeds[f"{region}: {country}"] = google_news_url(query)
    return feeds


def parse_date(entry):
    for key in ("published", "updated"):
        value = getattr(entry, key, None)
        if value:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fetch(feeds, max_entries=35):
    rows, seen = [], set()
    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_entries]:
                title = clean_text(getattr(entry, "title", ""))
                summary = clean_text(getattr(entry, "summary", ""))
                link = getattr(entry, "link", "")
                if not title:
                    continue
                key = re.sub(r"\W+", " ", title.lower()).strip()
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"Time": parse_date(entry), "Source": source, "Headline": title, "Summary": summary, "Link": link})
        except Exception:
            continue

    columns = ["Time", "Source", "Headline", "Summary", "Link"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("Time", ascending=False).reset_index(drop=True)


def relevant(row, topic_terms):
    text = f"{row['Headline']} {row['Summary']}".lower()
    return any(term.lower() in text for term in topic_terms)


def classify(text, rules):
    text = text.lower()
    hits, used_groups = [], set()
    score = 0
    for pattern, points, reason, group in rules:
        if re.search(pattern, text, flags=re.I):
            if group not in used_groups:
                score += points
                used_groups.add(group)
            hits.append((points, reason, group))
    return max(-4, min(4, score)), hits


def age_weight(dt):
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    return max(0.10, 2 ** (-age_hours / 12.0))


def build_market_news(df, topic_terms, rules):
    if df.empty:
        return 0.0, 0, df, 0.0, []

    cutoff = datetime.now(timezone.utc) - pd.Timedelta(hours=NEWS_WINDOW_HOURS)
    df = df[(df["Time"] >= cutoff) & df.apply(lambda r: relevant(r, topic_terms), axis=1)].copy()
    if df.empty:
        return 0.0, 0, df, 0.0, []

    scores, weights, reasons, groups, tags = [], [], [], [], []
    for _, row in df.iterrows():
        text = f"{row['Headline']} {row['Summary']}"
        score, hits = classify(text, rules)
        weight = age_weight(row["Time"]) * SOURCE_WEIGHT.get(row["Source"], 0.75)
        scores.append(score)
        weights.append(weight)
        reasons.append("; ".join(h[1] for h in hits[:3]) if hits else "No material market-impact rule")
        groups.append(sorted(set(h[2] for h in hits)))
        tags.append([t for t in topic_terms if t.lower() in text.lower()][:6])

    df["Impact"] = scores
    df["Weight"] = weights
    df["Weighted"] = df["Impact"] * df["Weight"]
    df["Reason"] = reasons
    df["Groups"] = groups
    df["Tags"] = tags

    material = df[df["Impact"] != 0].copy()
    raw_total = float(material["Weighted"].sum()) if not material.empty else 0.0

    # De-duplicate repeated coverage of the same market event. Multiple sources
    # can raise confidence, but the same event should not create unlimited score.
    event_sources = {}
    for _, row in material.iterrows():
        for group in row["Groups"]:
            event_sources.setdefault(group, set()).add(row["Source"])
    corroborated = sum(1 for sources in event_sources.values() if len(sources) >= 2)

    fresh = material[material["Time"] >= datetime.now(timezone.utc) - pd.Timedelta(hours=12)]
    fresh_count = len(fresh)
    source_count = len(set(material["Source"])) if not material.empty else 0
    confidence = 25 + min(25, fresh_count * 5) + min(20, source_count * 4) + min(20, corroborated * 8)
    if not material.empty and (material["Impact"] > 0).any() and (material["Impact"] < 0).any():
        confidence -= 20
    confidence = max(0.0, min(85.0, confidence))

    score = max(-10.0, min(10.0, raw_total))
    # Importance prioritises impact, freshness and credible-source weight.
    df["Importance"] = (df["Impact"].abs() * df["Weight"] * 10).round(1)
    df = df.sort_values(["Importance", "Time"], ascending=[False, False]).reset_index(drop=True)
    return score, int(round(score)), df, confidence, sorted(event_sources.items())


def bias_label(score):
    if score >= 5: return "🔥 STRONG BULLISH"
    if score >= 2: return "🟢 BULLISH"
    if score <= -5: return "🔥 STRONG BEARISH"
    if score <= -2: return "🔴 BEARISH"
    return "🟡 NEUTRAL"


def news_confirmation(price_action, score, confidence):
    if price_action == "SELL":
        if score <= -2 and confidence >= 55:
            return "🔴 SELL CONFIRMED", "Price action SELL + bearish 24H news confirmation", min(90, int(confidence + 10))
        if score >= 2:
            return "⛔ NO SELL", "News conflicts with SELL price action", int(max(0, confidence))
        return "🟡 WAIT", "SELL price action, but news does not confirm", int(confidence)
    if price_action == "BUY":
        if score >= 2 and confidence >= 55:
            return "🟢 BUY CONFIRMED", "Price action BUY + bullish 24H news confirmation", min(90, int(confidence + 10))
        if score <= -2:
            return "⛔ NO BUY", "News conflicts with BUY price action", int(max(0, confidence))
        return "🟡 WAIT", "BUY price action, but news does not confirm", int(confidence)
    return "⚪ NO CLEAR SETUP", "Wait for a clear price-action trigger", 0


def render_news(df):
    if df.empty:
        st.info("No relevant news in the last 24 hours. The app will retry in 60 seconds.")
        return
    for _, row in df.head(TOP_NEWS).iterrows():
        impact = int(row["Impact"])
        bias = "🟢 Bullish" if impact > 0 else "🔴 Bearish" if impact < 0 else "⚪ Neutral"
        time_text = row["Time"].strftime("%d-%b %H:%M UTC")
        tag_text = ", ".join(row["Tags"]) if row["Tags"] else "market"
        st.markdown(
            f"**{bias} | {row['Source']} | {time_text}** — [{row['Headline']}]({row['Link']})  \n"
            f"`Impact {impact:+d}` • `Importance {row['Importance']:.0f}` • **Tags:** {tag_text}  \n"
            f"{row['Reason']}"
        )


def show_market(title, score, rounded, confidence, df):
    st.subheader(title)
    st.metric("24H news impact", f"{rounded:+d}")
    st.write(bias_label(score))
    material_count = int((df["Impact"] != 0).sum()) if not df.empty else 0
    st.caption(f"News confidence: {confidence:.0f}% • Material events: {material_count} • Window: last {NEWS_WINDOW_HOURS}h")


# -----------------------------------------------------------------------------
# Pull official feeds + international country-by-country discovery feeds.
# -----------------------------------------------------------------------------
crude_feeds = {**CRUDE_FEEDS, **build_international_feeds("crude")}
ng_feeds = {**NG_FEEDS, **build_international_feeds("ng")}

raw_crude = fetch(crude_feeds)
raw_ng = fetch(ng_feeds)

crude_score, crude_round, crude, crude_conf, crude_events = build_market_news(raw_crude, CRUDE_TAGS, CRUDE_RULES)
ng_score, ng_round, ng, ng_conf, ng_events = build_market_news(raw_ng, NG_TAGS, NG_RULES)

st.title("🛢️ Crude Oil & 🔥 Natural Gas — International News Engine")
st.caption("24-hour international coverage • producer/exporter/consumer countries • event-based impact • refresh every 60 seconds")

c1, c2 = st.columns(2)
with c1:
    show_market("🛢️ CRUDE", crude_score, crude_round, crude_conf, crude)
with c2:
    show_market("🔥 NATURAL GAS", ng_score, ng_round, ng_conf, ng)

st.divider()
st.subheader("🎯 Price Action + News Confirmation")

p1, p2 = st.columns(2)
with p1:
    crude_pa = st.selectbox("Crude price-action trigger", ["NO CLEAR", "SELL", "BUY"], key="crude_pa")
    a, why, conf = news_confirmation(crude_pa, crude_score, crude_conf)
    st.metric("Crude decision", a)
    st.caption(f"{why} • Setup confidence: {conf}%")
with p2:
    ng_pa = st.selectbox("Natural Gas price-action trigger", ["NO CLEAR", "SELL", "BUY"], key="ng_pa")
    a, why, conf = news_confirmation(ng_pa, ng_score, ng_conf)
    st.metric("Natural Gas decision", a)
    st.caption(f"{why} • Setup confidence: {conf}%")

st.info("Price action remains the primary trigger. This screen uses international 24H news only as confirmation; it does not guarantee a profitable trade.")

st.divider()
col1, col2 = st.columns(2)
with col1:
    st.subheader(f"📰 Top {TOP_NEWS} Crude events — last 24H")
    render_news(crude)
with col2:
    st.subheader(f"📰 Top {TOP_NEWS} Natural Gas events — last 24H")
    render_news(ng)

st.divider()
with st.expander("🌍 Countries and tags covered", expanded=False):
    for region, countries in COUNTRY_TAGS.items():
        st.markdown(f"**{region}:** " + ", ".join(countries))
    st.markdown("**Crude tags:** " + ", ".join(CRUDE_TAGS))
    st.markdown("**NG tags:** " + ", ".join(NG_TAGS))

with st.expander("🧠 Decision rules", expanded=False):
    st.write("SELL + bearish news = SELL CONFIRMED. SELL + neutral news = WAIT. SELL + bullish news = NO SELL. BUY + bullish news = BUY CONFIRMED. BUY + neutral news = WAIT. BUY + bearish news = NO BUY.")
    st.warning("Use MCX live price, breakout/breakdown, volume/open interest where available, entry, stop-loss and RR before placing an order.")

st.caption("Last refresh: " + datetime.now().astimezone().strftime("%d-%b-%Y %H:%M:%S %Z"))
