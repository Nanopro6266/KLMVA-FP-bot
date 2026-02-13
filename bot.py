import os
import json
import asyncio
import discord
import websockets
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

WSS_URL = "wss://24data.ptfs.app/wss"

intents = discord.Intents.default()
client = discord.Client(intents=intents)


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

    channel = client.get_channel(CHANNEL_ID)
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

    await channel.send(embed=embed)



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

        except Exception as e:
            print(f"WebSocket error: {e}")
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(websocket_listener())


client.run(TOKEN)
