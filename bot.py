# import packages
import json
import asyncio
import re

import discord
import aiohttp
import websockets
from discord import app_commands

# env variabelen
TOKEN = ""
CHANNEL_ID_ROUTE = 1
CHANNEL_ID_FPL = 1
ROLE_ID = 1
SERVER_ID = 1
MASTER_ROLE = 1

WSS_URL = "wss://24data.ptfs.app/wss"
BOT_ACTIVE = True

# Gedefieneerde routes:
ROUTE_PAIRS = [
    ("IRFD", "IPPH"),
    ("IRFD", "ITKO"),
    ("IRFD", "ILAR"),
    ("IPPH", "IRFD"),
    ("IPPH", "ILAR"),
    ("IPPH", "ITKO"),
    ("ITKO", "IRFD"),
    ("ITKO", "IPPH"),
    ("ITKO", "ILAR"),
    ("ILAR", "IRFD"),
    ("ILAR", "IPPH"),
    ("ILAR", "ITKO")
]

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
tree = app_commands.CommandTree(client)


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
route_messages = {}

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

# Messages bijhouden
def route_key(dep_airport, arr_airport):
    return f"{dep_airport}-{arr_airport}"


# route embed
async def send_route_embed(dep_airport, dep_runway, arr_airport, arr_runway):
    if not BOT_ACTIVE:
        return

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

    if not channel:
        return

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

    key = route_key(dep_airport, arr_airport)

    # 🔁 Update of nieuw bericht
    if key in route_messages:
        try:
            message = await channel.fetch_message(route_messages[key])
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            # Bericht is handmatig verwijderd
            del route_messages[key]

    # Nieuw bericht
    message = await channel.send(embed=embed)
    route_messages[key] = message.id


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
    if not BOT_ACTIVE:
        return
    
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

# check of iemand de MASTER_ROLE heeft
def has_offline_role(interaction: discord.Interaction) -> bool:
    return any(role.id == MASTER_ROLE for role in interaction.user.roles)


# /offline command
@tree.command(
    name="offline",
    description="Disable bot and clear route channel",
    guild=discord.Object(id=SERVER_ID)
)
async def offline(interaction: discord.Interaction):
    global BOT_ACTIVE

    if not has_offline_role(interaction):
        await interaction.response.send_message(
            "❌ You are not allowed to use this command.",
            ephemeral=True
        )
        return

    BOT_ACTIVE = False

    channel = client.get_channel(CHANNEL_ID_ROUTE)
    if not channel:
        await interaction.response.send_message(
            "Route channel not found.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "🔴 Bot is now offline. Clearing routes...",
        ephemeral=True
    )

    async for message in channel.history(limit=None):
        await message.delete()

    embed = discord.Embed(
        title="🚫 Bot currently offline",
        description="Route recommendations are temporarily unavailable.",
        color=0xFF0000
    )

    await channel.send(embed=embed)



# start programma
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    server = discord.Object(id=SERVER_ID)
    await tree.sync(guild=server)
    print("Slash commands synced (server)")
    
    channel = client.get_channel(CHANNEL_ID_ROUTE)
    async for message in channel.history(limit=None):
        await message.delete()

    await fetch_initial_atis()
    client.loop.create_task(websocket_listener())



client.run(TOKEN)