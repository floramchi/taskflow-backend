def test_signup_returns_user_without_password_hash(client):
    resp = client.post("/auth/signup", json={"email": "a@example.com", "password": "password123"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "a@example.com"
    assert "password" not in resp.text


def test_duplicate_email_returns_409(client):
    body = {"email": "a@example.com", "password": "password123"}
    client.post("/auth/signup", json=body)
    assert client.post("/auth/signup", json=body).status_code == 409


def test_login_with_wrong_password_returns_401(client):
    client.post("/auth/signup", json={"email": "a@example.com", "password": "password123"})
    resp = client.post("/auth/login", data={"username": "a@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_returns_token_that_works_on_me(client, create_user):
    headers = create_user("a@example.com")
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "a@example.com"


def test_me_without_token_returns_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_invalid_token_returns_401(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_password_hash_never_in_any_response(client):
    body = {"email": "a@example.com", "password": "password123"}
    responses = [
        client.post("/auth/signup", json=body),
        client.post("/auth/login", data={"username": body["email"], "password": body["password"]}),
    ]
    token = responses[1].json()["access_token"]
    responses.append(client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}))
    for resp in responses:
        assert "password_hash" not in resp.text
        assert "$2b$" not in resp.text
