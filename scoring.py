"""
AI Visibility Score Framework
Implements scoring logic as per requirements
"""
from dataclasses import dataclass
from typing import List


@dataclass
class BrandScore:
    """Per-prompt brand score"""
    brand: str
    mentioned: bool
    rank: int | None  # 1-based position
    citation_type: str  # 'official', 'other', 'none'

    @property
    def mention_score(self) -> int:
        """Brand Mention Score: 1 if mentioned, 0 if not"""
        return 1 if self.mentioned else 0

    @property
    def ranking_score(self) -> int:
        """
        Ranking Score per prompt:
        Rank 1 → 100
        Rank 2 → 80
        Rank 3 → 60
        Rank 4 → 40
        Rank 5 → 20
        Rank 6+ → 0
        """
        if not self.mentioned or self.rank is None:
            return 0

        score_map = {
            1: 100,
            2: 80,
            3: 60,
            4: 40,
            5: 20,
        }

        if self.rank <= 5:
            return score_map[self.rank]
        else:
            return 0  # Rank 6+

    @property
    def citation_score(self) -> int:
        """
        Citation Score:
        Official site cited → 100
        Other site cited → 50
        No citation → 0
        """
        if self.citation_type == 'official':
            return 100
        elif self.citation_type == 'other':
            return 50
        else:
            return 0


def calculate_ai_visibility_score(brand_scores: List[BrandScore]) -> dict:
    """
    Calculate aggregate AI Visibility Score for a brand

    AI Visibility Score = (Mention Score × 40%) + (Ranking Score × 40%) + (Citation Score × 20%)

    Args:
        brand_scores: List of BrandScore objects across all prompts

    Returns:
        dict with mention_score, ranking_score, citation_score, ai_visibility_score
    """
    if not brand_scores:
        return {
            "mention_score": 0,
            "ranking_score": 0,
            "citation_score": 0,
            "ai_visibility_score": 0,
            "total_prompts": 0,
            "mention_count": 0,
            "mention_rate": 0,
        }

    total_prompts = len(brand_scores)
    mention_count = sum(1 for s in brand_scores if s.mentioned)

    # Brand Mention Score = (Total prompts mentioning brand / Total prompts) × 100
    mention_score = (mention_count / total_prompts) * 100

    # Ranking Score = Average ranking score across ALL prompts
    ranking_scores = [s.ranking_score for s in brand_scores]
    ranking_score = sum(ranking_scores) / len(ranking_scores)

    # Citation Score = Average citation score across ALL prompts
    citation_scores = [s.citation_score for s in brand_scores]
    citation_score = sum(citation_scores) / len(citation_scores)

    # AI Visibility Score (final)
    ai_visibility_score = (
        (mention_score * 0.40) +
        (ranking_score * 0.40) +
        (citation_score * 0.20)
    )

    return {
        "mention_score": round(mention_score, 2),
        "ranking_score": round(ranking_score, 2),
        "citation_score": round(citation_score, 2),
        "ai_visibility_score": round(ai_visibility_score, 2),
        "total_prompts": total_prompts,
        "mention_count": mention_count,
        "mention_rate": round((mention_count / total_prompts) * 100, 2),
    }


def get_score_grade(ai_visibility_score: float) -> str:
    """
    Convert AI Visibility Score to letter grade

    S+: 90-100 (Dominant)
    S:  80-89  (Excellent)
    A:  70-79  (Strong)
    B:  60-69  (Good)
    C:  50-59  (Fair)
    D:  40-49  (Weak)
    F:  <40    (Poor)
    """
    if ai_visibility_score >= 90:
        return "S+"
    elif ai_visibility_score >= 80:
        return "S"
    elif ai_visibility_score >= 70:
        return "A"
    elif ai_visibility_score >= 60:
        return "B"
    elif ai_visibility_score >= 50:
        return "C"
    elif ai_visibility_score >= 40:
        return "D"
    else:
        return "F"
