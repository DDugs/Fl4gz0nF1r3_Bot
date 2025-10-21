import discord
import secrets
import string
import aiohttp
import asyncio
import re
import os
import json
import zipfile
from discord.ui import Modal, TextInput, View, Select, Button, button
from discord.ext import commands, tasks
from discord import app_commands, Interaction, TextChannel
from discord import app_commands
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from collections import defaultdict

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
MAX_CONCURRENT_DOWNLOADS = 10 

solved_logs = []
ctf_events = []
user_ctfd_data = {}

class CTFSelectView(discord.ui.View):
    def __init__(self, events: list):
        super().__init__(timeout=60)
        self.events = events
        options = [
            discord.SelectOption(label=e['title'][:100], description=e['url'][:100], value=str(idx))
            for idx, e in enumerate(events)
        ]
        self.add_item(CTFSelect(options, events))

class CTFSelect(discord.ui.Select):
    def __init__(self, options, events):
        super().__init__(placeholder="Select a CTF to create…", options=options)
        self.events = events

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        event = self.events[idx]
        await create_ctf_from_event(interaction, event)

async def create_ctf_from_event(interaction: discord.Interaction, event: dict):
    guild = interaction.guild

    name = event.get("title")
    url = event.get("url")
    start = datetime.fromisoformat(event.get("start")).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    end = datetime.fromisoformat(event.get("finish")).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    desc = event.get("description", "No description provided.")

    try:
        category = await guild.create_category(f"--- {name} ---")

        admin_role = discord.utils.get(guild.roles, name="Admin")
        mod_role = discord.utils.get(guild.roles, name="Mod")

        overwrites_data = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            admin_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        overwrites_chat = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            admin_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        data_channel = await category.create_text_channel("data", overwrites=overwrites_data)
        chat_channel = await category.create_text_channel("chat", overwrites=overwrites_chat)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot lacks permissions to create channels or categories.", ephemeral=True)
        return

    # store in your ctf_events list
    ctf_data = {
        "name": name,
        "url": url,
        "start": start,
        "end": end,
        "description": desc,
        "channel_id": data_channel.id,
        "reminded_1h": False,
        "reminded_30m": False,
        "reminded_10m": False
    }
    ctf_events.append(ctf_data)

    await data_channel.send(
        f"@everyone 📢 **New CTF Incoming!**\n"
        f"**Name:** `{ctf_data['name']}`\n"
        f"**URL:** {ctf_data['url']}\n"
        f"**Start:** `{start.strftime('%Y-%m-%d %I:%M %p IST')}`\n"
        f"**End:** `{end.strftime('%Y-%m-%d %I:%M %p IST')}`\n"
        f"**Description:** {desc}\n\n"
        f"🔐 **CTF Credentials**\n"
        f"**Username:** `Fl4gz0nF1r3`\n"
        f"**Password:** `Fl4gz0nF1r3@ctf`",
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

    await interaction.response.send_message(
        f"✅ CTF `{name}` created! Details posted in {data_channel.mention}.",
        ephemeral=True
    )

@bot.tree.command(name="ctf", description="📅 Pick a CTF from CTFTime and create channels automatically")
async def create_ctf(interaction: discord.Interaction):
    url = "https://ctftime.org/api/v1/events/?limit=10"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message("❌ Failed to fetch CTFs from ctftime.org.", ephemeral=True)
                return
            events = await resp.json()

    view = CTFSelectView(events)
    await interaction.response.send_message("Select a CTF from the list:", view=view, ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
        check_reminders.start()
        #fetch_ctftime.start()
    except Exception as e:
        print(f"Error syncing commands: {e}")

@tasks.loop(minutes=1)
async def check_reminders():
    now_utc = datetime.now(timezone.utc)
    for ctf in ctf_events[:]:
        start_utc = ctf["start"].astimezone(timezone.utc)
        end_utc = ctf["end"].astimezone(timezone.utc)
        minutes_left = (start_utc - now_utc).total_seconds() / 60
        channel = bot.get_channel(ctf["channel_id"])
        if not channel:
            continue

        if not ctf["reminded_1h"] and minutes_left <= 60:
            await channel.send(f"@everyone ⏰ **Reminder:** `{ctf['name']}` starts in 1 hour!", allowed_mentions=discord.AllowedMentions(everyone=True))
            ctf["reminded_1h"] = True
        elif not ctf["reminded_30m"] and minutes_left <= 30:
            await channel.send(f"@everyone ⏰ **Reminder:** `{ctf['name']}` starts in 30 minutes!", allowed_mentions=discord.AllowedMentions(everyone=True))
            ctf["reminded_30m"] = True
        elif not ctf["reminded_10m"] and minutes_left <= 10:
            await channel.send(f"@everyone ⏰ **Reminder:** `{ctf['name']}` starts in 10 minutes!", allowed_mentions=discord.AllowedMentions(everyone=True))
            ctf["reminded_10m"] = True

        if now_utc >= end_utc:
            ctf_events.remove(ctf)
            await channel.send(f"✅ `{ctf['name']}` has ended and has been removed from the schedule.")

@tasks.loop(hours=24)
async def fetch_ctftime():
    url = "https://ctftime.org/api/v1/events/?limit=5"
    await bot.wait_until_ready()
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return
            events = await resp.json()

    channel = discord.utils.get(bot.get_all_channels(), name="ctftime")
    if not channel:
        return

    for event in events:
        name = event.get("title")
        url = event.get("url")
        format_ = event.get("format")
        weight = event.get("weight")
        start = datetime.fromisoformat(event.get("start"))
        end = datetime.fromisoformat(event.get("finish"))
        duration = event.get("duration", {}).get("days", 0)

        embed = discord.Embed(title=name, url=url, color=discord.Color.orange())
        embed.add_field(name="Duration", value=f"{duration} days, 0 hours", inline=True)
        embed.add_field(name="Format", value=format_, inline=True)
        embed.add_field(name="Weight", value=str(weight), inline=True)
        embed.add_field(name="Timeframe", value=f"{start.strftime('%A, %d %B, %Y %H:%M')} -> {end.strftime('%A, %d %B, %Y %H:%M')}", inline=False)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(everyone=False))

@bot.tree.command(name="ctftime", description="📅 Manually fetch and post upcoming CTFs from CTFTime.org")
async def ctftime(interaction: discord.Interaction):
    await interaction.response.defer()
    url = "https://ctftime.org/api/v1/events/?limit=5"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.followup.send("❌ Failed to fetch CTFs from ctftime.org.")
                return
            events = await resp.json()

    channel = discord.utils.get(interaction.guild.text_channels, name="ctftime")
    if not channel:
        await interaction.followup.send("❌ No channel named `ctftime` found.")
        return

    for event in events:
        name = event.get("title")
        url = event.get("url")
        format_ = event.get("format")
        weight = event.get("weight")
        start = datetime.fromisoformat(event.get("start"))
        end = datetime.fromisoformat(event.get("finish"))
        duration = event.get("duration", {}).get("days", 0)

        embed = discord.Embed(title=name, url=url, color=discord.Color.orange())
        embed.add_field(name="Duration", value=f"{duration} days, 0 hours", inline=True)
        embed.add_field(name="Format", value=format_, inline=True)
        embed.add_field(name="Weight", value=str(weight), inline=True)
        embed.add_field(name="Timeframe", value=f"{start.strftime('%A, %d %B, %Y %H:%M')} -> {end.strftime('%A, %d %B, %Y %H:%M')}", inline=False)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(everyone=False))
    await interaction.followup.send("✅ Posted the latest CTFs in #ctftime.")
    
        
#--------------------------------------------------------------- FETCH Challs ---------------------------------------------------------------#
# -------------------- Modals --------------------

CATEGORY_ORDER = ["welcome","web", "crypto", "pwn", "rev", "forensics", "cloud", "ai", "boot2root", "misc"]

def category_priority(name: str) -> int:
    """Return index for category ordering, unknowns go last."""
    try:
        return CATEGORY_ORDER.index(name.lower())
    except ValueError:
        return len(CATEGORY_ORDER)  # unknown → bottom

async def reorder_challenges(category: discord.CategoryChannel):
    """Reorder challenge channels with hardcoded category order:
       - #data and #chat always at the very top
       - Unsolved channels grouped by category order
       - Solved channels grouped by category order, after unsolved
    """
    channels = list(category.channels)

    # Always keep #data and #chat at top
    pinned = [c for c in channels if c.name in ("data", "chat")]

    # Remaining channels
    others = [c for c in channels if c not in pinned]

    # Separate solved vs unsolved
    unsolved = [c for c in others if not (c.name.startswith("✅-") or c.name.startswith("🔥-"))]
    solved = [c for c in others if c.name.startswith("✅-") or c.name.startswith("🔥-")]

    # Sort unsolved by hardcoded category order
    unsolved.sort(key=lambda c: category_priority(c.name.split("-")[0]))

    # Group solved by type prefix (without emoji prefix)
    from collections import defaultdict
    grouped_solved = defaultdict(list)
    for c in solved:
        name_without_prefix = c.name[2:]  # strip ✅- or 🔥-
        type_prefix = name_without_prefix.split("-")[0]
        grouped_solved[type_prefix].append(c)

    # Order solved by hardcoded category order
    ordered_solved = []
    for group in sorted(grouped_solved.keys(), key=category_priority):
        ordered_solved.extend(sorted(grouped_solved[group], key=lambda c: c.name.lower()))

    # Final order: pinned first, then unsolved, then solved
    final_order = pinned + unsolved + ordered_solved

    for index, ch in enumerate(final_order):
        await ch.edit(position=index)

# -------------------- SyncChallengesModal --------------------
class SyncChallengesModal(discord.ui.Modal, title="Sync CTFd Challenges"):
    ctfd_url = discord.ui.TextInput(label="CTFd URL", placeholder="https://example.ctfd.io")
    username = discord.ui.TextInput(label="Username", placeholder="Enter your CTFd username")
    password = discord.ui.TextInput(label="Password", placeholder="Enter your CTFd password ", style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        category = interaction.channel.category
        if not category:
            return await interaction.response.send_message("❌ Use this command inside a category.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        ctfd_url = self.ctfd_url.value.rstrip("/")
        username = self.username.value
        password = self.password.value

        try:
            async with aiohttp.ClientSession() as session:
                # 1️⃣ Get login page CSRF token
                async with session.get(f"{ctfd_url}/login") as resp:
                    html = await resp.text()
                match = re.search(r'name=["\']nonce["\']\s+type=["\']hidden["\']\s+value=["\'](.+?)["\']', html)
                if not match:
                    match = re.search(r'csrfNonce["\']\s*:\s*["\'](.+?)["\']', html)
                if not match:
                    return await interaction.followup.send("❌ CSRF token not found on login page.", ephemeral=True)
                csrf_nonce = match.group(1)

                # 2️⃣ Post login
                login_payload = {
                    "name": username,
                    "password": password,
                    "nonce": csrf_nonce,
                    "_submit": "Submit"
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                async with session.post(f"{ctfd_url}/login", data=login_payload, headers=headers) as resp:
                    if resp.status not in [200, 302]:
                        return await interaction.followup.send(f"❌ Login failed: {resp.status}", ephemeral=True)

                # 3️⃣ Fetch challenges
                async with session.get(f"{ctfd_url}/api/v1/challenges") as resp:
                    data = await resp.json()
                challenges = data.get("data") or []

                created = []
                skipped = []

                # 4️⃣ Create channels with duplicate-checking
                for chall in challenges:
                    name = chall.get("name")
                    type_ = chall.get("category") or chall.get("type") or "misc"
                    base_name = f"{type_.lower()}-{name.lower().replace(' ', '-')}"

                    # Check for duplicates including solved prefixes
                    exists = False
                    for ch in category.channels:
                        check_name = ch.name
                        if check_name.startswith("✅-") or check_name.startswith("🔥-"):
                            check_name = check_name[2:]
                        if check_name.lower() == base_name.lower():
                            exists = True
                            break
                    if exists:
                        skipped.append(base_name)
                        continue

                    new_ch = await category.create_text_channel(base_name)
                    created.append(new_ch.mention)

                # 5️⃣ Reorder channels consistently
                await reorder_challenges(category)

                msg = (
                    f"✅ Created channels: {', '.join(created)}\n⚠️ Skipped existing: {', '.join(skipped)}"
                    if created else f"⚠️ No new channels created, all exist."
                )
                await interaction.followup.send(msg, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

# -------------------- /fetch command --------------------
@bot.tree.command(name="fetch", description="Fetch CTFd challenges and create channels dynamically")
async def fetch(interaction: discord.Interaction):
    await interaction.response.send_modal(SyncChallengesModal())

# -------------------- /challenge command --------------------
@bot.tree.command(name="challenge", description="📂 Create a new challenge channel")
@app_commands.describe(type="Type of challenge (e.g., web, crypto, pwn)", name="Name of the challenge")
async def challenge(interaction: discord.Interaction, type: str, name: str):
    current_channel = interaction.channel
    if not isinstance(current_channel, discord.TextChannel) or not current_channel.category:
        await interaction.response.send_message("❌ You must use this command inside a category.", ephemeral=True)
        return

    category = current_channel.category
    base_name = f"{type.lower()}-{name.lower().replace(' ', '-')}"  # normalized new channel name

    # ✅ Check all channels in the category (including solved ones)
    for ch in category.channels:
        check_name = ch.name
        if check_name.startswith("✅-") or check_name.startswith("🔥-"):
            check_name = check_name[2:]  
        if check_name.lower() == base_name.lower():
            await interaction.response.send_message(
                f"⚠️ A challenge channel with the name `{base_name}` already exists in {category.name} "
                f"({ch.mention}).",
                ephemeral=True
            )
            return

    try:
        new_channel = await category.create_text_channel(base_name)

        # Reorder consistently
        await reorder_challenges(category)

        await interaction.response.send_message(f"✅ Created new challenge channel: {new_channel.mention}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission to create or reorder channels.", ephemeral=True)

@bot.tree.command(name="private", description="Make the current channel and its entire category private (Admin only)")
async def private(interaction: discord.Interaction):
    # Check if the user has Admin role or manage_guild permission
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    # Get the current channel
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ This command must be used in a text channel.", ephemeral=True)
        return

    # Get the category of the channel (if any)
    category = channel.category
    if not category:
        await interaction.response.send_message("❌ This channel is not in a category.", ephemeral=True)
        return

    # Define permission overwrites
    admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
    if not admin_role:
        await interaction.response.send_message("❌ No 'Admin' role found in the server.", ephemeral=True)
        return

    private_overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),  # Deny access to @everyone
        admin_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),  # Allow Admins
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)  # Allow bot
    }

    try:
        # Update the category permissions to private
        await category.edit(overwrites=private_overwrites)

        # Update all channels in the category to private
        for channel_in_category in category.channels:
            if isinstance(channel_in_category, (discord.TextChannel, discord.VoiceChannel)):
                await channel_in_category.edit(overwrites=private_overwrites)

        await interaction.response.send_message(
            f"✅ Category `{category.name}` and all its channels are now private.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission to edit channel or category permissions.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Unexpected error: {e}", ephemeral=True)

@bot.tree.command(name="solve", description="Mark the current challenge channel as solved")
@app_commands.describe(
    users="Users who solved the challenge (mention multiple)",
    blooded="Was this a first blood? (yes/no)"
)
async def solve(interaction: discord.Interaction, users: str, blooded: str):
    target_channel = interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command must be used inside a challenge text channel.", ephemeral=True
        )
        return

    old_name = target_channel.name
    if old_name.startswith("✅-") or old_name.startswith("🔥-"):
        await interaction.response.send_message(
            "⚠️ This challenge is already marked as solved.", ephemeral=True
        )
        return

    solver_mentions = [word for word in users.split() if word.startswith("<@") and word.endswith(">")]
    if not solver_mentions:
        await interaction.response.send_message(
            "❌ Please mention at least one valid user.", ephemeral=True
        )
        return

    is_blooded = blooded.lower() in ["yes", "y", "true", "1"]
    new_prefix = "🔥" if is_blooded else "✅"
    new_name = f"{new_prefix}-{old_name}"

    try:
        await target_channel.edit(name=new_name)
        if target_channel.category:
            channels = list(target_channel.category.channels)
            unsolved = [c for c in channels if not (c.name.startswith("✅-") or c.name.startswith("🔥-"))]
            solved = [c for c in channels if c.name.startswith("✅-") or c.name.startswith("🔥-")]

            reordered = unsolved + solved
            for index, channel in enumerate(reordered):
                await channel.edit(position=index)

        solvers_text = ", ".join(solver_mentions)
        if is_blooded:
            announcement = f"🎉 Congratulations to {solvers_text} on solving and getting `{old_name}`! 🔥 **(First Blood!)**"
        else:
            announcement = f"🎉 Congratulations to {solvers_text} for solving `{old_name}`!"

        await target_channel.send(announcement)

        solved_logs.append({
            "channel": old_name,
            "users": solver_mentions,
            "blooded": is_blooded,
            "time": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M IST")
        })

        await interaction.response.send_message(
            f"✅ Marked `{old_name}` as solved by {solvers_text}!", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Missing permission to rename or reorder channels.", ephemeral=True
        )

def is_admin(interaction: discord.Interaction) -> bool:
    """Check if the user has the Admin role or manage_guild permission"""
    admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
    return (
        interaction.user.guild_permissions.manage_guild
        or (admin_role in interaction.user.roles)
    )

@bot.tree.command(name="backup", description="Backup solved challenge logs to a file")
async def backup(interaction: discord.Interaction):
    if not solved_logs:
        await interaction.response.send_message("📂 No logs to backup.", ephemeral=True)
        return

    filename = f"solved_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        for entry in solved_logs:
            emoji = "🔥" if entry["blooded"] else "✅"
            users = ", ".join(entry["users"])
            f.write(f"{emoji} {entry['channel']} → {users} at {entry['time']}\n")

    await interaction.response.send_message(
        f"📂 Backup created: `{filename}`",
        file=discord.File(filename),
        ephemeral=True
    )

@bot.tree.command(name="logs", description="Show logs of solved challenges")
async def logs(interaction: discord.Interaction):
    if not solved_logs:
        await interaction.response.send_message("📜 No challenges solved yet.", ephemeral=True)
        return

    log_messages = []
    for entry in solved_logs:
        emoji = "🔥" if entry["blooded"] else "✅"
        users = ", ".join(entry["users"])
        log_messages.append(f"{emoji} `{entry['channel']}` → {users} at {entry['time']}")

    await interaction.response.send_message("\n".join(log_messages), ephemeral=True)

@bot.tree.command(name="leaderboard", description="Show leaderboard of solvers")
async def leaderboard(interaction: discord.Interaction):
    if not solved_logs:
        await interaction.response.send_message("🏆 No solves yet.", ephemeral=True)
        return

    stats = {}
    for entry in solved_logs:
        for user in entry["users"]:
            if user not in stats:
                stats[user] = {"solves": 0, "bloods": 0}
            stats[user]["solves"] += 1
            if entry["blooded"]:
                stats[user]["bloods"] += 1

    sorted_stats = sorted(stats.items(), key=lambda x: (x[1]["solves"], x[1]["bloods"]), reverse=True)

    leaderboard_lines = [
        f"{i+1}. {user} → 🏆 {data['solves']} solves | 🔥 {data['bloods']} first bloods"
        for i, (user, data) in enumerate(sorted_stats)
    ]

    await interaction.response.send_message("\n".join(leaderboard_lines), ephemeral=True)

@bot.tree.command(
    name="export",
    description="Export all messages in the current category to per-channel JSON files and a ZIP"
)
async def export_category(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel) or not interaction.channel.category:
        await interaction.response.send_message(
            "❌ You must use this command inside a text channel inside a category.",
            ephemeral=True
        )
        return

    category = interaction.channel.category
    await interaction.response.defer(thinking=True, ephemeral=True)

    folder_name = f"{category.name}_export"
    os.makedirs(folder_name, exist_ok=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

    # Send initial progress message
    progress_message = await interaction.followup.send(
        f"⏳ Starting export for category `{category.name}`...",
        ephemeral=True
    )

    async with aiohttp.ClientSession() as session:
        for ch in category.channels:
            if not isinstance(ch, discord.TextChannel):
                continue

            ch_folder = os.path.join(folder_name, ch.name.replace("/", "_"))
            os.makedirs(ch_folder, exist_ok=True)

            # Subfolders for file types
            folders = {
                "images": os.path.join(ch_folder, "images"),
                "txt": os.path.join(ch_folder, "txt"),  # txt includes .txt and renamed .py files
            }
            for f in folders.values():
                os.makedirs(f, exist_ok=True)

            messages = []
            msgs = [msg async for msg in ch.history(limit=None, oldest_first=True)]
            total_messages = len(msgs)
            processed_count = 0

            async def process_message(msg):
                async def download_attachment(att):
                    filename = f"{msg.id}_{att.filename}"
                    dest_folder = None

                    if att.content_type and att.content_type.startswith("image"):
                        dest_folder = folders["images"]
                    elif att.filename.endswith(".txt"):
                        dest_folder = folders["txt"]
                    elif att.filename.endswith(".py"):
                        dest_folder = folders["txt"]  # save .py files as .txt
                        filename = filename.rsplit(".", 1)[0] + ".txt"
                    else:
                        return None  # skip other files

                    dest = os.path.join(dest_folder, filename)
                    try:
                        async with semaphore:
                            async with session.get(att.url) as resp:
                                if resp.status == 200:
                                    with open(dest, "wb") as f:
                                        f.write(await resp.read())
                        return os.path.relpath(dest, ch_folder)
                    except Exception:
                        return None

                results = await asyncio.gather(*(download_attachment(att) for att in msg.attachments))
                local_files = [r for r in results if r]

                return {
                    "id": msg.id,
                    "author": str(msg.author),
                    "content": msg.content,
                    "attachments": local_files,
                    "embeds": [e.to_dict() for e in msg.embeds],
                }

            # process messages concurrently in batches
            batch_size = 10
            for i in range(0, len(msgs), batch_size):
                batch = msgs[i:i+batch_size]
                processed_batch = await asyncio.gather(*(process_message(m) for m in batch))
                messages.extend(processed_batch)
                processed_count += len(batch)
                # Update progress
                await progress_message.edit(
                    content=f"⏳ Exporting channel `{ch.name}`: {processed_count}/{total_messages} messages processed..."
                )

            # save channel JSON
            with open(os.path.join(ch_folder, f"{ch.name}.json"), "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=4, ensure_ascii=False)

    # zip the folder
    zip_name = f"{category.name}.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_name):
            for file in files:
                path = os.path.join(root, file)
                arcname = os.path.relpath(path, folder_name)
                zipf.write(path, arcname=arcname)

    # send final ZIP
    await progress_message.edit(
        content=f"✅ Export complete for `{category.name}`!",
    )
    await interaction.followup.send(
        file=discord.File(zip_name),
        ephemeral=True
    )

    # cleanup
    for root, dirs, files in os.walk(folder_name, topdown=False):
        for file in files:
            os.remove(os.path.join(root, file))
        for d in dirs:
            os.rmdir(os.path.join(root, d))
    os.rmdir(folder_name)
    os.remove(zip_name)

class ConfirmDeleteView(View):
    def __init__(self, category):
        super().__init__(timeout=15)  # 15-second timeout
        self.category = category
        self.confirmed = False

    @button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, button: Button):
        self.confirmed = True
        self.stop()  # stops waiting for interaction
        await interaction.response.send_message(
            f"🗑️ Deleting category `{self.category.name}` and its channels…",
            ephemeral=True
        )
        # delete channels
        for ch in self.category.channels:
            try:
                await ch.delete(reason=f"Deleted by {interaction.user}")
            except discord.Forbidden:
                continue
        # delete category
        try:
            await self.category.delete(reason=f"Deleted by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete the category.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Category `{self.category.name}` and all channels deleted.", ephemeral=True)

    @button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: Interaction, button: Button):
        self.stop()
        await interaction.response.send_message("❌ Category deletion cancelled.", ephemeral=True)

@bot.tree.command(
    name="delete",
    description="Delete the current category and all channels under it"
)
async def delete_category(interaction: Interaction):
    if not isinstance(interaction.channel, TextChannel) or not interaction.channel.category:
        await interaction.response.send_message(
            "❌ You must use this command inside a text channel inside a category.",
            ephemeral=True
        )
        return
    
    if not any(role.name.lower() == "admin" for role in interaction.user.roles):
        await interaction.response.send_message(
            "❌ You need the Admin role to use this command.",
            ephemeral=True
        )
        return

    category = interaction.channel.category

    view = ConfirmDeleteView(category)
    await interaction.response.send_message(
        f"⚠️ Are you sure you want to delete the category `{category.name}` and ALL its channels? This cannot be undone.",
        view=view,
        ephemeral=True
    )


@bot.tree.command(name="reset", description="Clear the solved challenges log and all saved CTFd credentials (Admin only)")
async def reset(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return
    solved_logs.clear()
    user_ctfd_data.clear()

    await interaction.response.send_message(
        "✅ Solved challenge logs and all saved CTFd credentials have been cleared.",
        ephemeral=True
    )

bot.run("l")
#https://discord.com/oauth2/authorize?client_id=1387392910604894259&permissions=397553003568&scope=bot%20applications.commands
#ctfd_36ea35cd6fe1860d4b222828858c99414c41fe812d75bee9aa1e07001ed84c3b


""" class CTFDetailsModal(discord.ui.Modal, title="Enter CTF Details"):
    ctf_name = discord.ui.TextInput(label="CTF Name", placeholder="e.g., HTB CTF")
    ctf_url = discord.ui.TextInput(label="CTF URL", placeholder="https://ctftime.org/event/XXXX")
    start_dt_str = discord.ui.TextInput(label="Start Date & Time", placeholder="YYYY-MM-DD HH:MM AM/PM")
    end_dt_str = discord.ui.TextInput(label="End Date & Time", placeholder="YYYY-MM-DD HH:MM AM/PM")
    password_type = discord.ui.TextInput(
        label="Password Type",
        placeholder="'default' - default password/'random' - random password"
    )

    def __init__(self, interaction_channel: discord.TextChannel):
        super().__init__()
        self.interaction_channel = interaction_channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start_dt = datetime.strptime(self.start_dt_str.value.strip(), "%Y-%m-%d %I:%M %p")
            end_dt = datetime.strptime(self.end_dt_str.value.strip(), "%Y-%m-%d %I:%M %p")
        except ValueError:
            await interaction.response.send_message("❌ Invalid date/time format. Use `YYYY-MM-DD HH:MM AM/PM`.", ephemeral=True)
            return

        ist = ZoneInfo("Asia/Kolkata")
        start_dt = start_dt.replace(tzinfo=ist)
        end_dt = end_dt.replace(tzinfo=ist)

        guild = interaction.guild
        try:
            category = await guild.create_category(f"--- {self.ctf_name.value} ---")

            # Define roles to have access to the data channel
            admin_role = discord.utils.get(guild.roles, name="Admin")
            mod_role = discord.utils.get(guild.roles, name="Mod")

            overwrites_data = {
                guild.default_role:discord.PermissionOverwrite(view_channel=True, send_messages=False),
                admin_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            overwrites_chat = {
                guild.default_role:discord.PermissionOverwrite(view_channel=True, send_messages=True),
                admin_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }

            data_channel = await category.create_text_channel("data", overwrites=overwrites_data)
            chat_channel = await category.create_text_channel("chat", overwrites=overwrites_chat)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot lacks permissions to create channels or categories.", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ Unexpected error: {e}", ephemeral=True)
            return

        ctf_data = {
            "name": self.ctf_name.value,
            "url": self.ctf_url.value,
            "start": start_dt,
            "end": end_dt,
            "channel_id": data_channel.id,
            "reminded_1h": False,
            "reminded_30m": False,
            "reminded_10m": False
        }

        ctf_events.append(ctf_data)

        # Decide password based on user choice
        if self.password_type.value.strip().lower() == "default":
            password = "Fl4gz0nF1r3@ctf"
        else:
            alphabet = string.ascii_letters + string.digits + string.punctuation
            password = ''.join(secrets.choice(alphabet) for _ in range(16))

        await data_channel.send(
            f"@everyone 📢 **New CTF Incoming!**\n"
            f"**Name:** `{ctf_data['name']}`\n"
            f"**URL:** {ctf_data['url']}`\n"
            f"**Start:** `{start_dt.strftime('%Y-%m-%d %I:%M %p IST')}`\n"
            f"**End:** `{end_dt.strftime('%Y-%m-%d %I:%M %p IST')}`\n\n"
            f"🔐 **CTF Credentials**\n"
            f"**Username:** `Fl4gz0nF1r3`\n"
            f"**Password:** `{password}`",
            allowed_mentions=discord.AllowedMentions(everyone=True)
        )

        await interaction.response.send_message(
            f"✅ CTF `{ctf_data['name']}` created! Details posted in {data_channel.mention}.",
            ephemeral=True
        )
        
@bot.tree.command(name="details", description="Enter CTF event details via form")
async def details(interaction: discord.Interaction):
    await interaction.response.send_modal(CTFDetailsModal(interaction.channel))"""