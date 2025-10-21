import os
from typing import Dict, Any

class Config:
    """Configuration settings for the application"""

    # Redis Configuration
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))

    # PostgreSQL Configuration
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME', 'multi_project_ai_assistant')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'root')

    # Ollama Configuration
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

    # Web Server Configuration
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5000))

    # Application Settings
    MAX_FILE_SIZE = 50000  # 50KB max per file
    MAX_CONTEXT_SIZE = 100000  # ~100KB total context

    # User Projects Configuration
    BASE_PROJECT_DIR = os.getenv('BASE_PROJECT_DIR', '/media/shivareddy/E/oct-2025/15_evg/oct/user_projects')

    # JWT Configuration
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-jwt-secret-key-change-in-production')

    # Available Models
    AVAILABLE_MODELS = [
        "qwen3-vl:235b-cloud",
        "nomic-embed-text:latest",
        "gpt-oss:120b-cloud",
        "qwen3-coder:480b-cloud",
        "deepseek-v3.1:671b-cloud",
        # ... other models
    ]

    @classmethod
    def get_db_config(cls) -> Dict[str, Any]:
        return {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'dbname': cls.DB_NAME,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD
        }

    @classmethod
    def get_redis_config(cls) -> Dict[str, Any]:
        return {
            'host': cls.REDIS_HOST,
            'port': cls.REDIS_PORT,
            'db': cls.REDIS_DB
        }

    @classmethod
    def get_base_project_dir(cls) -> str:
        """Get base project directory and create if it doesn't exist"""
        os.makedirs(cls.BASE_PROJECT_DIR, exist_ok=True)
        return cls.BASE_PROJECT_DIR