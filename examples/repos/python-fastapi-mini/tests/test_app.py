from app import get_user


def test_get_user_returns_email():
    assert get_user("1")["email"] == "ada@example.com"
