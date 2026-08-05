def test_list_tickets_requires_auth(client):
    res = client.get("/api/v1/tickets")
    assert res.status_code == 401


def test_get_ticket_requires_auth(client):
    import uuid
    res = client.get(f"/api/v1/tickets/{uuid.uuid4()}")
    assert res.status_code == 401
