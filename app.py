# ==== app.py ====
# Jalankan: streamlit run app.py

import sys
import asyncio

# 🔧 FIX WAJIB untuk Windows agar Playwright bisa spawn subprocess
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 🔧 Izinkan nested event loop dalam Streamlit
import nest_asyncio
nest_asyncio.apply()

import streamlit as st
import pandas as pd
from scraper import (
    can_fetch_robots,
    detect_captcha_from_html,
    scrape_with_requests,
    scrape_with_playwright,          # wrapper sync -> async (pakai asyncio.run di dalam)
    multi_page_scrape,               # meng-handle multi halaman + auto_extract/selector
)

st.set_page_config(page_title="Universal Scraper — Streamlit + Playwright", layout="wide")
st.title("🌐 Universal Web Scraper (Streamlit + Playwright)")

with st.sidebar:
    st.header("Settings")
    default_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    user_agent = st.text_input("User-Agent", value=default_ua)
    use_playwright = st.checkbox("Gunakan Playwright (untuk halaman dinamis / JS)", value=True)
    headless = st.checkbox("Headless mode", value=True)
    max_pages = st.number_input("Jumlah halaman (paginasi)", min_value=1, max_value=100, value=3)
    delay = st.number_input("Delay antar halaman (detik)", min_value=0.0, value=1.0, step=0.5)
    selector = st.text_input("CSS Selector (opsional; kosong = auto-extract)", value="")
    follow_pagination = st.checkbox("Coba deteksi tombol Next (paginasi)", value=True)

st.info("⚠️ Tool ini **tidak** membypass CAPTCHA. Jika terdeteksi, proses akan dihentikan.")

url = st.text_input("Masukkan URL target", "https://books.toscrape.com/")

col1, col2 = st.columns(2)
with col1:
    start_btn = st.button("🚀 Mulai Scrape")
with col2:
    example_btn = st.button("Gunakan contoh URL aman")

if example_btn:
    url = "https://books.toscrape.com/"
    st.rerun()

if start_btn:
    if not url.strip():
        st.warning("Masukkan URL terlebih dahulu.")
        st.stop()

    # robots.txt check ringan
    allowed, reason = can_fetch_robots(url, user_agent=user_agent)
    if not allowed:
        st.error(f"❌ Scraping diblokir oleh robots.txt: {reason}")
        st.stop()

    headers = {"User-Agent": user_agent}

    # --- Ambil satu halaman dulu untuk cek CAPTCHA (sesuai mode) ---
    with st.spinner("Mengambil halaman awal untuk cek CAPTCHA..."):
        try:
            if use_playwright:
                html_first = scrape_with_playwright(url, headless=headless, user_agent=user_agent)
            else:
                html_first = scrape_with_requests(url, headers=headers, timeout=60)
        except Exception as e:
            st.error(f"Gagal mengambil halaman awal: {e}")
            st.stop()

    if detect_captcha_from_html(html_first):
        st.error("🚨 CAPTCHA terdeteksi pada halaman awal. Hentikan proses otomatis.")
        st.stop()

    # --- Lanjut multi page scrape ---
    with st.spinner("Scraping berjalan..."):
        try:
            df = multi_page_scrape(
                url=url,
                max_pages=int(max_pages),
                use_playwright=use_playwright,
                headers=headers,
                delay=float(delay),
                selector=selector.strip() or None,
                headless=headless,
                user_agent=user_agent,
                follow_pagination=follow_pagination,
            )
        except Exception as e:
            st.error(f"Gagal melakukan scraping: {e}")
            st.stop()

    # --- Tampilkan hasil & ekspor ---
    if isinstance(df, list):
        # Jika fungsi mengembalikan list DataFrame (per halaman)
        st.success(f"✅ Berhasil! Terkumpul {len(df)} halaman.")
        for i, part in enumerate(df, start=1):
            st.subheader(f"Hasil Halaman {i}")
            st.dataframe(part.head(100))
        # Gabungkan untuk ekspor
        try:
            merged = pd.concat(df, ignore_index=True)
            csv = merged.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download Semua (CSV)", data=csv, file_name="scraped_data.csv", mime="text/csv")
        except Exception:
            pass
    else:
        st.success(f"✅ Berhasil! Total baris: {len(df)}")
        st.subheader("Preview Data")
        st.dataframe(df.head(200))
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv, file_name="scraped_data.csv", mime="text/csv")
