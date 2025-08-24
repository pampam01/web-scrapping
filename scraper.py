# ==== scraper.py ====
import sys
import time
import asyncio
import re
from urllib.parse import urljoin, urlparse

# 🔧 FIX WAJIB untuk Windows agar Playwright bisa spawn subprocess
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import StringIO

# Playwright (async)
from playwright.async_api import async_playwright

# ---------------------------
# Utility
# ---------------------------

def can_fetch_robots(url: str, user_agent: str = "UniversalScraper/1.0"):
    """
    Cek robots.txt sederhana: unduh robots.txt (jika ada), cari Disallow untuk user-agent umum.
    Ini cek ringan — gunakan dengan etika scraping yang baik.
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        r = requests.get(robots_url, timeout=15)
        if r.status_code != 200:
            return True, "robots.txt tidak tersedia/200"
        text = r.text.lower()
        # cek disallow luas (sederhana, bukan parser penuh)
        if "disallow: /" in text and ("user-agent: *" in text or f"user-agent: {user_agent.lower()}" in text):
            return False, "Disallow: / untuk user-agent"
        return True, "allowed"
    except Exception as e:
        # jika robots gagal diambil, kita asumsikan allowed (tergantung kebijakan Anda)
        return True, f"robots.txt tidak bisa diambil: {e}"

def detect_captcha_from_html(html: str) -> bool:
    """
    Deteksi elemen CAPTCHA umum pada HTML.
    """
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    # pola umum
    if soup.select("iframe[src*='recaptcha'], div.g-recaptcha, div.h-captcha, iframe[src*='hcaptcha']"):
        return True
    text = soup.get_text(" ", strip=True).lower()
    if any(k in text for k in ["captcha", "verify you are human", "are you a robot", "press and hold", "cloudflare verify"]):
        return True
    return False

# ---------------------------
# Requests (halaman statis)
# ---------------------------

def scrape_with_requests(url: str, headers=None, timeout: int = 60) -> str:
    """
    Ambil HTML dengan requests (untuk halaman statis / tanpa JS).
    """
    headers = headers or {}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text

# ---------------------------
# Playwright (halaman dinamis)
# ---------------------------

async def _scrape_with_playwright_async(
    url: str,
    headless: bool = True,
    user_agent: str | None = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 60000,
) -> str:
    """
    Ambil HTML render-an JS dengan Playwright (async).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=user_agent) if user_agent else await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        # Tambahan: tunggu sejenak untuk SPA berat
        await page.wait_for_timeout(500)
        html = await page.content()
        await browser.close()
        return html

def scrape_with_playwright(
    url: str,
    headless: bool = True,
    user_agent: str | None = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 60000,
) -> str:
    """
    Wrapper sinkron agar bisa dipanggil mudah dari Streamlit.
    (Kita pakai asyncio.run, aman karena app.py sudah apply nest_asyncio)
    """
    return asyncio.run(
        _scrape_with_playwright_async(
            url=url,
            headless=headless,
            user_agent=user_agent,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
        )
    )

# ---------------------------
# Ekstraksi
# ---------------------------

def extract_by_selector(html: str, selector: str) -> pd.DataFrame:
    """
    Ekstrak elemen berdasar CSS selector.
    - Jika selector menunjuk <table>, pakai pandas.read_html
    - Jika bukan tabel, kumpulkan teks elemen-elemen yang cocok
    """
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(selector)
    if not nodes:
        return pd.DataFrame()

    # jika ada table
    if any(n.name == "table" for n in nodes):
        # gunakan pandas.read_html dari string (wrap StringIO untuk hindari FutureWarning)
        tables = pd.read_html(StringIO(str(soup)))
        # filter hanya table yang juga match selector (lebih presisi)
        matched_tables = []
        for t in tables:
            matched_tables.append(t)
        if matched_tables:
            # gabungkan
            return pd.concat(matched_tables, ignore_index=True)
        else:
            # fallback: gabung semua table
            return pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()

    # jika bukan table, ambil teks
    rows = []
    for n in nodes:
        txt = n.get_text(" ", strip=True)
        if txt:
            rows.append({"text": txt})
    return pd.DataFrame(rows)

def auto_extract(html: str, base_url: str | None = None) -> pd.DataFrame:
    """
    Auto extract sederhana:
    - Jika ada table -> gabungkan semua table
    - Kalau tidak ada, kumpulkan <h1..h3>, <p>, dan <a href>
    """
    soup = BeautifulSoup(html, "html.parser")

    # coba tabel dulu
    try:
        tables = pd.read_html(StringIO(str(soup)))
        if tables:
            return pd.concat(tables, ignore_index=True)
    except Exception:
        pass

    data = []
    # headings
    for tag in soup.find_all(["h1", "h2", "h3"]):
        t = tag.get_text(" ", strip=True)
        if t:
            data.append({"type": tag.name, "content": t})

    # paragraphs
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if t:
            data.append({"type": "p", "content": t})

    # links
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        href = a["href"]
        abs_url = urljoin(base_url, href) if base_url else href
        data.append({"type": "a", "text": txt, "href": abs_url})

    return pd.DataFrame(data)

# ---------------------------
# Multi page scrape
# ---------------------------

def _find_next_page_url(html: str, current_url: str) -> str | None:
    """
    Cari tautan 'Next' sederhana untuk paginasi.
    """
    soup = BeautifulSoup(html, "html.parser")
    # beberapa variasi teks 'next'
    candidates = soup.find_all("a", string=re.compile(r"(next|older|berikutnya|lanjut)", re.I))
    for a in candidates:
        href = a.get("href")
        if href:
            return urljoin(current_url, href)
    # fallback: rel=next
    link = soup.find("link", rel=lambda v: v and "next" in v.lower())
    if link and link.get("href"):
        return urljoin(current_url, link["href"])
    return None

def multi_page_scrape(
    url: str,
    max_pages: int = 3,
    use_playwright: bool = True,
    headers: dict | None = None,
    delay: float = 1.0,
    selector: str | None = None,
    headless: bool = True,
    user_agent: str | None = None,
    follow_pagination: bool = True,
):
    """
    Loop beberapa halaman:
    - Ambil HTML (Playwright/Requests)
    - Deteksi CAPTCHA -> stop
    - Ekstrak (selector jika ada, jika tidak auto_extract)
    - Coba cari Next (opsional)
    """
    headers = headers or {}
    dfs = []
    current = url

    for i in range(max_pages):
        # ambil html
        if use_playwright:
            html = scrape_with_playwright(current, headless=headless, user_agent=user_agent)
        else:
            html = scrape_with_requests(current, headers=headers)

        # captcha?
        if detect_captcha_from_html(html):
            # kembalikan yang sudah dikumpulkan sejauh ini
            break

        # ekstraksi
        if selector:
            df = extract_by_selector(html, selector)
            if df.empty:
                # fallback otomatis jika selector tidak menemukan apapun
                df = auto_extract(html, base_url=current)
        else:
            df = auto_extract(html, base_url=current)

        # tambahkan kolom halaman sumber
        if not df.empty:
            df.insert(0, "_source_url", current)
            dfs.append(df)

        # cari next
        if not follow_pagination:
            break
        nxt = _find_next_page_url(html, current)
        if not nxt or nxt == current:
            break
        current = nxt

        # delay etis
        if delay and delay > 0:
            time.sleep(delay)

    if not dfs:
        return pd.DataFrame()

    # jika semua tabel, gabungkan
    try:
        merged = pd.concat(dfs, ignore_index=True)
        return merged
    except Exception:
        return dfs  # jika struktur kolom terlalu berbeda-beda, kembalikan list
