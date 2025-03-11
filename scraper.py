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
            
            # Extract date headers from the table
            date_headers = {}
            try:
                # Find table headers
                headers = driver.find_elements(By.TAG_NAME, "th")
                current_year = datetime.datetime.now().year
                
                for header in headers:
                    header_text = header.text.strip()
                    if any(day in header_text for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']):
                        # Extract the date from format like "Monday 10th Mar"
                        day_match = re.search(r'(\d+)(?:st|nd|rd|th)\s+([A-Za-z]+)', header_text)
                        if day_match:
                            day = int(day_match.group(1))
                            month = day_match.group(2)
                            # Convert month name to number
                            month_num = {
                                'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                            }[month[:3]]
                            date_str = f"{day:02d}/{month_num:02d}/{current_year}"
                            date_headers[header_text.split()[0]] = date_str
                            logger.info(f"Found date header: {header_text} -> {date_str}")
                
                logger.info(f"Extracted date headers: {date_headers}")
            except Exception as e:
                logger.error(f"Error extracting date headers: {str(e)}")
                date_headers = {}
            
            shifts = []
            
            # Find rows containing "Cristian Rus"
            rows = driver.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                try:
                    if "Cristian Rus" in row.text:
                        # Get all cells in the row
                        cells = row.find_elements(By.TAG_NAME, "td")
                        
                        # Find which day this shift is for
                        day_cell = cells[0].text.strip()  # First cell should contain the day
                        if day_cell in date_headers:
                            date_str = date_headers[day_cell]
                            
                            # Extract time and role information
                            time_cell = cells[1].text.strip()  # Second cell should contain time
                            role = ""
                            
                            # Check if there's a role in parentheses
                            role_match = re.search(r'\((.*?)\)', time_cell)
                            if role_match:
                                role = role_match.group(1)
                                time_cell = time_cell.replace(f"({role})", "").strip()
                            
                            # Format the time with arrow
                            if "→" not in time_cell and "-" in time_cell:
                                time_cell = time_cell.replace("-", "→")
                            
                            # Add role to the end if it exists
                            time_str = f"{time_cell}{' ' + role if role else ''}"
                            
                            shifts.append((date_str, time_str))
                            logger.info(f"Found shift: {date_str} - {time_str}")
                except Exception as e:
                    logger.error(f"Error processing row: {str(e)}")
                    continue
            
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
            
            # Fix the timezone for New Zealand
            # New Zealand is UTC+12 or UTC+13 depending on daylight saving time
            # For simplicity, we'll use a fixed offset of +12 hours
            tz_offset = datetime.timedelta(hours=12)
            
            # Convert to proper timezone-aware datetimes for New Zealand
            # (this assumes the parsed times are in local time, so we need to adjust for ICS storage)
            start_dt_utc = start_dt - tz_offset
            end_dt_utc = end_dt - tz_offset
            
            logger.info(f"Original times: {start_dt} - {end_dt}")
            logger.info(f"Adjusted for NZ timezone (UTC+12): {start_dt_utc} - {end_dt_utc}")
            
            # Create the event
            event = Event()
            event.name = f"Chou chou" + (f" ({role})" if role else "")
            event.begin = start_dt_utc
            event.end = end_dt_utc
            event.description = f"Work shift at Loaded" + (f"\nRole: {role}" if role else "")
            event.uid = f"loaded-shift-{date_str}-{times_str}".replace(" ", "").replace("/", "").replace("→", "to")
            
            # Add event to calendar
            cal.events.add(event)
            logger.info(f"Added shift to calendar: {event.name} on {start_dt_utc}")
            
        except Exception as e:
            logger.error(f"Error processing shift {shift}: {str(e)}")
            traceback.print_exc()
    
    # Merge with existing calendar to avoid duplicates
    # Add events from existing calendar that aren't in the new calendar
    for event in existing_cal.events:
        if event.uid not in {e.uid for e in cal.events}:
            # Update any existing event names from "Work Shift - Loaded" to "Chou chou"
            if "Work Shift - Loaded" in event.name:
                event.name = event.name.replace("Work Shift - Loaded", "Chou chou")
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


