import datetime
import pytz

def get_week_dates(week_offset=0):
    today = datetime.date.today()
    # calculate the start of the week (Monday)
    start_of_week = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    # calculate the end of the week (Sunday)
    end_of_week = start_of_week + datetime.timedelta(days=6)
    
    return start_of_week, end_of_week

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

        # Get dates for the current and next weeks
        current_week_start, current_week_end = get_week_dates(0)
        next_week_start, next_week_end = get_week_dates(1)
        
        logger.info(f"Current week: {current_week_start} to {current_week_end}")
        logger.info(f"Next week: {next_week_start} to {next_week_end}")
        
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
