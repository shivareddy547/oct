import psycopg2
import psycopg2.extras
from typing import List, Dict, Any, Optional
import os
import hashlib
import secrets
from datetime import datetime, timedelta
import jwt

class PostgresDB:
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        self.jwt_secret = "your-jwt-secret-key-change-in-production"
        self._init_database()

    def _init_database(self):
        """Initialize database and create tables if they don't exist"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE,
                    reset_token VARCHAR(255),
                    reset_token_expires TIMESTAMP
                )
            """)

            # Create user_projects table
            cursor.execute("""
                       CREATE TABLE IF NOT EXISTS user_projects (
                           id SERIAL PRIMARY KEY,
                           user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                           project_name VARCHAR(100) NOT NULL,
                           project_type VARCHAR(20) NOT NULL,
                           project_path VARCHAR(500) NOT NULL,
                           redis_project_id VARCHAR(255),  -- NEW: Store Redis project ID
                           port_number INTEGER UNIQUE,
                           created_at TIMESTAMP DEFAULT NOW(),
                           updated_at TIMESTAMP DEFAULT NOW(),
                           UNIQUE(user_id, project_name)
                       )
                   """)

            # Create API keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_projects_user_id ON user_projects(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON user_api_keys(user_id)")

            conn.commit()
            cursor.close()
            conn.close()
            print("✅ Database initialized successfully")

        except Exception as e:
            print(f"❌ Error initializing database: {e}")
            # Don't raise to allow application to continue

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
        """Execute a query and optionally fetch results - FIXED VERSION"""
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            print(f"📝 Executing query: {query[:100]}...")  # Log first 100 chars
            print(f"📝 Params: {params}")

            cursor.execute(query, params or ())

            if fetch:
                result = cursor.fetchall()
                print(f"📝 Fetch result: {len(result)} rows")
                conn.commit()  # Commit even for read operations to be safe
                return [dict(row) for row in result]
            else:
                conn.commit()  # Explicit commit for write operations
                affected = cursor.rowcount
                print(f"📝 Query affected {affected} rows - COMMITTED")
                return affected

        except Exception as e:
            print(f"❌ Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                print("📝 Database connection closed")

    # User Management Methods
    def hash_password(self, password: str) -> str:
        """Hash a password for storing using a more secure method"""
        # Add a pepper for extra security (in production, store this in environment variable)
        pepper = "multi-project-ai-pepper"
        return hashlib.sha256((password + pepper).encode()).hexdigest()

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a stored password against one provided by user"""
        return self.hash_password(password) == password_hash

    def create_user(self, username: str, email: str, password: str) -> Optional[int]:
        """Create a new user - FIXED VERSION"""
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            password_hash = self.hash_password(password)
            print(f"🔐 Creating user: {username}, email: {email}")
            print(f"🔐 Password hash: {password_hash}")

            query = """
            INSERT INTO users (username, email, password_hash, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id
            """

            cursor.execute(query, (username, email, password_hash))
            result = cursor.fetchone()

            if result:
                user_id = result[0]
                conn.commit()  # Explicit commit
                print(f"✅ User created successfully with ID: {user_id} - COMMITTED")

                # Verify the user was actually saved
                cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                verify = cursor.fetchone()
                if verify:
                    print(f"✅ User verification: User ID {verify[0]} confirmed in database")
                else:
                    print("❌ User verification: User NOT found in database after creation!")

                return user_id
            else:
                conn.rollback()
                print("❌ Failed to create user - no ID returned")
                return None

        except Exception as e:
            print(f"❌ Error creating user: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        """Authenticate a user with detailed debugging"""
        query = "SELECT id, username, email, password_hash FROM users WHERE email = %s AND is_active = TRUE"
        try:
            print(f"🔐 Attempting to authenticate user: {email}")

            result = self.execute_query(query, (email,), fetch=True)

            if not result:
                print(f"❌ No user found with email: {email}")
                return None

            user_data = result[0]
            stored_hash = user_data['password_hash']
            input_hash = self.hash_password(password)

            print(f"🔐 Stored hash: {stored_hash}")
            print(f"🔐 Input hash: {input_hash}")
            print(f"🔐 Hashes match: {stored_hash == input_hash}")

            if self.verify_password(password, stored_hash):
                print(f"✅ Authentication successful for user: {user_data['username']}")
                return dict(user_data)
            else:
                print(f"❌ Password verification failed for user: {user_data['username']}")
                return None

        except Exception as e:
            print(f"❌ Error authenticating user: {e}")
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        query = "SELECT id, username, email, created_at FROM users WHERE id = %s AND is_active = TRUE"
        try:
            result = self.execute_query(query, (user_id,), fetch=True)
            return result[0] if result else None
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None

    def update_password(self, user_id: int, new_password: str) -> bool:
        """Update user password"""
        query = "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s"
        try:
            password_hash = self.hash_password(new_password)
            rows_affected = self.execute_query(query, (password_hash, user_id))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error updating password: {e}")
            return False

    def set_reset_token(self, email: str, token: str) -> bool:
        """Set password reset token"""
        expires = datetime.now() + timedelta(hours=1)
        query = "UPDATE users SET reset_token = %s, reset_token_expires = %s WHERE email = %s"
        try:
            rows_affected = self.execute_query(query, (token, expires, email))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error setting reset token: {e}")
            return False

    def verify_reset_token(self, token: str) -> Optional[Dict]:
        """Verify reset token and get user"""
        query = "SELECT id, email FROM users WHERE reset_token = %s AND reset_token_expires > NOW()"
        try:
            result = self.execute_query(query, (token,), fetch=True)
            return result[0] if result else None
        except Exception as e:
            print(f"❌ Error verifying reset token: {e}")
            return None

    def clear_reset_token(self, user_id: int) -> bool:
        """Clear reset token after use"""
        query = "UPDATE users SET reset_token = NULL, reset_token_expires = NULL WHERE id = %s"
        try:
            rows_affected = self.execute_query(query, (user_id,))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error clearing reset token: {e}")
            return False

    # Project Management Methods
    # Update the create_user_project method to accept redis_project_id
    def create_user_project(self, user_id: int, project_name: str, project_type: str, project_path: str, redis_project_id: str = None) -> Optional[int]:
        """Create a new project for user with Redis project ID support"""
        # Find available port (starting from 3000)
        base_port = 3000
        max_port = 4000

        query = "SELECT port_number FROM user_projects ORDER BY port_number"
        try:
            existing_ports = self.execute_query(query, (), fetch=True)
            used_ports = {p['port_number'] for p in existing_ports} if existing_ports else set()

            port_number = None
            for port in range(base_port, max_port):
                if port not in used_ports:
                    port_number = port
                    break

            if not port_number:
                raise Exception("No available ports")

            # Updated insert query with redis_project_id
            insert_query = """
            INSERT INTO user_projects (user_id, project_name, project_type, project_path, redis_project_id, port_number)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """
            result = self.execute_query(
                insert_query,
                (user_id, project_name, project_type, project_path, redis_project_id, port_number),
                fetch=True
            )
            return result[0]['id'] if result else None
        except Exception as e:
            print(f"❌ Error creating user project: {e}")
            return None

    def get_user_projects(self, user_id: int) -> List[Dict]:
        """Get all projects for a user including Redis project ID"""
        query = """
        SELECT id, project_name, project_type, project_path, redis_project_id, port_number, created_at
        FROM user_projects
        WHERE user_id = %s
        ORDER BY created_at DESC
        """
        try:
            return self.execute_query(query, (user_id,), fetch=True)
        except Exception as e:
            print(f"❌ Error getting user projects: {e}")
            return []

    def get_project_by_id(self, project_id: int, user_id: int) -> Optional[Dict]:
        """Get specific project for user including Redis project ID"""
        query = """
        SELECT id, project_name, project_type, project_path, redis_project_id, port_number
        FROM user_projects
        WHERE id = %s AND user_id = %s
        """
        try:
            result = self.execute_query(query, (project_id, user_id), fetch=True)
            return result[0] if result else None
        except Exception as e:
            print(f"❌ Error getting project: {e}")
            return None

    # API Key Management Methods (updated for user_id)
    def save_api_key(self, user_id: int, provider: str, api_key: str) -> bool:
        """Save or update API key for a user and provider"""
        query = """
        INSERT INTO user_api_keys (user_id, provider, api_key, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id, provider)
        DO UPDATE SET api_key = %s, updated_at = NOW()
        """
        try:
            self.execute_query(query, (user_id, provider, api_key, api_key))
            print(f"✅ API key saved for user {user_id} - {provider}")
            return True
        except Exception as e:
            print(f"❌ Error saving API key: {e}")
            return False

    def update_project_redis_id(self, project_id: int, user_id: int, redis_project_id: str) -> bool:
        """Update Redis project ID for an existing project"""
        query = """
        UPDATE user_projects
        SET redis_project_id = %s, updated_at = NOW()
        WHERE id = %s AND user_id = %s
        """
        try:
            rows_affected = self.execute_query(query, (redis_project_id, project_id, user_id))
            return rows_affected > 0
        except Exception as e:
            print(f"❌ Error updating Redis project ID: {e}")
            return False
    def get_api_key(self, user_id: int, provider: str) -> Optional[str]:
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

    def get_user_api_keys(self, user_id: int) -> List[Dict]:
        """Get all API keys for a user"""
        query = "SELECT provider, created_at, updated_at FROM user_api_keys WHERE user_id = %s"
        try:
            return self.execute_query(query, (user_id,), fetch=True)
        except Exception as e:
            print(f"❌ Error getting user API keys: {e}")
            return []

    # Conversation Methods (FIXED - user_id is first parameter)
    def store_conversation(self, user_id: int, session_id: str, query: str, yaml_response: str,
                         model_used: str, provider: str = 'ollama') -> int:
        """Store a conversation in the database - FIXED VERSION"""
        query_sql = """
        INSERT INTO conversations (user_id, session_id, query, yaml_response, model_used, provider, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
        """

        try:
            print(f"💾 Storing conversation for user_id: {user_id}, session_id: {session_id}")
            print(f"💾 Model: {model_used}, Provider: {provider}")
            print(f"💾 Query preview: {query[:100]}...")
            print(f"💾 YAML preview: {yaml_response[:100]}...")

            result = self.execute_query(
                query_sql,
                (user_id, session_id, query, yaml_response, model_used, provider),
                fetch=True
            )

            if result:
                conversation_id = result[0]['id']
                print(f"✅ Conversation stored successfully with ID: {conversation_id}")
                return conversation_id
            else:
                print("❌ Failed to store conversation - no ID returned")
                return None
        except Exception as e:
            print(f"❌ Error storing conversation: {e}")
            raise

    def get_conversation_history(self, user_id: int, session_id: str, limit: int = 10) -> List[Dict]:
        """Get conversation history for a specific session and user"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE user_id = %s AND session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        try:
            return self.execute_query(query, (user_id, session_id, limit), fetch=True)
        except Exception as e:
            print(f"❌ Error getting conversation history: {e}")
            return []

    def get_all_conversations(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get all conversations for a user"""
        query = """
        SELECT id, session_id, query, yaml_response, model_used, provider, created_at
        FROM conversations
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        try:
            return self.execute_query(query, (user_id, limit), fetch=True)
        except Exception as e:
            print(f"❌ Error getting all conversations: {e}")
            return []

    def update_application_results(self, conversation_id: int, results: Dict[str, Any]):
        """Update conversation with application results"""
        query = """
        UPDATE conversations
        SET application_results = %s
        WHERE id = %s
        """
        self.execute_query(query, (psycopg2.extras.Json(results), conversation_id))

    # JWT Token Methods
    def generate_token(self, user_id: int) -> str:
        """Generate JWT token for user"""
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(days=7)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm='HS256')

    def verify_token(self, token: str) -> Optional[int]:
        """Verify JWT token and return user_id"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            return payload.get('user_id')
        except jwt.ExpiredSignatureError:
            print("❌ Token expired")
            return None
        except jwt.InvalidTokenError:
            print("❌ Invalid token")
            return None