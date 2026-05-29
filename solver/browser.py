import os
import time
import random
import asyncio
from patchright.async_api import async_playwright
from browser_configs import browser_config
from solver.store import save_result


COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}


async def _antishadow_inject(page):
    await page.add_init_script("""
      (function() {
        const originalAttachShadow = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function(init) {
          const shadow = originalAttachShadow.call(this, init);
          if (init.mode === 'closed') {
            window.__lastClosedShadowRoot = shadow;
          }
          return shadow;
        };
      })();
    """)


async def _optimized_route_handler(route):
    url = route.request.url
    resource_type = route.request.resource_type

    allowed_types = {'document', 'script', 'xhr', 'fetch'}

    allowed_domains = [
        'challenges.cloudflare.com',
        'static.cloudflareinsights.com',
        'cloudflare.com'
    ]

    if resource_type in allowed_types:
        await route.continue_()
    elif any(domain in url for domain in allowed_domains):
        await route.continue_()
    else:
        await route.abort()


async def _block_rendering(page):
    await page.route("**/*", _optimized_route_handler)


async def _unblock_rendering(page):
    await page.unroute("**/*", _optimized_route_handler)


async def _find_and_click_checkbox(page, index, debug):
    try:
        iframe_selectors = [
            'iframe[src*="challenges.cloudflare.com"]',
            'iframe[src*="turnstile"]',
            'iframe[title*="widget"]'
        ]

        iframe_locator = None
        for selector in iframe_selectors:
            try:
                test_locator = page.locator(selector).first
                try:
                    iframe_count = await test_locator.count()
                except Exception:
                    iframe_count = 0

                if iframe_count > 0:
                    iframe_locator = test_locator
                    if debug:
                        print(f"Browser {index}: Found Turnstile iframe with selector: {selector}")
                    break
            except Exception as e:
                if debug:
                    print(f"Browser {index}: Iframe selector '{selector}' failed: {str(e)}")
                continue

        if iframe_locator:
            try:
                iframe_element = await iframe_locator.element_handle()
                frame = await iframe_element.content_frame()

                if frame:
                    checkbox_selectors = [
                        'input[type="checkbox"]',
                        '.cb-lb input[type="checkbox"]',
                        'label input[type="checkbox"]'
                    ]

                    for selector in checkbox_selectors:
                        try:
                            try:
                                checkbox = frame.locator(selector).first
                                await checkbox.click(timeout=2000)
                                if debug:
                                    print(f"Browser {index}: Successfully clicked checkbox in iframe with selector '{selector}'")
                                return True
                            except Exception as click_e:
                                if debug:
                                    print(f"Browser {index}: Direct checkbox click failed for '{selector}': {str(click_e)}")
                                continue
                        except Exception as e:
                            if debug:
                                print(f"Browser {index}: Iframe checkbox selector '{selector}' failed: {str(e)}")
                            continue

                    try:
                        if debug:
                            print(f"Browser {index}: Trying to click iframe directly as fallback")
                        await iframe_locator.click(timeout=1000)
                        return True
                    except Exception as e:
                        if debug:
                            print(f"Browser {index}: Iframe direct click failed: {str(e)}")

            except Exception as e:
                if debug:
                    print(f"Browser {index}: Failed to access iframe content: {str(e)}")

    except Exception as e:
        if debug:
            print(f"Browser {index}: General iframe search failed: {str(e)}")

    return False


async def _safe_click(page, selector, index, debug):
    try:
        locator = page.locator(selector).first
        await locator.click(timeout=1000)
        return True
    except Exception as e:
        if debug and "Can't query n-th element" not in str(e):
            print(f"Browser {index}: Safe click failed for '{selector}': {str(e)}")
        return False


async def _try_click_strategies(page, index, debug):
    strategies = [
        ('checkbox_click', lambda: _find_and_click_checkbox(page, index, debug)),
        ('direct_widget', lambda: _safe_click(page, '.cf-turnstile', index, debug)),
        ('iframe_click', lambda: _safe_click(page, 'iframe[src*="turnstile"]', index, debug)),
        ('js_click', lambda: page.evaluate("document.querySelector('.cf-turnstile')?.click()")),
        ('sitekey_attr', lambda: _safe_click(page, '[data-sitekey]', index, debug)),
        ('any_turnstile', lambda: _safe_click(page, '*[class*="turnstile"]', index, debug)),
        ('xpath_click', lambda: _safe_click(page, "//div[@class='cf-turnstile']", index, debug))
    ]

    for strategy_name, strategy_func in strategies:
        try:
            result = await strategy_func()
            if result is True or result is None:
                if debug:
                    print(f"Browser {index}: Click strategy '{strategy_name}' succeeded")
                return True
        except Exception as e:
            if debug:
                print(f"Browser {index}: Click strategy '{strategy_name}' failed: {str(e)}")
            continue

    return False


async def _inject_captcha_directly(page, websiteKey, action, cdata, index, debug):
    script = f"""
    (function() {{
    const existingWidgets = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
    console.log('Turnstile Debug: Found ' + existingWidgets.length + ' potential widgets');
    let useExisting = false;
    let foundSitekey = null;

    for (const widget of existingWidgets) {{
        const widgetSitekey = widget.getAttribute('data-sitekey');
        console.log('Turnstile Debug: Checking widget with sitekey:', widgetSitekey);
        if (widgetSitekey === '{websiteKey}') {{
            useExisting = true;
            foundSitekey = widgetSitekey;
            console.log('Turnstile Debug: Found existing turnstile widget with matching sitekey');
            break;
        }}
    }}

    const turnstileIframes = document.querySelectorAll('iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]');
    console.log('Turnstile Debug: Found ' + turnstileIframes.length + ' turnstile iframes');

    let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
    if (!tokenInput) {{
        tokenInput = document.createElement('input');
        tokenInput.type = 'hidden';
        tokenInput.name = 'cf-turnstile-response';
        document.body.appendChild(tokenInput);
    }}

    window._turnstileTokenCallback = function(token) {{
        console.log('Turnstile token captured:', token);
        tokenInput.value = token;
    }};

    if (useExisting) {{
        console.log('Using existing turnstile widget');
        const originalCallback = window.turnstileCallback;
        window.turnstileCallback = function(token) {{
            window._turnstileTokenCallback(token);
            if (originalCallback) originalCallback(token);
        }};
        return 'existing';
    }}

    document.querySelectorAll('.cf-turnstile').forEach(el => el.remove());
    document.querySelectorAll('[data-sitekey]').forEach(el => {{
        if (el.getAttribute('data-sitekey') !== '{websiteKey}') el.remove();
    }});

    const captchaDiv = document.createElement('div');
    captchaDiv.className = 'cf-turnstile';
    captchaDiv.setAttribute('data-sitekey', '{websiteKey}');
    captchaDiv.setAttribute('data-callback', '_turnstileTokenCallback');
    {f'captchaDiv.setAttribute("data-action", "{action}");' if action else ''}
    {f'captchaDiv.setAttribute("data-cdata", "{cdata}");' if cdata else ''}
    captchaDiv.style.position = 'fixed';
    captchaDiv.style.top = '20px';
    captchaDiv.style.left = '20px';
    captchaDiv.style.zIndex = '9999';
    captchaDiv.style.backgroundColor = 'white';
    captchaDiv.style.padding = '15px';
    captchaDiv.style.border = '2px solid #0f79af';
    captchaDiv.style.borderRadius = '8px';
    captchaDiv.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.3)';

    document.body.appendChild(captchaDiv);

    const loadTurnstile = () => {{
        const script = document.createElement('script');
        script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
        script.async = true;
        script.defer = true;
        script.onload = function() {{
            console.log('Turnstile script loaded');
            setTimeout(() => {{
                if (window.turnstile && window.turnstile.render) {{
                    try {{
                        window.turnstile.render(captchaDiv, {{
                            sitekey: '{websiteKey}',
                            {f'action: "{action}",' if action else ''}
                            {f'cdata: "{cdata}",' if cdata else ''}
                            callback: function(token) {{
                                console.log('Turnstile solved with token:', token);
                                window._turnstileTokenCallback(token);
                            }},
                            'error-callback': function(error) {{
                                console.log('Turnstile error:', error);
                            }}
                        }});
                    }} catch (e) {{
                        console.log('Turnstile render error:', e);
                    }}
                }} else {{
                    console.log('Turnstile API not available');
                }}
            }}, 1000);
        }};
        script.onerror = function() {{
            console.log('Failed to load Turnstile script');
        }};
        document.head.appendChild(script);
    }};

    if (window.turnstile) {{
        console.log('Turnstile already loaded, rendering immediately');
        try {{
            window.turnstile.render(captchaDiv, {{
                sitekey: '{websiteKey}',
                {f'action: "{action}",' if action else ''}
                {f'cdata: "{cdata}",' if cdata else ''}
                callback: function(token) {{
                    console.log('Turnstile solved with token:', token);
                    window._turnstileTokenCallback(token);
                }},
                'error-callback': function(error) {{
                    console.log('Turnstile error:', error);
                }}
            }});
        }} catch (e) {{
            console.log('Immediate render error:', e);
            loadTurnstile();
        }}
    }} else {{
        loadTurnstile();
    }}

    window.onTurnstileCallback = function(token) {{
        console.log('Global turnstile callback executed:', token);
    }};

    return 'injected';
    }})();
    """

    result = await page.evaluate(script)
    if debug:
        if result == 'existing':
            print(f"Browser {index}: Detected existing turnstile widget with matching sitekey")
        else:
            print(f"Browser {index}: Injected new CAPTCHA widget with sitekey: {websiteKey}")
    return result


async def solve_turnstile(task_id, sitekey, pageurl, action=None, cdata=None, browser_type="chromium", headless=True, debug=False, proxy_support=False, useragent=None, sec_ch_ua=None):
    index = 1
    proxy = None

    if browser_type in ['chromium', 'chrome', 'msedge']:
        if not useragent:
            _, _, useragent, sec_ch_ua = browser_config.get_random_browser_config(browser_type)
    
    browser_args = [
        "--window-position=0,0",
        "--force-device-scale-factor=1"
    ]
    if useragent:
        browser_args.append(f"--user-agent={useragent}")

    if proxy_support:
        proxy_file_path = os.path.join(os.getcwd(), "proxies.txt")
        try:
            with open(proxy_file_path) as proxy_file:
                proxies = [line.strip() for line in proxy_file if line.strip()]
            proxy = random.choice(proxies) if proxies else None
            if debug and proxy:
                print(f"Browser {index}: Selected proxy: {proxy}")
            elif debug and not proxy:
                print(f"Browser {index}: No proxies available")
        except FileNotFoundError:
            print(f"Proxy file not found: {proxy_file_path}")
            proxy = None
        except Exception as e:
            print(f"Error reading proxy file: {str(e)}")
            proxy = None

    playwright = None
    browser = None

    try:
        if browser_type in ['chromium', 'chrome', 'msedge']:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                channel=browser_type,
                headless=headless,
                args=browser_args
            )
        else:
            raise ValueError(f"Unknown browser_type: {browser_type!r}. Supported: chromium, chrome, msedge")

        context_options = {}
        if useragent:
            context_options["user_agent"] = useragent
        if sec_ch_ua and sec_ch_ua.strip():
            context_options['extra_http_headers'] = {'sec-ch-ua': sec_ch_ua}

        if proxy:
            if '@' in proxy:
                try:
                    scheme_part, auth_part = proxy.split('://')
                    auth, address = auth_part.split('@')
                    username, password = auth.split(':')
                    ip, port = address.split(':')
                    if debug:
                        print(f"Browser {index}: Creating context with proxy {scheme_part}://{ip}:{port} (auth: {username}:***)")
                    context_options["proxy"] = {
                        "server": f"{scheme_part}://{ip}:{port}",
                        "username": username,
                        "password": password
                    }
                except ValueError:
                    raise ValueError(f"Invalid proxy format: {proxy}")
            else:
                parts = proxy.split(':')
                if len(parts) == 5:
                    proxy_scheme, proxy_ip, proxy_port, proxy_user, proxy_pass = parts
                    if debug:
                        print(f"Browser {index}: Creating context with proxy {proxy_scheme}://{proxy_ip}:{proxy_port} (auth: {proxy_user}:***)")
                    context_options["proxy"] = {
                        "server": f"{proxy_scheme}://{proxy_ip}:{proxy_port}",
                        "username": proxy_user,
                        "password": proxy_pass
                    }
                elif len(parts) == 3:
                    if debug:
                        print(f"Browser {index}: Creating context with proxy {proxy}")
                    context_options["proxy"] = {"server": f"{proxy}"}
                else:
                    raise ValueError(f"Invalid proxy format: {proxy}")

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        await _antishadow_inject(page)
        await _block_rendering(page)

        await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
        };
        """)

        if browser_type in ['chromium', 'chrome', 'msedge']:
            await page.set_viewport_size({"width": 500, "height": 100})
            if debug:
                print(f"Browser {index}: Set viewport size to 500x240")

        start_time = time.time()

        try:
            if debug:
                print(f"Browser {index}: Starting Turnstile solve for URL: {pageurl} with Sitekey: {sitekey} | Action: {action} | Cdata: {cdata} | Proxy: {proxy}")
                print(f"Browser {index}: Setting up optimized page loading with resource blocking")
                print(f"Browser {index}: Loading real website directly: {pageurl}")

            await page.goto(pageurl, wait_until='networkidle', timeout=30000)

            await _unblock_rendering(page)

            if debug:
                print(f"Browser {index}: Waiting for turnstile to appear...")

            turnstile_found = False
            for wait_attempt in range(15):
                widget_count = await page.locator('.cf-turnstile, [data-sitekey]').count()
                iframe_count = await page.locator('iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]').count()

                turnstile_ready = await page.evaluate("""() => {
                    return typeof window.turnstile !== 'undefined';
                }""")

                if debug and wait_attempt % 3 == 0:
                    print(f"Browser {index}: Wait {wait_attempt + 1}s - {widget_count} widgets, {iframe_count} iframes, turnstile API: {turnstile_ready}")

                if widget_count > 0 or iframe_count > 0 or turnstile_ready:
                    if debug:
                        print(f"Browser {index}: Turnstile ready after {wait_attempt + 1}s (widgets: {widget_count}, iframes: {iframe_count}, API: {turnstile_ready})")
                    turnstile_found = True
                    break
                await asyncio.sleep(1)

            if not turnstile_found:
                if debug:
                    print(f"Browser {index}: Turnstile not found naturally, will inject our own")

            if debug:
                print(f"Browser {index}: Injecting Turnstile widget directly into target site")

            if debug:
                widget_count = await page.locator('.cf-turnstile, [data-sitekey]').count()
                iframe_count = await page.locator('iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]').count()
                print(f"Browser {index}: Before injection - {widget_count} widgets, {iframe_count} iframes")
                try:
                    sitekey_elem = await page.locator('[data-sitekey]').get_attribute('data-sitekey')
                    print(f"Browser {index}: Found sitekey: {sitekey_elem}")
                except:
                    pass

            inject_result = await _inject_captcha_directly(page, sitekey, action or '', cdata or '', index, debug)

            if debug:
                if inject_result == 'existing':
                    print(f"Browser {index}: Using existing turnstile widget on page")
                else:
                    print(f"Browser {index}: Injected new turnstile widget")

            await asyncio.sleep(3)

            locator = page.locator('input[name="cf-turnstile-response"]')
            max_attempts = 30
            click_count = 0
            max_clicks = 10

            for attempt in range(max_attempts):
                try:
                    try:
                        count = await locator.count()
                    except Exception as e:
                        if debug:
                            print(f"Browser {index}: Locator count failed on attempt {attempt + 1}: {str(e)}")
                        count = 0

                    if count == 0:
                        if debug and attempt % 5 == 0:
                            print(f"Browser {index}: No token elements found on attempt {attempt + 1}")
                        if debug and attempt == 0:
                            widget_count = await page.locator('.cf-turnstile, [data-sitekey]').count()
                            iframe_count = await page.locator('iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]').count()
                            print(f"Browser {index}: Page has {widget_count} turnstile widgets and {iframe_count} iframes")
                    elif count == 1:
                        try:
                            token = await locator.input_value(timeout=500)
                            if token:
                                elapsed_time = round(time.time() - start_time, 3)
                                print(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                                await save_result(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})
                                return
                        except Exception as e:
                            if debug:
                                print(f"Browser {index}: Single token element check failed: {str(e)}")
                    else:
                        if debug:
                            print(f"Browser {index}: Found {count} token elements, checking all")

                        for i in range(count):
                            try:
                                element_token = await locator.nth(i).input_value(timeout=500)
                                if element_token:
                                    elapsed_time = round(time.time() - start_time, 3)
                                    print(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{element_token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                                    await save_result(task_id, "turnstile", {"value": element_token, "elapsed_time": elapsed_time})
                                    return
                            except Exception as e:
                                if debug:
                                    print(f"Browser {index}: Token element {i} check failed: {str(e)}")
                                continue

                    if attempt > 2 and attempt % 3 == 0 and click_count < max_clicks:
                        click_success = await _try_click_strategies(page, index, debug)
                        click_count += 1
                        if click_success and debug:
                            print(f"Browser {index}: Click successful (click #{click_count}/{max_clicks})")
                        elif not click_success and debug:
                            print(f"Browser {index}: All click strategies failed on attempt {attempt + 1} (click #{click_count}/{max_clicks})")

                    wait_time = min(0.5 + (attempt * 0.05), 2.0)
                    await asyncio.sleep(wait_time)

                    if debug and attempt % 5 == 0:
                        print(f"Browser {index}: Attempt {attempt + 1}/{max_attempts} - Waiting for token (clicks: {click_count}/{max_clicks})")

                except Exception as e:
                    if debug:
                        print(f"Browser {index}: Attempt {attempt + 1} error: {str(e)}")
                    continue

            elapsed_time = round(time.time() - start_time, 3)
            await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
            if debug:
                print(f"Browser {index}: Error solving Turnstile in {COLORS.get('RED')}{elapsed_time}{COLORS.get('RESET')} Seconds")
        except Exception as e:
            elapsed_time = round(time.time() - start_time, 3)
            await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
            if debug:
                print(f"Browser {index}: Error solving Turnstile: {str(e)}")
        finally:
            if debug:
                print(f"Browser {index}: Closing browser context and cleaning up")
            try:
                await context.close()
                if debug:
                    print(f"Browser {index}: Context closed successfully")
            except Exception as e:
                if debug:
                    print(f"Browser {index}: Error closing context: {str(e)}")

    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright:
            try:
                await playwright.stop()
            except Exception:
                pass
