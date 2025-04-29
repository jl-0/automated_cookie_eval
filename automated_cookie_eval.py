"""
Cookie and Header Tracker

This script uses Playwright to browse a website and track cookie growth over time.
It displays the browser to allow manual login before beginning automated browsing.
It also captures HTTP response codes and error messages for each navigation.

To run this script with automatic environment generation:
    $ uv run automated_cookie_eval.py [start_url] [duration] \
        [refresh_interval] [return_interval] [initial_pause] [cookie_mod_interval]

Example:
    $ uv run automated_cookie_eval.py https://example.com 3500 60 30 15 120
"""

import asyncio
import time
import json
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

# Get credentials from environment variables
COGNITO_USERNAME = os.getenv("COGNITO_USERNAME", "")
COGNITO_PASSWORD = os.getenv("COGNITO_PASSWORD", "")

def setup_logging():
    """Set up logging to a timestamped file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    
    # Create logs directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    log_file = os.path.join(log_dir, f"cookie_tracker_{timestamp}.log")
    return log_file

def calculate_header_size(headers):
    """Calculate the total size of headers in bytes"""
    total_size = 0
    if not headers:
        return total_size
        
    for key, value in headers.items():
        # Add key length + value length + 2 for the ": " separator
        total_size += len(key.encode('utf-8')) + len(str(value).encode('utf-8')) + 2
        # Add 2 more for the CRLF after each header line
        total_size += 2
    
    # Add the final CRLF that separates headers from the body
    total_size += 2
    
    return total_size

def log_message(log_file, message):
    """Log a message to both console and file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    
    # Write to log file (all messages)
    with open(log_file, "a") as f:
        f.write(log_entry + "\n")
    
    # Print to console only URL messages
    # Check if this is a URL-related message
    url_indicators = [
        "Navigating to ", 
        "Returning to starting page: ",
        "Current URL: ",
        "Clicking link: ",
        "Starting automated browsing at "
    ]
    
    # Only print to console if it's a URL message
    if any(indicator in message for indicator in url_indicators):
        # Extract just the URL part if possible
        for indicator in url_indicators:
            if indicator in message:
                url_part = message.split(indicator, 1)[1].split("\n")[0]
                print(f"[{timestamp}] {indicator}{url_part}")
                break
    # For starting and completion messages, still print those
    elif "==== BROWSING SESSION COMPLETE ====" in message or "Starting " in message:
        print(log_entry)

async def browse_and_track_cookies(
    url, 
    browse_duration=600, 
    refresh_interval=60, 
    return_interval=300, 
    log_file=None,
    initial_pause=60,
    cookie_mod_interval=120,
):
    """
    Browse a website and track cookie growth using Playwright.
    
    Args:
        url (str): The starting URL to browse
        browse_duration (int): Total duration to run the script in seconds
        refresh_interval (int): How often to refresh the page in seconds
        return_interval (int): How often to return to the starting page in seconds
        log_file (str): Path to the log file
        initial_pause (int): How long to wait initially for login in seconds
        cookie_mod_interval (int): How often to modify auth cookies in seconds
    """
    async with async_playwright() as p:
        # Launch the browser in headed mode (visible)
        browser = await p.chromium.launch(headless=False)
        
        # Configure the browser context to force links to open in the same tab
        context = await browser.new_context(
            # Prevents links with target="_blank" from opening in a new tab
            ignore_https_errors=True,
            java_script_enabled=True
        )
        
        # Create a new page first
        page = await context.new_page()
                
        # Setup event listener for new pages/tabs - AFTER the main page is created
        async def handle_new_page(new_page):
            # Ignore the main page
            if new_page == page:
                log_message(log_file, "Ignoring main page in page event handler")
                return
                
            log_message(log_file, "New tab detected, will close after capturing URL")
            try:
                # Wait briefly for the page to start loading
                await new_page.wait_for_load_state('domcontentloaded', timeout=5000)
                new_url = new_page.url
                log_message(log_file, f"New tab opened with URL: {new_url}")
                
                # Only redirect if it's not about:blank
                if new_url != "about:blank":
                    # Navigate the main page to this URL
                    log_message(log_file, f"Redirecting main tab to: {new_url}")
                    await page.goto(new_url)
                else:
                    log_message(log_file, "Ignoring about:blank tab")
                
                # Close the new tab
                await new_page.close()
                log_message(log_file, "Closed the new tab")
            except Exception as e:
                log_message(log_file, f"Error handling new tab: {e}")
                try:
                    await new_page.close()
                    log_message(log_file, "Closed the new tab after error")
                except:
                    log_message(log_file, "Could not close the new tab")
        
        # Listen for new pages/tabs AFTER page is created
        context.on('page', handle_new_page)
        
        # Set up response listener to capture status codes
        cognito_redirect_detected = False  # Flag to track if we need to handle login
        
        async def log_response_status(response):
            nonlocal cognito_redirect_detected
            status = response.status
            status_text = response.status_text
            url = response.url
            
            log_message(log_file, "\n==== RESPONSE STATUS ====")
            log_message(log_file, f"URL: {url}")
            log_message(log_file, f"Status Code: {status} {status_text}")
            
            # Detect Amazon Cognito redirects (302 redirects going to a Cognito URL)
            if status == 302:
                # Get the location header to see where the redirect is going
                location = response.headers.get('location', '')
                if location and "amazoncognito" in location:
                    log_message(log_file, f"Amazon Cognito redirect detected (302 to Cognito URL: {location})")
                    cognito_redirect_detected = True
                
            # Log error details if it's an error response
            if status >= 400:
                log_message(
                    log_file, 
                    f"ERROR: Response code {status} indicates an error"
                )
                try:
                    # Try to get response body for error details
                    body = await response.text()
                    # Only log first 500 characters to avoid huge logs
                    if body:
                        log_message(
                            log_file, 
                            f"Error response (truncated): {body[:500]}"
                        )
                        if len(body) > 500:
                            log_message(log_file, "... (response truncated)")
                except Exception as e:
                    log_message(
                        log_file, 
                        f"Could not retrieve error response body: {e}"
                    )
        
        # Register the response listener
        page.on("response", log_response_status)
        
        # Create a separate function for handling login
        async def handle_cognito_login():
            try:
                # Wait for the redirect to complete and page to stabilize
                # Use domcontentloaded instead of networkidle for more reliable loading
                await page.wait_for_load_state('domcontentloaded', timeout=30000)
                log_message(log_file, f"Login page loaded, URL: {page.url}")
               
                if COGNITO_USERNAME and COGNITO_PASSWORD:
                    log_message(log_file, "Attempting automatic login with stored credentials")
                    
                    # First check if page is still valid
                    if page.is_closed():
                        log_message(log_file, "Page is closed during login attempt, cannot proceed")
                        print('Login page closed. Please login manually within 60 seconds.')
                        await asyncio.sleep(60)
                        return
                    
                    try:
                        # Based on the actual HTML source of the login page
                        log_message(log_file, "Looking for NASA Cognito-specific login elements...")
                        
                        # Wait for a second to ensure the page is fully loaded
                        await asyncio.sleep(1)
                        
                        # The login page has duplicate IDs for responsive design (mobile vs desktop)
                        # We need to find the visible username field
                        log_message(log_file, "Checking for visible form elements (page has duplicate IDs)")
                        
                        # Function to find visible elements
                        async def find_visible_element(selectors):
                            for selector in selectors:
                                elements = await page.query_selector_all(selector)
                                for element in elements:
                                    if await element.is_visible():
                                        return element
                            return None
                        
                        # Target the specific username field, ensuring we get the visible one
                        username_field = await find_visible_element(['#signInFormUsername', 'input[name="username"]'])
                        
                        if username_field:
                            log_message(log_file, "Found visible username field")
                            await username_field.click()
                            await username_field.fill("")  # Clear first
                            await username_field.fill(COGNITO_USERNAME)
                            log_message(log_file, "Filled username field")
                            # Add a short pause to let the form process the input
                            await asyncio.sleep(1)
                        else:
                            log_message(log_file, "Could not find visible username field")
                            print('Could not find username field. Please login manually within 60 seconds.')
                            await asyncio.sleep(60)
                            return
                        
                        # Target the specific password field, ensuring we get the visible one
                        password_field = await find_visible_element(['#signInFormPassword', 'input[type="password"]'])
                        
                        if password_field:
                            log_message(log_file, "Found visible password field")
                            await password_field.click()
                            await password_field.fill("")  # Clear first
                            await password_field.fill(COGNITO_PASSWORD)
                            log_message(log_file, "Filled password field")
                            # Add a short pause to let the form process the input
                            await asyncio.sleep(1)
                        else:
                            log_message(log_file, "Could not find visible password field")
                            print('Could not find password field. Please login manually within 60 seconds.')
                            await asyncio.sleep(60)
                            return
                        
                        # Target the specific submit button, ensuring we get the visible one
                        submit_button = await find_visible_element(['input[name="signInSubmitButton"]', 'input[type="submit"]'])
                        
                        if submit_button:
                            log_message(log_file, "Found submit button with name: signInSubmitButton")
                            
                            # Capture current URL to detect changes
                            pre_submit_url = page.url
                            
                            # Click the button and wait for navigation to complete
                            log_message(log_file, "Clicking submit button")
                            await submit_button.click()
                            
                            try:
                                # Wait for navigation to complete - with shorter timeout and less strict condition
                                log_message(log_file, "Waiting for navigation after submit...")
                                
                                # First try waiting for a URL change, which is more reliable than waiting for load states
                                try:
                                    # Define a simple wait condition for URL change
                                    def url_changed():
                                        return page.url != pre_submit_url
                                        
                                    # Wait for URL to change with shorter timeout (10s)
                                    await page.wait_for_function('() => true', timeout=10000)
                                    if url_changed():
                                        log_message(log_file, f"URL changed to: {page.url}")
                                    else:
                                        log_message(log_file, "URL did not change, but continuing...")
                                except Exception as url_wait_error:
                                    log_message(log_file, f"Error waiting for URL change: {url_wait_error}")
                                
                                # Then try waiting for domcontentloaded, which is more reliable than networkidle
                                try:
                                    await page.wait_for_load_state('domcontentloaded', timeout=15000)
                                    log_message(log_file, "Page content loaded")
                                except Exception as load_error:
                                    log_message(log_file, f"Load state timeout, but continuing: {load_error}")
                                
                                # Log success or at least continued operation
                                log_message(log_file, f"Login process completed, current URL: {page.url}")
                                
                            except Exception as nav_error:
                                log_message(log_file, f"Navigation error: {nav_error}")
                                
                                # Check if we're still on a login page
                                current_url = page.url
                                log_message(log_file, f"Current URL after submit attempt: {current_url}")
                                
                                if "login" in current_url.lower() or "signin" in current_url.lower():
                                    log_message(log_file, "Still on login page, checking for error messages")
                                    
                                    # Look for error messages specific to this form
                                    error_element = await page.query_selector('.error-message, .alert-error')
                                    if error_element:
                                        error_text = await error_element.text_content() 
                                        log_message(log_file, f"Login error message found: {error_text}")
                                        print(f"Login error: {error_text}")
                                    
                                    print('Login failed. Please login manually within 60 seconds.')
                                    await asyncio.sleep(60)
                                else:
                                    log_message(log_file, "Page URL changed but navigation event not detected")
                        else:
                            log_message(log_file, "Could not find submit button with name: signInSubmitButton")
                            print('Could not find submit button. Please login manually within 60 seconds.')
                            await asyncio.sleep(60)
                    except Exception as e:
                        log_message(log_file, f"Error during login process: {e}")
                        # Fall back to manual login
                        print('Login error. Please login manually within 60 seconds.')
                        await asyncio.sleep(60)
                else:
                    log_message(log_file, "No credentials available. Waiting for manual login.")
                    print('Please login manually (no credentials found). Waiting 60 seconds.')
                    await asyncio.sleep(60)
            except Exception as outer_e:
                log_message(log_file, f"Outer login error: {outer_e}")
                print('Login process error. Please login manually within 60 seconds.')
                await asyncio.sleep(60)
        
        # Function to check if the current URL is a Cognito login URL
        async def check_and_handle_cognito_login():
            current_url = page.url
            if "awscognito" in current_url or "amazoncognito" in current_url:
                log_message(log_file, f"AWS Cognito login page detected in URL: {current_url}")
                await handle_cognito_login()
                return True
            return False
        
        # Define request header logging function
        async def log_request_headers(request):
            headers = request.headers
            if headers:
                log_message(log_file, "\n==== REQUEST HEADERS ====")
                log_message(log_file, f"URL: {request.url}")
                for key, value in headers.items():
                    log_message(log_file, f"{key}: {value}")
        
        # Define a function to modify specific cookies
        async def modify_auth_cookies():
            """Modify oidc_access_token and cognito cookies to a predefined value"""
            all_cookies = await context.cookies()
            modified_cookies = []
            
            # Log before modification
            log_message(log_file, "\n==== MODIFYING AUTH COOKIES ====")
            
            # Find and modify specific cookies
            for cookie in all_cookies:
                # Look for cookies containing these names
                if 'expires' in cookie:
                    # Create a modified cookie copy
                    modified_cookie = cookie.copy()
                    modified_cookie['expires'] = 0
                    modified_cookies.append(modified_cookie)
                    
                    # Log the modification
                    log_message(log_file, f"Reset 'xxpires' for cookie: {cookie['name']}")
            
            # Only proceed if we found cookies to modify
            if modified_cookies:
                try:
                    # Clear all cookies first
                    await context.clear_cookies()
                    
                    # Add back all original cookies except those we're modifying
                    cookie_names_to_modify = [cookie['name'] for cookie in modified_cookies]
                    original_cookies_to_keep = [cookie for cookie in all_cookies 
                                              if cookie['name'] not in cookie_names_to_modify]
                    
                    # Add back the unmodified cookies
                    if original_cookies_to_keep:
                        await context.add_cookies(original_cookies_to_keep)
                    
                    # Add the modified cookies
                    await context.add_cookies(modified_cookies)
                    log_message(log_file, f"Successfully modified {len(modified_cookies)} auth cookies")
                    
                    # Reload the page to apply cookie changes
                    try:
                        log_message(log_file, "Reloading page to apply cookie changes")
                        await page.reload(timeout=30000, wait_until='domcontentloaded')
                    except Exception as reload_error:
                        log_message(log_file, f"Error during reload after cookie modification: {reload_error}")
                except Exception as e:
                    log_message(log_file, f"Error modifying auth cookies: {e}")
            else:
                log_message(log_file, "No auth cookies found to modify")

        # Navigate to the starting URL
        log_message(log_file, f"Navigating to {url}")
        await page.goto(url)
        
        # Check if we detected a Cognito redirect during navigation
        if cognito_redirect_detected:
            log_message(log_file, "Handling Cognito login after redirect was detected")
            await handle_cognito_login()
            cognito_redirect_detected = False  # Reset the flag
        
        # Get initial cookies and headers
        initial_cookies = await context.cookies()
        log_message(log_file, "\n==== INITIAL REQUEST ====")
        log_message(log_file, f"Cookies count: {len(initial_cookies)}")
        
        # Calculate and log the total header size
        # Get headers from the next request
        request_headers = None
        
        async def capture_initial_headers(request):
            nonlocal request_headers
            request_headers = request.headers
        
        # Set up one-time event listener for next request
        page.once("request", capture_initial_headers)
        
        # Trigger a request by reloading
        try:
            # Make sure page is in a stable state before attempting to reload
            await page.wait_for_load_state('domcontentloaded', timeout=20000)
            
            # Reload with increased timeout and more relaxed wait condition
            await page.reload(timeout=45000, wait_until='domcontentloaded')
            
            # Try to wait for network idle but don't fail if it times out
            try:
                await page.wait_for_load_state('networkidle', timeout=20000)
            except Exception as nw_error:
                log_message(log_file, f"Network idle timeout after reload, continuing anyway: {nw_error}")
        except Exception as reload_error:
            log_message(log_file, f"Error during page reload: {reload_error}")
            # Try alternative approach - navigate to the same URL
            try:
                current_url = page.url
                log_message(log_file, f"Attempting alternative refresh by navigating to current URL: {current_url}")
                await page.goto(current_url, timeout=45000, wait_until='domcontentloaded')
            except Exception as alt_error:
                log_message(log_file, f"Alternative refresh also failed: {alt_error}")
        
        # Calculate and log header size if headers were captured
        if request_headers:
            header_size = calculate_header_size(request_headers)
            log_message(log_file, f"Total request header size: {header_size} bytes")
        
        cookie_details = json.dumps(initial_cookies, indent=2)
        log_message(log_file, f"Cookie details:\n{cookie_details}")
        
        # Wait for user to log in manually
        print(f"Waiting Initial Sleep Period of {initial_pause}...")
        await asyncio.sleep(initial_pause)
        log_message(log_file, f"\Refreshing starting page: {url}")
        try:
            await page.goto(url)
        except Exception:
            browse_duration = 0 # Just end it    
        log_message(log_file, "Continuing with automated browsing...\n")
        
        # Store starting time
        start_time = time.time()
        last_refresh_time = start_time
        last_return_time = start_time
        last_cookie_mod_time = start_time
        
        # Begin browsing loop
        while time.time() - start_time < browse_duration:
            current_time = time.time()
            
            # Check for AWS Cognito login page
            await check_and_handle_cognito_login()
            
            # Capture and display current cookies
            current_cookies = await context.cookies()
            log_message(log_file, "\n==== CURRENT REQUEST ====")
            log_message(log_file, f"Current URL: {page.url}")
            log_message(log_file, f"Cookies count: {len(current_cookies)}")
            
            # Check if we should modify auth cookies
            if current_time - last_cookie_mod_time >= cookie_mod_interval:
                log_message(log_file, "\nTime to modify auth cookies")
                try:
                    await modify_auth_cookies()
                except Exception as e:
                    log_message(log_file, f"Error modifying auth cookies: {e}")
                last_cookie_mod_time = current_time
            
            # Check if we should return to the starting page
            elif current_time - last_return_time >= return_interval:
                log_message(log_file, f"\nReturning to starting page: {url}")
                try:
                    await page.goto(url)
                except Exception as e:
                    log_message(log_file, f"Error returning to starting page: {e}")
                last_return_time = current_time
            
            # Check if we should refresh the current page
            elif current_time - last_refresh_time >= refresh_interval:
                log_message(log_file, "\nRefreshing current page...")
                try:
                    await page.reload()
                except Exception as e:
                    log_message(log_file, f"Error refreshing page: {e}")
                last_refresh_time = current_time
            
            else:
                # Find and click on a random link on the page
                links = await page.query_selector_all('a')
                if links:
                    import random
                    
                    # Filter out links containing certain words
                    bad_link_words = ["install", "uninstall", "forgot", "google"]
                    filtered_links = []
                    for link in links:
                        href = await link.get_attribute('href')
                        if href and not any(bad_word in href.lower() for bad_word in bad_link_words):
                            filtered_links.append((link, href))
                    
                    # Only proceed if we have valid links after filtering
                    if filtered_links:
                        # Select a random link from the first 10 (or fewer if less than 10)
                        random_choice = random.randint(0, min(9, len(filtered_links)-1))
                        random_link, href = filtered_links[random_choice]
                        
                        if (href and not href.startswith('#') and 
                            not href.startswith('javascript:')):
                            try:
                                log_message(log_file, f"\nClicking link: {href}")
                                await random_link.click()
                                # Wait for navigation to complete
                                await page.wait_for_load_state('networkidle')
                            except Exception as e:
                                log_message(log_file, f"Error clicking link: {e}")
                                # If clicking fails, try navigating directly
                                try:
                                    full_url = href if href.startswith('http') else (
                                        f"{url.rstrip('/')}/{href.lstrip('/')}"
                                    )
                                    await page.goto(full_url)
                                except Exception as inner_e:
                                    log_message(
                                        log_file, 
                                        f"Error navigating to link: {inner_e}"
                                    )
                    else:
                        log_message(log_file, "No suitable links found after filtering out install/uninstall links")
            
            # Capture request headers for calculating size
            request_headers = None
            
            async def capture_request_headers(request):
                nonlocal request_headers
                request_headers = request.headers
            
            # Set up one-time event listener for next request
            page.once("request", capture_request_headers)
            
            # Trigger a request by reloading with more resilient error handling
            try:
                # First wait for domcontentloaded (more reliable than networkidle)
                try:
                    await page.wait_for_load_state('domcontentloaded', timeout=10000)
                except Exception as load_error:
                    log_message(log_file, f"Load state timeout before reload, continuing anyway: {load_error}")
                
                # Perform the reload with a more generous timeout
                await page.reload(timeout=30000, wait_until='domcontentloaded')
                
                # Try to wait for a short period of networkidle, but don't fail if it times out
                try:
                    await page.wait_for_load_state('networkidle', timeout=5000)
                except Exception as nw_error:
                    log_message(log_file, f"Network idle timeout after reload, continuing anyway: {nw_error}")
            except Exception as reload_error:
                log_message(log_file, f"Error during page reload: {reload_error}")
                # Don't try alternative approaches here to avoid cascading timeouts
            
            # Calculate and log header size if headers were captured
            if request_headers:
                header_size = calculate_header_size(request_headers)
                log_message(log_file, f"Total request header size: {header_size} bytes")
            
            # Compare with initial cookies to show growth
            new_cookies = [c for c in current_cookies if c not in initial_cookies]
            if new_cookies:
                log_message(log_file, f"New cookies since start: {len(new_cookies)}")
                new_cookie_details = json.dumps(new_cookies, indent=2)
                log_message(log_file, f"New cookie details:\n{new_cookie_details}")
            
            # Set up event listener for next request
            page.once("request", log_request_headers)
                        
            # Wait before next action
            await asyncio.sleep(10)
        
        # Close the browser when done
        await browser.close()
        log_message(log_file, "\n==== BROWSING SESSION COMPLETE ====")

# Example usage
if __name__ == "__main__":
    # Default values
    start_url = "https://example.com"
    duration = 600  # 10 minutes
    refresh_every = 60  # 1 minute
    return_every = 300  # 5 minutes
    initial_pause = 60 # 60 seconds to wait after showing first page
    cookie_mod_every = 120 # 2 minutes to modify auth cookies
    
    # Set up logging to file
    log_file = setup_logging()
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        start_url = sys.argv[1]
    if len(sys.argv) > 2:
        duration = int(sys.argv[2])
    if len(sys.argv) > 3:
        refresh_every = int(sys.argv[3])
    if len(sys.argv) > 4:
        return_every = int(sys.argv[4])
    if len(sys.argv) > 5:
        initial_pause = int(sys.argv[5])
    if len(sys.argv) > 6:
        cookie_mod_every = int(sys.argv[6])
    
    log_message(log_file, f"Starting automated browsing at {start_url}")
    log_message(log_file, f"Running for {duration} seconds, refreshing every {refresh_every} seconds")
    log_message(log_file, f"Returning to start page every {return_every} seconds")
    log_message(log_file, f"Modifying auth cookies every {cookie_mod_every} seconds")
    log_message(log_file, f"Logging to file: {log_file}")
    
    # Run the main function
    asyncio.run(browse_and_track_cookies(
        start_url, 
        duration, 
        refresh_every, 
        return_every, 
        log_file, 
        initial_pause,
        cookie_mod_every
    ))