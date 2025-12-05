from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
import time, random
from faker import Faker
import gspread

def get_sheet_data():
    gc = gspread.service_account(filename='service_account.json')
    # Open Google Sheet by name
    sh = gc.open("auto_click_data")
    # Select the worksheet
    worksheet = sh.worksheet("Sheet1")
    # Get all rows as list of dictionaries
    data = worksheet.get_all_records()
    return data

# Initialize Faker
fake = Faker('nl_NL')

# --- Setup ---
chrome_options = Options()
chrome_options.add_argument("--start-maximized")
# chrome_options.add_argument("--headless")  # Uncomment for headless mode in production
driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 30)
BASE_URL = "https://zoeken.schepvastgoedmanagers.nl/huur/woningen?filter=stage:available"  # Base URL with available filter

def generate_random_data():
    first_name = fake.first_name()
    last_name = fake.last_name()
    phone = "+316" + "".join([str(random.randint(0, 9)) for _ in range(8)])
    email = f"{first_name}.{last_name}@yopmail.com".lower().replace(" ", "")
    return {"name": first_name, "lastname": last_name, "email": email, "phone": phone}

def accept_cookies_once():
    try:
        accept_button = wait.until(EC.element_to_be_clickable((By.ID, "cookiescript_accept")))
        accept_button.click()
        print("Cookies accepted")
        time.sleep(1)
    except TimeoutException:
        # no cookie popup found
        pass

def click_apply_button():
    """
    Try multiple ways to find/apply the filter button:
      1) Button by English label 'Apply filter'
      2) Button by Dutch label 'Filter toepassen'
      3) Full XPath (page-structure-specific)
      4) CSS fallback for first submit button inside the filter form
      5) JS fallback to click first matching button
    Returns True if clicked, False otherwise.
    """
    xpaths = [
        "//button[contains(normalize-space(.), 'Apply filter')]",
        "//button[contains(normalize-space(.), 'Filter toepassen')]",
        "//*[@id='__nuxt']//form//div[contains(@class,'form')]/../div[3]/button[1]",  # try a structure-based path (fallback)
        "//*[@id='__nuxt']/div/div/div/div/section[2]/article/div/div/div/div[1]/form/div[3]/button[1]"
    ]
    for xp in xpaths:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", btn)
            print(f"Clicked Apply button via XPath: {xp}")
            return True
        except (TimeoutException, Exception):
            continue

    # CSS fallback: find first button inside the filter form area
    try:
        form_btn = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR,
            "section article form button, form button.btn"
        )))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", form_btn)
        try:
            form_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", form_btn)
        print("Clicked Apply button via CSS fallback")
        return True
    except TimeoutException:
        pass

    # Last resort: JS to find button by innerText containing common words
    js_try = """
    var texts = ['Apply filter','Filter toepassen','Apply','Toepassen'];
    var btns = Array.from(document.querySelectorAll('button'));
    for (var b of btns) {
        var t = b.innerText || b.textContent || '';
        for (var txt of texts) {
            if (t.trim().toLowerCase().indexOf(txt.toLowerCase()) !== -1) {
                b.scrollIntoView({block:'center'});
                b.click();
                return true;
            }
        }
    }
    // fallback: click first visible button in the filter area
    var form = document.querySelector('section article form');
    if (form) {
        var fb = form.querySelector('button');
        if (fb) { fb.scrollIntoView({block:'center'}); fb.click(); return true; }
    }
    return false;
    """
    try:
        clicked = driver.execute_script(js_try)
        if clicked:
            print("Clicked Apply button via JS fallback")
            return True
    except Exception as e:
        print("JS fallback failed:", e)

    print("Apply button not found")
    return False

# --- Step 1: Navigate & Accept Cookies (first time) ---
try:
    driver.get(BASE_URL)
    print(f"Navigated to base page: {BASE_URL}")
    time.sleep(2)
    accept_cookies_once()
except Exception as e:
    print(f"Setup error: {e}")
    driver.quit()
    exit()

# --- Step 2: Read Sheet & Normalize Data ---
sheet_data_raw = get_sheet_data()
# Accept either a list of dicts or a single dict or list of strings
sheet_rows = []
if isinstance(sheet_data_raw, dict):
    # if dict possibly contains list under a key
    # try common shapes
    if all(isinstance(v, list) for v in sheet_data_raw.values()):
        # take first column-like list into rows
        # fallback: convert into list of dict rows if keys match
        try:
            # if structure {'home_type': ['Appartement','Huis',...]}
            if 'home_type' in sheet_data_raw and isinstance(sheet_data_raw['home_type'], list):
                sheet_rows = [{'home_type': s} for s in sheet_data_raw['home_type']]
            else:
                # attempt to make rows by zipping lists
                keys = list(sheet_data_raw.keys())
                zipped = list(zip(*[sheet_data_raw[k] for k in keys]))
                for z in zipped:
                    row = {k: v for k, v in zip(keys, z)}
                    sheet_rows.append(row)
        except Exception:
            sheet_rows = [sheet_data_raw]
    else:
        # single-row dict
        sheet_rows = [sheet_data_raw]
elif isinstance(sheet_data_raw, list):
    sheet_rows = sheet_data_raw
else:
    print("Unsupported sheet data type; expected list or dict.")
    driver.quit()
    exit()

print(f"Loaded {len(sheet_rows)} home types from sheet")

# --- Step 3: For each home type, apply filter & process results ---
for idx, row in enumerate(sheet_rows, start=1):
    # normalize row access
    max_price = int(row.get("max_rental_price", 2573))
    max_area = int(row.get("max_living_area", 153))
    max_rooms = int(row.get("max_bedrooms", 6))
    if isinstance(row, dict):
        home_type = row.get('Type_Of_Home') or row.get('Type_Of_Home') or row.get('Type_Of_Home') or str(list(row.values())[0])
    else:
        home_type = str(row)
    if not home_type:
        print(f"Row {idx}: no home_type value, skipping")
        continue

    home_type = home_type.strip()
    print(f"\n[{idx}/{len(sheet_rows)}] Applying filter for home type: '{home_type}'")

    # reload base page to clear previous filters
    driver.get(BASE_URL)
    time.sleep(2)
    # accept cookies if necessary (some sites clear cookie banner on reload)
    try:
        accept_cookies_once()
    except Exception:
        pass

    # build robust XPath to find checkbox container which has the label text inside (handles nested tags)
    # This looks for a q-checkbox div that contains any descendant with text equal to the home_type
    checkbox_xpath = f"//div[contains(@class,'q-checkbox')][.//text()[normalize-space(.) = '{home_type}']]"

    # Alternate fallback: match by partial text (case-insensitive)
    checkbox_partial_xpath = f"//div[contains(@class,'q-checkbox')][.//text()[contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), '{home_type.lower()}')]]"

    checkbox_clicked = False
    try:
        # try exact match first
        checkbox = wait.until(EC.presence_of_element_located((By.XPATH, checkbox_xpath)))
        # ensure it is clickable
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, checkbox_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", checkbox)
            try:
                checkbox.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", checkbox)
            print(f"Clicked checkbox (exact match) for: {home_type}")
            checkbox_clicked = True
        except TimeoutException:
            # try click via JS
            driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", checkbox)
            print(f"Clicked checkbox via JS (exact match) for: {home_type}")
            checkbox_clicked = True
    except TimeoutException:
        # try partial match
        try:
            checkbox = wait.until(EC.presence_of_element_located((By.XPATH, checkbox_partial_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", checkbox)
            try:
                checkbox.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", checkbox)
            print(f"Clicked checkbox (partial match) for: {home_type}")
            checkbox_clicked = True
        except TimeoutException:
            # last resort: iterate labels and compare text
            try:
                labels = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.q-checkbox__label")))
                for lbl in labels:
                    try:
                        txt = lbl.text.strip()
                        if txt and txt.lower() == home_type.lower():
                            # parent q-checkbox container
                            cont = lbl.find_element(By.XPATH, "./ancestor::div[contains(@class,'q-checkbox')]")
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cont)
                            try:
                                cont.click()
                            except ElementClickInterceptedException:
                                driver.execute_script("arguments[0].click();", cont)
                            print(f"Clicked checkbox via label scan for: {home_type}")
                            checkbox_clicked = True
                            break
                    except StaleElementReferenceException:
                        continue
            except Exception:
                pass

    if not checkbox_clicked:
        print(f"WARNING: Checkbox for '{home_type}' not found — continuing without this filter")
        # continue to try Apply anyway

    time.sleep(0.8)

    # Click apply button (robust)
    clicked_apply = click_apply_button()
    if not clicked_apply:
        print("Could not click Apply — continuing to next home type")
        continue

    # Wait for filtered results to appear
    try:
        # Wait until at least one offer-card is present (or timeout)
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.property.offer-card")))
        time.sleep(1)  # small buffer
        print("Filtered results loaded")
    except TimeoutException:
        print("No filtered results loaded for this filter — skipping this type")
        continue

    # Collect filtered listing URLs
    # Collect filtered listing URLs
    try:
        valid_listings = []
        import re

        while True:  # LOOP ALL PAGES
            cards = driver.find_elements(By.CSS_SELECTOR, "div.property.offer-card")
            print(f"➡ Found {len(cards)} cards on this page")

            for i in range(len(cards)):
                # -------------------------------
                # SAFE RE-LOCATE CARD (anti-stale)
                # -------------------------------
                try:
                    c = driver.find_elements(By.CSS_SELECTOR, "div.property.offer-card")[i]
                except:
                    print(f"⚠ Card #{i} missing, skipping")
                    continue

                # SAFE READ TEXT
                try:
                    card_text = c.text
                except:
                    try:
                        c = driver.find_elements(By.CSS_SELECTOR, "div.property.offer-card")[i]
                        card_text = c.text
                    except:
                        print("❌ Cannot read card text, skipping")
                        continue

                print("\ncard complete data:\n", card_text)

                # ================================
                # PRICE PARSER
                # ================================
                price = None

                # Method 1 – XPATH using global index
                try:
                    price_xpath = f"(//div[contains(@class,'property offer-card')])[{i+1}]//b[contains(text(), '€')]"
                    price_el = WebDriverWait(driver, 1).until(
                        EC.presence_of_element_located((By.XPATH, price_xpath))
                    )
                    price_raw = price_el.text

                    price = int(price_raw.replace("€", "").replace("p/m", "").replace(".", "").replace(",", "").strip())
                    print("→ Price via XPATH:", price)

                except:
                    print("XPATH price not found → fallback")
                    match = re.search(r"€\s*([\d\.\,]+)\s*p/m", card_text)
                    if match:
                        price = int(match.group(1).replace(".", "").replace(",", ""))
                        print("→ Price via fallback:", price)
                    else:
                        print("⚠ No price found → skipping card")
                        continue

                # ================================
                # AREA PARSER
                # ================================
                try:
                    area_match = re.search(r"(\d+)\s*m²", card_text)
                    if not area_match:
                        living_area = 153

                    living_area = int(area_match.group(1))
                    print("→ Living Area:", living_area)

                except:
                    print("⚠ Area error → skipping")
                    continue

                # ================================
                # BEDROOMS PARSER
                # ================================
                try:
                    # bedrooms often shown as a plain number; last digit not area
                    nums = re.findall(r"\b(\d+)\b", card_text)
                    bedrooms = 1

                    for n in nums:
                        if int(n) != living_area:  # avoid matching area
                            bedrooms = int(n)
                    print("→ Bedrooms:", bedrooms)
                except:
                    print("⚠ Bedrooms error → default 1")
                    bedrooms = 1

                # ================================
                # APPLY FILTERS
                # ================================
                if price <= max_price and living_area <= max_area and bedrooms <= max_rooms:
                    print("✔ ACCEPTED CARD")
                    try:
                        url = c.find_element(By.CSS_SELECTOR, "a.offer-card__content").get_attribute("href")
                        if url:
                            valid_listings.append(url)
                    except:
                        print("⚠ Cannot read URL")
                else:
                    print("✘ REJECTED CARD")

            # ================================
            # CHECK NEXT PAGE
            # ================================
            try:
                # Find the next button by span text 'Volgende' inside the button
                next_btn = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//button[.//span[text()='Volgende']]")
                    )
                )

                # Check if button is disabled (attribute or CSS class)
                is_disabled = next_btn.get_attribute("disabled") or "disabled" in next_btn.get_attribute("class").lower()
                if is_disabled:
                    print("⛔ Next page button is disabled — reached last page")
                    break  # exit your while loop here

                # Scroll into view and click
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
                try:
                    next_btn.click()
                    print("➡ Next page clicked")
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", next_btn)
                    print("➡ Next page clicked via JS fallback")

                time.sleep(2)

            except TimeoutException:
                print("⛔ Next page not found — likely last page")
                break

            

    except Exception as e:
        print("Error collecting listings:", e)
        valid_listings = []
    print(f"Found {len(valid_listings)} filtered listings.")

    # try:
    #     cards = driver.find_elements(By.CSS_SELECTOR, "div.property.offer-card")
    #     valid_listings = []
    #     import re
    #     for c in cards:
    #         print("card complete data", c.text)

    #         price = None  # default empty

    #         # --- METHOD 1: Try XPATH first ---
    #         try:
    #             price_el = WebDriverWait(c, 3).until(
    #                 EC.presence_of_element_located(
    #                     (By.XPATH, ".//a[contains(@class,'offer-card__content')]//b[contains(., '€')]")
    #                 )
    #             )
    #             price_text = price_el.text.strip()

    #             clean_price = (
    #                 price_text.replace("€", "")
    #                         .replace("p/m", "")
    #                         .replace(" ", "")
    #                         .replace(".", "")
    #                         .replace(",", "")
    #                         .strip()
    #             )
    #             price = int(clean_price)
    #             print(f"→ Price found via XPATH: €{price}")

    #         except Exception as e:
    #             print("XPATH price not found, fallback to text:", e)

    #             # --- METHOD 2: FALLBACK using c.text ---
    #             card_text = c.text

    #             match = re.search(r"€\s*([\d\.\,]+)\s*p/m", card_text)
    #             if match:
    #                 p = match.group(1)
    #                 price = int(p.replace(".", "").replace(",", ""))
    #                 print(f"→ Price found via TEXT fallback: €{price}")
    #             else:
    #                 print("⚠ Could not extract price from card text")
    #                 continue  # skip this card if price not found

    # # You can continue with area + bedrooms logic below...

    #         try:
    #             # --- Get Living Area ---
    #             area_el = c.find_element(By.XPATH, ".//span[contains(text(), 'm²')]")
    #             area_text = area_el.text.strip()

    #             clean_area = (
    #                 area_text.replace("m²", "")
    #                         .replace(" ", "")
    #                         .replace(".", "")
    #                         .replace(",", "")
    #                         .strip()
    #             )
    #             living_area = int(clean_area)
    #             print(f"→ Living Area: {living_area} m²")

    #         except Exception as e:
    #             print("Area read error:", e)
    #             continue
    #         try:
    #             # Get all detail spans in the card
    #             detail_spans = c.find_elements(By.CSS_SELECTOR, "span.property__details--item")
                
    #             if not detail_spans:
    #                 bedrooms = 1
    #             else:
    #                 # Assume bedrooms is the last span that contains digits (m² is handled separately)
    #                 bedrooms = 1  # default
    #                 for span in detail_spans[::-1]:  # reverse, last first
    #                     text = span.text.strip()
    #                     if text and text.isdigit():  # number found
    #                         bedrooms = int(text) + 1
    #                         break

    #             print(f"→ Bedrooms: {bedrooms}")

    #         except Exception as e:
    #             bedrooms = 1
    #             print(f"Bedrooms read error: {e}, defaulting to 1")

    #         # --- Apply both filters together ---
    #         if price <= max_price and living_area <= max_area and bedrooms <= max_rooms:
    #             print(f"   ✔ Accepted (price, area, bedrooms within limits)")
    #             url = c.find_element(By.CSS_SELECTOR, "a.offer-card__content").get_attribute("href")
    #             if url:
    #                 valid_listings.append(url)
    #         else:
    #             print(f"   ✘ Rejected (price/area/bedrooms out of range)")
    #     print(f"Found {len(valid_listings)} filtered listings for {home_type}")
    # except Exception as e:
    #     print("Error collecting listings:", e)
    #     valid_listings = []

    # --- Step 4: Process each listing (your original workflow preserved) ---
    for listing_url in valid_listings:
        
        print(f"\nProcessing listing: {listing_url}")
        try:
            driver.get(listing_url)
            wait.until(EC.url_to_be(listing_url))
        except Exception:
            print("Failed to open listing, skipping.")
            continue

        # -----------------------------
        # REPLACEMENT: USE SHEET DATA
        # -----------------------------
        sheet_first = row.get("First_Name", "")
        sheet_last = row.get("Last_Name", "")
        sheet_email = row.get("Email", "")
        sheet_phone = row.get("Phone", "")

        # Step 1: Click interest button
        INTEREST_BTN_XPATH = "//p[contains(text(), 'Ik heb interesse')]"
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, INTEREST_BTN_XPATH)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", btn)
            print("Clicked 'Ik heb interesse!'")
        except TimeoutException:
            print("Couldn't find 'Ik heb interesse!' button, skipping.")
            continue

        # Step 2: Wait for form
        try:
            form = wait.until(EC.visibility_of_element_located((By.ID, "subscription-form")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", form)
            time.sleep(1)
        except TimeoutException:
            print("Form did not appear, skipping.")
            continue

        # Step 3: Fill form using sheet data
        def fill_input(field_id, value):
            input_el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f"div.input-field#{field_id} input")))
            input_el.clear()
            input_el.send_keys(value)

        fill_input("name", sheet_first)
        fill_input("lastname", sheet_last)
        fill_input("email", sheet_email)
        fill_input("phone", str(sheet_phone))

        print(f"Filled form with SHEET data: {sheet_first} {sheet_last} ({sheet_email})")

        # === Activate ALL Toggles ===
        def activate_toggle(toggle_id):
            js = f"""
            const el = document.getElementById('{toggle_id}');
            if (el) {{
                const input = el.querySelector('.q-toggle__native');
                const label = el.querySelector('.q-toggle__label');
                if (input && !input.checked) {{
                    input.checked = true;
                    input.dispatchEvent(new Event('change', {{bubbles: true}}));
                    const vue = el.__vue__;
                    if (vue && vue.toggle) vue.toggle();
                    if (label) label.click();
                }}
            }}
            """
            driver.execute_script(js)
            print(f"Toggle ON: {toggle_id}")

        for tid in ["tags.RegisteredInNetherlands", "tags.CreditCheckConsent", "consent"]:
            try:
                activate_toggle(tid)
            except Exception as e:
                print(f"Toggle {tid} error: {e}")
        time.sleep(1)

        # === Click "Verzenden" Button ===
        try:
            submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Verzenden')]")))
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            driver.execute_script("arguments[0].click();", submit_btn)
            print("SUBMITTED: Verzenden button clicked via JS")

            try:
                WebDriverWait(driver, 15).until(EC.url_contains("/thank-you/"))
                print("SUCCESS: Thank you page loaded!")
            except Exception:
                print("No redirect, but form likely sent")
        except Exception as e:
            print(f"Submit failed: {e}")

        time.sleep(3)

# All done
driver.quit()
print("\nAutomation finished and browser closed")