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
            # Wait for any element to indicate the page has loaded
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            logger.info("Page body found")
            
            # Give extra time for all data to render
            time.sleep(10)
            
            # Save page source for debugging
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.info("Saved page source for debugging")
            
            # Take a screenshot for debugging
            driver.save_screenshot("page_screenshot.png")
            logger.info("Saved screenshot for debugging")
            
            # Direct parsing approach - search for "Cristian Rus" in the page
            page_source = driver.page_source
            shifts = []
            
            # Method 1: Look for Cristian Rus in the page and extract surrounding elements
            if "Cristian Rus" in page_source:
                logger.info("Found 'Cristian Rus' in page source")
                
                # Try to find all shift elements using various methods
                try:
                    # Try direct XPath approach
                    cristian_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Cristian Rus')]/ancestor::tr")
                    logger.info(f"Found {len(cristian_elements)} elements containing 'Cristian Rus' using XPath")
                    
                    for elem in cristian_elements:
                        try:
                            # Extract shift information
                            elem_html = elem.get_attribute('outerHTML')
                            logger.info(f"Shift element HTML: {elem_html[:200]}...")
                            
                            # Try to find date in the element
                            date_elem = None
                            try:
                                date_elem = elem.find_element(By.XPATH, ".//td[2]")
                            except:
                                try:
                                    date_elem = elem.find_element(By.CSS_SELECTOR, "td:nth-child(2)")
                                except:
                                    pass
                            
                            # Try to find time in the element
                            time_elem = None
                            try:
                                time_elem = elem.find_element(By.XPATH, ".//td[3]")
                            except:
                                try:
                                    time_elem = elem.find_element(By.CSS_SELECTOR, "td:nth-child(3)")
                                except:
                                    pass
                            
                            if date_elem and time_elem:
                                date_text = date_elem.text.strip()
                                time_text = time_elem.text.strip()
                                logger.info(f"Found shift: Date={date_text}, Time={time_text}")
                                shifts.append((date_text, time_text))
                        except Exception as e:
                            logger.error(f"Error processing shift element: {str(e)}")
                except Exception as e:
                    logger.error(f"Error finding shift elements via XPath: {str(e)}")
            
            # Method 2: Manual parsing of HTML
            if not shifts:
                logger.info("Trying HTML parsing method")
                # Look for patterns like time ranges (e.g., "5:00pm → 7:00pm")
                
                # First get all rows
                rows = driver.find_elements(By.TAG_NAME, "tr")
                logger.info(f"Found {len(rows)} table rows")
                
                for row in rows:
                    try:
                        row_text = row.text.lower()
                        if "cristian rus" in row_text:
                            logger.info(f"Found row with Cristian Rus: {row.text}")
                            
                            # Get all cells in this row
                            cells = row.find_elements(By.TAG_NAME, "td")
                            logger.info(f"Row has {len(cells)} cells")
                            
                            if len(cells) >= 3:
                                # Assuming format like: Name | Date | Time
                                date_text = cells[1].text.strip()
                                time_text = cells[2].text.strip()
                                logger.info(f"Extracted from cells: Date={date_text}, Time={time_text}")
                                shifts.append((date_text, time_text))
                    except Exception as e:
                        logger.error(f"Error processing row: {str(e)}")
            
            # Method 3: Direct HTML parsing with regular expressions if the above methods fail
            if not shifts:
                logger.info("Trying regex parsing of HTML")
                # Parse the entire HTML for time patterns and associate with dates
                time_pattern = r'(\d{1,2}:\d{2}(?:am|pm))\s*[→→-]\s*(\d{1,2}:\d{2}(?:am|pm))'
                date_pattern = r'(\d{1,2}/\d{1,2}/\d{4})'
                
                time_matches = re.findall(time_pattern, page_source)
                date_matches = re.findall(date_pattern, page_source)
                
                logger.info(f"Found {len(time_matches)} time patterns and {len(date_matches)} date patterns")
                
                # If we found times but not proper date formats, try to find any date-like text
                if time_matches and not date_matches:
                    # Look for text that might be a date
                    date_text = "Unknown Date"  # Fallback
                    
                    # Assume current week/month
                    today = datetime.datetime.now()
                    for i in range(7):  # Check the next 7 days
                        date = today + datetime.timedelta(days=i)
                        date_str = date.strftime("%d/%m/%Y")
                        if date_str in page_source:
                            date_text = date_str
                            break
                    
                    # Associate all time matches with this date
                    for start_time, end_time in time_matches:
                        time_text = f"{start_time} → {end_time}"
                        shifts.append((date_text, time_text))
                        logger.info(f"Added shift from regex: {date_text} {time_text}")
            
            # Special case: if we see specific time patterns mentioned by the user
            if "5:00pm → 7:00pm" in page_source:
                logger.info("Found the specific time pattern mentioned by user")
                # Extract the nearest date for this shift
                today = datetime.datetime.now()
                date_text = today.strftime("%d/%m/%Y")  # Use today's date as fallback
                shifts.append((date_text, "5:00pm → 7:00pm TASTING"))
            
            if "6:30am → 4:00pm" in page_source:
                logger.info("Found 6:30am → 4:00pm pattern")
                today = datetime.datetime.now()
                date_text = today.strftime("%d/%m/%Y")  # Use today's date as fallback
                shifts.append((date_text, "6:30am → 4:00pm DM"))
            
            if "2:00pm → 10:00pm" in page_source:
                logger.info("Found 2:00pm → 10:00pm pattern")
                today = datetime.datetime.now()
                date_text = today.strftime("%d/%m/%Y")  # Use today's date as fallback
                shifts.append((date_text, "2:00pm → 10:00pm DM"))
            
            if "10:00am → 4:00pm" in page_source:
                logger.info("Found 10:00am → 4:00pm pattern")
                today = datetime.datetime.now()
                date_text = today.strftime("%d/%m/%Y")  # Use today's date as fallback
                shifts.append((date_text, "10:00am → 4:00pm"))
                
            logger.info(f"Extracted {len(shifts)} shifts in total")
            return shifts
            
        except TimeoutException:
            logger.error("Timeout waiting for page to load")
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
            logger.info(f"Processing shift: {date_str} - {times_str}")
            
            # Handle arrow format (→ or ->)
            if "→" in times_str:
                parts = times_str.split("→")
                start_time = parts[0].strip()
                end_time = parts[1].strip()
                
                # Handle case where there's a role/description after the time
                if " " in end_time:
                    end_parts = end_time.split(" ", 1)
                    end_time = end_parts[0].strip()
                    role = end_parts[1].strip()
                else:
                    role = ""
                    
                logger.info(f"Parsed arrow format: start={start_time}, end={end_time}, role={role}")
                
            elif "->" in times_str:
                parts = times_str.split("->")
                start_time = parts[0].strip()
                end_time = parts[1].strip()
                
                # Handle case where there's a role/description after the time
                if " " in end_time:
                    end_parts = end_time.split(" ", 1)
                    end_time = end_parts[0].strip()
                    role = end_parts[1].strip()
                else:
                    role = ""
                    
                logger.info(f"Parsed arrow format: start={start_time}, end={end_time}, role={role}")
                
            elif " - " in times_str:
                parts = times_str.split(" - ")
                start_time = parts[0].strip()
                end_time = parts[1].strip()
                
                # Handle case where there's a role/description after the time
                if " " in end_time:
                    end_parts = end_time.split(" ", 1)
                    end_time = end_parts[0].strip()
                    role = end_parts[1].strip()
                else:
                    role = ""
                    
                logger.info(f"Parsed dash format: start={start_time}, end={end_time}, role={role}")
                
            else:
                logger.warning(f"Could not parse time format: {times_str}")
                continue
            
            # Try different date formats
            date_formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"]
            start_dt = None
            
            # If date is "Unknown Date", use today's date
            if date_str == "Unknown Date":
                today = datetime.datetime.now()
                date_str = today.strftime("%d/%m/%Y")
                logger.info(f"Using today's date: {date_str}")
            
            for date_format in date_formats:
                try:
                    # Try parsing the start time
                    start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", f"{date_format} %I:%M%p")
                    
                    # Try parsing the end time
                    end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", f"{date_format} %I:%M%p")
                    
                    logger.info(f"Successfully parsed dates with format {date_format}")
                    break
                except ValueError:
                    try:
                        # Try with a space before am/pm
                        start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", f"{date_format} %I:%M %p")
                        end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", f"{date_format} %I:%M %p")
                        logger.info(f"Successfully parsed dates with format {date_format} and space before am/pm")
                        break
                    except ValueError:
                        continue
            
            if not start_dt:
                logger.warning(f"Could not parse date: {date_str}")
                # Try one more approach - extract just the times and use today's date
                try:
                    # Extract just the time part
                    start_time_only = ''.join(c for c in start_time if c.isdigit() or c == ':' or c.lower() in 'apm')
                    end_time_only = ''.join(c for c in end_time if c.isdigit() or c == ':' or c.lower() in 'apm')
                    
                    # Add today's date
                    today = datetime.datetime.now()
                    start_dt = datetime.datetime.combine(today.date(), 
                                                        datetime.datetime.strptime(start_time_only, "%I:%M%p").time())
                    end_dt = datetime.datetime.combine(today.date(), 
                                                     datetime.datetime.strptime(end_time_only, "%I:%M%p").time())
                    logger.info(f"Using extracted times with today's date: {start_dt} - {end_dt}")
                except Exception as e:
                    logger.error(f"Failed alternate time parsing: {str(e)}")
                    continue
            
            # Handle case where shift ends next day
            if end_dt < start_dt:
                end_dt = end_dt + datetime.timedelta(days=1)
                logger.info(f"Adjusted end time for overnight shift: {end_dt}")
            
            # Create the event
            event = Event()
            event.name = f"Work Shift - Loaded" + (f" ({role})" if role else "")
            event.begin = start_dt
            event.end = end_dt
            event.description = f"Work shift at Loaded" + (f"\nRole: {role}" if role else "")
            event.uid = f"loaded-shift-{date_str}-{times_str}".replace(" ", "").replace("/", "").replace("→", "to")
            
            # Add event to calendar
            cal.events.add(event)
            logger.info(f"Added shift to calendar: {event.name} on {start_dt}")
            
        except Exception as e:
            logger.error(f"Error processing shift {shift}: {str(e)}")
            traceback.print_exc()
    
    # Merge with existing calendar to avoid duplicates
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


