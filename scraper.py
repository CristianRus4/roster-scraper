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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_chrome_driver():
    """Set up Chrome WebDriver based on the current environment."""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-features=NetworkService')
    options.add_argument('--disable-dev-tools')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Check if running in GitHub Actions
    is_github_actions = os.environ.get('GITHUB_ACTIONS') == 'true'
    
    if is_github_actions:
        logger.info("Running in GitHub Actions environment")
        # In GitHub Actions, Chrome is installed system-wide
        try:
            driver = webdriver.Chrome(options=options)
            logger.info("Successfully created Chrome driver in GitHub Actions")
            return driver
        except Exception as e:
            logger.error(f"Error creating Chrome driver in GitHub Actions: {str(e)}")
            # Fallback to ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            return driver
    else:
        # Local environment
        system = platform.system()
        logger.info(f"Running on local {system} environment")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver

def get_shifts():
    logger.info("Starting to extract shifts")
    
    try:
        driver = setup_chrome_driver()
        
        url = "https://loadedhub.com/App/PublicRoster#/roster/03138d50-b542-4ca2-952f-8756ef67c2ba/e023f92d-acb6-91a7-fbc0-2555e704bf53"
        driver.get(url)
        logger.info(f"Navigated to {url}")
        
        # Wait longer for page to fully load and JavaScript to execute
        wait = WebDriverWait(driver, 30)
        
        try:
            # Wait for the roster table to be visible
            table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#editor-body")))
            logger.info("Roster table found")
            
            # Give extra time for all data to render
            time.sleep(5)
            
            # Save page source for debugging
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.info("Saved page source for debugging")
            
            shifts = []
            
            # Try multiple possible selectors for rows
            selectors = [
                "#editor-body > tbody > tr",
                ".roster-table tr",
                "[data-testid='roster-row']",
                "tr.roster-row"
            ]
            
            rows = []
            for selector in selectors:
                try:
                    found_rows = driver.find_elements(By.CSS_SELECTOR, selector)
                    if found_rows:
                        rows = found_rows
                        logger.info(f"Found {len(rows)} rows using selector: {selector}")
                        break
                except Exception as e:
                    logger.warning(f"Selector {selector} failed: {str(e)}")
            
            if not rows:
                # Take screenshot for debugging
                driver.save_screenshot("debug_screenshot.png")
                logger.error("No roster rows found with any selectors. Check debug_screenshot.png")
                
                # Fallback: try to get the entire page source to parse
                page_source = driver.page_source
                logger.info(f"Page source length: {len(page_source)}")
            
            for row in rows:
                try:
                    # Try multiple possible selectors for the name
                    name_selectors = [
                        "td:nth-child(1) div", 
                        ".employee-name",
                        "td:first-child div",
                        "*[data-testid='employee-name']"
                    ]
                    
                    name = None
                    for selector in name_selectors:
                        try:
                            name_elem = row.find_element(By.CSS_SELECTOR, selector)
                            name = name_elem.text.strip().lower()
                            break
                        except:
                            continue
                    
                    if not name:
                        logger.warning("Could not find name in row")
                        continue
                        
                    logger.info(f"Found employee: {name}")
                    
                    if "cristian rus" in name:
                        # Try multiple possible selectors for date and time
                        date = None
                        times = None
                        
                        date_selectors = [
                            "td:nth-child(2) div",
                            ".shift-date",
                            "*[data-testid='shift-date']"
                        ]
                        
                        time_selectors = [
                            "td:nth-child(3) div",
                            ".shift-time",
                            "*[data-testid='shift-time']"
                        ]
                        
                        for selector in date_selectors:
                            try:
                                date_elem = row.find_element(By.CSS_SELECTOR, selector)
                                date = date_elem.text.strip()
                                break
                            except:
                                continue
                                
                        for selector in time_selectors:
                            try:
                                time_elem = row.find_element(By.CSS_SELECTOR, selector)
                                times = time_elem.text.strip()
                                break
                            except:
                                continue
                        
                        if date and times:
                            logger.info(f"Found shift: {date} - {times}")
                            shifts.append((date, times))
                        else:
                            logger.warning(f"Incomplete shift data for {name}: date={date}, times={times}")
                except Exception as e:
                    logger.error(f"Error processing row: {str(e)}")
                    traceback.print_exc()
            
            return shifts
            
        except TimeoutException:
            logger.error("Timeout waiting for roster table to load")
            driver.save_screenshot("timeout_error.png")
            return []
    
    except Exception as e:
        logger.error(f"Error in get_shifts: {str(e)}")
        traceback.print_exc()
        return []
    
    finally:
        try:
            driver.quit()
            logger.info("WebDriver closed")
        except:
            pass

def generate_ics(shifts):
    logger.info(f"Generating ICS file from {len(shifts)} shifts")
    
    # Try to read existing calendar to preserve previous events
    existing_cal = Calendar()
    try:
        if os.path.exists("roster.ics") and os.path.getsize("roster.ics") > 0:
            with open("roster.ics", "r") as f:
                existing_cal = Calendar(f.read())
                logger.info(f"Loaded existing calendar with {len(existing_cal.events)} events")
    except Exception as e:
        logger.error(f"Error reading existing calendar: {str(e)}")
        # Continue with empty calendar if we can't read the existing one
    
    # Create a new calendar for the current shifts
    cal = Calendar()
    
    # Add each shift as an event
    for shift in shifts:
        try:
            date_str, times_str = shift
            
            # Handle various time formats
            if " - " in times_str:
                start_time, end_time = times_str.split(" - ")
                
                # Try different date formats
                date_formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"]
                start_dt = None
                
                for date_format in date_formats:
                    try:
                        start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", f"{date_format} %I:%M %p")
                        end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", f"{date_format} %I:%M %p")
                        break
                    except ValueError:
                        continue
                
                if not start_dt:
                    logger.warning(f"Could not parse date: {date_str}")
                    continue
                
                # Handle case where shift ends next day
                if end_dt < start_dt:
                    end_dt = end_dt + datetime.timedelta(days=1)
                
                event = Event()
                event.name = "Work Shift - Loaded"
                event.begin = start_dt
                event.end = end_dt
                event.description = f"Work shift at Loaded"
                event.uid = f"loaded-shift-{date_str}-{times_str}".replace(" ", "").replace("/", "")
                
                # Add event to calendar
                cal.events.add(event)
                logger.info(f"Added shift: {date_str} {start_time} - {end_time}")
            else:
                logger.warning(f"Skipping invalid time format: {times_str}")
        except Exception as e:
            logger.error(f"Error processing shift {shift}: {str(e)}")
    
    # Merge with existing calendar to avoid duplicates
    # First convert existing events to a set of UIDs
    existing_uids = {event.uid for event in existing_cal.events}
    
    # Add events from existing calendar that aren't in the new calendar
    for event in existing_cal.events:
        if event.uid not in {e.uid for e in cal.events}:
            cal.events.add(event)
    
    logger.info(f"Final calendar has {len(cal.events)} events")
    
    # Write the calendar to file
    with open("roster.ics", "w") as f:
        f.write(str(cal))
    
    logger.info("ICS file updated successfully")
    
if __name__ == "__main__":
    try:
        shifts = get_shifts()
        if shifts:
            logger.info(f"Extracted {len(shifts)} shifts")
            generate_ics(shifts)
        else:
            logger.warning("No shifts were extracted")
            # Still create/update the ICS file even when no shifts are found
            # This helps verify the script ran successfully
            current_time = datetime.datetime.now()
            
            # Try to read existing calendar
            existing_cal = Calendar()
            try:
                if os.path.exists("roster.ics") and os.path.getsize("roster.ics") > 0:
                    with open("roster.ics", "r") as f:
                        existing_cal = Calendar(f.read())
                        logger.info(f"Loaded existing calendar with {len(existing_cal.events)} events")
            except Exception as e:
                logger.error(f"Error reading existing calendar: {str(e)}")
            
            # Add a timestamp comment event if allowed
            comment_event = Event()
            comment_event.name = "Roster check - No shifts found"
            comment_event.begin = current_time
            comment_event.end = current_time + datetime.timedelta(minutes=1)
            comment_event.description = "Script ran but no shifts were found for Cristian Rus"
            comment_event.uid = f"loaded-roster-check-{current_time.strftime('%Y%m%d%H%M%S')}"
            
            cal = Calendar()
            cal.events.add(comment_event)
            
            # Add all existing events back
            for event in existing_cal.events:
                cal.events.add(event)
                
            # Write the updated calendar
            with open("roster.ics", "w") as f:
                f.write(str(cal))
                
            logger.info("ICS file updated with timestamp comment only")
            
        logger.info(f"DEBUG: extracted shifts = {shifts}")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        traceback.print_exc()


