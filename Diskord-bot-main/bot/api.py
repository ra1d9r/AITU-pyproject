import asyncio
import asyncpg
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import json
import random
import base64

load_dotenv()

# --- CONFIGURATION ---
CLIENT_ID = "1441381190371246261"
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
OWNER_ID = 777206368389038081

DB_CONFIG = {
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# Globals
db_pool = None

# --- WEB SERVER SETUP ---
routes = web.RouteTableDef()
MAX_UPLOAD_SIZE = 10 * 1024 * 1024 # 10MB

def cors_headers():
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Credentials': 'true'
    }

def json_response(data, status=200):
    return web.Response(
        text=json.dumps(data, default=str),
        content_type='application/json',
        status=status,
        headers=cors_headers()
    )

def find_static_folder():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, '..', 'web-console'),
        os.path.join(current_dir, 'web-console'),
        os.path.join(current_dir, 'Diskord-bot-main', 'web-console'),
        os.path.join(os.getcwd(), 'web-console'),
        os.path.join(os.getcwd(), 'Diskord-bot-main', 'web-console'),
    ]
    
    for path in candidates:
        full_path = os.path.abspath(path)
        if os.path.exists(os.path.join(full_path, 'index.html')):
            print(f"[API] ✅ Serving website from: {full_path}")
            return full_path
            
    print("[API] ❌ Web folder not found. Searched:")
    for p in candidates:
        print(f" - {os.path.abspath(p)}")
    return None

STATIC_PATH = find_static_folder()
UPLOADS_PATH = os.path.join(STATIC_PATH, 'uploads') if STATIC_PATH else 'uploads'
os.makedirs(UPLOADS_PATH, exist_ok=True)

# --- ROUTES ---

@routes.options('/{tail:.*}')
async def handle_options(request):
    return web.Response(status=204, headers=cors_headers())

@routes.get('/api/status')
async def handle_status(request):
    return json_response({'status': 'online', 'service': 'api-only'})

# --- AUTH ---
@routes.post('/api/auth/login')
async def handle_auth_login(request):
    try:
        data = await request.json()
        code = data.get('code')
        if not code: return json_response({'error': 'No code provided'}, 400)
        
        # Log this error explicitly if secret is missing
        if not CLIENT_SECRET: 
            print("❌ [API] Missing DISCORD_CLIENT_SECRET in .env")
            return json_response({'error': 'Server Config Error: Missing Client Secret'}, 500)

        async with aiohttp.ClientSession() as session:
            try:
                payload = {
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': 'http://localhost:5000/folders'
                }
                async with session.post('https://discord.com/api/oauth2/token', data=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"❌ [API] Discord Token Error: {text}")
                        return json_response({'error': f'Discord Auth Failed: {text}'}, 400)
                    token_data = await resp.json()
                    access_token = token_data['access_token']

                async with session.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'}) as resp:
                    if resp.status != 200: return json_response({'error': 'Failed to fetch user profile'}, 400)
                    user_data = await resp.json()
                    
            except Exception as e:
                return json_response({'error': str(e)}, 500)

        # Upsert Member
        user_id = int(user_data['id'])
        username = user_data['username']
        email = user_data.get('email')
        avatar = user_data.get('avatar')
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else None

        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO members (user_id, username, email, avatar, join_date)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET username = EXCLUDED.username, email = EXCLUDED.email, avatar = EXCLUDED.avatar
                """, user_id, username, email, avatar_url, datetime.now(timezone.utc))

        return json_response({
            'success': True,
            'user': {'id': str(user_id), 'username': username, 'email': email, 'avatar': avatar_url}
        })
    except Exception as e:
        print(f"❌ [API] Auth Crash: {e}")
        return json_response({'error': str(e)}, 500)

# --- FOLDERS API ---

@routes.get('/api/folders')
async def handle_folders_get(request):
    if not db_pool: return json_response([], 500)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, color, owner_id FROM folders ORDER BY id ASC")
        return json_response([{'id': r['id'], 'name': r['name'], 'color': r['color'] or '#FFE989', 'owner_id': r['owner_id']} for r in rows])

@routes.post('/api/folders')
async def handle_folder_create(request):
    data = await request.json()
    name = data.get('name')
    if not db_pool: return json_response({'error': 'Database not ready'}, 500)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("INSERT INTO folders (name, color, owner_id) VALUES ($1, $2, $3) RETURNING id", name, '#FFE989', 'system')
    return json_response({'id': row['id'], 'name': name})

@routes.delete('/api/folders/{id}')
async def handle_folder_delete(request):
    try:
        folder_id = int(request.match_info['id'])
        if not db_pool: return json_response({'error': 'DB Error'}, 500)
        
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM server_folders WHERE folder_id=$1", folder_id)
            # Safe delete from folder_admins if it exists
            try:
                await conn.execute("DELETE FROM folder_admins WHERE folder_id=$1", folder_id)
            except:
                pass
            result = await conn.execute("DELETE FROM folders WHERE id=$1", folder_id)
            
            if result == "DELETE 0":
                 return json_response({'error': 'Folder not found'}, 404)
                     
        return json_response({'success': True})
    except Exception as e:
        print(f"Delete Folder Error: {e}")
        return json_response({'error': f'Server Error: {str(e)}'}, 500)

@routes.get('/api/folders/{id}/servers')
async def handle_folder_servers_get(request):
    folder_id = int(request.match_info['id'])
    if not db_pool: return json_response([], 500)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT server_id, server_name FROM server_folders WHERE folder_id=$1", folder_id)
        return json_response([{'server_id': str(r['server_id']), 'server_name': r['server_name']} for r in rows])

@routes.post('/api/folders/{id}/servers')
async def handle_folder_server_add(request):
    folder_id = int(request.match_info['id'])
    data = await request.json()
    server_id = int(data.get('serverId'))
    server_name = data.get('serverName', f'Server {server_id}')
    
    if not db_pool: return json_response({'error': 'DB Error'}, 500)
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO server_folders (folder_id, server_id, server_name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", folder_id, server_id, server_name)
    return json_response({'status': 'added'})

@routes.delete('/api/folders/{folder_id}/servers/{server_id}')
async def handle_folder_server_remove(request):
    folder_id = int(request.match_info['folder_id'])
    server_id = int(request.match_info['server_id'])
    
    if not db_pool: return json_response({'error': 'DB Error'}, 500)
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM server_folders WHERE folder_id=$1 AND server_id=$2", folder_id, server_id)
    return json_response({'status': 'removed'})

@routes.get('/api/stats')
async def handle_stats(request):
    folder_id = request.query.get('folderId')
    total_members = 0
    active_servers = 0
    
    if not db_pool: return json_response({'totalMembers': 0, 'activeServers': 0})
    
    async with db_pool.acquire() as conn:
        try:
            if folder_id:
                rows = await conn.fetch("""
                    SELECT gs.member_count 
                    FROM guild_stats gs
                    JOIN server_folders sf ON gs.guild_id = sf.server_id
                    WHERE sf.folder_id = $1
                """, int(folder_id))
                
                server_count_row = await conn.fetchval("SELECT COUNT(*) FROM server_folders WHERE folder_id=$1", int(folder_id))
                
                active_servers = server_count_row
                total_members = sum(r['member_count'] for r in rows if r['member_count'])

            else:
                row = await conn.fetchrow("SELECT SUM(member_count) as total_mem, COUNT(*) as count FROM guild_stats")
                total_members = row['total_mem'] or 0
                active_servers = row['count'] or 0
                
        except Exception as e:
            print(f"Stats Error: {e}")
            
    return json_response({'totalMembers': total_members, 'activeServers': active_servers})

# --- SERVER DETAILS & CONFIG API ---

@routes.get('/api/servers/{id}')
async def handle_server_details(request):
    guild_id = int(request.match_info['id'])
    if not db_pool: return json_response({'error': 'DB Error'}, 500)
    
    async with db_pool.acquire() as conn:
        stats = await conn.fetchrow("SELECT * FROM guild_stats WHERE guild_id=$1", guild_id)
        config = await conn.fetchrow("SELECT * FROM server_configs WHERE guild_id=$1", guild_id)
        
        response = {
            'guild_id': str(guild_id),
            'name': stats['name'] if stats else f"Unknown Server ({guild_id})",
            'member_count': stats['member_count'] if stats else 0,
            'icon_url': stats['icon_url'] if stats else None,
            'config': {
                'log_channel_id': str(config['log_channel_id']) if config and config['log_channel_id'] else '',
                'big_action_channel_id': str(config['big_action_channel_id']) if config and config['big_action_channel_id'] else '',
                'bot_name': config['bot_name'] if config and config['bot_name'] else '',
                'prefix': config['prefix'] if config and config['prefix'] else 'C7/'
            }
        }
        return json_response(response)

@routes.post('/api/servers/{id}/config')
async def handle_server_config_save(request):
    guild_id = int(request.match_info['id'])
    data = await request.json()
    
    log_channel = int(data.get('log_channel_id')) if data.get('log_channel_id') else None
    big_action = int(data.get('big_action_channel_id')) if data.get('big_action_channel_id') else None
    bot_name = data.get('bot_name')
    prefix = data.get('prefix')
    
    if not db_pool: return json_response({'error': 'DB Error'}, 500)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO server_configs (guild_id, log_channel_id, big_action_channel_id, bot_name, prefix)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id) DO UPDATE 
            SET log_channel_id = EXCLUDED.log_channel_id,
                big_action_channel_id = EXCLUDED.big_action_channel_id,
                bot_name = EXCLUDED.bot_name,
                prefix = EXCLUDED.prefix
        """, guild_id, log_channel, big_action, bot_name, prefix)
        
    return json_response({'success': True})

# --- LOGS API ---
@routes.get('/api/logs/messages')
async def handle_logs_messages(request):
    limit = int(request.query.get('limit', 50))
    folder_id = request.query.get('folderId')
    
    if not db_pool: return json_response({'logs': [], 'total': 0})
    
    async with db_pool.acquire() as conn:
        try:
            if folder_id:
                srv_rows = await conn.fetch("SELECT server_id FROM server_folders WHERE folder_id=$1", int(folder_id))
                server_ids = [r['server_id'] for r in srv_rows]
                if not server_ids: return json_response({'success': True, 'logs': [], 'total': 0})
                rows = await conn.fetch("""
                    SELECT server_name, channel_name, username, content, created_at 
                    FROM message_logs WHERE server_id = ANY($1::bigint[]) ORDER BY created_at DESC LIMIT $2
                """, server_ids, limit)
            else:
                rows = await conn.fetch("SELECT server_name, channel_name, username, content, created_at FROM message_logs ORDER BY created_at DESC LIMIT $1", limit)
            
            logs = [{
                'server_name': r['server_name'] or 'Unknown',
                'channel_name': r['channel_name'] or 'Unknown',
                'username': r['username'],
                'content': r['content'],
                'created_at': r['created_at'].isoformat() if r['created_at'] else None
            } for r in rows]
            return json_response({'success': True, 'logs': logs, 'total': len(logs)})
        except:
            return json_response({'success': True, 'logs': [], 'total': 0})

# --- MEMES & EXTRAS ---
@routes.get('/api/memes')
async def handle_memes_get(request):
    sort_by = request.query.get('sort', 'new')
    user_id = request.query.get('userId')
    order_clause = "created_at DESC"
    if sort_by == 'popular': order_clause = "like_count DESC, created_at DESC"
        
    if not db_pool: return json_response({'memes': []})
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT m.*, (SELECT vote_type FROM votes WHERE meme_id = m.id AND user_id = $1) as user_vote 
            FROM memes m ORDER BY {order_clause}
        """, int(user_id) if user_id and user_id.isdigit() else 0)
        memes = [{'id': r['id'], 'url': r['image_path'], 'caption': r['caption'], 'likes': r['like_count'], 'dislikes': r['dislike_count'], 'author_id': str(r['user_id']), 'user_vote': r['user_vote']} for r in rows]
        return json_response({'memes': memes})

@routes.post('/api/memes')
async def handle_meme_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    caption = ""
    user_id = 0
    filename = None
    while field:
        if field.name == 'caption':
            caption = (await field.read_chunk()).decode('utf-8')
        elif field.name == 'userId':
            user_id = int((await field.read_chunk()).decode('utf-8'))
        elif field.name == 'image':
            filename = f"meme_{int(datetime.now().timestamp())}_{random.randint(1000,9999)}.jpg"
            filepath = os.path.join(UPLOADS_PATH, filename)
            with open(filepath, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk: break
                    f.write(chunk)
        field = await reader.next()
    
    if not filename: return json_response({'error': 'No image'}, 400)
    url = f"/uploads/{filename}"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO memes (image_path, caption, user_id) VALUES ($1, $2, $3)", url, caption, user_id)
    return json_response({'success': True})

@routes.post('/api/memes/{id}/vote')
async def handle_meme_vote(request):
    meme_id = int(request.match_info['id'])
    data = await request.json()
    user_id, vote_type = int(data.get('userId')), data.get('voteType')
    if not db_pool: return json_response({'error': 'DB Error'}, 500)
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT vote_type FROM votes WHERE meme_id=$1 AND user_id=$2", meme_id, user_id)
        if existing:
            if existing['vote_type'] == vote_type:
                await conn.execute("DELETE FROM votes WHERE meme_id=$1 AND user_id=$2", meme_id, user_id)
                col = "like_count" if vote_type == 'like' else "dislike_count"
                await conn.execute(f"UPDATE memes SET {col} = {col} - 1 WHERE id=$1", meme_id)
            else:
                await conn.execute("UPDATE votes SET vote_type=$1 WHERE meme_id=$2 AND user_id=$3", vote_type, meme_id, user_id)
                if vote_type == 'like': await conn.execute("UPDATE memes SET like_count = like_count + 1, dislike_count = dislike_count - 1 WHERE id=$1", meme_id)
                else: await conn.execute("UPDATE memes SET like_count = like_count - 1, dislike_count = dislike_count + 1 WHERE id=$1", meme_id)
        else:
            await conn.execute("INSERT INTO votes (meme_id, user_id, vote_type) VALUES ($1, $2, $3)", meme_id, user_id, vote_type)
            col = "like_count" if vote_type == 'like' else "dislike_count"
            await conn.execute(f"UPDATE memes SET {col} = {col} + 1 WHERE id=$1", meme_id)
    return json_response({'success': True})

# --- ADMIN API (Folder Scoped) ---

@routes.get('/api/folders/{id}/admins')
async def handle_folder_admins_get(request):
    try:
        folder_id = int(request.match_info['id'])
        admins = []
        if not db_pool:
            return json_response({'error': 'Database not connected'}, 500)

        async with db_pool.acquire() as conn:
            # Safely fetch admins. This will fail if table doesn't exist, triggering the except block
            rows = await conn.fetch("SELECT user_id, added_at FROM folder_admins WHERE folder_id=$1 ORDER BY added_at DESC", folder_id)
            
            for r in rows:
                added_at_str = str(r['added_at']) 
                if r['added_at']:
                    try: added_at_str = r['added_at'].strftime('%Y-%m-%d %H:%M')
                    except: pass
                admins.append({'user_id': str(r['user_id']), 'added_at': added_at_str})
                
        return json_response({'admins': admins})
    except Exception as e:
        print(f"❌ [API] Error fetching admins: {e}")
        # THIS IS THE CRITICAL FIX: Return JSON so frontend can display the error instead of crashing
        return json_response({'error': f"DB/Server Error: {str(e)}"}, 500)

@routes.post('/api/folders/{id}/admins')
async def handle_folder_admins_add(request):
    try:
        folder_id = int(request.match_info['id'])
        data = await request.json()
        user_id_raw = data.get('userId')
        
        if not user_id_raw: 
            return json_response({'error': 'User ID required'}, 400)
            
        try:
            user_id = int(user_id_raw)
        except ValueError:
            return json_response({'error': 'User ID must be a number'}, 400)
        
        if not db_pool: 
            return json_response({'error': 'Database not connected'}, 500)

        async with db_pool.acquire() as conn:
            folder_exists = await conn.fetchval("SELECT 1 FROM folders WHERE id=$1", folder_id)
            if not folder_exists:
                return json_response({'error': 'Folder not found'}, 404)

            # Check if user exists
            existing = await conn.fetchval("SELECT 1 FROM folder_admins WHERE folder_id=$1 AND user_id=$2", folder_id, user_id)
            if existing:
                return json_response({'success': True, 'message': 'User is already an admin'})

            await conn.execute("""
                INSERT INTO folder_admins (folder_id, user_id, added_at) 
                VALUES ($1, $2, $3)
            """, folder_id, user_id, datetime.now(timezone.utc))
            
        return json_response({'success': True})
    except Exception as e:
        print(f"❌ [API] Error adding admin: {e}")
        return json_response({'error': f"Server Error: {str(e)}"}, 500)

@routes.delete('/api/folders/{folder_id}/admins/{user_id}')
async def handle_folder_admins_delete(request):
    try:
        folder_id = int(request.match_info['folder_id'])
        user_id = int(request.match_info['user_id'])
        
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("DELETE FROM folder_admins WHERE folder_id=$1 AND user_id=$2", folder_id, user_id)
        return json_response({'success': True})
    except Exception as e:
        return json_response({'error': str(e)}, 500)

# --- START SERVER ---
async def serve_index(request):
    if not STATIC_PATH: return web.Response(status=404, text="Web folder not found")
    return web.FileResponse(os.path.join(STATIC_PATH, 'index.html'))

@routes.get('/')
async def handle_root(request): return await serve_index(request)
@routes.get('/folders')
async def handle_folders_route(request): return await serve_index(request)
@routes.get('/uploads/{filename}')
async def serve_upload(request):
    path = os.path.join(UPLOADS_PATH, request.match_info['filename'])
    return web.FileResponse(path) if os.path.exists(path) else web.Response(status=404)
@routes.get('/{tail:.*}')
async def serve_assets(request):
    if not STATIC_PATH: return web.Response(status=404)
    path = os.path.join(STATIC_PATH, request.match_info['tail'])
    return web.FileResponse(path) if os.path.exists(path) and os.path.isfile(path) else web.Response(status=404)

async def start_server():
    global db_pool
    # 1. Init DB
    try:
        db_pool = await asyncpg.create_pool(**DB_CONFIG)
        print("✅ [API] Database connected")
        async with db_pool.acquire() as conn:
            tables = [
                """CREATE TABLE IF NOT EXISTS message_logs (
                    id SERIAL PRIMARY KEY,
                    server_id BIGINT, server_name TEXT, channel_id BIGINT, channel_name TEXT,
                    user_id BIGINT, username TEXT, content TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
                );""",
                """CREATE TABLE IF NOT EXISTS bot_admins (user_id BIGINT PRIMARY KEY, added_at TIMESTAMPTZ DEFAULT NOW());""",
                """CREATE TABLE IF NOT EXISTS saved_msg (
                    id SERIAL PRIMARY KEY, user_id BIGINT, folder TEXT, username TEXT,
                    content TEXT, timestamp TIMESTAMPTZ, channel_id BIGINT, message_id BIGINT, guild_id BIGINT
                );""",
                """CREATE TABLE IF NOT EXISTS members (
                    id SERIAL PRIMARY KEY, user_id BIGINT UNIQUE NOT NULL, username TEXT,
                    email TEXT, avatar TEXT, join_date TIMESTAMPTZ
                );""",
                """CREATE TABLE IF NOT EXISTS folders (id SERIAL PRIMARY KEY, name TEXT, color TEXT, owner_id TEXT);""",
                """CREATE TABLE IF NOT EXISTS server_folders (
                    id SERIAL PRIMARY KEY, folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                    server_id BIGINT, server_name TEXT, UNIQUE(folder_id, server_id)
                );""",
                # THIS TABLE WAS MISSING IN PREVIOUS VERSIONS, CAUSING THE 500 ERROR
                """CREATE TABLE IF NOT EXISTS folder_admins (
                    id SERIAL PRIMARY KEY, 
                    folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                    user_id BIGINT, 
                    added_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(folder_id, user_id)
                );""",
                """CREATE TABLE IF NOT EXISTS memes (
                    id SERIAL PRIMARY KEY, image_path TEXT NOT NULL, caption TEXT,
                    user_id BIGINT NOT NULL, like_count INTEGER DEFAULT 0, dislike_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );""",
                """CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY, meme_id INTEGER REFERENCES memes(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL, vote_type TEXT, UNIQUE(meme_id, user_id)
                );""",
                """CREATE TABLE IF NOT EXISTS guild_stats (
                    guild_id BIGINT PRIMARY KEY,
                    name TEXT,
                    member_count INTEGER,
                    icon_url TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );""",
                """CREATE TABLE IF NOT EXISTS server_configs (
                    guild_id BIGINT PRIMARY KEY,
                    log_channel_id BIGINT,
                    big_action_channel_id BIGINT,
                    bot_name TEXT,
                    prefix TEXT DEFAULT 'C7/'
                );"""
            ]
            
            for sql in tables:
                try:
                    await conn.execute(sql)
                except Exception as table_err:
                    print(f"⚠️ [API] Warning creating table: {table_err}")
            
    except Exception as e:
        print(f"❌ [API] DB Init Failed: {e}")

    # 2. Start App
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("✅ [API] Server running on http://localhost:5000")
    
    # Keep alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        pass