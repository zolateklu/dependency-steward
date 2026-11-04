import httpx

from steward.providers import GitHub


async def test_repository_endpoint_has_no_trailing_slash():
    paths = []

    async def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/fixture"):
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        return httpx.Response(200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await GitHub("fake", "owner/fixture", client).head()
    assert paths == ["/repos/owner/fixture", "/repos/owner/fixture/commits/main"]
