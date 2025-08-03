import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import aiohttp

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

solved_logs = []
ctf_events = []

class CTFDetailsModal(discord.ui.Modal, title="Enter CTF Details"):
    ctf_name = discord.ui.TextInput(label="CTF Name", placeholder="e.g., HTB CTF")
    start_date = discord.ui.TextInput(label="Start Date", placeholder="YYYY-MM-DD")
    start_time = discord.ui.TextInput(label="Start Time", placeholder="HH:MM AM/PM")
    end_date = discord.ui.TextInput(label="End Date", placeholder="YYYY-MM-DD")
    end_time = discord.ui.TextInput(label="End Time", placeholder="HH:MM AM/PM")

    def __init__(self, interaction_channel: discord.TextChannel):
        super().__init__()
        self.interaction_channel = interaction_channel

    async def on_submit(self, interaction: discord.Interaction):
            try:
                start_date = datetime.strptime(self.start_date.value.strip(), "%Y-%m-%d")
                start_time = datetime.strptime(self.start_time.value.strip(), "%I:%M %p").time()
                end_date = datetime.strptime(self.end_date.value.strip(), "%Y-%m-%d")
                end_time = datetime.strptime(self.end_time.value.strip(), "%I:%M %p").time()
            except ValueError:
                await interaction.response.send_message("❌ Invalid date or time format.", ephemeral=True)
                return

            ist = ZoneInfo("Asia/Kolkata")
            start_dt = datetime.combine(start_date, start_time).replace(tzinfo=ist)
            end_dt = datetime.combine(end_date, end_time).replace(tzinfo=ist)

            if start_dt <= datetime.now(ist):
                await interaction.response.send_message("❌ Start time must be in the future.", ephemeral=True)
                return

            guild = interaction.guild
            try:
                category = await guild.create_category(f"--- {self.ctf_name.value} ---")
                data_channel = await category.create_text_channel("data")
                chat_channel = await category.create_text_channel("chat")
                await data_channel.send("**@everyone 📢**\n🔐 **CTF Credentials**\n**Username:** `Fl4gz0nF1r3`\n**Password:** `Fl4gz0nF1r3@ctf`")
            except discord.Forbidden:
                await interaction.response.send_message("❌ Bot lacks permissions to create channels or categories.", ephemeral=True)
                return
            except Exception as e:
                await interaction.response.send_message(f"❌ Unexpected error: {e}", ephemeral=True)
                return

            ctf_data = {
                "name": self.ctf_name.value,
                "start": start_dt,
                "end": end_dt,
                "channel_id": data_channel.id,
                "reminded_1h": False,
                "reminded_30m": False,
                "reminded_10m": False
            }

            ctf_events.append(ctf_data)

            await interaction.response.send_message(
                f"@everyone 📢 **New CTF Incoming!**\n"
                f"**Name:** `{ctf_data['name']}`\n"
                f"**Start:** `{start_dt.strftime('%Y-%m-%d %I:%M %p IST')}`\n"
                f"**End:** `{end_dt.strftime('%Y-%m-%d %I:%M %p IST')}`",
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
        check_reminders.start()
        fetch_ctftime.start()
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

        embed = discord.Embed(title=name, url=url, color=discord.Color.blue())
        embed.add_field(name="Duration", value=f"{duration} days, 0 hours", inline=True)
        embed.add_field(name="Format", value=format_, inline=True)
        embed.add_field(name="Weight", value=str(weight), inline=True)
        embed.add_field(name="Timeframe", value=f"{start.strftime('%A, %d %B, %Y %H:%M')} -> {end.strftime('%A, %d %B, %Y %H:%M')}", inline=False)
        await channel.send("@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))
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

        embed = discord.Embed(title=name, url=url, color=discord.Color.blue())
        embed.add_field(name="Duration", value=f"{duration} days, 0 hours", inline=True)
        embed.add_field(name="Format", value=format_, inline=True)
        embed.add_field(name="Weight", value=str(weight), inline=True)
        embed.add_field(name="Timeframe", value=f"{start.strftime('%A, %d %B, %Y %H:%M')} -> {end.strftime('%A, %d %B, %Y %H:%M')}", inline=False)
        await channel.send("@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

    await interaction.followup.send("✅ Posted the latest CTFs in #ctftime.")
    
@bot.tree.command(name="solve", description="Mark a challenge as solved by a user")
@app_commands.describe(channel_name="Name of the channel where the challenge was", user="User who solved the challenge")
async def solve(interaction: discord.Interaction, channel_name: str, user: discord.Member):
    guild = interaction.guild
    target_channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not target_channel:
        await interaction.response.send_message(f"❌ Channel `{channel_name}` not found.", ephemeral=True)
        return

    new_name = f"✅-{channel_name}"
    try:
        await target_channel.edit(name=new_name)
        await target_channel.send(f"🎉 Congratulations to {user.mention} for solving `{channel_name}`!")
        solved_logs.append({
            "channel": channel_name,
            "user": user.mention,
            "time": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M IST")
        })
        await interaction.response.send_message(f"✅ Renamed `{channel_name}` and congratulated {user.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission to rename or send messages in that channel.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="logs", description="Show list of solved challenges")
async def logs(interaction: discord.Interaction):
    if not solved_logs:
        await interaction.response.send_message("No challenges have been solved yet.", ephemeral=True)
        return

    log_lines = ["| Challenge | Solver | Time |", "|-----------|--------|------|"]
    for entry in solved_logs:
        log_lines.append(f"| `{entry['channel']}` | {entry['user']} | {entry['time']} |")

    await interaction.response.send_message(f"📜 **Solved Challenges:**\n{chr(10).join(log_lines)}")

@bot.tree.command(name="leaderboard", description="🏆 Display a Solver Leaderboard")
async def leaderboard(interaction: discord.Interaction):
    count = {}
    for log in solved_logs:
        count[log['user']] = count.get(log['user'], 0) + 1
    if not count:
        await interaction.response.send_message("No solves yet.", ephemeral=True)
        return
    leaderboard_text = "\n".join([f"**{user}** — {count[user]} solve(s)" for user in sorted(count, key=count.get, reverse=True)])
    await interaction.response.send_message(f"🏆 **Solver Leaderboard:**\n{leaderboard_text}")

@bot.tree.command(name="backup", description="💾 Export Solved Logs and CTF Events")
async def backup(interaction: discord.Interaction):
    data = {
        "solved_logs": solved_logs,
        "ctf_events": [
            {
                "name": c["name"],
                "start": c["start"].isoformat(),
                "end": c["end"].isoformat(),
            } for c in ctf_events
        ]
    }
    with open("backup.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    await interaction.response.send_message("💾 Backup created.", file=discord.File("backup.json"))

@bot.tree.command(name="reset", description="Clear the solved challenges log (Admin only)")
async def reset(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return

    solved_logs.clear()
    await interaction.response.send_message("✅ Solved challenge logs have been cleared.", ephemeral=True)

@bot.tree.command(name="details", description="Enter CTF event details via form")
async def details(interaction: discord.Interaction):
    await interaction.response.send_modal(CTFDetailsModal(interaction.channel))

bot.run("enter your bot token")
