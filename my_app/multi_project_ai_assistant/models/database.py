import psycopg2
import psycopg2.extras
from typing import List, Dict, Any, Optional
import os
from datetime import datetime

class PostgresDB:
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        self._init_database()

    def _init_database(self):
        """Initialize database and create tables if they don't exist"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Create API keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    provider VARCHAR(50) NOT NULL,
                    api_key TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, provider)
                )
            """)

            # Create conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    query TEXT NOT NULL,
                    yaml_response TEXT,
                    model_used VARCHAR(100),
                    provider VARCHAR(50) DEFAULT 'ollama',
                    application_results JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Create indexes for better performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_session_id
                ON conversations(session_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_created_at
                ON conversations(created_at DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_user_id
                ON user_api_keys(user_id)
            """)

            conn.commit()
            cursor.close()
            conn.close()
            print("✅ Database initialized successfully")

        except Exception as e:
            print(f"❌ Error initializing database: {e}")
            raise

    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(
            host=self.db_config['host'],
            port=self.db_config['port'],
            dbname=self.db_config['dbname'],
            user=self.db_config['user'],
            password=self.db_config['password']
        )

    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute a query and optionally fetch results"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            cursor.execute(query, params)

            if fetch:
                result = cursor.fetchall()
                # Convert to list of dictionaries
                return [dict(row) for row in result]
            else:
                conn.commit()
                return cursor.rowcount

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"❌ Database error: {e}")
            raise
        finally:
            if conn:
                cursor.close()
                conn.close()

    # API Key Management Methods
    def save_api_key(self, user_id: str, provider: str, api_key: str) -> bool:
        """Save or update API key for a user and provider"""
        query = """
        INSERT INTO user_api_keys (user_id, provider, api_key, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id, provider)
        DO UPDATE SET api_key = %s, updated_at = NOW()
        """
        try:
            self.execute_query(query, (user_id, provider, api_key, api_key))
            print(f"✅ API key saved for {user_id} - {provider}")
            return True
        except Exception as e:
            print(f"❌ Error saving API key: {e}")
            return False

    def get_api_key(self, user_id: str, provider: str) -> Optional[str]:
        """Get API key for a user and provider"""
        query = """
        SELECT api_key FROM user_api_keys
        WHERE user_id = %s AND provider = %s
        """
        try:
            result = self.execute_query(query, (user_id, provider), fetch=True)
            return result[0]['api_key'] if result else None
        except Exception as e:
            print(f"❌ Error getting API key: {e}")
            return None

    def delete_api_key(self, user_id: str, provider: str) -> bool:
        """Delete API key for a user and provider"""
        query = "DELETE FROM user_api_keys WHERE user_id = %s AND provider = %s"
        try:
            rows_affected = self.execute_query(query, (user_id, provider))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error deleting API key: {e}")
            return False

    def get_user_api_keys(self, user_id: str) -> List[Dict]:
        """Get all API keys for a user"""
        query = "SELECT provider, created_at, updated_at FROM user_api_keys WHERE user_id = %s"
        try:
            return self.execute_query(query, (user_id,), fetch=True)
        except Exception as e:
            print(f"❌ Error getting user API keys: {e}")
            return []

    # Conversation Methods
    def store_conversation(self, session_id: str, query: str, yaml_response: str,
                         model_used: str, provider: str = 'ollama') -> int:
        """Store a conversation in the database"""
        query_sql = """
        INSERT INTO conversations (session_id, query, yaml_response, model_used, provider, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING id
        """

        try:
            result = self.execute_query(
                query_sql,
                (session_id, query, yaml_response, model_used, provider),
                fetch=True
            )

            if result:
                print(f"✅ Conversation stored with ID: {result[0]['id']}")
                return result[0]['id']
            return None
        except Exception as e:
            print(f"❌ Error storing conversation: {e}")
            raise

    def get_conversation_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get conversation history for a specific session"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        try:
            return self.execute_query(query, (session_id, limit), fetch=True)
        except Exception as e:
            print(f"❌ Error getting conversation history: {e}")
            return []

    def get_all_conversations(self, limit: int = 50) -> List[Dict]:
        """Get all conversations across all sessions"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        ORDER BY created_at DESC
        LIMIT %s
        """
        try:
            return self.execute_query(query, (limit,), fetch=True)
        except Exception as e:
            print(f"❌ Error getting all conversations: {e}")
            return []

    def get_conversation_by_id(self, conversation_id: int) -> Optional[Dict]:
        """Get a specific conversation by ID"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at, application_results
        FROM conversations
        WHERE id = %s
        """
        result = self.execute_query(query, (conversation_id,), fetch=True)
        return result[0] if result else None

    def update_application_results(self, conversation_id: int, results: Dict[str, Any]):
        """Update conversation with application results"""
        query = """
        UPDATE conversations
        SET application_results = %s
        WHERE id = %s
        """
        self.execute_query(query, (psycopg2.extras.Json(results), conversation_id))

    def get_recent_conversations(self, hours: int = 24) -> List[Dict]:
        """Get conversations from the last specified hours"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE created_at >= NOW() - INTERVAL '%s hours'
        ORDER BY created_at DESC
        """
        return self.execute_query(query, (hours,), fetch=True)

    def delete_conversation(self, conversation_id: int) -> bool:
        """Delete a specific conversation"""
        query = "DELETE FROM conversations WHERE id = %s"
        try:
            rows_affected = self.execute_query(query, (conversation_id,))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error deleting conversation: {e}")
            return False

    def get_conversations_by_model(self, model_name: str, limit: int = 20) -> List[Dict]:
        """Get conversations that used a specific model"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE model_used = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        return self.execute_query(query, (model_name, limit), fetch=True)

    def get_conversations_by_provider(self, provider: str, limit: int = 20) -> List[Dict]:
        """Get conversations that used a specific provider"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE provider = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        return self.execute_query(query, (provider, limit), fetch=True)