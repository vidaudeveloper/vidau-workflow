"""测试账号 — 与正式账号批次数据隔离（editor 仅见本人批次）。"""

TEST_ACCOUNT_EMAIL = "test@vidau.info"
TEST_ACCOUNT_LOGIN_ALIASES = frozenset({"test", TEST_ACCOUNT_EMAIL})


def normalize_login_email(raw: str) -> str:
    e = (raw or "").strip().lower()
    if e == "test":
        return TEST_ACCOUNT_EMAIL
    return e


def is_test_user(user: dict | None) -> bool:
    if not user:
        return False
    if int(user.get("is_test") or 0):
        return True
    return normalize_login_email(user.get("email", "")) == TEST_ACCOUNT_EMAIL
