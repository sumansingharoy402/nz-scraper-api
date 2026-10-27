import asyncio
import json
import logging
import random
import re
from typing import AsyncGenerator, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_proxy_auth import ProxyPool
from bs4 import BeautifulSoup

# ------------------------------------------------------------------
# লগিং কনফিগারেশন
# ------------------------------------------------------------------
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

file_handler = logging.FileHandler("scraper_output.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger("NZ_Commercial_DetailStreamer")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ------------------------------------------------------------------

class HumanLikeInterface:
    def __init__(self, page: Page):
        self.page = page

    async def random_sleep(self, min_sec: float = 2.0, max_sec: float = 4.0):
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def move_mouse_randomly(self):
        try:
            viewport = self.page.viewport_size
            if viewport:
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await self.page.mouse.move(x, y, steps=random.randint(10, 20))
        except Exception:
            pass

class NZCommercialPropertyScraper:
    BASE_URL = "https://www.realestate.co.nz"
    COMMERCIAL_SEARCH_URL = "https://www.realestate.co.nz/commercial/sale"

    def __init__(self, max_pages: int = 150, proxy_gateway: Optional[str] = None, headless: bool = False):
        self.max_pages = max_pages
        self.proxy_gateway = proxy_gateway
        self.headless = headless
        self.results_count = 0
        self.seen_urls = set()

    async def _extract_detail_page(self, page: Page, detail_url: str, basic_data: dict) -> dict:
        """
        ডিটেইল পেজে গিয়ে এজেন্টের নাম, ফোন এবং ইমেইল বের করে।
        এখানে Auto-Update (Self-Healing) লজিক যুক্ত করা হয়েছে।
        """
        try:
            logger.info(f"Visiting detail page: {detail_url}")
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(2.0, 4.0)) 

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # ---------------------------------------------------------
            # ১. ফোন নম্বর বের করা (Auto-Update Fallback লজিক)
            # ---------------------------------------------------------
            phone = None
            # প্রথমে সরাসরি tel: লিংক খুঁজবে
            phone_link = soup.select_one("a[href^='tel:']")
            if phone_link:
                phone = phone_link.get("href").replace("tel:", "").strip()
            else:
                # যদি tel: লিংক না থাকে, তবে পেজের টেক্সটে ফোন নম্বরের প্যাটার্ন খুঁজবে
                phone_pattern = r'(?:\+?64|0)\s?\d{1,2}[\s-]?\d{3,4}[\s-]?\d{3,4}'
                match = re.search(phone_pattern, soup.get_text())
                if match:
                    phone = match.group(0).strip()
            
            basic_data["agent_phone"] = phone

            # ---------------------------------------------------------
            # ২. ইমেইল বের করা (Auto-Update Fallback লজিক)
            # ---------------------------------------------------------
            email = None
            # প্রথমে mailto: লিংক খুঁজবে
            email_link = soup.select_one("a[href^='mailto:']")
            if email_link:
                email = email_link.get("href").replace("mailto:", "").split("?")[0].strip()
            else:
                # যদি mailto: না থাকে, তবে রেগেক্স দিয়ে যেকোনো ইমেইল খুঁজবে
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                emails = re.findall(email_pattern, html)
                if emails:
                    # ওয়েবসাইটের নিজস্ব ইমেইল বাদ দেওয়ার লজিক
                    valid_emails = [e for e in emails if "realestate.co.nz" not in e.lower()]
                    if valid_emails:
                        email = valid_emails[0]
            
            basic_data["agent_email"] = email

            # ---------------------------------------------------------
            # ৩. এজেন্টের নাম বের করা (Fallback Selectors)
            # ---------------------------------------------------------
            # একাধিক সিলেক্টর দিয়ে চেষ্টা করবে। যেটি আগে পাবে, সেটিই নেবে।
            name_selectors = [
                "h3.agent-name", 
                ".agent-details h3", 
                "[class*='agent-name']",
                "[class*='contact-name']",
                "h4[class*='name']"
            ]
            
            for selector in name_selectors:
                name_el = soup.select_one(selector)
                if name_el and name_el.get_text(strip=True):
                    basic_data["agent_name"] = name_el.get_text(strip=True)
                    break

        except Exception as e:
            logger.error(f"Error extracting details from {detail_url}: {e}")
            
        return basic_data

    async def stream_commercial_listings(self) -> AsyncGenerator[Dict[str, Any], None]:
        proxy_pool = None
        if self.proxy_gateway:
            try:
                proxy_pool = ProxyPool(gateway=self.proxy_gateway)
                logger.info("Residential Proxy Pool initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize ProxyPool: {e}")
                logger.warning("Running WITHOUT proxy. Expect blocks after a few pages.")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])

            for page_num in range(1, self.max_pages + 1):
                if self.results_count >= 4000:
                    logger.info("Reached 4000 limit. Stopping.")
                    break

                proxy_config = None
                if proxy_pool:
                    try:
                        proxy_config = proxy_pool.get()
                        logger.info(f"Page {page_num}: Using rotated residential proxy IP.")
                    except Exception as e:
                        logger.error(f"Proxy rotation failed: {e}. Continuing without proxy for this page.")
                else:
                    if self.proxy_gateway:
                        parsed = urlparse(self.proxy_gateway)
                        proxy_config = {
                            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                            "username": parsed.username,
                            "password": parsed.password
                        }

                context: BrowserContext = await browser.new_context(
                    proxy=proxy_config,
                    viewport={"width": 1366, "height": 768},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                page = await context.new_page()
                human = HumanLikeInterface(page)

                if page_num == 1:
                    page_url = self.COMMERCIAL_SEARCH_URL
                else:
                    sep = "&" if "?" in self.COMMERCIAL_SEARCH_URL else "?"
                    page_url = f"{self.COMMERCIAL_SEARCH_URL}{sep}page={page_num}"

                logger.info(f"Streaming Search Page {page_num}: {page_url}")

                try:
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                    await human.random_sleep(2, 4)
                    await human.move_mouse_randomly()

                    card_links = await page.evaluate("""
                        () => {
                            const links = [];
                            const cards = document.querySelectorAll("div[class*='listing'], article[class*='listing']");
                            cards.forEach(card => {
                                const a = card.querySelector("a[href*='/commercial/'], a[href*='/property/']");
                                if (a && a.href) links.push(a.href);
                            });
                            return links;
                        }
                    """)

                    if not card_links:
                        logger.warning(f"No cards found on page {page_num}. Stopping.")
                        break

                    logger.info(f"Found {len(card_links)} properties on page {page_num}.")

                    for link in card_links:
                        if self.results_count >= 4000:
                            break

                        if link in self.seen_urls:
                            continue
                        self.seen_urls.add(link)

                        try:
                            listing_data = {
                                "url": link,
                                "listing_id": re.search(r"/(\d+)/", link).group(1) if re.search(r"/(\d+)/", link) else "Unknown",
                                "title": "Commercial Property",
                                "price": "By Negotiation",
                                "property_type": "Commercial",
                                "source": "realestate.co.nz",
                                "extraction_mode": "direct_stream_detail"
                            }

                            final_data = await self._extract_detail_page(page, link, listing_data)
                            
                            self.results_count += 1
                            
                            formatted_json = json.dumps(final_data, indent=4, ensure_ascii=False)
                            logger.info(f"\n--- Extracted Property {self.results_count} / 4000 ---\n{formatted_json}\n")
                            
                            yield final_data
                            
                            await asyncio.sleep(random.uniform(2.0, 4.0))

                        except Exception as e:
                            logger.error(f"Error processing link {link}: {e}")
                            continue

                except Exception as e:
                    logger.error(f"Error processing page {page_num}: {e}")
                finally:
                    await context.close()
                
                await asyncio.sleep(random.uniform(3.0, 6.0))

            await browser.close()
            logger.info(f"Streaming Complete. Total properties extracted: {self.results_count}")

async def main():
    RESIDENTIAL_PROXY_GATEWAY = None 

    scraper = NZCommercialPropertyScraper(
        max_pages=150, 
        proxy_gateway=RESIDENTIAL_PROXY_GATEWAY,
        headless=False
    )
    
    print("=" * 80)
    print(" STARTING DIRECT STREAMING (LIMIT: 4000) WITH AUTO-UPDATE LOGIC ")
    print("=" * 80)

    async for property_data in scraper.stream_commercial_listings():
        pass

if __name__ == "__main__":
    asyncio.run(main())