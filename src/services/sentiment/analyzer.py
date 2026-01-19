"""Sentiment analysis using AWS Comprehend or fallback."""

from dataclasses import dataclass
from typing import Literal

import structlog

from src.core.config import settings

logger = structlog.get_logger()


@dataclass
class SentimentResult:
    """Result from sentiment analysis."""

    sentiment: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"]
    score: float  # -1 to 1 scale (negative to positive)
    confidence: float  # 0 to 1

    # Raw scores
    positive_score: float = 0.0
    negative_score: float = 0.0
    neutral_score: float = 0.0
    mixed_score: float = 0.0


class SentimentAnalyzer:
    """Sentiment analyzer using AWS Comprehend.

    Falls back to simple keyword-based analysis if AWS is not configured.
    """

    def __init__(self) -> None:
        self._comprehend_client = None
        self._use_comprehend = False

        # Try to initialize AWS Comprehend
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            try:
                import boto3

                self._comprehend_client = boto3.client(
                    "comprehend",
                    region_name=settings.aws_region,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                )
                self._use_comprehend = True
                logger.info("AWS Comprehend initialized")
            except Exception as e:
                logger.warning("Failed to initialize AWS Comprehend", error=str(e))
        else:
            logger.info("Using fallback sentiment analysis (AWS not configured)")

    async def analyze(self, text: str, language: str = "en") -> SentimentResult:
        """Analyze sentiment of text.

        Args:
            text: Text to analyze
            language: Language code (default: en)

        Returns:
            SentimentResult
        """
        if not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                score=0.0,
                confidence=1.0,
            )

        if self._use_comprehend:
            return await self._analyze_with_comprehend(text, language)
        else:
            return self._analyze_with_keywords(text)

    async def _analyze_with_comprehend(self, text: str, language: str) -> SentimentResult:
        """Analyze using AWS Comprehend."""
        try:
            # Comprehend has a max text length
            truncated_text = text[:5000] if len(text) > 5000 else text

            response = self._comprehend_client.detect_sentiment(
                Text=truncated_text,
                LanguageCode=language if language in ["en", "es", "fr", "de", "it", "pt"] else "en",
            )

            sentiment = response["Sentiment"]
            scores = response["SentimentScore"]

            # Calculate composite score (-1 to 1)
            composite_score = scores["Positive"] - scores["Negative"]

            # Confidence is the max score
            confidence = max(scores.values())

            result = SentimentResult(
                sentiment=sentiment,
                score=composite_score,
                confidence=confidence,
                positive_score=scores["Positive"],
                negative_score=scores["Negative"],
                neutral_score=scores["Neutral"],
                mixed_score=scores["Mixed"],
            )

            logger.debug(
                "Comprehend sentiment analysis",
                sentiment=sentiment,
                score=round(composite_score, 3),
            )

            return result

        except Exception as e:
            logger.error("Comprehend analysis failed, using fallback", error=str(e))
            return self._analyze_with_keywords(text)

    def _analyze_with_keywords(self, text: str) -> SentimentResult:
        """Simple keyword-based sentiment analysis as fallback.

        This is a basic implementation for when AWS is not available.
        """
        text_lower = text.lower()

        # Keyword lists (simplified)
        positive_words = {
            "good", "great", "excellent", "amazing", "wonderful", "fantastic",
            "happy", "pleased", "satisfied", "thanks", "thank", "love", "perfect",
            "awesome", "helpful", "best", "nice", "appreciate", "gracias", "bien",
            "excelente", "genial", "bueno", "feliz",
        }

        negative_words = {
            "bad", "terrible", "awful", "horrible", "angry", "frustrated",
            "disappointed", "upset", "hate", "worst", "useless", "stupid",
            "annoying", "ridiculous", "unacceptable", "furious", "disgusting",
            "mal", "terrible", "horrible", "enojado", "frustrado", "decepcionado",
        }

        intensifiers = {"very", "really", "extremely", "absolutely", "totally", "muy"}

        # Count matches
        words = set(text_lower.split())
        positive_count = len(words & positive_words)
        negative_count = len(words & negative_words)
        intensifier_count = len(words & intensifiers)

        # Apply intensifier boost
        if intensifier_count > 0:
            positive_count *= 1.5
            negative_count *= 1.5

        # Calculate scores
        total = positive_count + negative_count + 0.1  # Avoid division by zero

        positive_score = positive_count / total if positive_count > 0 else 0.1
        negative_score = negative_count / total if negative_count > 0 else 0.1
        neutral_score = 1 - positive_score - negative_score
        neutral_score = max(0, neutral_score)

        # Normalize
        total_score = positive_score + negative_score + neutral_score
        positive_score /= total_score
        negative_score /= total_score
        neutral_score /= total_score

        # Determine sentiment
        if positive_score > negative_score and positive_score > neutral_score:
            sentiment = "POSITIVE"
        elif negative_score > positive_score and negative_score > neutral_score:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        # Composite score
        composite_score = positive_score - negative_score

        result = SentimentResult(
            sentiment=sentiment,
            score=composite_score,
            confidence=max(positive_score, negative_score, neutral_score),
            positive_score=positive_score,
            negative_score=negative_score,
            neutral_score=neutral_score,
            mixed_score=0.0,
        )

        logger.debug(
            "Keyword sentiment analysis",
            sentiment=sentiment,
            score=round(composite_score, 3),
        )

        return result


# Singleton instance
_sentiment_analyzer: SentimentAnalyzer | None = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    """Get or create the sentiment analyzer singleton."""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = SentimentAnalyzer()
    return _sentiment_analyzer
