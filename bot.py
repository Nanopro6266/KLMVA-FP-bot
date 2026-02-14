# import packages
import os
import json
import asyncio
import re

import discord
import aiohttp
import websockets

# env variabelen
TOKEN = "MTQ3MTU2OTg4NzIyOTkwMjk5Mw.GsfYNg.IuFqF3jMA7R_DGDEI7aB4g4ZwAmxiy5h10UhnY"
CHANNEL_ID_ROUTE = 1471606787986690364
CHANNEL_ID_FPL = 1463622717377872056
ROLE_ID = 1471933896198459567

WSS_URL = "wss://24data.ptfs.app/wss"

# Gedefieneerde routes:
BASE_ROUTES = [
    ("IRFD", "IPPH"),
    ("IRFD", "ITKO"),
    ("IPPH", "ITKO"),
    ("ITKO", "ILAR"),
    ("IPPH", "ILAR"),
    ("IRFD", "ILAR"),
]

ROUTE_PAIRS = []
for a, b in BASE_ROUTES:
    ROUTE_PAIRS.append((a, b))
    ROUTE_PAIRS.append((b, a))


# Airport ICAO -> FPL namen
AIRPORT_NAMES = {
    "IRFD": "Greater Rockford",
    "IPPH": "Perth",
    "ITKO": "Tokyo",
    "ILAR": "Larnaca"
}


# Discord client
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


# initial ATIS laden
async def fetch_initial_atis():
    url = "https://24data.ptfs.app/atis"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                print("Failed to fetch initial ATIS:", resp.status)
                return

            data = await resp.json()

            print(f"Loaded {len(data)} ATIS entries")

            for atis in data:
                await handle_atis(atis)



# ATIS status 
atis_dep_runways = {}
atis_arr_runways = {}
last_send_dep_runway = {}
last_send_arr_runway = {}

def extract_dep_runway_from_atis(lines):
    for line in lines:
        match = re.search(r"DEP RWY (\d{1,2}[LRC]?)", line.upper())
        if match:
            runway = match.group(1)

            # 7 -> 07
            if runway[0].isdigit() and len(runway) == 1:
                runway = runway.zfill(2)

            return runway
    return None 

def extract_arr_runway_from_atis(lines):
    for line in lines:
        match = re.search(r"ARR RWY (\d{1,2}[LRC]?)", line.upper())
        if match:
            runway = match.group(1)

            # 7 -> 07
            if runway[0].isdigit() and len(runway) == 1:
                runway = runway.zfill(2)

            return runway
    return None 

# Routes laden
with open("routes.json") as f:
    ROUTES = json.load(f)

def get_route_config(dep_airport, dep_runway, arr_airport, arr_runway):
    return (
        ROUTES
        .get(dep_airport, {})
        .get(dep_runway, {})
        .get(arr_airport, {})
        .get(arr_runway, {})
    )


# FPL bouwen
def build_flightplan_command(
    callsign="KLM###",
    aircraft="A320",
    departing="IRFD",
    dep_rwy = "25L",
    arriving="IPPH",
    arr_rwy = "29",
    flightlevel="###",
    route=""
):
    
    departing_name = AIRPORT_NAMES.get(departing, departing)
    arriving_name = AIRPORT_NAMES.get(arriving, arriving)
    
    return (
        "/createflightplan "
        f"ingamecallsign: "
        f"callsign:{callsign} "
        f"aircraft:{aircraft} "
        f"flightrules:IFR "
        f"departing:{departing_name} "
        f"arriving:{arriving_name} "
        f"flightlevel:{flightlevel} "
        f"route:{departing}/{dep_rwy} {route} {arriving}/{arr_rwy} "
        "/RMK KLMVA"
    )

# route embed
async def send_route_embed(dep_airport, dep_runway, arr_airport, arr_runway):
    config = get_route_config(dep_airport, dep_runway, arr_airport, arr_runway)

    if not config:
        return

    command = build_flightplan_command(
        aircraft="A/Bxxx",
        departing=dep_airport,
        dep_rwy=dep_runway,
        arriving=arr_airport,
        arr_rwy=arr_runway,
        flightlevel=config["flightlevel"],
        route=config["route"]
    )

    channel = client.get_channel(CHANNEL_ID_ROUTE)

    embed = discord.Embed(
        title=f"📍 KLM Route Recommendation – {dep_airport} to {arr_airport}",
        description=f"**Active departure runway:** {dep_runway}",
        color=0x00A1E4
    )

    embed.add_field(
        name="Create Flight Plan Command",
        value=f"```{command}```",
        inline=False
    )

    await channel.send(
        embed=embed
    )


# Anti spam
async def evaluate_routes():
    for dep_airport, arr_airport in ROUTE_PAIRS:
        dep_runway = atis_dep_runways.get(dep_airport)
        arr_runway = atis_arr_runways.get(arr_airport)

        if not dep_runway or not arr_runway:
            continue

        # Anti-spam key per combinatie
        key = f"{dep_airport}-{arr_airport}"

        if last_send_dep_runway.get(key) == (dep_runway, arr_runway):
            continue

        config = get_route_config(
            dep_airport,
            dep_runway,
            arr_airport,
            arr_runway
        )

        if not config:
            continue

        last_send_dep_runway[key] = (dep_runway, arr_runway)

        await send_route_embed(
            dep_airport,
            dep_runway,
            arr_airport,
            arr_runway
        )


# ATIS event handler
async def handle_atis(data):
    airport = data.get("airport")
    lines = data.get("lines", [])

    dep_runway = extract_dep_runway_from_atis(lines)
    arr_runway = extract_arr_runway_from_atis(lines)
    print(f"ATIS received for {airport}, departure runway {dep_runway}, arrival runway {arr_runway}")
    if dep_runway:
        atis_dep_runways[airport] = dep_runway

    if arr_runway:
        atis_arr_runways[airport] = arr_runway

    await evaluate_routes()



# KLMVA FPL handler
async def handle_flight_plan(data, event_type):
    route = data.get("route", "")

    # Normalize (hoofdletters + spaties verwijderen aan begin/einde)
    route_clean = route.upper().strip()

    # Filter:
    if not route.endswith("/RMK KLMVA"):
        return

    # Knip "/RMK KLMVA" van het einde af
    cleaned_route = route_clean.removesuffix("/RMK KLMVA").strip()

    # Gebruik originele formatting behalve het RMK deel
    if route.upper().strip().endswith("/RMK KLMVA"):
        cleaned_route = route[: -len("/RMK KLMVA")].strip()

    channel = client.get_channel(CHANNEL_ID_FPL)
    if channel is None:
        print("Channel not found!")
        return

    embed = discord.Embed(
        title="✈️ KLM VA Flight Plan Filed",
        color=0x00A1E4
    )

    embed.add_field(name="Username", value=data.get("robloxName", "N/A"), inline=True)
    embed.add_field(name="Callsign", value=data.get("callsign", "N/A"), inline=True)
    embed.add_field(name="Aircraft", value=data.get("aircraft", "N/A"), inline=True)
    embed.add_field(name="Flight Rules", value=data.get("flightrules", "N/A"), inline=True)
    embed.add_field(name="From", value=data.get("departing", "N/A"), inline=True)
    embed.add_field(name="To", value=data.get("arriving", "N/A"), inline=True)
    embed.add_field(name="Flight Level", value=data.get("flightlevel", "N/A"), inline=True)
    embed.add_field(name="Route", value=cleaned_route or "N/A", inline=False)

    embed.set_footer(text=f"Server: {'Event' if event_type == 'EVENT_FLIGHT_PLAN' else 'Main'}")

    await channel.send(
        content=f"<@&{ROLE_ID}>",
        embed=embed
    )

# connectie naar websocket
async def websocket_listener():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            async with websockets.connect(WSS_URL, origin=None) as websocket:
                print("Connected to 24data WebSocket")

                async for message in websocket:
                    payload = json.loads(message)

                    event_type = payload.get("t")
                    data = payload.get("d")

                    if event_type in ["FLIGHT_PLAN", "EVENT_FLIGHT_PLAN"]:
                        await handle_flight_plan(data, event_type)

                    elif event_type == "ATIS":
                        await handle_atis(data)

        except Exception as e:
            print(f"WebSocket error: {e}")
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


# start programma
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    await fetch_initial_atis()
    client.loop.create_task(websocket_listener())


client.run(TOKEN)