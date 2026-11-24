"""The error shape in tests: `plain(res)` is the body reduced to {"detail": ...}, for tests that check the sentence only."""


def plain(res):
    body = res.json() if hasattr(res, "json") else res
    return {"detail": body["detail"]} if isinstance(body, dict) and "code" in body else body
