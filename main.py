import asyncio
import aiohttp
import time
import uuid
import json
from loguru import logger
from colorama import Fore, Style, init
import sys
import os

# Banner (你可以自定义或删除)
banner = """

               ╔═╗╔═╦╗─╔╦═══╦═══╦═══╦═══╗
               ╚╗╚╝╔╣║─║║╔══╣╔═╗║╔═╗║╔═╗║
               ─╚╗╔╝║║─║║╚══╣║─╚╣║─║║║─║║
               ─╔╝╚╗║║─║║╔══╣║╔═╣╚═╝║║─║║
               ╔╝╔╗╚╣╚═╝║╚══╣╚╩═║╔═╗║╚═╝║
               ╚═╝╚═╩═══╩═══╩═══╩╝─╚╩═══╝
               原作者：github.com/zlkcyber
               汉化：推特雪糕战神@Hy78516012       
                
"""

# Initialize colorama and configure loguru
init(autoreset=True)
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>", colorize=True)

# Constants
PING_INTERVAL = 180
RETRIES = 120
TOKEN_FILE = 'np_tokens.txt'
SESSION_FILE = 'sessions.json'
DOMAIN_API = {
    "SESSION": "https://api.nodepay.org/api/auth/session?",
    "PING": "https://nw.nodepay.org/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

# Global variables
status_connect = CONNECTION_STATES["NONE_CONNECTION"]
proxy_auth_status = {}
browser_id = None
account_info = {}
last_ping_time = {}

def uuidv4():
    return str(uuid.uuid4())

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("Invalid response")
    return resp

def save_session_info(proxy, data):
    session_data = load_all_sessions()
    session_data[proxy] = {
        "uid": data.get("uid"),
        "browser_id": browser_id
    }
    with open(SESSION_FILE, 'w') as file:
        json.dump(session_data, file)
    logger.info(f"Session saved for proxy {proxy}")

def load_all_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as file:
            return json.load(file)
    return {}

def load_session_info(proxy):
    session_data = load_all_sessions()
    return session_data.get(proxy, {})

def load_proxies_from_file(filename="proxy.txt"):
    """Load proxies from proxy.txt file"""
    try:
        with open(filename, 'r') as file:
            proxies = [line.strip() for line in file if line.strip()]
        logger.info(f"成功加载 {len(proxies)} 代理从文件 {filename}")
        return proxies
    except FileNotFoundError:
        logger.error(f"代理文件 {filename} 没有找到")
        return []
    except Exception as e:
        logger.error(f"从文件 {filename}加载失败: {e}")
        return []

def load_tokens_from_file(filename):
    try:
        with open(filename, 'r') as file:
            tokens = file.read().splitlines()
        return tokens
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        return []

async def call_api(url, data, proxy, token, max_retries=3):
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': '*/*',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0',
    }
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True)) as session:
        try:
            async with session.options(url, headers=headers, proxy=proxy, timeout=10) as options_response:
                if options_response.status not in (200, 204):
                    logger.warning(f"Request to {url} failed with status {options_response.status} with proxy {proxy}")
                    return None
                else:
                    logger.debug(f"Request successful for {url} with proxy {proxy}")
        except Exception as e:
            return None

        for attempt in range(max_retries):
            try:
                async with session.post(url, json=data, headers=headers, proxy=proxy, timeout=10) as response:
                    response.raise_for_status()
                    resp_json = await response.json()
                    return valid_resp(resp_json)
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed for proxy {proxy}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

async def render_profile_info(proxy, token):
    global browser_id, account_info

    try:
        if not proxy_auth_status.get(proxy):
            saved_session = load_session_info(proxy)
            if saved_session:
                browser_id = saved_session["browser_id"]
                account_info["uid"] = saved_session["uid"]
                proxy_auth_status[proxy] = True
                logger.info(f"成功加载代理 {proxy}")
            else:
                browser_id = uuidv4()
                response = await call_api(DOMAIN_API["SESSION"], {}, proxy, token)
                if response:
                    valid_resp(response)
                    account_info = response["data"]
                    if account_info.get("uid"):
                        proxy_auth_status[proxy] = True
                        save_session_info(proxy, account_info)
                        logger.info(f"Proxy {proxy} authenticated successfully.")
                    else:
                        handle_logout(proxy)
                else:
                    return

        await start_ping(proxy, token)

    except Exception as e:
        logger.error(f"Exception in render_profile_info for proxy {proxy}: {e}")

async def start_ping(proxy, token):
    try:
        while True:
            await ping(proxy, token)
            await asyncio.sleep(PING_INTERVAL)
    except asyncio.CancelledError:
        logger.info(f"Ping task for proxy {proxy} was cancelled")
    except Exception as e:
        logger.error(f"Error in start_ping for proxy {proxy}: {e}")

async def ping(proxy, token):
    global last_ping_time, RETRIES, status_connect

    current_time = time.time()
    if proxy in last_ping_time and (current_time - last_ping_time[proxy]) < PING_INTERVAL:
        return

    last_ping_time[proxy] = current_time

    try:
        data = {
            "id": account_info.get("uid"),
            "browser_id": browser_id,
            "timestamp": int(time.time()),
            "version": '2.2.7'
        }
        response = await call_api(DOMAIN_API["PING"], data, proxy, token)
        if response and response["code"] == 0:
            logger.info(f"Ping successful via proxy {proxy}")
            RETRIES = 0
            status_connect = CONNECTION_STATES["CONNECTED"]
        else:
            handle_ping_fail(proxy, response)
    except Exception as e:
        logger.error(f"Ping error for proxy {proxy}: {e}")
        handle_ping_fail(proxy, None)

def handle_ping_fail(proxy, response):
    global RETRIES, status_connect
    RETRIES += 1
    if response and response.get("code") == 403:
        handle_logout(proxy)
    elif RETRIES < 2:
        status_connect = CONNECTION_STATES["DISCONNECTED"]
    else:
        status_connect = CONNECTION_STATES["DISCONNECTED"]

def handle_logout(proxy):
    global status_connect, account_info
    status_connect = CONNECTION_STATES["NONE_CONNECTION"]
    account_info = {}
    proxy_auth_status[proxy] = False
    logger.info(f"Logged out and cleared session info for proxy {proxy}")

async def proxy_handler(proxy, token):
    await render_profile_info(proxy, token)
    if proxy_auth_status.get(proxy):
        asyncio.create_task(start_ping(proxy, token))

async def main():
    print(Fore.MAGENTA + Style.BRIGHT + banner + Style.RESET_ALL)
    logger.info("正在加载代理")
    await asyncio.sleep(5)

    # Load proxies and tokens
    all_proxies = load_proxies_from_file("proxy.txt")
    if not all_proxies:
        logger.error("No proxies found in proxy.txt. Please add proxies and restart.")
        return

    tokens = load_tokens_from_file(TOKEN_FILE)
    if not tokens:
        logger.error("No tokens found. Please add tokens to np_tokens.txt")
        return

    logger.info(f"加载了 {len(all_proxies)} 个代理 和 {len(tokens)} 个tokens")

    while True:
        for token in tokens:
            tasks = []
            for proxy in all_proxies:
                formatted_proxy = f"http://{proxy}" if not proxy.startswith(('http://', 'https://')) else proxy
                tasks.append(asyncio.create_task(proxy_handler(formatted_proxy, token)))

            await asyncio.gather(*tasks)
            await asyncio.sleep(3)
        await asyncio.sleep(10)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user.")
    except Exception as e:
        logger.error(f"Program terminated due to error: {e}")
