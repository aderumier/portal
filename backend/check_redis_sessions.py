#!/usr/bin/env python3
"""Script to check Redis session storage and diagnose session issues."""
import os
import sys
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings

try:
    import redis.asyncio as aioredis
except ImportError:
    print("ERROR: redis module not installed. Install with: pip install redis")
    sys.exit(1)

async def check_redis_sessions():
    """Check Redis for session keys and diagnose issues."""
    print("=" * 80)
    print("Redis Session Storage Diagnostic")
    print("=" * 80)
    print()
    
    # Check configuration
    print("1. Configuration:")
    print(f"   SESSION_STORAGE: {settings.SESSION_STORAGE}")
    print(f"   REDIS_URL: {settings.REDIS_URL}")
    print(f"   REDIS_SESSION_KEY_PREFIX: {settings.REDIS_SESSION_KEY_PREFIX}")
    print()
    
    if settings.SESSION_STORAGE.lower() != 'redis':
        print(f"⚠️  WARNING: SESSION_STORAGE is set to '{settings.SESSION_STORAGE}', not 'redis'!")
        print("   Sessions are NOT being stored in Redis.")
        print("   Check your .env file and set SESSION_STORAGE=redis")
        return
    
    # Connect to Redis
    print("2. Connecting to Redis...")
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,  # Use text mode for easier inspection
            encoding='utf-8'
        )
        
        # Test connection
        pong = await redis_client.ping()
        print(f"   ✓ Connected to Redis: {pong}")
        
        # Get Redis info
        info = await redis_client.info()
        print(f"   Redis version: {info.get('redis_version', 'unknown')}")
        print(f"   Connected clients: {info.get('connected_clients', 'unknown')}")
        print(f"   Used memory: {info.get('used_memory_human', 'unknown')}")
        print()
        
        # Check which database we're using
        db_num = redis_client.connection_pool.connection_kwargs.get('db', 0)
        print(f"3. Using Redis database: {db_num}")
        print()
        
        # List all keys
        print("4. Searching for session keys...")
        key_prefix = settings.REDIS_SESSION_KEY_PREFIX or "session:"
        print(f"   Looking for keys with prefix: '{key_prefix}'")
        
        # Get all keys matching the prefix
        pattern = f"{key_prefix}*"
        all_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
            all_keys.extend(keys)
            if cursor == 0:
                break
        
        print(f"   Found {len(all_keys)} keys with prefix '{key_prefix}'")
        print()
        
        if all_keys:
            print("5. Sample session keys (first 10):")
            for i, key in enumerate(all_keys[:10], 1):
                ttl = await redis_client.ttl(key)
                key_type = await redis_client.type(key)
                size = await redis_client.strlen(key) if key_type == 'string' else 'N/A'
                print(f"   {i}. {key}")
                print(f"      Type: {key_type}, TTL: {ttl}s, Size: {size} bytes")
            print()
            
            # Try to get a sample session
            if all_keys:
                sample_key = all_keys[0]
                print(f"6. Sample session data (key: {sample_key}):")
                try:
                    data = await redis_client.get(sample_key)
                    if data:
                        # Try to parse as JSON
                        import json
                        try:
                            session_data = json.loads(data)
                            print(f"   Keys in session: {list(session_data.keys())}")
                            if 'user' in session_data:
                                user = session_data['user']
                                print(f"   User ID: {user.get('id', 'N/A')}")
                                print(f"   Username: {user.get('username', 'N/A')}")
                        except json.JSONDecodeError:
                            print(f"   Data (first 200 chars): {data[:200]}...")
                    else:
                        print("   (empty)")
                except Exception as e:
                    print(f"   Error reading session: {e}")
                print()
        else:
            print("5. ⚠️  No session keys found!")
            print()
            print("   Possible reasons:")
            print("   - Sessions haven't been created yet (try logging in)")
            print("   - Sessions are stored with a different prefix")
            print("   - Sessions are stored in a different Redis database")
            print("   - Sessions expired and were deleted")
            print("   - Sessions are stored elsewhere (database, file, or memory)")
            print()
            
            # Check for keys without prefix
            print("   Checking for any keys in Redis...")
            all_redis_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, count=100)
                all_redis_keys.extend(keys)
                if cursor == 0:
                    break
            
            if all_redis_keys:
                print(f"   Found {len(all_redis_keys)} total keys in Redis (without prefix filter)")
                print(f"   Sample keys (first 10): {all_redis_keys[:10]}")
            else:
                print("   Redis is completely empty")
            print()
        
        # Check other databases
        print("7. Checking other Redis databases (0-15)...")
        original_db = db_num
        for db in range(16):
            if db == original_db:
                continue
            try:
                test_client = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    db=db
                )
                cursor = 0
                keys_in_db = []
                while True:
                    cursor, keys = await test_client.scan(cursor, match=f"{key_prefix}*", count=100)
                    keys_in_db.extend(keys)
                    if cursor == 0:
                        break
                if keys_in_db:
                    print(f"   ⚠️  Found {len(keys_in_db)} session keys in database {db}!")
                await test_client.close()
            except Exception:
                pass
        print()
        
        await redis_client.close()
        
    except Exception as e:
        print(f"   ✗ Error connecting to Redis: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("=" * 80)
    print("Diagnostic complete")
    print("=" * 80)

if __name__ == '__main__':
    asyncio.run(check_redis_sessions())

