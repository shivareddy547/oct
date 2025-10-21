#!/usr/bin/env python3

import psycopg2
from config import Config

def migrate_database():
    """Migrate the database to the new schema"""
    db_config = Config.get_db_config()

    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        cursor = conn.cursor()

        print("🔄 Migrating database to new schema...")

        # Drop old tables if they exist
        cursor.execute("DROP TABLE IF EXISTS conversations CASCADE")
        cursor.execute("DROP TABLE IF EXISTS user_api_keys CASCADE")
        cursor.execute("DROP TABLE IF EXISTS user_projects CASCADE")
        cursor.execute("DROP TABLE IF EXISTS users CASCADE")

        print("✅ Old tables dropped")

        # The new tables will be created automatically when the application starts
        conn.commit()
        cursor.close()
        conn.close()

        print("✅ Database migration completed!")
        print("🚀 Now restart your application to create the new tables")

    except Exception as e:
        print(f"❌ Migration error: {e}")

if __name__ == "__main__":
    migrate_database()