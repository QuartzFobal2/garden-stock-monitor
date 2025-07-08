import os, asyncio
from datetime import datetime, timezone
from email.message import EmailMessage
from dotenv import load_dotenv
import aiohttp
import aiosmtplib

# Carrega variáveis do .env
load_dotenv()

SHOP_URL = 'https://api.joshlei.com/v2/growagarden/stock'
CATEGORIES = ['seed_stock', 'gear_stock', 'egg_stock']
TARGET = {
    'Master Sprinkler', 'Godly Sprinkler', 'Bug Egg', 'Bee Egg',
    'Burning Bud', 'Sugar Apple', 'Ember Lily',
    'Beanstalk', 'Tanning Mirror', 'Lightning Rod'
}

SMTP = {
    'host': os.getenv('SMTP_HOST'),
    'port': int(os.getenv('SMTP_PORT', 587)),
    'user': os.getenv('SMTP_USER'),
    'pass': os.getenv('SMTP_PASS'),
    'to':   os.getenv('MAIL_TO')
}

POLL_AFTER_END = 5  # segundos de polling até detectar a nova sessão

def aggregate_by_item_id(items):
    acc = {}
    for it in items:
        iid = it['item_id']
        if iid not in acc:
            acc[iid] = it.copy()
        else:
            acc[iid]['quantity'] += it['quantity']
    return list(acc.values())

async def send_email_alert(cat, items):
    body = "\n".join(f"• {it['display_name']}: {it['quantity']}" for it in items)
    msg = EmailMessage()
    msg['From'] = SMTP['user']
    msg['To'] = SMTP['to']
    msg['Subject'] = f"🔔 [{cat}] Target items in stock"
    msg.set_content(f"Category reset: {cat}\n\n{body}")
    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP['host'], port=SMTP['port'],
            username=SMTP['user'], password=SMTP['pass'],
            start_tls=True
        )
        print(f"✉️ Email sent for {cat}")
    except Exception as e:
        print(f"⚠️ Error sending email for {cat}: {e}")

async def fetch_stock(session):
    resp = await session.get(SHOP_URL, headers={'Accept': 'application/json'})
    resp.raise_for_status()
    data = await resp.json()
    datehdr = resp.headers.get('Date')
    server_time = datetime.strptime(datehdr, '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)
    return data, server_time

async def monitor():
    last_start = {cat: None for cat in CATEGORIES}
    expected_ends = {}

    async with aiohttp.ClientSession() as session:
        # Sessão inicial
        data, server_time = await fetch_stock(session)
        print(f"📋 [{server_time.isoformat()}] Fetched stock\n")

        for cat in CATEGORIES:
            items = data.get(cat, [])
            if not items:
                continue
            last_start[cat] = items[0]['Date_Start']
            end = items[0]['Date_End']
            expected_ends[cat] = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(timezone.utc)

            print(f"🔄 Initial session for {cat}: {last_start[cat]}")
            agg = aggregate_by_item_id(items)
            for it in agg:
                print(f" • {it['display_name']}: {it['quantity']}")
            found = [it for it in agg if it['display_name'] in TARGET and it['quantity'] > 0]
            if found:
                await send_email_alert(cat, found)

        while True:
            now = server_time
            upcoming = [end for end in expected_ends.values() if end > now]
            if not upcoming:
                print("⚠️ Nenhuma sessão futura detectada, refetching...")
                data, server_time = await fetch_stock(session)
                continue

            next_end = min(upcoming)
            wait = (next_end - now).total_seconds()
            print(f"⏱️ Sleeping {int(wait)}s until {next_end.isoformat()} UTC")
            await asyncio.sleep(wait)

            data, server_time = await fetch_stock(session)
            print(f"📋 [{server_time.isoformat()}] Fetched stock after end\n")

            updated = False
            for cat in CATEGORIES:
                items = data.get(cat, [])
                if not items:
                    continue
                start = items[0]['Date_Start']
                if start != last_start.get(cat):
                    last_start[cat] = start
                    end = items[0]['Date_End']
                    expected_ends[cat] = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(timezone.utc)

                    print(f"🔄 New session for {cat}: {start}")
                    agg = aggregate_by_item_id(items)
                    for it in agg:
                        print(f" • {it['display_name']}: {it['quantity']}")
                    found = [it for it in agg if it['display_name'] in TARGET and it['quantity'] > 0]
                    if found:
                        await send_email_alert(cat, found)
                    else:
                        print(f" ⚪ [{cat}] no target items.\n")
                    updated = True

            if not updated:
                print("🔄 Nenhuma sessão nova detectada, polling leve...")
                await asyncio.sleep(POLL_AFTER_END)
                continue

if __name__ == '__main__':
    asyncio.run(monitor())