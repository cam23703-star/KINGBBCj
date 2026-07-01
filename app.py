import asyncio
import time
import httpx
import json
import base64
from collections import defaultdict
from proto import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
from google.protobuf import json_format, message
from google.protobuf.message import Message
from Crypto.Cipher import AES
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# === Settings ===

MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB53"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"
SUPPORTED_REGIONS = ["IND", "BD", "BR", "US", "SAC", "NA", "SG", "RU", "ID", "TW", "VN", "TH", "ME", "PK", "CIS", "EUROPE"]

# === Telegram Config ===
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

cached_tokens = defaultdict(dict)
uid_region_cache = {}
token_generating = defaultdict(bool)  # To prevent concurrent token generation

# === LEVELS Dictionary ===
LEVELS = {
    "1": 0, "2": 48, "3": 202, "4": 544, "5": 1012, "6": 1844, "7": 2792, "8": 3800,
    "9": 4870, "10": 6004, "11": 7192, "12": 8448, "13": 9776, "14": 11140, "15": 12566,
    "16": 14060, "17": 15610, "18": 17224, "19": 18902, "20": 20632, "21": 22424,
    "22": 24728, "23": 26192, "24": 28166, "25": 30200, "26": 32294, "27": 34448,
    "28": 37804, "29": 41174, "30": 44870, "31": 48852, "32": 53334, "33": 58566,
    "34": 64096, "35": 69994, "36": 76460, "37": 83108, "38": 91128, "39": 99322,
    "40": 108092, "41": 120144, "42": 133266, "43": 147472, "44": 162760, "45": 179126,
    "46": 196572, "47": 215368, "48": 235516, "49": 257010, "50": 279860, "51": 304056,
    "52": 348318, "53": 394982, "54": 444044, "55": 495508, "56": 549364, "57": 633756,
    "58": 721744, "59": 813336, "60": 908522, "61": 1041438, "62": 1180352, "63": 1325256,
    "64": 1476184, "65": 1634300, "66": 1840946, "67": 2056594, "68": 2281242, "69": 2514880,
    "70": 2757530, "71": 3059506, "72": 3372284, "73": 3699456, "74": 4041030, "75": 4397020,
    "76": 4829104, "77": 5282204, "78": 5756304, "79": 6251404, "80": 6767504, "81": 7381324,
    "82": 8043154, "83": 8752952, "84": 9510808, "85": 10316638, "86": 11277190, "87": 12360748,
    "88": 13360304, "89": 14482858, "90": 15659418, "91": 17026708, "92": 18453688, "93": 19941280,
    "94": 21488570, "95": 23095858, "96": 24763138, "97": 26490138, "98": 28277708, "99": 30124996,
    "100": 32032284,
}

# === Helper Functions ===

def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

def decode_protobuf(encoded_data: bytes, message_type: message.Message) -> message.Message:
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance

async def json_to_proto(json_data: str, proto_message: Message) -> bytes:
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()

def get_account_credentials(region: str) -> str:
    r = region.upper()
    if r == "IND":
        return "uid=5057358329&password=17E44CBAB9C32734F0B480AB7B89AD95AAD12F7D64EE629E5E9B8102FE7C72EF"
    elif r == "BD":
        return "uid=4612988977&password=FLASH_TR_TCQZ6EVSZ"
    elif r in {"BR", "US", "SAC", "NA"}:
        return "uid=4612968156&password=FLASH_TR_MZRVWF07I"
    else:
        return "uid=3158350464&password=70EA041FCF79190E3D0A8F3CA95CAAE1F39782696CE9D85C2CCD525E28D223FC"

# === Level Calculation Functions ===

def format_num(num):
    return "{:,}".format(num)

def get_exp_for_level(level):
    try:
        level_str = str(int(level))
        return LEVELS.get(level_str, 0)
    except:
        return 0

def calculate_level_progress(current_exp, current_level):
    try:
        current_level = int(current_level)
        if current_level >= 100:
            return {
                "current_level": 100,
                "current_exp": current_exp,
                "exp_for_current_level": LEVELS["100"],
                "exp_for_next_level": LEVELS["100"],
                "exp_needed": 0,
                "exp_needed_for_100": 0,
                "progress_percentage": 100
            }
        
        exp_for_current = get_exp_for_level(current_level)
        exp_for_next = get_exp_for_level(current_level + 1)
        exp_for_100 = get_exp_for_level(100)
        
        if exp_for_next == 0 or exp_for_current == 0:
            return None
        
        exp_needed = exp_for_next - current_exp
        exp_needed_for_100 = exp_for_100 - current_exp
        
        exp_in_current_level = current_exp - exp_for_current
        exp_range_for_level = exp_for_next - exp_for_current
        if exp_range_for_level > 0:
            progress_percentage = min(100, max(0, (exp_in_current_level / exp_range_for_level) * 100))
        else:
            progress_percentage = 0
        
        return {
            "current_level": current_level,
            "current_exp": current_exp,
            "exp_for_current_level": exp_for_current,
            "exp_for_next_level": exp_for_next,
            "exp_needed": exp_needed,
            "exp_needed_for_100": exp_needed_for_100,
            "progress_percentage": round(progress_percentage, 1)
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

# === Token Generation (On-Demand) ===

async def get_access_token(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip", 'Content-Type': "application/x-www-form-urlencoded"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            data = resp.json()
            return data.get("access_token", "0"), data.get("open_id", "0")
    except Exception as e:
        print(f"Error getting access token: {e}")
        return "0", "0"

async def create_jwt(region: str):
    # Check if already generating
    if token_generating[region]:
        # Wait for existing generation to complete
        for _ in range(30):  # Wait max 30 seconds
            if region in cached_tokens and cached_tokens[region].get('token'):
                return True
            await asyncio.sleep(1)
        return False
    
    token_generating[region] = True
    
    try:
        # Check if token already exists and valid
        if region in cached_tokens:
            info = cached_tokens[region]
            if info.get('token') and info.get('expires_at', 0) > time.time():
                return True
        
        account = get_account_credentials(region)
        token_val, open_id = await get_access_token(account)
        
        if token_val == "0" or open_id == "0":
            print(f"⚠️ Failed to get token for region: {region}")
            return False
        
        body = json.dumps({"open_id": open_id, "open_id_type": "4", "login_token": token_val, "orign_platform_type": "4"})
        proto_bytes = await json_to_proto(body, FreeFire_pb2.LoginReq())
        payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)
        url = "https://loginbp.ggblueshark.com/MajorLogin"
        headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
                   'Content-Type': "application/octet-stream", 'Expect': "100-continue", 'X-Unity-Version': "2018.4.11f1",
                   'X-GA': "v1 1", 'ReleaseVersion': RELEASEVERSION}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            msg = json.loads(json_format.MessageToJson(decode_protobuf(resp.content, FreeFire_pb2.LoginRes)))
            cached_tokens[region] = {
                'token': f"Bearer {msg.get('token','0')}",
                'region': msg.get('lockRegion','0'),
                'server_url': msg.get('serverUrl','0'),
                'expires_at': time.time() + 25200
            }
            print(f"✅ Token generated for region: {region}")
            return True
    except Exception as e:
        print(f"❌ Failed to create JWT for {region}: {e}")
        return False
    finally:
        token_generating[region] = False

async def get_token_info(region: str):
    # Check if token exists and valid
    info = cached_tokens.get(region)
    if info and info.get('token') and time.time() < info.get('expires_at', 0):
        return info['token'], info.get('region', region), info.get('server_url', '')
    
    # Generate new token
    success = await create_jwt(region)
    if success and region in cached_tokens:
        info = cached_tokens[region]
        return info['token'], info.get('region', region), info.get('server_url', '')
    
    return None, None, None

async def GetAccountInformation(uid, unk, region, endpoint):
    try:
        token, lock, server = await get_token_info(region)
        
        if not token or token == "Bearer 0":
            return None
        
        payload = await json_to_proto(json.dumps({'a': uid, 'b': unk}), main_pb2.GetPlayerPersonalShow())
        data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, payload)
        
        headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
                   'Content-Type': "application/octet-stream", 'Expect': "100-continue",
                   'Authorization': token, 'X-Unity-Version': "2018.4.11f1", 'X-GA': "v1 1",
                   'ReleaseVersion': RELEASEVERSION}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(server+endpoint, data=data_enc, headers=headers)
            result = json.loads(json_format.MessageToJson(decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)))
            return result
    except Exception as e:
        print(f"Error getting account info for {uid} in {region}: {e}")
        return None

# === Stylish Formatter ===

def get_rank_name(rank_id: int) -> str:
    ranks = {
        0: "🥉 Bronze", 1: "🥈 Silver", 2: "🥇 Gold", 3: "💎 Platinum",
        4: "🔷 Diamond", 5: "⭐ Heroic", 6: "👑 Grand Master"
    }
    return ranks.get(rank_id, f"Rank {rank_id}")

def get_language_name(lang_code: str) -> str:
    languages = {
        "Language_ARABIC": "🇸🇦 Arabic", "Language_ENGLISH": "🇬🇧 English",
        "Language_INDONESIAN": "🇮🇩 Indonesian", "Language_PORTUGUESE": "🇵🇹 Portuguese",
        "Language_RUSSIAN": "🇷🇺 Russian", "Language_SPANISH": "🇪🇸 Spanish",
        "Language_THAI": "🇹🇭 Thai", "Language_TURKISH": "🇹🇷 Turkish",
        "Language_VIETNAMESE": "🇻🇳 Vietnamese", "Language_HINDI": "🇮🇳 Hindi",
        "Language_BENGALI": "🇧🇩 Bengali"
    }
    return languages.get(lang_code, lang_code.replace("Language_", ""))

def create_progress_bar(percentage: float, length: int = 20) -> str:
    filled = int(length * percentage / 100)
    empty = length - filled
    return "█" * filled + "░" * empty

def format_complete_info(data: dict, uid: str) -> str:
    if not data:
        return "❌ Failed to fetch data"
    
    basic = data.get('basicInfo', {})
    if not basic:
        return "❌ No basic info found"
    
    profile = data.get('profileInfo', {})
    clan = data.get('clanBasicInfo', {})
    pet = data.get('petInfo', {})
    social = data.get('socialInfo', {})
    credit = data.get('creditScoreInfo', {})
    
    # Level Progress Calculation
    current_exp = basic.get('exp', 0)
    current_level = basic.get('level', 0)
    level_progress = calculate_level_progress(current_exp, current_level)
    
    # Format timestamps
    created_date = time.strftime('%d-%m-%Y', time.localtime(int(basic.get('createAt', 0)))) if basic.get('createAt') else 'N/A'
    last_login = time.strftime('%d-%m-%Y', time.localtime(int(basic.get('lastLoginAt', 0)))) if basic.get('lastLoginAt') else 'N/A'
    days_old = int((time.time() - int(basic.get('createAt', time.time()))) / 86400) if basic.get('createAt') else 0
    
    # Level progress bar
    progress_bar = ""
    level_info_text = ""
    if level_progress:
        progress_bar = create_progress_bar(level_progress['progress_percentage'])
        level_info_text = f"\n📊 Progress: `{progress_bar}` `{level_progress['progress_percentage']}%`"
        level_info_text += f"\n✨ EXP to Next Level: `{format_num(level_progress['exp_needed'])}`"
        level_info_text += f"\n🎯 EXP to Level 100: `{format_num(level_progress['exp_needed_for_100'])}`"
    
    message = f"""
╔════════════════════════════════════════════╗
║     🔥 FREE FIRE ACCOUNT INFO 🔥          ║
╠════════════════════════════════════════════╣

👤 *【 BASIC INFO 】*
┌─────────────────────────────────────────────
│ 🆔 UID: `{basic.get('accountId', uid)}`
│ 👤 Name: `{basic.get('nickname', 'N/A')}`
│ 🌍 Region: `{basic.get('region', 'N/A')}`
│ 📊 Level: `{basic.get('level', 'N/A')}`
│ ⭐ EXP: `{format_num(current_exp)}`{level_info_text}
│ 🔄 Version: `{basic.get('releaseVersion', 'N/A')}`
│ 🎮 Season: `{basic.get('seasonId', 'N/A')}`
└─────────────────────────────────────────────

🎖️ *【 RANK INFO 】*
┌─────────────────────────────────────────────
│ 🏆 BR Rank: `{get_rank_name(basic.get('rank', 0))}`
│ 📈 BR Points: `{format_num(basic.get('rankingPoints', 0))}`
│ 🏅 Max BR: `{get_rank_name(basic.get('maxRank', 0))}`
│ 🎯 CS Rank: `{get_rank_name(basic.get('csRank', 0))}`
│ 📊 CS Points: `{basic.get('csRankingPoints', 0)}`
│ ⭐ Max CS: `{get_rank_name(basic.get('csMaxRank', 0))}`
└─────────────────────────────────────────────

🏢 *【 CLAN INFO 】*
┌─────────────────────────────────────────────
│ 🏠 Clan: `{clan.get('clanName', 'No Clan')}`
│ 🆔 ID: `{clan.get('clanId', 'N/A')}`
│ 📊 Level: `{clan.get('clanLevel', 'N/A')}`
│ 👥 Members: `{clan.get('memberNum', 0)}/{clan.get('capacity', 0)}`
└─────────────────────────────────────────────

🐾 *【 PET INFO 】*
┌─────────────────────────────────────────────
│ 🐶 Name: `{pet.get('name', 'No Pet')}`
│ 📊 Level: `{pet.get('level', 'N/A')}`
│ ⭐ EXP: `{format_num(pet.get('exp', 0))}`
└─────────────────────────────────────────────

🎨 *【 PROFILE 】*
┌─────────────────────────────────────────────
│ 🖼️ Avatar: `{profile.get('avatarId', 'N/A')}`
│ 🎨 Banner: `{basic.get('bannerId', 'N/A')}`
│ 🏅 Badges: `{basic.get('badgeCnt', 0)}`
│ 💝 Likes: `{format_num(basic.get('liked', 0))}`
│ 💎 Credit: `{credit.get('creditScore', 'N/A')}`
│ 🌐 Language: `{get_language_name(social.get('language', 'N/A'))}`
└─────────────────────────────────────────────

📅 *【 TIMELINE 】*
┌─────────────────────────────────────────────
│ 📆 Created: `{created_date}`
│ 🔄 Last Login: `{last_login}`
│ 📅 Age: `{days_old} days`
└─────────────────────────────────────────────

📝 *【 SIGNATURE 】*
┌─────────────────────────────────────────────
│ `{social.get('signature', 'No Signature')[:60]}`
└─────────────────────────────────────────────

╚════════════════════════════════════════════╝
🤖 *Bot by Flash | Real-time Data*
"""
    return message

def format_level_only(data: dict, uid: str) -> str:
    """Only level information with progress"""
    if not data:
        return "❌ Failed to fetch data"
    
    basic = data.get('basicInfo', {})
    if not basic:
        return "❌ No basic info found"
    
    current_exp = basic.get('exp', 0)
    current_level = basic.get('level', 0)
    nickname = basic.get('nickname', 'Unknown')
    
    level_progress = calculate_level_progress(current_exp, current_level)
    
    if not level_progress:
        return "❌ Could not calculate level progress"
    
    progress_bar = create_progress_bar(level_progress['progress_percentage'])
    
    message = f"""
╔════════════════════════════════════╗
║     📊 LEVEL PROGRESSION INFO      ║
╠════════════════════════════════════╣

👤 *Player:* `{nickname}`
🆔 *UID:* `{uid}`
🌍 *Region:* `{basic.get('region', 'N/A')}`

⭐ *Current Level:* `{current_level}`
✨ *Current EXP:* `{format_num(current_exp)}`

📊 *Progress to Level {current_level + 1}:*
{progress_bar} `{level_progress['progress_percentage']}%`

🎯 *EXP Needed:*
├ Next Level: `{format_num(level_progress['exp_needed'])}`
└ Level 100: `{format_num(level_progress['exp_needed_for_100'])}`

📈 *EXP Details:*
├ Current Level EXP: `{format_num(level_progress['exp_for_current_level'])}`
└ Next Level EXP: `{format_num(level_progress['exp_for_next_level'])}`

╚════════════════════════════════════╝
"""
    return message

# === Telegram Bot Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Account Info", callback_data="help_info")],
        [InlineKeyboardButton("📈 Level System", callback_data="help_level")],
        [InlineKeyboardButton("🌍 Regions", callback_data="help_regions")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔥 *FREE FIRE ACCOUNT INFO BOT* 🔥\n\n"
        "⚡ *Features:*\n"
        "• Complete Account Information\n"
        "• Level Progression with Progress Bar\n"
        "• Rank Details (BR/CS)\n"
        "• Clan & Pet Info\n"
        "• Profile Customization\n\n"
        "*Commands:*\n"
        "• `/info <UID>` - Complete info\n"
        "• `/level <UID>` - Only level progress\n"
        "• `/clothes <UID>` - Equipped items\n"
        "• `/skills <UID>` - Skills list\n"
        "• `/raw <UID>` - Raw JSON\n"
        "• `/regions` - Supported regions\n\n"
        "*Example:* `/info 3419823759`",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide UID\nExample: `/info 3419823759`", parse_mode='Markdown')
        return
    
    uid = context.args[0].strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ Invalid UID! Only numbers allowed.")
        return
    
    # Send initial message
    msg = await update.message.reply_text("🔍 *Searching for account...*\n\n⏳ This may take a few seconds...", parse_mode='Markdown')
    
    # Check cached region first
    if uid in uid_region_cache:
        try:
            data = await GetAccountInformation(uid, "7", uid_region_cache[uid], "/GetPlayerPersonalShow")
            if data and data.get('basicInfo'):
                await msg.edit_text(format_complete_info(data, uid), parse_mode='Markdown')
                return
        except:
            pass
    
    # Try all regions
    for region in SUPPORTED_REGIONS:
        try:
            await msg.edit_text(f"🔍 *Checking region:* `{region}`...", parse_mode='Markdown')
            data = await GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow")
            if data and data.get('basicInfo'):
                uid_region_cache[uid] = region
                await msg.edit_text(format_complete_info(data, uid), parse_mode='Markdown')
                return
        except:
            continue
    
    await msg.edit_text(f"❌ UID `{uid}` not found in any region!\n\nPossible reasons:\n• Invalid UID\n• Account is private/banned\n• Server issue", parse_mode='Markdown')

async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide UID\nExample: `/level 3419823759`", parse_mode='Markdown')
        return
    
    uid = context.args[0].strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ Invalid UID! Only numbers allowed.")
        return
    
    msg = await update.message.reply_text("🔍 *Searching...*", parse_mode='Markdown')
    
    if uid in uid_region_cache:
        try:
            data = await GetAccountInformation(uid, "7", uid_region_cache[uid], "/GetPlayerPersonalShow")
            if data:
                await msg.edit_text(format_level_only(data, uid), parse_mode='Markdown')
                return
        except:
            pass
    
    for region in SUPPORTED_REGIONS:
        try:
            await msg.edit_text(f"🔍 *Checking:* `{region}`...", parse_mode='Markdown')
            data = await GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow")
            if data and data.get('basicInfo'):
                uid_region_cache[uid] = region
                await msg.edit_text(format_level_only(data, uid), parse_mode='Markdown')
                return
        except:
            continue
    
    await msg.edit_text(f"❌ UID `{uid}` not found!", parse_mode='Markdown')

async def clothes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide UID")
        return
    
    uid = context.args[0].strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ Invalid UID!")
        return
    
    msg = await update.message.reply_text("🔍 *Searching...*", parse_mode='Markdown')
    
    for region in SUPPORTED_REGIONS:
        try:
            data = await GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow")
            if data:
                profile = data.get('profileInfo', {})
                clothes = profile.get('clothes', [])
                
                if not clothes:
                    await msg.edit_text("👕 No clothes equipped!")
                    return
                
                result = "👕 *EQUIPPED CLOTHES/SKINS:*\n"
                for i, cloth in enumerate(clothes, 1):
                    result += f"`{i}. ID: {cloth}`\n"
                await msg.edit_text(result, parse_mode='Markdown')
                return
        except:
            continue
    
    await msg.edit_text(f"❌ UID `{uid}` not found!", parse_mode='Markdown')

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide UID")
        return
    
    uid = context.args[0].strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ Invalid UID!")
        return
    
    msg = await update.message.reply_text("🔍 *Searching...*", parse_mode='Markdown')
    
    for region in SUPPORTED_REGIONS:
        try:
            data = await GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow")
            if data:
                profile = data.get('profileInfo', {})
                skills = profile.get('equipedSkills', [])
                
                if not skills:
                    await msg.edit_text("⚡ No skills equipped!")
                    return
                
                result = "⚡ *EQUIPPED SKILLS:*\n"
                for i in range(0, len(skills), 4):
                    if i+3 < len(skills):
                        result += f"`Skill {i//4 + 1}: ID {skills[i]} | Slot {skills[i+1]}`\n"
                await msg.edit_text(result, parse_mode='Markdown')
                return
        except:
            continue
    
    await msg.edit_text(f"❌ UID `{uid}` not found!", parse_mode='Markdown')

async def raw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide UID")
        return
    
    uid = context.args[0].strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ Invalid UID!")
        return
    
    msg = await update.message.reply_text("🔍 *Fetching data...*", parse_mode='Markdown')
    
    for region in SUPPORTED_REGIONS:
        try:
            data = await GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow")
            if data:
                json_str = json.dumps(data, indent=2, ensure_ascii=False)
                if len(json_str) > 4000:
                    json_str = json_str[:4000] + "\n... (truncated)"
                await msg.edit_text(f"```json\n{json_str}\n```", parse_mode='Markdown')
                return
        except:
            continue
    
    await msg.edit_text(f"❌ UID `{uid}` not found!", parse_mode='Markdown')

async def regions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    regions_list = "\n".join([f"🌍 `{r}`" for r in sorted(SUPPORTED_REGIONS)])
    await update.message.reply_text(
        f"🌐 *SUPPORTED REGIONS*\n\n{regions_list}\n\n"
        f"📊 *Total:* `{len(SUPPORTED_REGIONS)}` regions\n\n"
        f"⚡ *Status:* On-Demand Token Generation Active",
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "help_info":
        await query.edit_message_text(
            "📊 *Account Info Command*\n\n"
            "`/info <UID>` - Get complete account information\n\n"
            "*Includes:*\n"
            "• Basic Info (Name, Level, EXP)\n"
            "• Rank Info (BR/CS Ranks)\n"
            "• Clan Info\n"
            "• Pet Info\n"
            "• Profile Customization\n"
            "• Account Timeline\n\n"
            "*Example:* `/info 3419823759`",
            parse_mode='Markdown'
        )
    elif query.data == "help_level":
        await query.edit_message_text(
            "📈 *Level System*\n\n"
            "`/level <UID>` - Show level progression\n\n"
            "*Features:*\n"
            "• Current Level & EXP\n"
            "• Progress Bar to Next Level\n"
            "• EXP Needed for Next Level\n"
            "• EXP Needed for Level 100\n\n"
            "*Level EXP Table:*\n"
            "• Level 1: 0 EXP\n"
            "• Level 50: 279,860 EXP\n"
            "• Level 100: 32,032,284 EXP",
            parse_mode='Markdown'
        )
    elif query.data == "help_regions":
        await query.edit_message_text(
            "🌍 *Supported Regions*\n\n" +
            "\n".join([f"• `{r}`" for r in sorted(SUPPORTED_REGIONS)]) +
            f"\n\n*Total:* {len(SUPPORTED_REGIONS)} regions\n"
            "*Status:* On-Demand Token Generation",
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 8:
        context.args = [text]
        await info_command(update, context)
    else:
        await update.message.reply_text(
            "❌ Send a valid UID or use /help for commands\n\n"
            "Quick commands:\n"
            "• `/info <UID>` - Full info\n"
            "• `/level <UID>` - Level only",
            parse_mode='Markdown'
        )

# === Main Function ===

async def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║                                                      ║
    ║     🔥 FREE FIRE COMPLETE INFO BOT 🔥               ║
    ║                                                      ║
    ║     • Account Information                           ║
    ║     • Level Progression with Progress Bar          ║
    ║     • Multi-Region Support                          ║
    ║     • On-Demand Token Generation                    ║
    ║                                                      ║
    ║          Created by Flash                           ║
    ║                                                      ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    print("🤖 Bot is starting with ON-DEMAND token generation...")
    print("⚡ Tokens will be generated only when needed!")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("level", level_command))
    application.add_handler(CommandHandler("clothes", clothes_command))
    application.add_handler(CommandHandler("skills", skills_command))
    application.add_handler(CommandHandler("raw", raw_command))
    application.add_handler(CommandHandler("regions", regions_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot is starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print(f"✅ Bot is running! Send UID to test")
    print("⚡ Tokens will be generated automatically when someone searches a UID")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())