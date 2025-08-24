import asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ==============================
# SCRAPER WITH REQUESTS (fallback)
# ==============================
def scrape_with_requests(url: str) -> str:
    """
    Simple scraping using requests (for static HTML).
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/114.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        return f"<html><body><h1>Error with requests: {e}</h1></body></html>"


# ==============================
# SCRAPER WITH PLAYWRIGHT (async)
# ==============================
async def scrape_with_playwright(url: str, headless: bool = True) -> str:
    """
    Scrape a page using Playwright (handles JavaScript-rendered content).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=60000)
            html = await page.content()
        except Exception as e:
            html = f"<html><body><h1>Error with Playwright: {e}</h1></body></html>"
        await browser.close()
        return html


# ==============================
# EXTRACT DATA (BeautifulSoup)
# ==============================
def extract_by_selector(html: str, selector: str):
    """
    Extract text content from HTML using a CSS selector.
    """
    soup = BeautifulSoup(html, "lxml")
    elements = soup.select(selector)
    return [el.get_text(strip=True) for el in elements]


# ==============================
# AUTO SCRAPER DEMO (Books to Scrape)
# ==============================
async def auto_extract_books(url="http://books.toscrape.com/"):
    """
    Demo: extract book titles and prices from Books to Scrape.
    """
    html = await scrape_with_playwright(url)
    soup = BeautifulSoup(html, "lxml")
    titles = [a.get_text(strip=True) for a in soup.select("h3 a")]
    prices = [p.get_text(strip=True) for p in soup.select(".price_color")]
    return list(zip(titles, prices))


# ==============================
# FOR DIRECT TESTING
# ==============================
if __name__ == "__main__":
    url = "http://books.toscrape.com/"
    print("Scraping with requests...")
    html_req = scrape_with_requests(url)
    print("Length (requests):", len(html_req))

    print("Scraping with playwright (async)...")
    html_play = asyncio.run(scrape_with_playwright(url))
    print("Length (playwright):", len(html_play))

    print("Extracting sample data...")
    books = asyncio.run(auto_extract_books(url))
    for title, price in books[:5]:
        print(title, "-", price)
