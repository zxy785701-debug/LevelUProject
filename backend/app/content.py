import re
from .errors import AppError

# Conservative local rules for explicitly harmful content; not a moderation service.
_BLOCKED = (
    re.compile(r"(?:制作|制造|自制).{0,12}(?:炸弹|爆炸物)"),
    re.compile(r"(?:未成年人?|儿童|幼女).{0,12}(?:色情|裸照|性行为)"),
)

def check_content(text: str) -> None:
    compact = re.sub(r"\s+", "", text)
    if any(pattern.search(compact) for pattern in _BLOCKED):
        raise AppError("CONTENT_BLOCKED", "请使用适合学习的内容")
