from app.core.logging import mask_secrets


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_mask_secrets():
    text = "cookie2=abcdef123456789; unb=2200123456789; foo=bar"
    masked = mask_secrets(text)
    assert "abcdef123456789" not in masked
    assert "2200123456789" not in masked
    assert "foo=bar" in masked
