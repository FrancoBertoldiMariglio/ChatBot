"""Tests for sentiment analysis."""

import pytest

from src.services.sentiment.analyzer import SentimentAnalyzer


@pytest.fixture
def analyzer():
    """Create sentiment analyzer (uses fallback since AWS not configured in tests)."""
    return SentimentAnalyzer()


@pytest.mark.asyncio
async def test_positive_sentiment(analyzer):
    """Test positive sentiment detection."""
    result = await analyzer.analyze("I love this product! It's amazing and fantastic!")
    assert result.sentiment == "POSITIVE"
    assert result.score > 0


@pytest.mark.asyncio
async def test_negative_sentiment(analyzer):
    """Test negative sentiment detection."""
    result = await analyzer.analyze("This is terrible and I hate it. Worst experience ever!")
    assert result.sentiment == "NEGATIVE"
    assert result.score < 0


@pytest.mark.asyncio
async def test_neutral_sentiment(analyzer):
    """Test neutral sentiment detection."""
    result = await analyzer.analyze("The item arrived on Tuesday.")
    assert result.sentiment == "NEUTRAL"
    assert abs(result.score) < 0.5


@pytest.mark.asyncio
async def test_empty_text(analyzer):
    """Test handling of empty text."""
    result = await analyzer.analyze("")
    assert result.sentiment == "NEUTRAL"
    assert result.score == 0.0
