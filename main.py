import os
import json
import discord
from discord.ext import commands
import asyncio
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="<", intents=intents)
relayChannelsCache = {}
waitingUsers = set()

# Helper functions for config
def loadConfig():
    try:
        with open("config.json", "r") as f:
            content = f.read().strip()
            if not content:
                return {"relayChannels": {}}
            logging.info(f"Loading config...")
            return json.loads(content)
    except FileNotFoundError:
        defaultConfig = {"relayChannels": {}}
        with open("config.json", "w") as f:
            json.dump(defaultConfig, f, indent=2)
        return defaultConfig
    except json.JSONDecodeError:
        print("Warning: config.json is invalid JSON. Resetting to default.")
        defaultConfig = {"relayChannels": {}}
        with open("config.json", "w") as f:
            json.dump(defaultConfig, f, indent=2)
        return defaultConfig

def getRelayChannels():
    config = loadConfig()
    logging.info(f"Getting relay channels...")
    return config.get("relayChannels", {})

def updateRelayChannels(sourceId, destId):
    config = loadConfig()
    relay = config.get("relayChannels", {})
    relay.setdefault(sourceId, []).append(destId)
    config["relayChannels"] = relay
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    logging.info(f"Added {destId} to {sourceId}.")

    global relayChannelsCache
    relayChannelsCache = relay

async def refreshRelayChannelsPeriodically():
    global relayChannelsCache
    await bot.wait_until_ready()
    while not bot.is_closed():
        relayChannelsCache = getRelayChannels()
        await asyncio.sleep(30)

def removeRelayEntry(sourceId=None, destId=None):
    config = loadConfig()
    relayChannels = config.get("relayChannels", {})

    if sourceId is None and destId is None:
        relayChannels.clear()
        logging.info("All channel connections removed from config.")
    
    elif sourceId is not None:
        if destId is None:
            if sourceId in relayChannels:
                del relayChannels[sourceId]
                logging.info(f"Removed {sourceId} from sources.")
            else:
                return False
    
    else:
        if destId in relayChannels[sourceId]:
            relayChannels[sourceId].remove(destId)
            logging.info(f"Removed {destId} from source: {sourceId}.")
            if not relayChannels[sourceId]:
                del relayChannels[sourceId]
                logging.info(f"Source {sourceId} is now empty. Deleting source...")
        else:
            return False

    config["relayChannels"] = relayChannels
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    return True

# Main bot code
@bot.event
async def on_ready():
    bot.loop.create_task(refreshRelayChannelsPeriodically())
    logging.info(f'Bot: {bot.user} is ready\n-------------\n')

@bot.command(name='add', help='Adds a source or destination channel to the channel connections.')
@commands.has_permissions(administrator=True)
async def add(ctx):
    global waitingUsers
    user_id = ctx.author.id
    waitingUsers.add(user_id)

    await ctx.send("Please mention the **source** channel (e.g. #general) or type channel ID:")

    def checkChannel(m):
        return m.author.id == ctx.author.id and m.channel == ctx.channel

    try:
        sourceMsg = await bot.wait_for("message", check=checkChannel, timeout=60)
        sourceChannel = None

        if sourceMsg.channel_mentions:
            sourceChannel = sourceMsg.channel_mentions[0]
        else:
            try:
                sourceChannel = bot.get_channel(int(sourceMsg.content.strip()))
            except:
                await ctx.send("Invalid source channel. Command cancelled.")
                return

        await ctx.send("Now please mention the **destination** channel or type channel ID:")

        destMsg = await bot.wait_for("message", check=checkChannel, timeout=60)
        destChannel = None

        if destMsg.channel_mentions:
            destChannel = destMsg.channel_mentions[0]
        else:
            try:
                destChannel = bot.get_channel(int(destMsg.content.strip()))
            except:
                await ctx.send("Invalid destination channel. Command cancelled.")
                return

        sourceID = str(sourceChannel.id)
        destID = destChannel.id
        updateRelayChannels(sourceID, destID)

        await ctx.send(f"Relay added: messages from {sourceChannel.mention} will be sent to {destChannel.mention}")

    except Exception as e:
        await ctx.send("Timed out or error occurred, command cancelled.")
        logging.warning(e)
    
    finally:
        waitingUsers.discard(user_id)

@bot.command(name='remove', help='Removes a source or destination channel from the channel connections.')
@commands.has_permissions(administrator=True)
async def remove(ctx):
    global waitingUsers
    user_id = ctx.author.id
    waitingUsers.add(user_id)
    def checkChannel(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send("Type `all` to remove the entire source relay, or mention a **source** channel to remove (e.g. #general) or type channel ID:")

    try:
        sourceMsg = await bot.wait_for("message", check=checkChannel, timeout=60)
        sourceChannel = None

        if sourceMsg.content.lower() == "all":
            await ctx.send("Are you sure you want to delete ***__EVERY SINGLE__*** channel connection? This is irreversible! (Y/N)")
            confirmation = await bot.wait_for("message", check=checkChannel, timeout=60)
            if confirmation.content.lower() == "y":
                success = removeRelayEntry()
                if success:
                    await ctx.send("Removed every channel connection.")
                else:
                    await ctx.send("Failed to remove every channel connection.")
                return
            else:
                await ctx.send("User aborted. Command cancelled.")
                return
        if sourceMsg.channel_mentions:
            sourceChannel = sourceMsg.channel_mentions[0]
        else:
            sourceChannel = bot.get_channel(int(sourceMsg.content.strip()))

        if sourceChannel is None:
            await ctx.send("Invalid source channel. Command cancelled.")
            return

        sourceID = str(sourceChannel.id)

        await ctx.send("Type `all` to remove the entire source relay, or mention a **destination** channel to remove:")

        destMsg = await bot.wait_for("message", check=checkChannel, timeout=60)

        if destMsg.content.lower() == "all":
            success = removeRelayEntry(sourceID)
            if success:
                await ctx.send(f"Removed all relays from source channel {sourceChannel.mention}.")
            else:
                await ctx.send("No relays found for that source channel.")
            return

        destChannel = None
        if destMsg.channel_mentions:
            destChannel = destMsg.channel_mentions[0]
        else:
            try:
                destChannel = bot.get_channel(int(destMsg.content.strip()))
            except ValueError:
                await ctx.send("Invalid destination channel ID. Command cancelled.")
                return

        if destChannel is None:
            await ctx.send("Invalid destination channel. Command cancelled.")
            return

        destID = destChannel.id

        success = removeRelayEntry(sourceID, destID)
        if success:
            await ctx.send(f"Removed relay from {sourceChannel.mention} to {destChannel.mention}.")
        else:
            await ctx.send("That relay was not found.")

    except Exception as e:
        await ctx.send("Timed out or error occurred, command cancelled.")
        logging.warning(e)
    
    finally:
        waitingUsers.discard(user_id)

bot.remove_command('help')
@bot.command(name='help', help='Gives you an overview over the available commands.')
async def help(ctx):
    prefix = '<'
    description = "**Available Commands:**\n"
    for command in bot.commands:
        if not command.hidden:
            description += f"- `{prefix}{command.name}` - {command.help or '''No clue mate, wasn't told.'''}\n"
    await ctx.send(description)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Skip the rest if user is currently using a command
    global waitingUsers
    if message.author.id in waitingUsers:
        # Let wait_for handle it silently
        return
    
    # Check if valid command
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
    else:
        logging.info(f'Unkown command sent: {message.content}')

    # Relay messages
    messageChannelID = str(message.channel.id)
    if messageChannelID in relayChannelsCache:
        for destId in relayChannelsCache[messageChannelID]:
            dest = bot.get_channel(int(destId))
            if dest:
                await dest.send(message.content)

bot.run(os.environ.get('TOKEN'))
