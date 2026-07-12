# Computer-Use manual smoke tests

## 1. llama-server: json_schema + image
Prereq: llama-server running with `--jinja` and an `--mmproj` (vision) model.

    cd back-end && python tests/smoke_json_schema_image.py

PASS: prints `PARSED: {...}` with a valid action.
FAIL (e.g. server rejects json_schema with image, or returns prose): switch
`ComputerUseDecider` to prompt-enforced JSON — append "Respond ONLY with a JSON
object" to the decider prompt, drop `response_format`, and parse with a tolerant
`json.loads` that strips ```json fences. The rest of the loop is unchanged.

## 2. ScreenParse over the wire
Prereq: shore-ai-service deployed with the ScreenParse servicer + weights,
Health shows `screenparse.loaded=true`.

    cd back-end && python - <<'PY'
    import asyncio, base64
    from app.services.ai_client import channel
    from app.services.ai_client.screenparse import screenparse_client
    from app.tools.screen_tools import _capture_screen_b64
    async def main():
        channel.init()
        png = base64.b64decode(_capture_screen_b64())  # jpeg ok too
        res = await screenparse_client.parse(png)
        print("elements:", len(res.elements), "dims:", res.width, res.height)
        for e in res.elements[:10]:
            print(e.id, e.type, repr(e.content), e.interactable)
    asyncio.run(main())
    PY

PASS: prints a non-empty element list with sensible captions.
