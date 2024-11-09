import asyncio
import aiohttp
import time
import uuid
import json
from loguru import logger
from colorama import Fore, Style, init
import sys
import os
from utils.banner import banner

# 初始化 colorama 和配置 loguru
init(autoreset=True)
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>", colorize=True)

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

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
proxy_auth_status = {}
browser_id = None
account_info = {}
last_ping_time = {}

def uuidv4():
    return str(uuid.uuid4())

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("无效的响应")
    return resp

# 将会话信息保存到 JSON 文件
def save_session_info(proxy, data):
    session_data = load_all_sessions()
    session_data[proxy] = {
        "uid": data.get("uid"),
        "browser_id": browser_id
    }
    with open(SESSION_FILE, 'w') as file:
        json.dump(session_data, file)
    logger.info(f"已为代理 {proxy} 保存会话")

# 从 JSON 文件加载所有会话
def load_all_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as file:
            return json.load(file)
    return {}

# 加载特定代理的会话
def load_session_info(proxy):
    session_data = load_all_sessions()
    return session_data.get(proxy, {})

async def render_profile_info(proxy, token):
    global browser_id, account_info

    try:
        if not proxy_auth_status.get(proxy):
            
            saved_session = load_session_info(proxy)
            if saved_session:
                browser_id = saved_session["browser_id"]
                account_info["uid"] = saved_session["uid"]
                proxy_auth_status[proxy] = True
                logger.info(f"为代理 {proxy} 加载了保存的会话")
            else:
                browser_id = uuidv4()
                response = await call_api(DOMAIN_API["SESSION"], {}, proxy, token)
                if response:
                    valid_resp(response)
                    account_info = response["data"]
                    if account_info.get("uid"):
                        proxy_auth_status[proxy] = True
                        save_session_info(proxy, account_info)
                        logger.info(f"代理 {proxy} 认证成功。")
                    else:
                        handle_logout(proxy)
                        
                else:
                    return

        await start_ping(proxy, token)

    except Exception as e:
        logger.error(f"代理 {proxy} 的 render_profile_info 中发生异常: {e}")

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
                    logger.warning(f"请求 {url} 失败，状态码 {options_response.status}，代理 {proxy}")
                    return None
                else:
                    logger.debug(f"请求 {url} 成功，代理 {proxy}")
        except Exception as e:
            return None

        # 如果 OPTIONS 请求成功，则发送 POST 请求
        for attempt in range(max_retries):
            try:
                logger.debug(f"代理 {proxy} 的 POST 请求尝试 {attempt + 1}")
                async with session.post(url, json=data, headers=headers, proxy=proxy, timeout=10) as response:
                    response.raise_for_status()
                    resp_json = await response.json()
                    logger.debug(f"代理 {proxy} 的 POST 请求在尝试 {attempt + 1} 成功")
                    return valid_resp(resp_json)
            except aiohttp.ClientResponseError as e:
                if e.status == 403:
                    logger.warning(f"API 调用")
