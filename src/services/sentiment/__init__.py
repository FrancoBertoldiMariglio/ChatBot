"""Sentiment analysis service."""

from src.services.sentiment.analyzer import SentimentAnalyzer, SentimentResult, get_sentiment_analyzer

__all__ = ["SentimentAnalyzer", "SentimentResult", "get_sentiment_analyzer"]
