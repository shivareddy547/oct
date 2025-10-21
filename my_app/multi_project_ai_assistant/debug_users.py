#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from models.database import PostgresDB

def debug_users():
    """Debug script to check users in database"""
    db_config = Config.get_db_config()
    db = PostgresDB(db_config)
    print(db)

    print("🔍 Debugging users in database...")

    # Check if users table exists and has data
    try:
        # Get all users
        users = db.execute_query("SELECT id, username, email, password_hash FROM users", fetch=True)
        print(f"📊 Total users in database: {len(users)}")

        for user in users:
            print(f"👤 User: ID={user['id']}, Username='{user['username']}', Email='{user['email']}'")
            print(f"   Password Hash: {user['password_hash']}")

        # Test password hashing
        test_password = "test123"
        test_hash = db.hash_password(test_password)
        print(f"\n🔐 Password hash test:")
        print(f"   Password: {test_password}")
        print(f"   Hash: {test_hash}")

    except Exception as e:
        print(f"❌ Error debugging users: {e}")

# if __name__ == "__main__":
#     debug_users()