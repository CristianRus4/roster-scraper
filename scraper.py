from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import datetime
from ics import Calendar, Event
import time
import os

def get_shifts():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    url = "https://loadedhub.com/App/PublicRoster#/roster/03138d50-b542-4ca2-952f-8756ef67c2ba/e023f92d-acb6-91a7-fbc0-2555e704bf53"
    driver.get(url)
    time.sleep(5)  # wait for JS to load content
    
    shifts = []
    
    rows = driver.find_elements(By.CSS_SELECTOR, "#editor-body > tbody > tr")
    for row in rows:
        name = row.find_element(By.CSS_SELECTOR, "td:nth-child(1) div").text.strip().lower()
        if "cristian rus" in name:
            date = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) div").text.strip()
            times = row.find_element(By.CSS_SELECTOR, "td:nth-child(3) div").text.strip()
            shifts.append((date, times))
    
    driver.quit()
    return shifts
print(f"DEBUG: extracted shifts = {shifts}")
def generate_ics(shifts):
    cal = Calendar()
    
    for shift in shifts:
        date_str, times_str = shift
        if " - " in times_str:
            start_time, end_time = times_str.split(" - ")
            start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", "%d/%m/%Y %I:%M %p")
            end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", "%d/%m/%Y %I:%M %p")
            
            event = Event()
            event.name = "Work Shift"
            event.begin = start_dt.isoformat()
            event.end = end_dt.isoformat()
            cal.events.add(event)
        else:
            print(f"Skipping invalid time format: {times_str}")
    
    with open("roster.ics", "w") as f:
        f.writelines(cal)
    
    print("ICS file updated.")
    
if __name__ == "__main__":
    shifts = get_shifts()
    generate_ics(shifts)
