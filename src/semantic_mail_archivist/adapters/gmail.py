from __future__ import annotations

from dataclasses import dataclass, field

from ..model import LabelClass


GMAIL_SYSTEM_LABELS = frozenset(
    {
        "INBOX",
        "SPAM",
        "TRASH",
        "UNREAD",
        "STARRED",
        "IMPORTANT",
        "SENT",
        "DRAFT",
        "CATEGORY_PERSONAL",
        "CATEGORY_SOCIAL",
        "CATEGORY_PROMOTIONS",
        "CATEGORY_UPDATES",
        "CATEGORY_FORUMS",
    }
)


@dataclass(frozen=True)
class GmailLabelClassifier:
    """Classify Gmail-visible labels without calling the Gmail API.

    Operational labels are explicit configuration because their semantics belong
    to the user, not Gmail. Any non-system, non-operational Gmail label is treated
    as a user semantic label for gap detection.
    """

    operational_labels: frozenset[str] = field(default_factory=frozenset)

    def classify(self, label: str) -> LabelClass:
        if label in GMAIL_SYSTEM_LABELS:
            return LabelClass.SYSTEM
        if label in self.operational_labels:
            return LabelClass.USER_OPERATIONAL
        return LabelClass.USER_SEMANTIC
