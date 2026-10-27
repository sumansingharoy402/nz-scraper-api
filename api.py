from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from scraper import NZCommercialPropertyScraper

app = FastAPI(title="NZ Commercial Real Estate API")

# Bubble.io বা অন্য যেকোনো জায়গা থেকে রিকোয়েস্ট আসার জন্য CORS অনুমতি
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def run_scraper(
    pages: int = Query(default=2, description="Number of pages to scrape (e.g., 5, 10)")
):
    """
    Bubble.io will send a GET request to this endpoint.
    Example: https://your-api.com/scrape?pages=5
    """
    try:
        # আপনার scraper.py-র ক্লাসটি কল করা হচ্ছে (কোনো location প্যারামিটার ছাড়া)
        scraper = NZCommercialPropertyScraper(
            max_pages=pages,
            headless=True # সার্ভারে চালানোর জন্য True
        )
        
        results = []
        
        # আপনার স্ক্র্যাপারের জেনারেটর থেকে ডেটা সংগ্রহ করা
        async for data in scraper.stream_commercial_listings():
            results.append(data)
            
        # Bubble.io-র জন্য JSON রেসপন্স
        return {
            "status": "success",
            "count": len(results),
            "pages_scraped": pages,
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)