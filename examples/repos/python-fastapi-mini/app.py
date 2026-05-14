from fastapi import FastAPI, HTTPException

app = FastAPI()

USERS = {
    "1": {"id": "1", "email": "ada@example.com", "active": True},
}


def get_user(user_id: str) -> dict:
    user = USERS.get(user_id)
    if user is None:
        raise KeyError(user_id)
    return user


@app.get("/users/{user_id}")
def read_user(user_id: str) -> dict:
    try:
        return get_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
