from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import datetime
from ics import Calendar, Event
import time
import os
import logging
import traceback
import platform
import re
import pytz

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def extract_shifts():
    driver = setup_driver()
    url = "https://loadedhub.com/App/PublicRoster#/roster/03138d50-b542-4ca2-952f-8756ef67c2ba/e023f92d-acb6-91a7-fbc0-2555e704bf53"
    
    try:
        driver.get(url)
        time.sleep(10)  # Wait for JavaScript to load
        
        # Save page source for debugging
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
            
        # Get date headers
        headers = driver.find_elements(By.CSS_SELECTOR, "th span.ng-binding")
        dates = {}
        current_day = None
        
        for header in headers:
            text = header.text.strip()
            if any(day in text for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']):
                current_day = text
            elif current_day and text:  # This would be the date part (e.g., "10th Mar")
                match = re.search(r'(\d+)(?:st|nd|rd|th)\s+([A-Za-z]+)', text)
                if match:
                    day = int(match.group(1))
                    month = match.group(2)[:3]
                    month_num = {
                        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                    }[month]
                    dates[current_day] = (day, month_num)
                    current_day = None
        
        # Find Cristian's shifts
        shifts = []
        rows = driver.find_elements(By.CSS_SELECTOR, "tr")
        
        for row in rows:
            if "Cristian Rus" in row.text:
                # Get all cells for the week, not just those with shifts
                cells = row.find_elements(By.CSS_SELECTOR, "td")
                day_index = 0
                
                for cell in cells:
                    # Skip the first cell which contains the name
                    if day_index == 0:
                        day_index += 1
                        continue
                        
                    # Adjust day_index since we skipped the first cell
                    current_day_index = day_index - 1
                    if current_day_index >= len(dates):
                        break
                        
                    day_name = list(dates.keys())[current_day_index]
                    day_num, month = dates[day_name]
                    year = 2025  # From the HTML we can see it's 2025
                    
                    # Look for shift information within the cell
                    shift_div = cell.find_elements(By.CSS_SELECTOR, "div.week-shift")
                    if shift_div:
                        shift_text = shift_div[0].get_attribute("uib-tooltip-html")
                        if shift_text:
                            # Extract role and time
                            match = re.search(r"'FOH - (.+)'", shift_text)
                            if match:
                                time_text = match.group(1)
                                role = ""
                                
                                # Check for role in the cell text
                                role_divs = shift_div[0].find_elements(By.CSS_SELECTOR, "div.shift-jobs")
                                if role_divs:
                                    role = role_divs[0].text
                                
                                shifts.append({
                                    'date': f"{day_num:02d}/{month:02d}/{year}",
                                    'shift': time_text,
                                    'role': role,
                                    'day_name': day_name
                                })
                    
                    day_index += 1
        
        return shifts
    
    finally:
        driver.quit()

def create_ics(shifts):
    cal = Calendar()
    nz_tz = pytz.timezone('Pacific/Auckland')
    
    for shift in shifts:
        date = shift['date']
        times = shift['shift'].split('→')
        if len(times) != 2:
            continue
            
        start_time, end_time = [t.strip() for t in times]
        role = shift['role']
        
        try:
            day, month, year = map(int, date.split('/'))
            
            # Create datetime objects
            start_dt = datetime.datetime.strptime(f"{day:02d}/{month:02d}/{year} {start_time}", "%d/%m/%Y %I:%M%p")
            end_dt = datetime.datetime.strptime(f"{day:02d}/{month:02d}/{year} {end_time}", "%d/%m/%Y %I:%M%p")
            
            # Handle overnight shifts
            if end_dt < start_dt:
                end_dt += datetime.timedelta(days=1)
            
            # Convert to UTC
            start_dt_local = nz_tz.localize(start_dt)
            end_dt_local = nz_tz.localize(end_dt)
            start_dt_utc = start_dt_local.astimezone(pytz.UTC)
            end_dt_utc = end_dt_local.astimezone(pytz.UTC)
            
            # Create event
            event = Event()
            event.name = f"Chouchou" + (f" ({role})" if role else "")
            event.begin = start_dt_utc
            event.end = end_dt_utc
            event.description = f"Work shift at Loaded" + (f"\nRole: {role}" if role else "")
            
            event.location = "Chouchou\n1 Taranaki Street, Te Aro, Wellington, 6011"
            cal.events.add(event)
            
        except ValueError as e:
            print(f"Error parsing shift: {shift} - {e}")
    
    # Write to ICS file
    with open("roster.ics", "w") as f:
        f.write(str(cal))

def create_text_summary(shifts):
    # Create a text summary
    with open("roster_summary.txt", "w") as f:
        for shift in shifts:
            f.write(f"Date: {shift['day_name']}, {shift['date']}\n")
            f.write(f"Event name: Chouchou" + (f" ({shift['role']})" if shift['role'] else "") + "\n")
            f.write(f"Time: {shift['shift']}\n")
            f.write("-" * 40 + "\n")

if __name__ == "__main__":
    shifts = extract_shifts()
    if shifts:
        create_ics(shifts)
        create_text_summary(shifts)
        print(f"Found {len(shifts)} shifts")
    else:
        print("No shifts found")
