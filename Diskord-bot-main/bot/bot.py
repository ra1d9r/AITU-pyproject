import discord
from discord.ext import commands, tasks
import asyncio
import asyncpg
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN") 
DEFAULT_LOGS_ID = 1441383049794420746
DEFAULT_BIG_ACTION_ID = 1441383700368724078
GLOBAL_SEND_ID = 1441380472579162285
ADMIN_ROLE_ID = 1441382969628426240

# Colors
psi_yellow = 0xffe989
goldish = 0xcfb54e
white = 0xffffff
dark_red = 0xad1f1f
nice_pink = 0xffaff2
very_purple = 0x7301ff
eggplant = 0x722095
gojo_blue = 0x7274d9
pastel_blue = 0x72a9d9
ultra_green = 0x3bff00
nice_green = 0xb2fb98
dark_green = 0x256600

# Database Config
DB_CONFIG = {
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# Admin IDs
ADMIN = {777206368389038081}

# --- HELPER: CLEAN ID (THE BUG FIX) ---
def clean_id(id_val):
    """Removes commas and spaces that cause the int() conversion to fail."""
    if isinstance(id_val, int):
        return id_val
    try:
        # This removes any trailing commas or spaces copied from the website/lists
        return int(str(id_val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None

# --- DYNAMIC PREFIX ---
async def get_prefix(bot, message):
    if not message.guild or not db_pool:
        return "C7/"
    async with db_pool.acquire() as conn:
        res = await conn.fetchval("SELECT prefix FROM server_configs WHERE guild_id = $1", message.guild.id)
    return res if res else "C7/"

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True 
bot = commands.Bot(command_prefix=get_prefix, intents=intents)

# Globals
db_pool = None
waiting_users = {}

# --- HELPER FUNCTIONS ---
async def get_server_config(guild_id):
    if not db_pool or guild_id is None: return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM server_configs WHERE guild_id = $1", guild_id)

class SaveView(discord.ui.View):
    def __init__(self, message: discord.Message = None):
        super().__init__(timeout=None)
        if message is None: return 
        custom_id = f"save|{message.author.id}|{message.channel.id}|{message.id}"
        self.add_item(discord.ui.Button(label="Save", style=discord.ButtonStyle.primary, custom_id=custom_id))

    async def interaction_check(self, interaction: discord.Interaction):
        parts = interaction.data["custom_id"].split("|")
        _, user_id, channel_id, message_id = parts
        channel = bot.get_channel(int(channel_id))
        try:
            msg = await channel.fetch_message(int(message_id))
        except:
            return await interaction.response.send_message("Message no longer exists.", ephemeral=True)

        waiting_users[interaction.user.id] = {
            "user_id": int(user_id),
            "username": str(msg.author),
            "content": msg.content,
            "channel_id": int(channel_id),
            "message_id": int(message_id)
        }
        await interaction.response.send_message("Send folder name or No/None/Default/- for default.", ephemeral=True)
        return False

# --- SYNC TASK ---
async def perform_sync():
    if not db_pool: return
    try:
        async with db_pool.acquire() as conn:
            for guild in bot.guilds:
                icon_url = str(guild.icon.url) if guild.icon else None
                await conn.execute("""
                    INSERT INTO guild_stats (guild_id, name, member_count, icon_url, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (guild_id) DO UPDATE 
                    SET name = EXCLUDED.name, 
                        member_count = EXCLUDED.member_count,
                        icon_url = EXCLUDED.icon_url,
                        updated_at = NOW()
                """, guild.id, guild.name, guild.member_count, icon_url)
    except Exception as e:
        print(f"Sync error: {e}")

@tasks.loop(minutes=5)
async def sync_guild_stats():
    await perform_sync()

# --- EVENTS ---

@bot.event
async def on_ready():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(**DB_CONFIG)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS members (user_id BIGINT PRIMARY KEY, username TEXT, join_date TIMESTAMPTZ);
                CREATE TABLE IF NOT EXISTS saved_msg (
                    id SERIAL PRIMARY KEY, user_id BIGINT, folder TEXT, username TEXT, content TEXT, 
                    timestamp TIMESTAMPTZ, channel_id BIGINT, message_id BIGINT, guild_id BIGINT
                );
                CREATE TABLE IF NOT EXISTS folders (id SERIAL PRIMARY KEY, name TEXT, color TEXT);
                CREATE TABLE IF NOT EXISTS server_folders (folder_id INTEGER, server_id BIGINT, server_name TEXT, PRIMARY KEY(folder_id, server_id));
                CREATE TABLE IF NOT EXISTS server_configs (
                    guild_id BIGINT PRIMARY KEY, log_channel_id BIGINT, big_action_channel_id BIGINT, 
                    bot_name TEXT, prefix TEXT DEFAULT 'C7/'
                );
                CREATE TABLE IF NOT EXISTS guild_stats (
                    guild_id BIGINT PRIMARY KEY, name TEXT, member_count INTEGER, icon_url TEXT, updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS message_logs (
                    id SERIAL PRIMARY KEY, server_id BIGINT, server_name TEXT, channel_id BIGINT, channel_name TEXT,
                    user_id BIGINT, username TEXT, content TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
        print("✅ Database connected and tables ensured.")
    except Exception as e:
        print(f"❌ DB Error: {e}")

    print(f"✅ Logged in as {bot.user}")
    await perform_sync()
    if not sync_guild_stats.is_running():
        sync_guild_stats.start()
    bot.add_view(SaveView())

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user: return

    # Dynamic Nickname Check (Updates from website changes)
    if message.guild:
        config = await get_server_config(message.guild.id)
        if config and config['bot_name'] and message.guild.me.display_name != config['bot_name']:
            try:
                await message.guild.me.edit(nick=config['bot_name'])
            except: pass

    # Command Handling
    prefix = await bot.get_prefix(message)
    if message.content.startswith(prefix):
        await bot.process_commands(message)
        return

    # Member tracking
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO members (user_id, username, join_date) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO NOTHING", 
                               message.author.id, str(message.author), datetime.now(timezone.utc))

    # Message Saving Interaction
    uid = message.author.id
    if uid in waiting_users:
        folder = message.content.strip()
        if folder.lower() in ['no', 'none', 'default', '-']: folder = 'default'
        data = waiting_users[uid]
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO saved_msg (user_id, folder, username, content, timestamp, channel_id, message_id, guild_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, data['user_id'], folder, data['username'], data['content'], datetime.now(timezone.utc), data['channel_id'], data['message_id'], message.guild.id if message.guild else 0)
        await message.reply("message saved")
        del waiting_users[uid]
        return

    # Logging Logic
    if message.guild:
        config = await get_server_config(message.guild.id)
        log_channel_id = config['log_channel_id'] if config and config['log_channel_id'] else DEFAULT_LOGS_ID
        
        # 1. DB Log for website
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO message_logs (server_id, server_name, channel_id, channel_name, user_id, username, content, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """, message.guild.id, message.guild.name, message.channel.id, message.channel.name,
                       message.author.id, str(message.author), message.content, datetime.now(timezone.utc))
            except: pass

        # 2. Discord Log Embed
        log_chan = bot.get_channel(log_channel_id)
        if log_chan:
            embed = discord.Embed(
                title="Message sent",
                description=f"**{message.author}** ({message.author.id}) sent\n```{message.content}```\nin {message.channel.mention}",
                color=psi_yellow
            )
            embed.set_author(name=str(message.author), icon_url=message.author.avatar.url if message.author.avatar else None)
            await log_chan.send(embed=embed, view=SaveView(message))

# --- COMMANDS ---

@bot.command(name="show_saved")
async def show_saved(ctx, folder: str = None):
    folder = folder or "default"
    if not db_pool: return await ctx.send("Database not connected.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM saved_msg WHERE folder = $1 ORDER BY timestamp ASC", folder)

    if not rows: return await ctx.send(f"No saved messages in '{folder}'")

    embeds = []
    page = []
    for r in rows:
        content = r["content"][:500] + ("..." if len(r["content"]) > 500 else "")
        link = f"https://discord.com/channels/{ctx.guild.id if ctx.guild else 0}/{r['channel_id']}/{r['message_id']}"
        page.append(f"**{r['username']}** ({r['user_id']}) at {r['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n```{content}```\n[msg origin]({link})")
        if len("\n".join(page)) > 900:
            embeds.append(discord.Embed(title=f"Saved messages - folder '{folder}'", description="\n\n".join(page), color=psi_yellow))
            page = []
    if page: embeds.append(discord.Embed(title=f"Saved messages - folder '{folder}'", description="\n\n".join(page), color=psi_yellow))

    current_page = 0
    view = discord.ui.View()
    async def update_embed(interaction, change):
        nonlocal current_page
        new_page = current_page + change
        if 0 <= new_page < len(embeds):
            current_page = new_page
            await interaction.response.edit_message(embed=embeds[current_page], view=view)

    btn_p = discord.ui.Button(label="previous", style=discord.ButtonStyle.secondary)
    btn_n = discord.ui.Button(label="next", style=discord.ButtonStyle.secondary)
    btn_p.callback = lambda i: update_embed(i, -1)
    btn_n.callback = lambda i: update_embed(i, 1)
    view.add_item(btn_p); view.add_item(btn_n)
    await ctx.send(embed=embeds[0], view=view)

@bot.command(name="global_send")
async def global_sending(ctx, guild_id_raw: str, channel_id_raw: str, *, content: str):
    # FIXED: Manual ID cleaning before conversion
    guild_id = clean_id(guild_id_raw)
    channel_id = clean_id(channel_id_raw)

    if guild_id is None or channel_id is None:
        return await ctx.send("Invalid ID format. Make sure you use numbers.")

    if ctx.author.id not in ADMIN:
        try_embed = discord.Embed(title="Event:", description="__Global send attempt__", color=dark_red)
        try_embed.add_field(name="User:", value=ctx.author.mention, inline=False)
        try_embed.add_field(name="Content:", value=content, inline=False)
        try_embed.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        config = await get_server_config(ctx.guild.id) if ctx.guild else None
        log_chan = bot.get_channel(config['log_channel_id'] if config else DEFAULT_LOGS_ID)
        if log_chan: await log_chan.send(embed=try_embed)
        return await ctx.send(f"heaven's watching you, {ctx.author.mention}.")
    
    guild = bot.get_guild(guild_id)
    channel = bot.get_channel(channel_id)
    if not guild or not channel: return await ctx.send("Targeted location unreachable.")
    
    try:
        sent = await channel.send(content)
        log_embed = discord.Embed(title="Global_send", description=f"**Sent in** {sent.channel.mention} [Jump]({sent.jump_url})", color=goldish)
        log_embed.add_field(name="User:", value=ctx.author.mention, inline=False)
        log_embed.add_field(name="Message content:", value=content, inline=False)
        log_embed.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        log_embed.set_footer(text=f"{sent.guild.name} • User ID: {ctx.author.id}", icon_url=sent.guild.icon.url if sent.guild.icon else None)
        
        config = await get_server_config(ctx.guild.id) if ctx.guild else None
        log_chan = bot.get_channel(config['log_channel_id'] if config else DEFAULT_LOGS_ID)
        if log_chan: await log_chan.send(embed=log_embed)
        await ctx.send("Sent successfuly")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command(name="heaven_strike")
async def heaven_strike(ctx, big: bool, user_id_raw: str, guild_id_raw: str, *, reason: str = None):
    # FIXED: Manual ID cleaning before conversion
    user_id = clean_id(user_id_raw)
    guild_id = clean_id(guild_id_raw)

    if user_id is None or guild_id is None:
        return await ctx.send("Invalid ID format.")

    if ctx.author.id not in ADMIN:
        await ctx.send("heaven watches you")
        return

    guild = bot.get_guild(guild_id)
    if not guild: return await ctx.send(f"the sky is dark in {guild_id}")
    
    try:
        user = await bot.fetch_user(user_id)
        await guild.ban(user, reason=f"Struck by {ctx.author} ({ctx.author.id}). Reason: {reason or '—'}")
        await ctx.send(f"{user.mention} struck in {guild.name}.")
        
        # Log Logic
        config = await get_server_config(guild_id)
        log_cid = config['log_channel_id'] if config else DEFAULT_LOGS_ID
        big_aid = config['big_action_channel_id'] if config else DEFAULT_BIG_ACTION_ID
        
        log_e = discord.Embed(title="Event:", description=f"Heaven struck {user} in {guild.name}", color=dark_red)
        log_e.add_field(name="Reason:", value=reason or "—")
        log_e.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        l_chan = bot.get_channel(log_cid)
        if l_chan: await l_chan.send(embed=log_e)
        
        if big:
            b_chan = bot.get_channel(big_aid)
            if b_chan: await b_chan.send(embed=discord.Embed(title="BIG ACTION", description=f"{user.mention} banned in {guild.name}", color=dark_red))
    except Exception as e:
        await ctx.send(f"Error: {e}")

if __name__ == "__main__":
    if TOKEN: bot.run(TOKEN)
    else: print("DISCORD_TOKEN missing in .env")
