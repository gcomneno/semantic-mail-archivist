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
        "CHAT",
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
    to the user, not Gmail. System labels are configurable so a future Gmail API
    adapter can pass provider metadata instead of depending only on built-in
    well-known names.
    """

    operational_labels: frozenset[str] = field(default_factory=frozenset)
    system_labels: frozenset[str] = field(default_factory=lambda: GMAIL_SYSTEM_LABELS)

    def classify(self, label: str) -> LabelClass:
        if label in self.system_labels:
            return LabelClass.SYSTEM
        if label in self.operational_labels:
            return LabelClass.USER_OPERATIONAL
        return LabelClass.USER_SEMANTIC
