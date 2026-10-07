"""Pull today's trending searches from Google Trends and keep only the sports ones.

Google Trends has no official API. The daily-trends RSS feed is the most stable
public surface -- it needs no scraping and no unofficial client library. The feed
carries no category tag, so sports detection is a two-signal heuristic:

  1. the domain of the attached news articles (a Cricbuzz link is a strong signal)
  2. a sports term lexicon matched against the query and the headlines

A topic needs to clear a score threshold, which keeps out generic news that merely
mentions a player's name.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

import config

NS = {"ht": "https://trends.google.com/trending/rss"}

SPORTS_DOMAINS = {
    "espn.com", "espncricinfo.com", "cricbuzz.com", "sportstar.thehindu.com",
    "skysports.com", "bbc.com/sport", "goal.com", "olympics.com", "nba.com",
    "nfl.com", "fifa.com", "icc-cricket.com", "atptour.com", "wtatennis.com",
    "formula1.com", "sportskeeda.com", "khelnow.com", "insidesport.in",
    "hindustantimes.com/sports", "indianexpress.com/sports", "the-aiff.com",
    "olympics.org", "pro-kabaddi.com", "bcci.tv", "premierleague.com",
}

SPORTS_TERMS = {
    # cricket
    "cricket", "ipl", "odi", "t20", "test match", "wicket", "innings", "bcci",
    "ranji", "wpl", "bowler", "batsman", "batter", "century", "stumps",
    # football
    "football", "soccer", "premier league", "la liga", "serie a", "bundesliga",
    "ucl", "champions league", "fifa", "isl", "goalkeeper", "penalty", "offside",
    # general
    "match", "tournament", "league", "championship", "final", "semifinal",
    "quarterfinal", "playoff", "squad", "lineup", "fixture", "scorecard",
    "olympics", "medal", "athlete", "coach", "transfer", "debut", "retirement",
    # other sports
    "tennis", "atp", "wta", "grand slam", "wimbledon", "us open", "badminton",
    "hockey", "kabaddi", "nba", "nfl", "mlb", "ufc", "boxing", "formula 1",
    "f1", "grand prix", "motogp", "wrestling", "chess", "golf", "marathon",
}


@dataclass
class Trend:
    title: str
    traffic: str = ""
    headlines: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def context(self) -> str:
        """Compact brief handed to the script writer."""
        lines = [f"Trending search: {self.title}"]
        if self.traffic:
            lines.append(f"Approx. search volume: {self.traffic}")
        if self.headlines:
            lines.append("Related headlines:")
            lines.extend(f"  - {h}" for h in self.headlines)
        return "\n".join(lines)


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _score(trend: Trend) -> int:
    score = 0
    haystack = " ".join([trend.title, *trend.headlines]).lower()

    for src in trend.sources:
        dom = _domain(src)
        if any(dom == d or dom.endswith("." + d) or d.startswith(dom) for d in SPORTS_DOMAINS):
            score += 3

    for term in SPORTS_TERMS:
        # word-boundary match so "final" does not fire on "finally"
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            score += 2 if term in trend.title.lower() else 1

    return score


def fetch(min_score: int | None = None, limit: int = 10) -> list[Trend]:
    """Return sports-looking trends, highest confidence first."""
    min_score = config.MIN_SPORTS_SCORE if min_score is None else min_score
    resp = requests.get(
        config.TRENDS_RSS,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sports-reels/1.0)"},
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    trends: list[Trend] = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue

        trend = Trend(
            title=title,
            traffic=(item.findtext("ht:approx_traffic", namespaces=NS) or "").strip(),
        )
        for news in item.iterfind("ht:news_item", NS):
            headline = (news.findtext("ht:news_item_title", namespaces=NS) or "").strip()
            url = (news.findtext("ht:news_item_url", namespaces=NS) or "").strip()
            if headline:
                trend.headlines.append(headline)
            if url:
                trend.sources.append(url)

        trend.score = _score(trend)
        if trend.score >= min_score:
            trends.append(trend)

    trends.sort(key=lambda t: t.score, reverse=True)
    return trends[:limit]


if __name__ == "__main__":
    for t in fetch():
        print(f"[{t.score:>2}] {t.title}  ({t.traffic})")
