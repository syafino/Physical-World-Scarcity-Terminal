"""
News Ingestion Module

Fetches RSS feeds for Texas Node keywords and scores sentiment locally using NLTK VADER.
Free data sources only - uses Google News RSS feeds.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import structlog
from nltk.sentiment.vader import SentimentIntensityAnalyzer

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# Texas Node RSS Query Keywords - grouped by domain
TEXAS_NODE_QUERIES = {
    "GRID": [
        "ERCOT",
        "Texas power grid",
        "Texas electricity",
        "Texas blackout",
    ],
    "WATER": [
        "Texas drought",
        "Texas water shortage",
        "Texas aquifer",
        "Edwards Aquifer",
    ],
    "LOGISTICS": [
        "Port of Houston",
        "Houston Ship Channel",
        "Texas shipping",
    ],
    "EQUITY": [
        "Vistra Energy",
        "NRG Energy stock",
        "Texas Instruments TXN",
    ],
}

# Flatten for full fetch
ALL_QUERIES = [q for queries in TEXAS_NODE_QUERIES.values() for q in queries]

# Google News RSS base URL
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# Sentiment thresholds
SENTIMENT_THRESHOLDS = {
    "VERY_NEGATIVE": -0.5,
    "NEGATIVE": -0.05,
    "NEUTRAL_LOW": 0.05,
    "POSITIVE": 0.5,
}


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────


@dataclass
class NewsHeadline:
    """Parsed news headline with sentiment."""
    
    title: str
    source: str
    url: str
    published_at: Optional[datetime]
    query_category: str  # GRID, WATER, LOGISTICS, EQUITY
    query_term: str
    
    # Sentiment scores from VADER
    compound_score: float  # -1 to 1
    positive_score: float
    negative_score: float
    neutral_score: float
    sentiment_label: str  # VERY_NEGATIVE, NEGATIVE, NEUTRAL, POSITIVE, VERY_POSITIVE


@dataclass
class NewsSummary:
    """Aggregated news summary for a category."""
    
    category: str
    headline_count: int
    avg_sentiment: float
    negative_count: int
    positive_count: int
    most_negative: Optional[NewsHeadline]
    most_positive: Optional[NewsHeadline]


# ─────────────────────────────────────────────────────────────
# Sentiment Analyzer (Singleton)
# ─────────────────────────────────────────────────────────────

_vader_analyzer: Optional[SentimentIntensityAnalyzer] = None


def get_vader_analyzer() -> SentimentIntensityAnalyzer:
    """
    Get or initialize VADER sentiment analyzer.
    Downloads lexicon on first use if needed.
    """
    global _vader_analyzer
    
    if _vader_analyzer is None:
        import nltk
        try:
            nltk.data.find("sentiment/vader_lexicon.zip")
        except LookupError:
            logger.info("downloading_vader_lexicon")
            nltk.download("vader_lexicon", quiet=True)
        
        _vader_analyzer = SentimentIntensityAnalyzer()
        logger.info("vader_analyzer_initialized")
    
    return _vader_analyzer


def score_sentiment(text: str) -> dict:
    """
    Score sentiment of text using VADER.
    
    Returns:
        Dict with compound, pos, neg, neu scores and label
    """
    analyzer = get_vader_analyzer()
    scores = analyzer.polarity_scores(text)
    
    compound = scores["compound"]
    
    # Determine label based on compound score
    if compound <= SENTIMENT_THRESHOLDS["VERY_NEGATIVE"]:
        label = "VERY_NEGATIVE"
    elif compound <= SENTIMENT_THRESHOLDS["NEGATIVE"]:
        label = "NEGATIVE"
    elif compound < SENTIMENT_THRESHOLDS["NEUTRAL_LOW"]:
        label = "NEUTRAL"
    elif compound < SENTIMENT_THRESHOLDS["POSITIVE"]:
        label = "POSITIVE"
    else:
        label = "VERY_POSITIVE"
    
    return {
        "compound": compound,
        "positive": scores["pos"],
        "negative": scores["neg"],
        "neutral": scores["neu"],
        "label": label,
    }


# ─────────────────────────────────────────────────────────────
# RSS Feed Parsing
# ─────────────────────────────────────────────────────────────


def parse_published_date(entry: dict) -> Optional[datetime]:
    """Parse published date from RSS entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def extract_source(entry: dict) -> str:
    """Extract source name from Google News RSS entry."""
    # Google News format: "Title - Source Name"
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1]
    return "Unknown"


def clean_title(title: str) -> str:
    """Clean headline title, removing source suffix."""
    if " - " in title:
        return title.rsplit(" - ", 1)[0]
    return title


def fetch_rss_feed(query: str, category: str, max_items: int = 10) -> list[NewsHeadline]:
    """
    Fetch and parse a single RSS feed for a query.
    
    Args:
        query: Search query string
        category: Category (GRID, WATER, LOGISTICS, EQUITY)
        max_items: Maximum headlines to return per query
        
    Returns:
        List of NewsHeadline objects with sentiment scores
    """
    url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    
    logger.debug("fetching_rss", query=query, category=category, url=url)
    
    try:
        feed = feedparser.parse(url)
        
        if feed.bozo:
            logger.warning("rss_parse_warning", query=query, error=str(feed.bozo_exception))
        
        headlines = []
        for entry in feed.entries[:max_items]:
            title = clean_title(entry.get("title", ""))
            if not title:
                continue
            
            # Score sentiment
            sentiment = score_sentiment(title)
            
            headline = NewsHeadline(
                title=title,
                source=extract_source(entry),
                url=entry.get("link", ""),
                published_at=parse_published_date(entry),
                query_category=category,
                query_term=query,
                compound_score=sentiment["compound"],
                positive_score=sentiment["positive"],
                negative_score=sentiment["negative"],
                neutral_score=sentiment["neutral"],
                sentiment_label=sentiment["label"],
            )
            headlines.append(headline)
        
        logger.info("rss_fetched", query=query, headlines=len(headlines))
        return headlines
        
    except Exception as e:
        logger.error("rss_fetch_error", query=query, error=str(e))
        return []


def fetch_all_news(max_per_query: int = 5) -> list[NewsHeadline]:
    """
    Fetch news for all Texas Node queries.
    
    Args:
        max_per_query: Max headlines per query term
        
    Returns:
        List of all NewsHeadline objects, sorted by published date
    """
    all_headlines = []
    
    for category, queries in TEXAS_NODE_QUERIES.items():
        for query in queries:
            headlines = fetch_rss_feed(query, category, max_per_query)
            all_headlines.extend(headlines)
    
    # Sort by published date (newest first), None dates at end
    all_headlines.sort(
        key=lambda h: (h.published_at is None, h.published_at),
        reverse=True
    )
    
    # Deduplicate by title (keep first occurrence)
    seen_titles = set()
    unique_headlines = []
    for h in all_headlines:
        title_key = h.title.lower().strip()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_headlines.append(h)
    
    logger.info("all_news_fetched", total=len(unique_headlines))
    return unique_headlines


def fetch_news_by_category(category: str, max_per_query: int = 10) -> list[NewsHeadline]:
    """
    Fetch news for a specific category.
    
    Args:
        category: GRID, WATER, LOGISTICS, or EQUITY
        max_per_query: Max headlines per query term
        
    Returns:
        List of NewsHeadline objects for that category
    """
    if category not in TEXAS_NODE_QUERIES:
        logger.warning("unknown_category", category=category)
        return []
    
    all_headlines = []
    for query in TEXAS_NODE_QUERIES[category]:
        headlines = fetch_rss_feed(query, category, max_per_query)
        all_headlines.extend(headlines)
    
    # Deduplicate
    seen_titles = set()
    unique_headlines = []
    for h in all_headlines:
        title_key = h.title.lower().strip()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_headlines.append(h)
    
    return unique_headlines


# ─────────────────────────────────────────────────────────────
# Aggregation & Summary
# ─────────────────────────────────────────────────────────────


def get_category_summary(headlines: list[NewsHeadline], category: str) -> NewsSummary:
    """
    Generate summary statistics for a category.
    """
    category_headlines = [h for h in headlines if h.query_category == category]
    
    if not category_headlines:
        return NewsSummary(
            category=category,
            headline_count=0,
            avg_sentiment=0.0,
            negative_count=0,
            positive_count=0,
            most_negative=None,
            most_positive=None,
        )
    
    avg_sentiment = sum(h.compound_score for h in category_headlines) / len(category_headlines)
    negative_count = sum(1 for h in category_headlines if h.compound_score < -0.05)
    positive_count = sum(1 for h in category_headlines if h.compound_score > 0.05)
    
    sorted_by_sentiment = sorted(category_headlines, key=lambda h: h.compound_score)
    
    return NewsSummary(
        category=category,
        headline_count=len(category_headlines),
        avg_sentiment=avg_sentiment,
        negative_count=negative_count,
        positive_count=positive_count,
        most_negative=sorted_by_sentiment[0] if sorted_by_sentiment else None,
        most_positive=sorted_by_sentiment[-1] if sorted_by_sentiment else None,
    )


def get_news_summary() -> dict:
    """
    Fetch all news and return summary with headlines.
    
    Returns:
        Dict with headlines list and category summaries
    """
    headlines = fetch_all_news()
    
    summaries = {}
    for category in TEXAS_NODE_QUERIES.keys():
        summaries[category] = get_category_summary(headlines, category)
    
    # Overall sentiment
    if headlines:
        overall_sentiment = sum(h.compound_score for h in headlines) / len(headlines)
    else:
        overall_sentiment = 0.0
    
    # High-impact negative headlines (for ticker tray)
    critical_headlines = [
        h for h in headlines 
        if h.compound_score <= SENTIMENT_THRESHOLDS["VERY_NEGATIVE"]
    ]
    
    return {
        "headlines": headlines,
        "summaries": summaries,
        "overall_sentiment": overall_sentiment,
        "critical_headlines": critical_headlines,
        "total_count": len(headlines),
        "fetched_at": datetime.now(timezone.utc),
    }


def get_sentiment_for_correlation(category: str) -> float:
    """
    Quick sentiment check for correlation engine.
    Returns average sentiment for a category (-1 to 1).
    
    Used by Linked Fate v3 for real-time correlation.
    """
    headlines = fetch_news_by_category(category, max_per_query=5)
    
    if not headlines:
        return 0.0  # Neutral if no news
    
    return sum(h.compound_score for h in headlines) / len(headlines)
