import httpx, asyncio

async def test():
    c = httpx.AsyncClient()
    
    # Test with dub=true for English audio
    r = await c.get("http://localhost:8000/api/stream?anime_id=1535&episode=1&dub=true", timeout=30)
    data = r.json()
    print(f"Source: {data.get('data',{}).get('source','?')}")
    print(f"Subtitles: {data.get('data',{}).get('subtitles',[])}")
    if data.get('status') == 'success':
        print(f"URL: {data['data']['video_url'][:70]}...")
    else:
        print(f"Error: {data}")

asyncio.run(test())
