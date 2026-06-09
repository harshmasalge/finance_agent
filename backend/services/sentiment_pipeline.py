import re
import structlog
from typing import List, Dict, Tuple
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sqlalchemy.orm import Session
from backend.db.models import SentimentScore

logger = structlog.get_logger(__name__)

class SentimentPipeline:
    def __init__(self, db: Session):
        self.db = db
        self.vader = SentimentIntensityAnalyzer()
        self.finbert = None
        self.tokenizer = None
        self._load_finbert()

    def _load_finbert(self):
        """Lazy load FinBERT to avoid blocking startup if unused."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            
            logger.info("Loading local FinBERT model...")
            self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            self.finbert = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
            self.finbert.eval()
            logger.info("FinBERT loaded successfully.")
        except Exception as e:
            logger.warning("Could not load FinBERT, will fallback to VADER.", error=str(e))

    def clean_text(self, text: str) -> str:
        """Basic text cleaning (remove URLs, special chars, multiple spaces)."""
        text = re.sub(r'http\S+', '', text)
        text = re.sub(r'[^A-Za-z0-9\s.,!?]', '', text)
        return ' '.join(text.split())

    def extract_mentions(self, text: str, tracked_tickers: List[str]) -> List[str]:
        """Naively extract ticker mentions from text."""
        mentions = []
        for ticker in tracked_tickers:
            # Drop the '.NS' suffix for keyword matching
            keyword = ticker.split('.')[0]
            if keyword.upper() in text.upper():
                mentions.append(ticker)
        return mentions

    def score_text(self, text: str) -> float:
        """Score text using FinBERT if available, else VADER. Returns -1.0 to +1.0."""
        text = self.clean_text(text)
        
        if self.finbert and self.tokenizer:
            try:
                import torch
                inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
                with torch.no_grad():
                    outputs = self.finbert(**inputs)
                    probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                    # ProsusAI/finbert outputs: [positive, negative, neutral]
                    pos = probs[0][0].item()
                    neg = probs[0][1].item()
                    # Calculate net score
                    score = pos - neg
                    return score
            except Exception as e:
                logger.error("FinBERT scoring failed, falling back to VADER", error=str(e))
                
        # VADER Fallback
        vader_scores = self.vader.polarity_scores(text)
        return vader_scores['compound']

    def process_and_store(self, text: str, source: str, tracked_tickers: List[str]):
        """Processes an article/post and stores sentiment for mentioned tickers."""
        mentions = self.extract_mentions(text, tracked_tickers)
        if not mentions:
            return

        score = self.score_text(text)
        
        for ticker in mentions:
            sentiment_entry = SentimentScore(
                ticker=ticker,
                score=score,
                source_count=1,
                confidence=1.0 if self.finbert else 0.5 # Lower confidence if using fallback
            )
            self.db.add(sentiment_entry)
            
        self.db.commit()
        logger.info("Stored sentiment scores", source=source, tickers=mentions, score=score)
