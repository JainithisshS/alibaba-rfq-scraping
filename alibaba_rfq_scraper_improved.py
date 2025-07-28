"""
Improved Alibaba RFQ Scraper
This script scrapes RFQ (Request for Quotation) listings from Alibaba sourcing website
with better data extraction and deduplication.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
import json
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import random
import hashlib

class ImprovedAlibabaRFQScraper:
    def __init__(self):
        self.base_url = "https://sourcing.alibaba.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.driver = None
        self.scraped_data = []
        self.seen_urls = set()  # To avoid duplicates
        
    def setup_selenium(self):
        """Setup Selenium WebDriver with Chrome"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✓ Selenium WebDriver setup successful")
            return True
        except Exception as e:
            print(f"✗ Error setting up Selenium: {e}")
            return False
    
    def extract_rfq_id_from_url(self, url):
        """Extract RFQ ID from detail URL"""
        try:
            if 'p=ID1' in url:
                # Extract the ID from the p parameter
                start = url.find('p=ID1') + 2
                end = url.find('&', start)
                if end == -1:
                    end = len(url)
                return url[start:start+10] if start+10 <= len(url) else url[start:end]
            return "N/A"
        except:
            return "N/A"
    
    def clean_text(self, text):
        """Clean and normalize text"""
        if not text:
            return ""
        # Remove extra whitespace and newlines
        text = re.sub(r'\s+', ' ', text.strip())
        # Remove special characters that might break CSV
        text = re.sub(r'[^\w\s\-\.\,\(\)\/\&\%\#\@\!\?\:\;]', '', text)
        return text
    
    def get_rfq_containers(self, soup):
        """Find RFQ containers using multiple strategies"""
        # Strategy 1: Look for elements with RFQ-related links
        rfq_elements = []
        
        # Find all links that point to rfq_detail
        detail_links = soup.find_all('a', href=re.compile(r'rfq_detail\.htm'))
        
        for link in detail_links:
            # Get the parent container that likely contains all RFQ data
            container = link
            for _ in range(5):  # Go up to 5 levels to find the main container
                parent = container.parent
                if not parent:
                    break
                # Look for containers that seem to hold complete RFQ info
                if len(parent.get_text()) > 100:  # Reasonable amount of text
                    container = parent
                else:
                    break
            
            if container not in rfq_elements:
                rfq_elements.append(container)
        
        print(f"✓ Found {len(rfq_elements)} potential RFQ containers")
        return rfq_elements[:50]  # Limit to avoid processing navigation elements
    
    def scrape_page_with_selenium(self, url, page_num=1):
        """Scrape a single page using Selenium with improved parsing"""
        try:
            print(f"📄 Scraping page {page_num}: {url}")
            
            self.driver.get(url)
            time.sleep(random.uniform(4, 7))  # Random delay
            
            # Wait for page to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Scroll to load more content
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Parse with BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Get RFQ containers
            rfq_containers = self.get_rfq_containers(soup)
            
            page_data = []
            processed_urls = set()
            
            for i, container in enumerate(rfq_containers):
                try:
                    rfq_data = self.extract_rfq_data_improved(container)
                    
                    # Skip if no meaningful data or duplicate
                    if (rfq_data['Title'] == "N/A" or 
                        len(rfq_data['Title']) < 10 or 
                        rfq_data['Inquiry URL'] in processed_urls or
                        rfq_data['Inquiry URL'] in self.seen_urls):
                        continue
                    
                    # Skip promotional/navigation elements
                    if any(skip_word in rfq_data['Title'].lower() for skip_word in 
                           ['buy access', 'submit buying', 'join free', 'sign in']):
                        continue
                    
                    processed_urls.add(rfq_data['Inquiry URL'])
                    self.seen_urls.add(rfq_data['Inquiry URL'])
                    page_data.append(rfq_data)
                    
                    print(f"  ✓ Extracted item {len(page_data)}: {rfq_data['Title'][:60]}...")
                    
                    if len(page_data) >= 20:  # Limit per page
                        break
                        
                except Exception as e:
                    print(f"  ⚠ Error extracting item {i+1}: {str(e)}")
                    continue
            
            print(f"📊 Page {page_num} completed: {len(page_data)} valid items extracted")
            return page_data
            
        except Exception as e:
            print(f"✗ Error scraping page {page_num}: {str(e)}")
            return []
    
    def extract_rfq_data_improved(self, container):
        """Extract RFQ data with improved parsing"""
        current_date = datetime.now().strftime('%d-%m-%Y')
        
        rfq_data = {
            'RFQ ID': 'N/A',
            'Title': 'N/A',
            'Buyer Name': 'N/A',
            'Buyer Image': 'N/A',
            'Inquiry Time': 'N/A',
            'Quotes Left': 'N/A',
            'Country': 'United Arab Emirates',
            'Quantity Required': 'N/A',
            'Email Confirmed': 'No',
            'Experienced Buyer': 'No',
            'Complete Order via RFQ': 'No',
            'Typical Replies': 'No',
            'Interactive User': 'No',
            'Inquiry URL': 'N/A',
            'Inquiry Date': current_date,
            'Scraping Date': current_date
        }
        
        try:
            container_text = container.get_text() if container else ""
            
            # Extract title and URL
            title_link = container.find('a', href=re.compile(r'rfq_detail\.htm'))
            if title_link:
                title = self.clean_text(title_link.get_text())
                if len(title) > 10:
                    rfq_data['Title'] = title
                    
                href = title_link.get('href')
                if href:
                    if href.startswith('/'):
                        href = urljoin(self.base_url, href)
                    rfq_data['Inquiry URL'] = href
                    rfq_data['RFQ ID'] = self.extract_rfq_id_from_url(href)
            
            # Extract buyer information
            # Look for buyer name patterns
            name_patterns = [
                r'([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',  # Names
                r'([A-Z][a-z]+\s+[A-Z]+[a-z]*)',  # Name with abbreviated middle/last
            ]
            
            for pattern in name_patterns:
                matches = re.findall(pattern, container_text)
                for match in matches:
                    # Filter out common non-name words
                    exclude_words = ['Posted', 'Quote', 'United', 'Arab', 'Emirates', 'Date', 'Quantity', 
                                   'Required', 'Email', 'Confirmed', 'Quotes', 'Left', 'Before', 'Piece']
                    if not any(word in match for word in exclude_words) and len(match) > 5:
                        rfq_data['Buyer Name'] = match.strip()
                        break
                if rfq_data['Buyer Name'] != 'N/A':
                    break
            
            # Extract buyer image
            img_elements = container.find_all('img')
            for img in img_elements:
                src = img.get('src', '')
                if ('50x50' in src or 'avatar' in src.lower()) and 'alicdn.com' in src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    rfq_data['Buyer Image'] = src
                    break
            
            # Extract time posted
            time_patterns = [
                r'(\d+\s+(?:hour|hours|minute|minutes|day|days)\s+(?:ago|before))',
                r'(\d+\s+(?:hour|hours|minute|minutes|day|days))',
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, container_text, re.IGNORECASE)
                if match:
                    rfq_data['Inquiry Time'] = match.group(1)
                    break
            
            # Extract quotes left
            quotes_patterns = [
                r'Quotes?\s+Left\s+(\d+)',
                r'(\d+)\s+quote[s]?\s+left',
            ]
            
            for pattern in quotes_patterns:
                match = re.search(pattern, container_text, re.IGNORECASE)
                if match:
                    rfq_data['Quotes Left'] = match.group(1)
                    break
            
            # Extract quantity required
            quantity_patterns = [
                r'Quantity\s+Required:\s*(\d+[^,\n\r]*(?:Piece|Unit|Box|Carton|Meter|Kilogram|Ton|Liter)[^,\n\r]*)',
                r'(\d+\s*(?:Piece|Pieces|Unit|Units|Box|Boxes|Carton|Cartons|Meter|Meters|Kilogram|Ton|Liter)[^,\n\r]*)',
            ]
            
            for pattern in quantity_patterns:
                match = re.search(pattern, container_text, re.IGNORECASE)
                if match:
                    quantity = self.clean_text(match.group(1))
                    if len(quantity) < 100:  # Reasonable length
                        rfq_data['Quantity Required'] = quantity
                        break
            
            # Check for flags
            text_lower = container_text.lower()
            
            if 'email confirmed' in text_lower:
                rfq_data['Email Confirmed'] = 'Yes'
            
            if 'typically replies' in text_lower:
                rfq_data['Typical Replies'] = 'Yes'
                
            if 'interactive user' in text_lower:
                rfq_data['Interactive User'] = 'Yes'
                
            if 'experienced buyer' in text_lower:
                rfq_data['Experienced Buyer'] = 'Yes'
            
        except Exception as e:
            print(f"    ⚠ Error in data extraction: {str(e)}")
        
        return rfq_data
    
    def scrape_multiple_pages(self, base_url, max_pages=10):
        """Scrape multiple pages with better pagination handling"""
        all_data = []
        
        if not self.setup_selenium():
            print("✗ Failed to setup Selenium. Exiting.")
            return []
        
        try:
            for page in range(1, max_pages + 1):
                if page == 1:
                    url = base_url
                else:
                    # Try different pagination patterns
                    if '?' in base_url:
                        url = f"{base_url}&page={page}"
                    else:
                        url = f"{base_url}?page={page}"
                
                page_data = self.scrape_page_with_selenium(url, page)
                
                if not page_data:
                    print(f"⚠ No data found on page {page}. Trying alternative pagination...")
                    # Try alternative pagination
                    alt_url = base_url.replace('&recently=Y', f'&recently=Y&startIndex={(page-1)*20}')
                    if alt_url != url:
                        page_data = self.scrape_page_with_selenium(alt_url, page)
                    
                    if not page_data:
                        print(f"⚠ Still no data on page {page}. Stopping pagination.")
                        break
                
                all_data.extend(page_data)
                print(f"📈 Total items collected so far: {len(all_data)}")
                
                # Random delay between pages
                time.sleep(random.uniform(3, 6))
                
        except KeyboardInterrupt:
            print("\n⚠ Scraping interrupted by user")
        except Exception as e:
            print(f"✗ Error during multi-page scraping: {str(e)}")
        finally:
            if self.driver:
                self.driver.quit()
                print("✓ Browser closed")
        
        return all_data
    
    def save_to_csv(self, data, filename=None):
        """Save scraped data to CSV file with better formatting"""
        if not filename:
            timestamp = datetime.now().strftime('%Y_%m_%d_%H%M%S')
            filename = f"alibaba_rfq_final_{timestamp}.csv"
        
        try:
            df = pd.DataFrame(data)
            
            if len(df) == 0:
                print("⚠ No data to save")
                return None
            
            # Remove duplicates based on Inquiry URL
            df = df.drop_duplicates(subset=['Inquiry URL'], keep='first')
            
            # Clean data
            for col in df.columns:
                if col in ['Title', 'Buyer Name', 'Quantity Required']:
                    df[col] = df[col].apply(lambda x: self.clean_text(str(x)) if pd.notna(x) else 'N/A')
            
            # Ensure column order matches template
            required_columns = [
                'RFQ ID', 'Title', 'Buyer Name', 'Buyer Image', 'Inquiry Time',
                'Quotes Left', 'Country', 'Quantity Required', 'Email Confirmed',
                'Experienced Buyer', 'Complete Order via RFQ', 'Typical Replies',
                'Interactive User', 'Inquiry URL', 'Inquiry Date', 'Scraping Date'
            ]
            
            df = df[required_columns]
            
            # Save to CSV
            df.to_csv(filename, index=False, encoding='utf-8')
            print(f"✓ Data saved to {filename}")
            print(f"📊 Total unique records: {len(df)}")
            
            # Display sample data
            if len(df) > 0:
                print("\n📋 Sample data (first 3 rows):")
                sample_df = df.head(3)
                for idx, row in sample_df.iterrows():
                    print(f"\nRecord {idx + 1}:")
                    print(f"  Title: {row['Title']}")
                    print(f"  Buyer: {row['Buyer Name']}")
                    print(f"  Quantity: {row['Quantity Required']}")
                    print(f"  Time: {row['Inquiry Time']}")
                    print(f"  Quotes Left: {row['Quotes Left']}")
            
            return filename
            
        except Exception as e:
            print(f"✗ Error saving to CSV: {str(e)}")
            return None

def main():
    """Main execution function"""
    print("🚀 Starting Improved Alibaba RFQ Scraper")
    print("=" * 60)
    
    # Target URL
    target_url = "https://sourcing.alibaba.com/rfq/rfq_search_list.htm?spm=a2700.8073608.1998677541.1.82be65aaoUUItC&country=AE&recently=Y&tracelog=newest"
    
    # Initialize scraper
    scraper = ImprovedAlibabaRFQScraper()
    
    try:
        print(f"🎯 Target URL: {target_url}")
        print("🔍 Starting to scrape RFQ listings from multiple pages...")
        
        # Scrape more pages for comprehensive data
        scraped_data = scraper.scrape_multiple_pages(target_url, max_pages=10)
        
        if scraped_data:
            csv_file = scraper.save_to_csv(scraped_data)
            
            if csv_file:
                print(f"\n🎉 Scraping completed successfully!")
                print(f"📁 Output file: {csv_file}")
                print(f"📊 Total unique RFQ records: {len(scraped_data)}")
                
                # Create summary
                print(f"\n📈 Summary:")
                print(f"   • Pages scraped: Multiple pages")
                print(f"   • Records collected: {len(scraped_data)}")
                print(f"   • File format: CSV")
                print(f"   • Data fields: 16 columns matching template")
            else:
                print("✗ Failed to save data to CSV")
        else:
            print("⚠ No data was scraped. Please check the website structure or network connection.")
    
    except Exception as e:
        print(f"✗ Fatal error: {str(e)}")
    finally:
        print("\n" + "=" * 60)
        print("🏁 Scraping session ended")

if __name__ == "__main__":
    main()
