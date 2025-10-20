#!/usr/bin/env python3
import os
import json
import yaml
import requests
import redis
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re
import subprocess
from flask import Flask, request, jsonify, copy_current_request_context, session, render_template_string
from flask_socketio import SocketIO, emit
import threading
import uuid
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import math
from difflib import SequenceMatcher
import time
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# Configuration
class Config:
    SECRET_KEY = 'multi-project-ai-assistant-secret-key-2024'
    JWT_SECRET_KEY = 'jwt-secret-key-2024'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    DB_CONFIG = {
        'dbname': 'multi_project_ai_assistant_json',
        'user': 'postgres',
        'password': 'root',
        'host': 'localhost',
        'port': 5432
    }
    HOME_PATH = "/media/shivareddy/E/oct-2025"

# Authentication decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
            current_user = data['user_id']
        except Exception as e:
            return jsonify({'error': 'Token is invalid'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

class MultiProjectFileFinder:
    def __init__(self, project_roots: List[str]):
        self.project_roots = project_roots
        self.react_extensions = (".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".json", ".html")
        self.rails_extensions = (".rb", ".erb", ".haml", ".slim", ".yml", ".yaml", ".json", ".js", ".css", ".scss", ".coffee", ".html")

    def get_project_type(self, file_path: str) -> str:
        """Determine if file belongs to React or Rails project"""
        for root in self.project_roots:
            if file_path.startswith(root):
                # Check for Rails-specific directories
                if any(rail_dir in file_path for rail_dir in ['app/', 'config/', 'db/', 'lib/', 'test/', 'spec/']):
                    return 'rails'
                # Check for React-specific directories
                if any(react_dir in file_path for react_dir in ['src/', 'public/', 'components/']):
                    return 'react'
        return 'unknown'

    def get_all_files(self) -> List[Tuple[str, str]]:
        """Get all files from all projects with their project type"""
        files_with_type = []

        for project_root in self.project_roots:
            for root, _, file_list in os.walk(project_root):
                # Skip common directories that don't contain source code
                if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next', 'tmp', 'log', 'vendor/bundle']):
                    continue

                for file in file_list:
                    full_path = os.path.join(root, file)
                    project_type = self.get_project_type(full_path)

                    # Check file extensions based on project type
                    if project_type == 'react' and file.endswith(self.react_extensions):
                        files_with_type.append((full_path, 'react'))
                    elif project_type == 'rails' and file.endswith(self.rails_extensions):
                        files_with_type.append((full_path, 'rails'))
                    elif project_type == 'unknown':
                        # For unknown project type, check both extensions
                        if file.endswith(self.react_extensions) or file.endswith(self.rails_extensions):
                            files_with_type.append((full_path, 'unknown'))

        return files_with_type

    def analyze_query_intent(self, query: str) -> Dict[str, bool]:
        """Analyze query to determine if it requires frontend, backend, or both changes"""
        query_lower = query.lower()

        # Frontend-related keywords
        frontend_keywords = [
            'ui', 'component', 'button', 'form', 'input', 'dropdown', 'modal', 'popup',
            'layout', 'design', 'style', 'css', 'responsive', 'mobile', 'desktop',
            'render', 'display', 'show', 'hide', 'visible', 'interface', 'user interface',
            'page', 'screen', 'view', 'frontend', 'client-side', 'browser', 'dom'
        ]

        # Backend-related keywords
        backend_keywords = [
            'api', 'endpoint', 'controller', 'model', 'database', 'db', 'server', 'backend',
            'route', 'authentication', 'auth', 'login', 'register', 'session', 'cookie',
            'validation', 'business logic', 'server-side', 'crud', 'create', 'read', 'update', 'delete',
            'rest', 'graphql', 'endpoint', 'request', 'response', 'middleware'
        ]

        # Full-stack features (require both)
        fullstack_keywords = [
            'contact form', 'user registration', 'login system', 'authentication',
            'shopping cart', 'payment', 'checkout', 'user profile', 'dashboard',
            'data table', 'search', 'filter', 'pagination', 'upload', 'download'
        ]

        requires_frontend = any(keyword in query_lower for keyword in frontend_keywords)
        requires_backend = any(keyword in query_lower for keyword in backend_keywords)
        requires_both = any(keyword in query_lower for keyword in fullstack_keywords)

        # If no specific keywords found, analyze context
        if not requires_frontend and not requires_backend and not requires_both:
            # Default to frontend for simple UI changes
            if any(word in query_lower for word in ['add', 'create', 'make', 'build', 'show']):
                requires_frontend = True
            # Default to backend for data-related changes
            if any(word in query_lower for word in ['save', 'store', 'process', 'handle', 'validate']):
                requires_backend = True

        # If both flags are set or fullstack keyword found, require both
        if requires_both or (requires_frontend and requires_backend):
            requires_frontend = True
            requires_backend = True

        return {
            'frontend': requires_frontend,
            'backend': requires_backend,
            'fullstack': requires_frontend and requires_backend
        }

    def relevance_score(self, filename: str, query: str, project_type: str, intent: Dict[str, bool]) -> float:
        """Compute similarity between filename/path and user query with intent consideration"""
        base = os.path.basename(filename).lower()
        path_lower = filename.lower()
        query_lower = query.lower()

        # Calculate base filename similarity
        base_ratio = SequenceMatcher(None, base, query_lower).ratio()

        # Calculate path similarity
        path_ratio = SequenceMatcher(None, path_lower, query_lower).ratio()

        # Check for keyword matches in filename and path
        keyword_bonus = 0
        query_words = query_lower.split()
        for word in query_words:
            if len(word) > 3:  # Only consider words longer than 3 characters
                if word in base or word in path_lower:
                    keyword_bonus += 0.2

        # Intent-based scoring - boost files that match the query intent
        intent_bonus = 0
        if intent['frontend'] and project_type == "react":
            intent_bonus += 0.4
        if intent['backend'] and project_type == "rails":
            intent_bonus += 0.4

        # Project type bonus
        type_bonus = 0
        if "rails" in query_lower and project_type == "rails":
            type_bonus += 0.3
        elif "react" in query_lower and project_type == "react":
            type_bonus += 0.3
        elif "api" in query_lower and project_type == "rails":
            type_bonus += 0.2
        elif "frontend" in query_lower and project_type == "react":
            type_bonus += 0.2

        # Combine scores with weights
        final_score = (base_ratio * 0.4) + (path_ratio * 0.3) + min(keyword_bonus, 0.2) + min(intent_bonus, 0.4) + min(type_bonus, 0.2)

        return min(final_score, 1.0)

    def find_relevant_files(self, query: str, top_n: int = 10) -> List[Tuple[str, str]]:
        """Return most relevant files based on query, filename, content, project type, and intent."""
        if not query or not query.strip():
            return []

        all_files = self.get_all_files()
        if not all_files:
            return []

        query_lower = query.lower().strip()
        query_words = set(query_lower.split())

        # Analyze query intent first
        intent = self.analyze_query_intent(query)
        print(f"🎯 Query Intent Analysis: {intent}")

        ranked = []

        for file_path, project_type in all_files:
            file_name = os.path.basename(file_path).lower()
            file_path_lower = file_path.lower()

            # Base score with intent consideration
            base_score = self.relevance_score(file_path, query, project_type, intent)
            keyword_boost = 0
            content_boost = 0

            # Boost for filename/path match
            for word in query_words:
                if word in file_name or word in file_path_lower:
                    keyword_boost += 1.0

            # Check file content
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
                    content = file.read().lower()
                    for w in query_words:
                        if w in content:
                            content_boost += 0.5
            except Exception as e:
                print(f"⚠️ Could not read {file_path}: {e}")

            # Intent-based filtering - prioritize files that match the intent
            if intent['frontend'] and not intent['backend'] and project_type == 'rails':
                # If only frontend needed, reduce rails file scores
                base_score *= 0.3
            elif intent['backend'] and not intent['frontend'] and project_type == 'react':
                # If only backend needed, reduce react file scores
                base_score *= 0.3

            # 🔒 Strict filtering when specific keywords are mentioned
            if "contact" in query_lower:
                if "contact" not in file_name and "contact" not in file_path_lower and "contact" not in content:
                    continue

            # Project-specific filtering
            if "controller" in query_lower and project_type == "rails" and "controller" not in file_path_lower:
                continue
            if "model" in query_lower and project_type == "rails" and "model" not in file_path_lower:
                continue
            if "component" in query_lower and project_type == "react" and "component" not in file_path_lower:
                continue

            final_score = base_score + keyword_boost + content_boost
            ranked.append((file_path, project_type, final_score))

        # Sort and filter
        ranked = sorted(ranked, key=lambda x: x[2], reverse=True)

        # Ensure we get files from both project types if fullstack is needed
        if intent['fullstack']:
            react_files = [(f, p) for f, p, _ in ranked if p == 'react'][:top_n//2]
            rails_files = [(f, p) for f, p, _ in ranked if p == 'rails'][:top_n//2]
            relevant_files = react_files + rails_files
            # Fill with remaining high-scoring files if needed
            remaining_slots = top_n - len(relevant_files)
            if remaining_slots > 0:
                other_files = [(f, p) for f, p, _ in ranked if (f, p) not in relevant_files][:remaining_slots]
                relevant_files.extend(other_files)
        else:
            relevant_files = [(f, p) for f, p, _ in ranked[:top_n]]

        print(f"🔍 Found {len(relevant_files)} relevant files for query: '{query}'")
        for file_path, project_type, score in ranked[:10]:
            print(f"   - [{project_type.upper()}] {os.path.basename(file_path)}: {score:.3f}")

        return relevant_files

class MultiProjectContextBuilder:
    def __init__(self, max_file_size=50000):  # 50KB max per file
        self.max_file_size = max_file_size

    def build_context(self, file_paths_with_types: List[Tuple[str, str]], intent: Dict[str, bool]) -> str:
        """Combine contents of found files into one unified context with project type info"""
        context_parts = []
        total_size = 0

        context_parts.append("=== MULTI-PROJECT CONTEXT ===")
        context_parts.append(f"=== QUERY INTENT: Frontend: {intent['frontend']}, Backend: {intent['backend']}, Fullstack: {intent['fullstack']} ===")

        # Group files by project type
        react_files = [f for f, t in file_paths_with_types if t == 'react']
        rails_files = [f for f, t in file_paths_with_types if t == 'rails']
        unknown_files = [f for f, t in file_paths_with_types if t == 'unknown']

        # Prioritize files based on intent
        if intent['frontend'] and react_files:
            context_parts.append(f"\n--- REACT PROJECT FILES ({len(react_files)} files) ---")
            for path in react_files:
                context_parts.extend(self._read_file_content(path, "REACT"))
                total_size += len(context_parts[-1]) if context_parts else 0

        if intent['backend'] and rails_files:
            context_parts.append(f"\n--- RAILS PROJECT FILES ({len(rails_files)} files) ---")
            for path in rails_files:
                context_parts.extend(self._read_file_content(path, "RAILS"))
                total_size += len(context_parts[-1]) if context_parts else 0

        if unknown_files and (not intent['frontend'] or not intent['backend']):
            context_parts.append(f"\n--- UNKNOWN PROJECT TYPE FILES ({len(unknown_files)} files) ---")
            for path in unknown_files:
                context_parts.extend(self._read_file_content(path, "UNKNOWN"))
                total_size += len(context_parts[-1]) if context_parts else 0

        # Limit total context size
        if total_size > 100000:  # ~100KB total context
            print(f"⚠️  Context size limit reached ({total_size} bytes), truncating...")
            context_parts.append("\n--- CONTEXT TRUNCATED DUE TO SIZE LIMIT ---")

        final_context = "\n".join(context_parts)
        print(f"📚 Built context with {len(file_paths_with_types)} files, total size: {len(final_context)} bytes")
        return final_context

    def _read_file_content(self, path: str, project_type: str) -> List[str]:
        """Read file content and return formatted context lines"""
        content_parts = []
        try:
            file_size = os.path.getsize(path)
            if file_size > self.max_file_size:
                content_parts.append(f"\n--- {project_type} FILE: {path} (SKIPPED - Too large: {file_size} bytes) ---")
                return content_parts

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            content_parts.append(f"\n--- {project_type} FILE: {path} ---")
            content_parts.append(content)

        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="latin-1") as f:
                    content = f.read()
                content_parts.append(f"\n--- {project_type} FILE: {path} (latin-1 encoding) ---")
                content_parts.append(content)
            except Exception as e:
                content_parts.append(f"\n--- {project_type} FILE: {path} (Error reading: {e}) ---")
        except Exception as e:
            content_parts.append(f"\n--- {project_type} FILE: {path} (Error: {e}) ---")

        return content_parts

# PostgreSQL Database Manager
class PostgresDB:
    def __init__(self, dbname='multi_project_ai_assistant_json', user='postgres', password='root',
                 host='localhost', port=5432):
        self.db_config = {
            'dbname': dbname,
            'user': user,
            'password': password,
            'host': host,
            'port': port
        }
        self.init_database()

    def get_connection(self):
        """Get database connection with error handling"""
        try:
            return psycopg2.connect(**self.db_config)
        except Exception as e:
            print(f"❌ Database connection error: {e}")
            return None

    def init_database(self):
        """Initialize database and create tables if they don't exist"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to initialize database - no connection")
            return

        try:
            cursor = conn.cursor()

            # Create users table for authentication
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')

            # Create password_reset_tokens table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    token VARCHAR(255) UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create user_setup table to store user-specific environment setup
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_setup (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) UNIQUE,
                    react_port INTEGER NOT NULL,
                    rails_port INTEGER NOT NULL,
                    react_path VARCHAR(500) NOT NULL,
                    rails_path VARCHAR(500) NOT NULL,
                    database_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create user_projects table to store project paths per user
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_projects (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    frontend_path VARCHAR(500),
                    backend_path VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Update conversations table with new columns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    session_id VARCHAR(255) NOT NULL,
                    query TEXT NOT NULL,
                    json_response JSONB NOT NULL,
                    project_type VARCHAR(50) NOT NULL,
                    project_paths JSONB NOT NULL,
                    conversation_model VARCHAR(100),
                    execution_time FLOAT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied_at TIMESTAMP NULL,
                    application_results JSONB NULL
                )
            ''')

            # Create application_results table for detailed results
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS application_results (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER REFERENCES conversations(id),
                    files_created JSONB,
                    files_updated JSONB,
                    files_failed JSONB,
                    packages_installed BOOLEAN,
                    install_output JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            cursor.close()
            print("✅ PostgreSQL database initialized successfully")

        except Exception as e:
            print(f"❌ Error initializing PostgreSQL database: {e}")
        finally:
            conn.close()

    # User Management Methods
    def create_user(self, username: str, email: str, password: str) -> Optional[int]:
        """Create a new user and return user ID"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            password_hash = generate_password_hash(password)

            cursor.execute('''
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id
            ''', (username, email, password_hash))

            user_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            print(f"✅ User created with ID: {user_id}")
            return user_id
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return None
        finally:
            conn.close()

    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user and return user data"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT id, username, email, password_hash, is_active
                FROM users
                WHERE username = %s AND is_active = TRUE
            ''', (username,))

            user = cursor.fetchone()
            cursor.close()

            if user and check_password_hash(user['password_hash'], password):
                return dict(user)
            return None
        except Exception as e:
            print(f"❌ Error authenticating user: {e}")
            return None
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT id, username, email, is_active
                FROM users
                WHERE email = %s AND is_active = TRUE
            ''', (email,))

            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except Exception as e:
            print(f"❌ Error getting user by email: {e}")
            return None
        finally:
            conn.close()

    def store_password_reset_token(self, user_id: int, token: str, expires_at: datetime) -> bool:
        """Store password reset token"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO password_reset_tokens (user_id, token, expires_at)
                VALUES (%s, %s, %s)
            ''', (user_id, token, expires_at))

            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Error storing reset token: {e}")
            return False
        finally:
            conn.close()

    def validate_reset_token(self, token: str) -> Optional[Dict]:
        """Validate password reset token"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT prt.id, prt.user_id, u.username, u.email
                FROM password_reset_tokens prt
                JOIN users u ON prt.user_id = u.id
                WHERE prt.token = %s AND prt.expires_at > NOW() AND prt.used = FALSE
            ''', (token,))

            result = cursor.fetchone()
            cursor.close()
            return dict(result) if result else None
        except Exception as e:
            print(f"❌ Error validating reset token: {e}")
            return None
        finally:
            conn.close()

    def mark_token_used(self, token: str) -> bool:
        """Mark reset token as used"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE password_reset_tokens
                SET used = TRUE
                WHERE token = %s
            ''', (token,))

            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Error marking token used: {e}")
            return False
        finally:
            conn.close()

    def update_user_password(self, user_id: int, new_password: str) -> bool:
        """Update user password"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            password_hash = generate_password_hash(new_password)
            cursor.execute('''
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
            ''', (password_hash, user_id))

            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Error updating user password: {e}")
            return False
        finally:
            conn.close()

    # User Setup Management
    def save_user_setup(self, user_id: int, react_port: int, rails_port: int,
                       react_path: str, rails_path: str, database_name: str) -> bool:
        """Save or update user environment setup"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_setup (user_id, react_port, rails_port, react_path, rails_path, database_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    react_port = EXCLUDED.react_port,
                    rails_port = EXCLUDED.rails_port,
                    react_path = EXCLUDED.react_path,
                    rails_path = EXCLUDED.rails_path,
                    database_name = EXCLUDED.database_name,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, react_port, rails_port, react_path, rails_path, database_name))

            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Error saving user setup: {e}")
            return False
        finally:
            conn.close()

    def get_user_setup(self, user_id: int) -> Optional[Dict]:
        """Get user environment setup"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT react_port, rails_port, react_path, rails_path, database_name
                FROM user_setup
                WHERE user_id = %s
            ''', (user_id,))

            result = cursor.fetchone()
            cursor.close()
            return dict(result) if result else None
        except Exception as e:
            print(f"❌ Error getting user setup: {e}")
            return None
        finally:
            conn.close()

    def check_port_availability(self, react_port: int, rails_port: int, exclude_user_id: int = None) -> bool:
        """Check if ports are available (unique across users)"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            if exclude_user_id:
                cursor.execute('''
                    SELECT COUNT(*) FROM user_setup
                    WHERE (react_port = %s OR rails_port = %s) AND user_id != %s
                ''', (react_port, rails_port, exclude_user_id))
            else:
                cursor.execute('''
                    SELECT COUNT(*) FROM user_setup
                    WHERE react_port = %s OR rails_port = %s
                ''', (react_port, rails_port))

            count = cursor.fetchone()[0]
            cursor.close()
            return count == 0
        except Exception as e:
            print(f"❌ Error checking port availability: {e}")
            return False
        finally:
            conn.close()

    def check_database_name_availability(self, database_name: str, exclude_user_id: int = None) -> bool:
        """Check if database name is available (unique across users)"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            if exclude_user_id:
                cursor.execute('''
                    SELECT COUNT(*) FROM user_setup
                    WHERE database_name = %s AND user_id != %s
                ''', (database_name, exclude_user_id))
            else:
                cursor.execute('''
                    SELECT COUNT(*) FROM user_setup
                    WHERE database_name = %s
                ''', (database_name,))

            count = cursor.fetchone()[0]
            cursor.close()
            return count == 0
        except Exception as e:
            print(f"❌ Error checking database name availability: {e}")
            return False
        finally:
            conn.close()

    # User Projects Management
    def save_user_projects(self, user_id: int, frontend_path: str, backend_path: str) -> bool:
        """Save or update user project paths"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_projects (user_id, frontend_path, backend_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    frontend_path = EXCLUDED.frontend_path,
                    backend_path = EXCLUDED.backend_path,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, frontend_path, backend_path))

            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"❌ Error saving user projects: {e}")
            return False
        finally:
            conn.close()

    def get_user_projects(self, user_id: int) -> Optional[Dict]:
        """Get user project paths"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT frontend_path, backend_path
                FROM user_projects
                WHERE user_id = %s
            ''', (user_id,))

            result = cursor.fetchone()
            cursor.close()
            return dict(result) if result else None
        except Exception as e:
            print(f"❌ Error getting user projects: {e}")
            return None
        finally:
            conn.close()

    # Updated conversation methods with new columns
    def store_conversation(self, user_id: int, session_id: str, query: str, json_response: Dict,
                          project_paths: List[str], conversation_model: str = None,
                          execution_time: float = None) -> int:
        """Store a conversation in the database and return the conversation ID"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to store conversation - no database connection")
            return -1

        try:
            cursor = conn.cursor()

            # Determine project type based on paths
            project_type = "multi"
            if len(project_paths) == 1:
                if "rails" in project_paths[0].lower() or any(x in project_paths[0].lower() for x in ['app/', 'config/', 'db/']):
                    project_type = "rails"
                elif "react" in project_paths[0].lower() or any(x in project_paths[0].lower() for x in ['src/', 'components/']):
                    project_type = "react"

            cursor.execute('''
                INSERT INTO conversations (user_id, session_id, query, json_response, project_type,
                                         project_paths, conversation_model, execution_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (user_id, session_id, query, json.dumps(json_response), project_type,
                  json.dumps(project_paths), conversation_model, execution_time))

            conversation_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()

            print(f"✅ Conversation stored in PostgreSQL with ID: {conversation_id}")
            return conversation_id

        except Exception as e:
            print(f"❌ Error storing conversation in PostgreSQL: {e}")
            import traceback
            traceback.print_exc()
            return -1
        finally:
            conn.close()

    def get_conversation_history(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get conversation history for a user"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get conversation history - no database connection")
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, json_response, project_type, project_paths,
                       conversation_model, execution_time, created_at, applied_at
                FROM conversations
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (user_id, limit))

            conversations = cursor.fetchall()
            cursor.close()

            result = []
            for conv in conversations:
                conv_dict = dict(conv)
                if conv_dict['created_at'] and isinstance(conv_dict['created_at'], datetime):
                    conv_dict['created_at'] = conv_dict['created_at'].isoformat()
                if conv_dict['applied_at'] and isinstance(conv_dict['applied_at'], datetime):
                    conv_dict['applied_at'] = conv_dict['applied_at'].isoformat()
                result.append(conv_dict)

            return result

        except Exception as e:
            print(f"❌ Error fetching conversation history from PostgreSQL: {e}")
            return []
        finally:
            conn.close()

    def get_conversation_by_id(self, conversation_id: int, user_id: int = None) -> Optional[Dict]:
        """Get a specific conversation by ID with optional user check"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get conversation by ID - no database connection")
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            if user_id:
                cursor.execute('''
                    SELECT id, session_id, query, json_response, project_type, project_paths,
                           conversation_model, execution_time, created_at, applied_at
                    FROM conversations
                    WHERE id = %s AND user_id = %s
                ''', (conversation_id, user_id))
            else:
                cursor.execute('''
                    SELECT id, session_id, query, json_response, project_type, project_paths,
                           conversation_model, execution_time, created_at, applied_at
                    FROM conversations
                    WHERE id = %s
                ''', (conversation_id,))

            conversation = cursor.fetchone()
            cursor.close()

            if conversation:
                conv_dict = dict(conversation)
                if conv_dict['created_at'] and isinstance(conv_dict['created_at'], datetime):
                    conv_dict['created_at'] = conv_dict['created_at'].isoformat()
                if conv_dict['applied_at'] and isinstance(conv_dict['applied_at'], datetime):
                    conv_dict['applied_at'] = conv_dict['applied_at'].isoformat()
                return conv_dict

            return None

        except Exception as e:
            print(f"❌ Error fetching conversation by ID from PostgreSQL: {e}")
            return None
        finally:
            conn.close()

    def update_application_results(self, conversation_id: int, results: Dict):
        """Update conversation with application results"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to update application results - no database connection")
            return

        try:
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE conversations
                SET applied_at = CURRENT_TIMESTAMP,
                    application_results = %s
                WHERE id = %s
            ''', (json.dumps(results), conversation_id))

            # Store detailed results in application_results table
            cursor.execute('''
                INSERT INTO application_results
                (conversation_id, files_created, files_updated, files_failed,
                 packages_installed, install_output)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                conversation_id,
                json.dumps(results.get('files_created', [])),
                json.dumps(results.get('files_updated', [])),
                json.dumps(results.get('files_failed', [])),
                results.get('packages_installed', False),
                json.dumps(results.get('install_output', []))
            ))

            conn.commit()
            cursor.close()

            print(f"✅ Application results stored for conversation ID: {conversation_id}")

        except Exception as e:
            print(f"❌ Error storing application results in PostgreSQL: {e}")
        finally:
            conn.close()

    def get_all_conversations(self, limit: int = 100) -> List[Dict]:
        """Get all conversations across all sessions"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get all conversations - no database connection")
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, user_id, session_id, query, json_response, project_type, project_paths,
                       conversation_model, execution_time, created_at, applied_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT %s
            ''', (limit,))

            conversations = cursor.fetchall()
            cursor.close()

            result = []
            for conv in conversations:
                conv_dict = dict(conv)
                if conv_dict['created_at'] and isinstance(conv_dict['created_at'], datetime):
                    conv_dict['created_at'] = conv_dict['created_at'].isoformat()
                if conv_dict['applied_at'] and isinstance(conv_dict['applied_at'], datetime):
                    conv_dict['applied_at'] = conv_dict['applied_at'].isoformat()
                result.append(conv_dict)

            print(f"📊 Retrieved {len(result)} total conversations from database")
            return result

        except Exception as e:
            print(f"❌ Error fetching all conversations from PostgreSQL: {e}")
            return []
        finally:
            conn.close()

class MultiProjectRedisManager:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                socket_connect_timeout=100
            )
            # Test connection
            self.redis_client.ping()
            print("✅ Redis connection successful")
        except Exception as e:
            print(f"❌ Redis connection failed: {e}")
            self.redis_client = None

        self.project_key_prefix = "multi_project:"

    def store_project_structure(self, project_paths: List[str], user_id: int = None, project_id: str = "default"):
        """Store multiple project structures in Redis with user-specific key"""
        if not self.redis_client:
            print("❌ Redis not available, skipping project storage")
            return {}

        # Use user-specific key if provided
        if user_id:
            project_id = f"user_{user_id}"

        all_project_data = {}

        for i, project_path in enumerate(project_paths):
            project_path = Path(project_path)
            project_type = self._detect_project_type(project_path)
            project_data = {
                'project_root': str(project_path),
                'project_type': project_type,
                'files': {}
            }

            if project_type == 'react':
                extensions = ['*.js', '*.jsx', '*.ts', '*.tsx', '*.css', '*.scss', '*.json', '*.html']
            elif project_type == 'rails':
                extensions = ['*.rb', '*.erb', '*.haml', '*.slim', '*.yml', '*.yaml', '*.json', '*.js', '*.css', '*.scss', '*.coffee', '*.html']
            else:
                extensions = ['*.js', '*.jsx', '*.ts', '*.tsx', '*.rb', '*.erb', '*.yml', '*.yaml', '*.json', '*.html']

            for root, _, file_list in os.walk(project_path):
                # Skip common directories
                if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next', 'tmp', 'log', 'vendor/bundle']):
                    continue

                for file in file_list:
                    file_path = Path(root) / file
                    relative_path = str(file_path.relative_to(project_path))

                    if any(fnmatch.fnmatch(file, pattern) for pattern in extensions):
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            file_key = f"{self.project_key_prefix}{project_id}:project_{i}:file:{relative_path}"
                            self.redis_client.set(file_key, content)

                            project_data['files'][relative_path] = {
                                'path': relative_path,
                                'size': len(content),
                                'hash': hashlib.md5(content.encode()).hexdigest(),
                                'project_type': project_type
                            }

                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")

            structure_key = f"{self.project_key_prefix}{project_id}:project_{i}:structure"
            self.redis_client.set(structure_key, json.dumps(project_data))
            all_project_data[f'project_{i}'] = project_data

        main_structure_key = f"{self.project_key_prefix}{project_id}:main_structure"
        self.redis_client.set(main_structure_key, json.dumps({
            'project_paths': project_paths,
            'projects': all_project_data,
            'user_id': user_id,
            'stored_at': datetime.now().isoformat()
        }))

        print(f"✅ Project structure stored in Redis for user: {user_id}")
        return all_project_data

    def _detect_project_type(self, project_path: Path) -> str:
        """Detect project type based on directory structure and files"""
        if (project_path / 'package.json').exists():
            return 'react'
        elif (project_path / 'Gemfile').exists():
            return 'rails'
        elif (project_path / 'app').exists() and (project_path / 'config').exists():
            return 'rails'
        elif (project_path / 'src').exists():
            return 'react'
        return 'unknown'

    def get_project_structure(self, user_id: int = None, project_id: str = "default") -> Optional[Dict]:
        """Get main project structure from Redis with user-specific key"""
        if not self.redis_client:
            return None

        # Use user-specific key if provided
        if user_id:
            project_id = f"user_{user_id}"

        main_structure_key = f"{self.project_key_prefix}{project_id}:main_structure"
        structure_data = self.redis_client.get(main_structure_key)
        if structure_data:
            return json.loads(structure_data)
        return None

    def get_user_projects_info(self, user_id: int) -> Optional[Dict]:
        """Get user-specific project information"""
        return self.get_project_structure(user_id)

class OllamaAnalyzer:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.available_models = [
            "gpt-oss:20b-cloud",
            "gpt-oss:120b-cloud",
            "deepseek-v3.1:671b-cloud",
            "qwen3-coder:480b-cloud",
            "kimi-k2:1t-cloud"
        ]
        self.model = "qwen3-coder:480b-cloud"

    def set_model(self, model_name: str):
        """Set the model to use for analysis"""
        if model_name in self.available_models:
            self.model = model_name
            print(f"✅ Model set to: {model_name}")
        else:
            print(f"⚠️  Model {model_name} not in available models. Using default: {self.model}")

    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        return self.available_models

    def auto_generate_file_changes(self, user_query: str, project_roots: List[str]):
        """Automatically generate file changes based on user query and multi-project context"""
        print(f"🎯 Auto-generating file changes for: '{user_query}'")
        print(f"📁 Projects: {project_roots}")
        print(f"🤖 Using model: {self.model}")

        # Step 1: Analyze query intent and dynamically find relevant files across all projects
        finder = MultiProjectFileFinder(project_roots)
        intent = finder.analyze_query_intent(user_query)
        relevant_files_with_types = finder.find_relevant_files(user_query)

        if not relevant_files_with_types:
            print("⚠️  No relevant files found. Using default project context.")
            # Fallback to key files for each project based on intent
            relevant_files_with_types = []
            for project_root in project_roots:
                project_type = finder.get_project_type(project_root)

                # Only include projects that match the intent
                if (intent['frontend'] and project_type == 'react') or (intent['backend'] and project_type == 'rails') or (not intent['frontend'] and not intent['backend']):
                    key_files_to_try = self._get_key_files_for_project(project_root, project_type)

                    for file in key_files_to_try:
                        potential_path = os.path.join(project_root, file)
                        if os.path.exists(potential_path):
                            relevant_files_with_types.append((potential_path, project_type))
                            if len([f for f, t in relevant_files_with_types if t == project_type]) >= 3:
                                break

        # Step 2: Build project context from them with intent information
        context_builder = MultiProjectContextBuilder()
        project_context = context_builder.build_context(relevant_files_with_types, intent)

        # Step 3: Send to Ollama with intent-aware prompt
        json_output = self.analyze_and_generate_changes(user_query, project_context, project_roots, intent)
        return json_output

    def _get_key_files_for_project(self, project_root: str, project_type: str) -> List[str]:
        """Get key files for different project types"""
        if project_type == 'react':
            return [
                'package.json',
                'src/App.js', 'src/App.jsx', 'src/App.tsx',
                'src/index.js', 'src/index.jsx', 'src/index.tsx',
                'src/main.js', 'src/main.jsx', 'src/main.tsx'
            ]
        elif project_type == 'rails':
            return [
                'Gemfile',
                'config/routes.rb',
                'app/controllers/application_controller.rb',
                'app/views/layouts/application.html.erb',
                'config/database.yml',
                'package.json'  # Some Rails apps have frontend assets
            ]
        else:
            return ['package.json', 'Gemfile']

    def analyze_and_generate_changes(self, prompt: str, project_context: str, project_roots: List[str], intent: Dict[str, bool]) -> Dict:
        """Use Ollama to analyze projects and generate specific file changes for multiple projects in JSON format"""
        print(f"Analyzing {len(project_roots)} projects for: {prompt}")
        print(f"Intent: Frontend: {intent['frontend']}, Backend: {intent['backend']}")
        print(f"Using model: {self.model}")

        # Find which projects are React and which are Rails
        react_projects = [p for p in project_roots if any(x in p.lower() for x in ['react', 'src/', 'components/'])]
        rails_projects = [p for p in project_roots if any(x in p.lower() for x in ['rails', 'app/', 'config/', 'db/'])]

        # If we can't determine, assume first is React, second is Rails
        if not react_projects and not rails_projects:
            if len(project_roots) >= 2:
                react_projects = [project_roots[0]]
                rails_projects = [project_roots[1]]
            else:
                react_projects = project_roots
                rails_projects = []

        system_prompt = f"""You are an expert full-stack developer working with both React.js and Ruby on Rails applications.
Analyze the user's request and the current project structures, then provide ONLY the specific file changes and required packages in JSON format.

Available Projects:
React: {', '.join(react_projects) if react_projects else 'None'}
Rails: {', '.join(rails_projects) if rails_projects else 'None'}

Query Intent Analysis:
- Requires Frontend Changes: {intent['frontend']}
- Requires Backend Changes: {intent['backend']}
- Fullstack Feature: {intent['fullstack']}

IMPORTANT: Based on the intent analysis, focus on the appropriate projects:
{"**FRONTEND FOCUS** - Primarily modify React files" if intent['frontend'] and not intent['backend'] else ""}
{"**BACKEND FOCUS** - Primarily modify Rails files" if intent['backend'] and not intent['frontend'] else ""}
{"**FULLSTACK FOCUS** - Modify both React and Rails files" if intent['fullstack'] else ""}

Respond ONLY with valid JSON in this exact format:

{{
  "projects": [
    {{
      "project_path": "{react_projects[0] if react_projects else '.'}",
      "project_type": "react",
      "files": [
        {{
          "path": "src/components/Component.js",
          "content": "// Full file content with changes\\nimport React from 'react';\\n\\nconst Component = () => {{\\n  return <div>Content</div>;\\n}};\\n\\nexport default Component;"
        }}
      ]
    }},
    {{
      "project_path": "{rails_projects[0] if rails_projects else ''}",
      "project_type": "rails",
      "files": [
        {{
          "path": "app/controllers/some_controller.rb",
          "content": "class SomeController < ApplicationController\\n  def index\\n    # Controller code here\\n  end\\nend"
        }}
      ]
    }}
  ],
  "packages": {{
    "react_dependencies": ["package-name@version"],
    "react_devDependencies": ["@types/package@version"],
    "rails_gems": ["gem-name"]
  }},
  "install_commands": [
    "cd {react_projects[0] if react_projects else '.'} && npm install package-name@version",
    "cd {rails_projects[0] if rails_projects else '.'} && bundle add gem-name"
  ]
}}

Rules:
1. {"Focus on React files only" if intent['frontend'] and not intent['backend'] else ""}
2. {"Focus on Rails files only" if intent['backend'] and not intent['frontend'] else ""}
3. {"Create both frontend and backend files" if intent['fullstack'] else ""}
4. Provide COMPLETE file content, not just diffs
5. For existing files, include the entire content with changes
6. Use proper file paths relative to each project root
7. Include all necessary imports and dependencies
8. Make sure the code is syntactically correct for each project type
9. For React: use proper React patterns and JSX syntax
10. For Rails: use proper Ruby syntax and Rails conventions
11. Include required packages/gems in the appropriate sections
12. Provide exact install commands with proper cd commands for each project
13. Only include packages that are actually needed for the implementation
14. Check if packages are already in package.json/Gemfile before including
15. If creating API endpoints in Rails, ensure they work with React frontend
16. For database changes in Rails, include migration files if needed
17. For Rails: we dont have authentication so just create apis without any authentication changes

Do not include any explanations, analysis, or text outside the JSON format."""

        full_prompt = f"""MULTI-PROJECT CONTEXT:
{project_context}

USER REQUEST: {prompt}

QUERY INTENT:
- Frontend changes needed: {intent['frontend']}
- Backend changes needed: {intent['backend']}
- Fullstack feature: {intent['fullstack']}

Generate the appropriate file changes and required packages in JSON format:"""

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "system": system_prompt,
                    "stream": False
                },
                timeout=10000  # 2 minute timeout
            )
            response.raise_for_status()
            response_text = response.json()["response"]

            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON without markers
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text

            # Parse JSON
            return json.loads(json_str)

        except requests.exceptions.Timeout:
            return {"error": "Request timeout - Ollama server took too long to respond"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response: {e}", "raw_response": response_text}
        except Exception as e:
            return {"error": str(e)}

class MultiProjectAIAssistant:
    def __init__(self, project_paths: List[str], redis_host='localhost', redis_port=6379,
                 db_config=None, user_id=None):
        self.project_paths = project_paths
        self.redis_manager = MultiProjectRedisManager(redis_host, redis_port)
        self.ollama = OllamaAnalyzer()
        self.project_id = hashlib.md5("_".join(project_paths).encode()).hexdigest()[:8]
        self.user_id = user_id

        # Initialize PostgreSQL database
        self.db = PostgresDB(**(db_config or {}))

    def set_model(self, model_name: str):
        """Set the model for the Ollama analyzer"""
        self.ollama.set_model(model_name)

    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        return self.ollama.get_available_models()

    def initialize_projects(self):
        """Initialize and store all projects in Redis with user-specific key"""
        print(f"🔍 Scanning and storing multiple project structures in Redis for user {self.user_id}...")
        project_data = self.redis_manager.store_project_structure(self.project_paths, self.user_id, self.project_id)

        total_files = 0
        for project_key, data in project_data.items():
            file_count = len(data['files'])
            total_files += file_count
            print(f"✅ {data['project_type'].upper()} Project stored: {data['project_root']} with {file_count} files")

        print(f"🎉 All projects stored in Redis with {total_files} total files (User ID: {self.user_id}, Project ID: {self.project_id})")
        return project_data

    def validate_and_complete_json(self, json_response: Dict) -> Dict:
        """Validate JSON and ensure all required sections are present"""
        try:
            # Ensure projects section exists
            if 'projects' not in json_response:
                json_response['projects'] = [{
                    'project_path': self.project_paths[0],
                    'project_type': 'unknown',
                    'files': []
                }]

            # Ensure packages section exists with proper structure
            if 'packages' not in json_response:
                json_response['packages'] = {
                    'react_dependencies': [],
                    'react_devDependencies': [],
                    'rails_gems': []
                }
            else:
                if 'react_dependencies' not in json_response['packages']:
                    json_response['packages']['react_dependencies'] = []
                if 'react_devDependencies' not in json_response['packages']:
                    json_response['packages']['react_devDependencies'] = []
                if 'rails_gems' not in json_response['packages']:
                    json_response['packages']['rails_gems'] = []

            # Ensure install_commands section exists
            if 'install_commands' not in json_response:
                json_response['install_commands'] = []

                # Generate install commands from packages if not provided
                react_deps = json_response['packages']['react_dependencies']
                react_dev_deps = json_response['packages']['react_devDependencies']
                rails_gems = json_response['packages']['rails_gems']

                # Find project paths for each type
                react_projects = [p for p in self.project_paths if 'react' in p.lower() or not any('rails' in rp.lower() for rp in self.project_paths)]
                rails_projects = [p for p in self.project_paths if 'rails' in p.lower()]

                if react_deps and react_projects:
                    for project in react_projects:
                        json_response['install_commands'].append(f"cd {project} && npm install {' '.join(react_deps)}")
                if react_dev_deps and react_projects:
                    for project in react_projects:
                        json_response['install_commands'].append(f"cd {project} && npm install --save-dev {' '.join(react_dev_deps)}")
                if rails_gems and rails_projects:
                    for project in rails_projects:
                        for gem in rails_gems:
                            json_response['install_commands'].append(f"cd {project} && bundle add {gem}")
                        json_response['install_commands'].append(f"cd {project} && bundle install")

                if not react_deps and not react_dev_deps and not rails_gems:
                    json_response['install_commands'].append("echo 'No additional packages required'")

            return json_response

        except Exception as e:
            # Return a basic valid JSON structure with the error
            return {
                "projects": [
                    {
                        "project_path": self.project_paths[0],
                        "project_type": "unknown",
                        "files": [
                            {
                                "path": "error.txt",
                                "content": f"Invalid JSON response: {e}"
                            }
                        ]
                    }
                ],
                "packages": {
                    "react_dependencies": [],
                    "react_devDependencies": [],
                    "rails_gems": []
                },
                "install_commands": [
                    "echo 'Error in JSON generation'"
                ]
            }

    def apply_changes(self, json_response: Dict) -> Dict:
        """Apply changes from LLM JSON response to project files."""
        try:
            results = {
                'files_created': [],
                'files_updated': [],
                'files_failed': [],
                'packages_installed': False,
                'install_output': []
            }

            # Get user-specific project paths
            user_setup = self.db.get_user_setup(self.user_id) if self.user_id else None
            if user_setup:
                rails_path = user_setup['rails_path']
                react_path = user_setup['react_path']
            else:
                # Fallback to default paths
                rails_path = "/media/shivareddy/E/oct-2025/oct/my_api_app"
                react_path = "/media/shivareddy/E/oct-2025/oct/my-blue-app"

            projects = json_response.get('projects', [])

            # ------------------------
            # 1. Write project files
            # ------------------------
            for project_info in projects:
                project_path = project_info.get('project_path')

                # Force correct project root for React or Rails
                if project_info.get('project_type') == 'react' and project_path == '.':
                    project_path = react_path
                elif project_info.get('project_type') == 'rails' and project_path == '.':
                    project_path = rails_path

                project_type = project_info.get('project_type', 'unknown')

                if not project_path:
                    project_path = self.project_paths[0]

                print(f"🔄 Applying changes to project: {project_path} (type: {project_type})")

                for file_info in project_info.get('files', []):
                    file_path = file_info.get('path')
                    content = file_info.get('content', '')

                    if "db/migrate/" in file_path:
                        from datetime import datetime
                        import re
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        base_name = os.path.basename(file_path)
                        base_name = re.sub(r'^\d+_', '', base_name)
                        if not base_name.endswith('.rb'):
                            base_name = base_name.replace('_rb', '.rb')
                            if not base_name.endswith('.rb'):
                                base_name += '.rb'
                        base_name = re.sub(r'[^a-z0-9_.]', '_', base_name.lower())
                        full_path = os.path.join(project_path, "db/migrate", f"{timestamp}_{base_name}")
                    else:
                        full_path = os.path.join(project_path, file_path)

                    try:
                        os.makedirs(os.path.dirname(full_path), exist_ok=True)
                        file_exists = os.path.exists(full_path)

                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        os.utime(full_path, None)

                        entry = f"[{project_type.upper()}] {file_path} -> {project_path}"
                        if file_exists:
                            results['files_updated'].append(entry)
                            print(f"✅ Updated: {entry}")
                        else:
                            results['files_created'].append(entry)
                            print(f"✅ Created: {entry}")

                    except Exception as e:
                        entry = f"[{project_type.upper()}] {file_path} -> {project_path}: {str(e)}"
                        results['files_failed'].append(entry)
                        print(f"❌ Failed: {entry}")

            # ------------------------
            # 2. Handle Package Installation
            # ------------------------
            install_cmds = json_response.get('install_commands', [])
            if install_cmds:
                results['packages_installed'] = True
                rails_updated = False
                react_updated = False

                for cmd in install_cmds:
                    if 'npm' in cmd:
                        cwd = react_path
                        react_updated = True
                    elif any(x in cmd for x in ['bundle', 'rails', 'gem']):
                        cwd = rails_path
                        rails_updated = True
                    else:
                        cwd = os.getcwd()

                    print(f"📦 Running: {cmd} (in {cwd})")
                    try:
                        completed = subprocess.run(
                            cmd,
                            cwd=cwd,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        output = completed.stdout.strip() + "\n" + completed.stderr.strip()
                        results['install_output'].append(f"{cmd}\n{output}")
                        print(f"✅ Command completed: {cmd}")
                    except Exception as e:
                        results['install_output'].append(f"{cmd}\n❌ Error: {str(e)}")
                        print(f"❌ Failed command: {cmd}")

                # ------------------------
                # 3. Restart servers silently
                # ------------------------
                if react_updated:
                    self._restart_react_server(react_path)
                if rails_updated:
                    self._restart_rails_server(rails_path)

            # ------------------------
            # 4. Update Redis Cache with user-specific key
            # ------------------------
            self.redis_manager.store_project_structure(self.project_paths, self.user_id, self.project_id)

            return results

        except Exception as e:
            return {
                'files_created': [],
                'files_updated': [],
                'files_failed': [f"Application error: {str(e)}"],
                'packages_installed': False,
                'install_output': [f"Application error: {str(e)}"]
            }

    def _restart_react_server(self, react_path: str):
        """Silently restart the React development server."""
        print("🔁 Restarting React server silently...")
        try:
            # Get user-specific port
            user_setup = self.db.get_user_setup(self.user_id) if self.user_id else None
            react_port = user_setup['react_port'] if user_setup else 4000

            # Kill any running npm start on this port
            subprocess.run(f"pkill -f 'PORT={react_port}'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Restart it in background
            subprocess.Popen(
                f"nohup npm start --port {react_port} >/dev/null 2>&1 &",
                cwd=react_path,
                shell=True
            )
            print(f"✅ React server restarted on port {react_port}.")
        except Exception as e:
            print(f"⚠️ React restart failed: {e}")

    def _restart_rails_server(self, rails_path: str):
        """Silently restart the Rails server."""
        print("🔁 Restarting Rails server silently...")
        try:
            # Get user-specific port
            user_setup = self.db.get_user_setup(self.user_id) if self.user_id else None
            rails_port = user_setup['rails_port'] if user_setup else 3000

            # Kill running Rails process on this port
            subprocess.run(f"pkill -f 'rails s.*-p {rails_port}'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Restart it in background
            subprocess.Popen(
                f"nohup rails s -p {rails_port} >/dev/null 2>&1 &",
                cwd=rails_path,
                shell=True
            )
            print(f"✅ Rails server restarted on port {rails_port}.")
        except Exception as e:
            print(f"⚠️ Rails restart failed: {e}")

    def process_query(self, query: str, user_id: int = None, session_id: str = "default", use_auto_generate: bool = True) -> Dict:
        """Process user query and return JSON response"""
        print(f"🔄 Processing: {query}")
        print(f"🤖 Using model: {self.ollama.model}")

        start_time = time.time()

        if use_auto_generate:
            # Use the new auto-generate approach with dynamic file finding across all projects
            json_response = self.ollama.auto_generate_file_changes(query, self.project_paths)
        else:
            # For multi-project, we'll use auto-generate as default
            json_response = self.ollama.auto_generate_file_changes(query, self.project_paths)

        execution_time = time.time() - start_time

        # Validate and complete the JSON structure
        final_json = self.validate_and_complete_json(json_response)

        # Store conversation in PostgreSQL with new columns
        conversation_id = self.db.store_conversation(
            user_id,
            session_id,
            query,
            final_json,
            self.project_paths,
            self.ollama.model,
            execution_time
        )

        if conversation_id == -1:
            print("❌ Failed to store conversation in database!")
        else:
            print(f"✅ Successfully stored conversation with ID: {conversation_id}")

        return final_json

    def get_project_info(self) -> Dict:
        """Get project information for all projects with user-specific data"""
        structure = self.redis_manager.get_project_structure(self.user_id, self.project_id)
        if structure:
            projects_info = []
            for project_key, project_data in structure.get('projects', {}).items():
                projects_info.append({
                    'type': project_data['project_type'],
                    'root': project_data['project_root'],
                    'file_count': len(project_data['files']),
                    'files': list(project_data['files'].keys())[:5]  # First 5 files
                })

            return {
                'project_id': self.project_id,
                'user_id': self.user_id,
                'total_projects': len(projects_info),
                'projects': projects_info,
                'stored_at': structure.get('stored_at', 'Unknown')
            }
        return {'user_id': self.user_id, 'projects': []}

# Environment Setup Manager
class EnvironmentSetupManager:
    def __init__(self, db_config=None):
        self.db = PostgresDB(**(db_config or {}))
        self.home_path = Config.HOME_PATH

    def setup_user_environment(self, user_id: int, react_port: int, rails_port: int,
                              react_path: str, rails_path: str, database_name: str) -> Dict:
        """Setup user environment by creating directories and copying template applications"""
        try:
            # Check if ports and database name are available
            if not self.db.check_port_availability(react_port, rails_port, user_id):
                return {'success': False, 'error': 'Ports already in use by another user'}

            if not self.db.check_database_name_availability(database_name, user_id):
                return {'success': False, 'error': 'Database name already in use by another user'}

            # Create user directory
            user_dir = os.path.join(self.home_path, f"user{user_id}")
            os.makedirs(user_dir, exist_ok=True)

            # Define source template paths - use the provided paths as templates
            react_template_path = "/media/shivareddy/E/oct-2025/15/my-blue-app"
            rails_template_path = "/media/shivareddy/E/oct-2025/15/my_api_app"

            # Copy React application
            user_react_path = os.path.join(user_dir, "my-blue-app")
            if os.path.exists(react_template_path):
                subprocess.run(['cp', '-r', react_template_path, user_react_path])
                print(f"✅ Copied React app from {react_template_path} to {user_react_path}")
            else:
                os.makedirs(user_react_path, exist_ok=True)
                print(f"⚠️ React template not found, created empty directory: {user_react_path}")

            # Copy Rails application
            user_rails_path = os.path.join(user_dir, "my_api_app")
            if os.path.exists(rails_template_path):
                subprocess.run(['cp', '-r', rails_template_path, user_rails_path])
                print(f"✅ Copied Rails app from {rails_template_path} to {user_rails_path}")
            else:
                os.makedirs(user_rails_path, exist_ok=True)
                print(f"⚠️ Rails template not found, created empty directory: {user_rails_path}")

            # Update Rails database configuration with user-specific database name
            self._update_rails_database_config(user_rails_path, database_name)

            # Update React package.json for port
            self._update_react_port_config(user_react_path, react_port)

            # Save user setup to database
            if self.db.save_user_setup(user_id, react_port, rails_port, user_react_path, user_rails_path, database_name):
                # Start user's servers
                self._start_user_servers(user_id, user_react_path, user_rails_path, react_port, rails_port)

                return {
                    'success': True,
                    'message': 'Environment setup completed successfully',
                    'react_path': user_react_path,
                    'rails_path': user_rails_path,
                    'react_port': react_port,
                    'rails_port': rails_port,
                    'database_name': database_name
                }
            else:
                return {'success': False, 'error': 'Failed to save user setup to database'}

        except Exception as e:
            print(f"❌ Environment setup error: {e}")
            return {'success': False, 'error': f'Environment setup failed: {str(e)}'}

    def _update_rails_database_config(self, rails_path: str, database_name: str):
        """Update Rails database.yml with user-specific database name"""
        database_yml_path = os.path.join(rails_path, 'config', 'database.yml')
        if os.path.exists(database_yml_path):
            with open(database_yml_path, 'r') as f:
                content = f.read()

            # Replace database name
            content = re.sub(r'database:.*$', f'database: {database_name}', content, flags=re.MULTILINE)

            with open(database_yml_path, 'w') as f:
                f.write(content)
            print(f"✅ Updated database.yml with database: {database_name}")

    def _update_react_port_config(self, react_path: str, react_port: int):
        """Update React package.json with user-specific port"""
        package_json_path = os.path.join(react_path, 'package.json')
        if os.path.exists(package_json_path):
            with open(package_json_path, 'r') as f:
                package_data = json.load(f)

            # Add or update start script with port
            if 'scripts' not in package_data:
                package_data['scripts'] = {}

            package_data['scripts']['start'] = f"PORT={react_port} react-scripts start"

            with open(package_json_path, 'w') as f:
                json.dump(package_data, f, indent=2)
            print(f"✅ Updated package.json with port: {react_port}")

    def _start_user_servers(self, user_id: int, react_path: str, rails_path: str, react_port: int, rails_port: int):
        """Start user's React and Rails servers"""
        try:
            # Start Rails server
            subprocess.Popen(
                f"cd {rails_path} && bundle exec rails s -p {rails_port} -d",
                shell=True
            )

            # Start React server
            subprocess.Popen(
                f"cd {react_path} && PORT={react_port} npm start &",
                shell=True
            )

            print(f"✅ Started servers for user {user_id}: React on port {react_port}, Rails on port {rails_port}")
        except Exception as e:
            print(f"⚠️ Failed to start servers for user {user_id}: {e}")

    def execute_user_script(self, user_id: int, script_name: str) -> Dict:
        """Execute user-specific script (reset_db, migrate, restart_servers, etc.)"""
        try:
            user_setup = self.db.get_user_setup(user_id)
            if not user_setup:
                return {'success': False, 'error': 'User setup not found'}

            script_path = f"/home/opc/ai/{script_name}.sh"
            if not os.path.exists(script_path):
                return {'success': False, 'error': f'Script {script_name} not found'}

            # Execute script with user-specific parameters
            result = subprocess.run([
                'bash', script_path,
                user_setup['rails_path'],
                user_setup['react_path'],
                str(user_setup['rails_port']),
                str(user_setup['react_port']),
                user_setup['database_name']
            ], capture_output=True, text=True)

            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }

        except Exception as e:
            return {'success': False, 'error': f'Script execution failed: {str(e)}'}

# Web-based Chatbot UI (Updated for multi-user environment)
class MultiProjectAIChatbotWebUI:
    def __init__(self, project_paths: List[str], redis_host='localhost', redis_port=6379,
                 ollama_url='http://localhost:11434', host='0.0.0.0', port=5000,
                 db_config=None):
        self.project_paths = project_paths
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.ollama_url = ollama_url
        self.host = host
        self.port = port
        self.db_config = db_config
        self.env_manager = EnvironmentSetupManager(db_config)

        # Initialize Flask app
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = Config.SECRET_KEY
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # Store sessions and user assistants
        self.sessions = {}
        self.user_assistants = {}

        self.setup_routes()

    def get_user_assistant(self, user_id: int):
        """Get or create user-specific assistant instance"""
        if user_id not in self.user_assistants:
            # Get user setup to determine project paths
            db = PostgresDB(**(self.db_config or {}))
            user_setup = db.get_user_setup(user_id)

            if user_setup:
                # Use user-specific project paths
                user_project_paths = [user_setup['react_path'], user_setup['rails_path']]
            else:
                # Use default project paths
                user_project_paths = self.project_paths

            # Create user-specific assistant
            self.user_assistants[user_id] = MultiProjectAIAssistant(
                user_project_paths,
                self.redis_host,
                self.redis_port,
                self.db_config,
                user_id
            )

            # Initialize projects for this user
            try:
                self.user_assistants[user_id].initialize_projects()
            except Exception as e:
                print(f"⚠️ Error initializing projects for user {user_id}: {e}")

        return self.user_assistants[user_id]

    def setup_routes(self):
        """Setup Flask routes"""

        # Main route - serve the HTML template
        @self.app.route('/')
        def index():
            return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Project AI Assistant 🤖</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/highlight.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/github.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            padding: 20px;
            text-align: center;
            color: white;
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
        }
        .header h1 {
            font-size: 24px;
            margin-bottom: 5px;
        }
        .header .subtitle {
            font-size: 14px;
            opacity: 0.8;
        }
        .container {
            flex: 1;
            display: flex;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
            padding: 20px;
            gap: 20px;
        }
        .chat-container {
            flex: 1;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .chat-messages {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            background: #f8f9fa;
        }
        .message {
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 15px;
            max-width: 80%;
            animation: fadeIn 0.3s ease-in;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .user-message {
            background: #007bff;
            color: white;
            margin-left: auto;
            border-bottom-right-radius: 5px;
        }
        .assistant-message {
            background: white;
            color: #333;
            margin-right: auto;
            border-bottom-left-radius: 5px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }
        .system-message {
            background: #e9ecef;
            color: #6c757d;
            margin: 10px auto;
            text-align: center;
            max-width: 60%;
            font-style: italic;
        }

        /* Loader Styles */
        .loader {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #007bff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .loading-message {
            background: #e9ecef;
            color: #6c757d;
            padding: 10px 15px;
            border-radius: 10px;
            display: inline-flex;
            align-items: center;
            font-style: italic;
        }

        .setup-loader {
            text-align: center;
            padding: 20px;
        }

        .setup-loader .loader {
            width: 40px;
            height: 40px;
            border-width: 4px;
        }

        .input-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #e9ecef;
        }
        .input-group {
            display: flex;
            gap: 10px;
        }
        #message-input {
            flex: 1;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            font-size: 14px;
            resize: none;
            height: 60px;
            transition: border-color 0.3s;
        }
        #message-input:focus {
            outline: none;
            border-color: #007bff;
        }
        #send-button {
            padding: 15px 25px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            transition: background 0.3s;
        }
        #send-button:hover:not(:disabled) {
            background: #0056b3;
        }
        #send-button:disabled {
            background: #6c757d;
            cursor: not-allowed;
        }
        .model-selector {
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .model-selector label {
            font-weight: bold;
            color: #333;
        }
        .model-selector select {
            padding: 8px 12px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            background: white;
            font-size: 14px;
            min-width: 200px;
        }
        .model-selector select:focus {
            outline: none;
            border-color: #007bff;
        }

        .results-panel {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            width: 600px;
            max-height: 850px;
            display: flex;
            flex-direction: column;
        }
        .results-panel h3 {
            margin-bottom: 15px;
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 5px;
        }
        .project-item {
            padding: 10px;
            margin: 8px 0;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }
        .project-react {
            border-left-color: #61dafb;
        }
        .project-rails {
            border-left-color: #cc0000;
        }
        .file-item {
            padding: 6px 10px;
            margin: 4px 0;
            background: white;
            border-radius: 6px;
            font-size: 11px;
            border-left: 3px solid #28a745;
        }
        .success { border-left-color: #28a745; }
        .warning { border-left-color: #ffc107; }
        .error { border-left-color: #dc3545; }
        .history-container {
            flex: 1;
            overflow-y: auto;
            max-height: 400px;
        }
        .history-item {
            padding: 8px;
            margin: 5px 0;
            background: #f8f9fa;
            border-radius: 6px;
            font-size: 11px;
            cursor: pointer;
            border-left: 3px solid #6c757d;
            transition: all 0.2s ease;
        }
        .history-item:hover {
            background: #e9ecef;
            transform: translateX(2px);
        }
        .history-item.active {
            background: #007bff;
            color: white;
            border-left-color: #0056b3;
        }

        /* Auth Styles */
        .auth-container {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .auth-form {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            width: 400px;
        }
        .auth-form h2 {
            text-align: center;
            margin-bottom: 20px;
            color: #333;
        }
        .auth-form input {
            width: 100%;
            padding: 12px;
            margin: 8px 0;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 14px;
        }
        .auth-form input:focus {
            outline: none;
            border-color: #007bff;
        }
        .auth-form button {
            width: 100%;
            padding: 12px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
        }
        .auth-form button:hover {
            background: #0056b3;
        }
        .auth-links {
            text-align: center;
            margin-top: 15px;
        }
        .auth-links a {
            color: #007bff;
            text-decoration: none;
        }
        .auth-links a:hover {
            text-decoration: underline;
        }
        .user-info {
            position: absolute;
            top: 20px;
            right: 20px;
            color: white;
            font-size: 14px;
        }
        .logout-btn {
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.3);
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            margin-left: 10px;
        }
        .logout-btn:hover {
            background: rgba(255, 255, 255, 0.3);
        }

        .setup-form {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .setup-form h3 {
            margin-bottom: 15px;
            color: #333;
        }

        .form-group {
            margin-bottom: 15px;
        }

        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }

        .form-group input {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }

        .setup-button {
            background: #28a745;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
        }

        .setup-button:hover {
            background: #218838;
        }

        .setup-button:disabled {
            background: #6c757d;
            cursor: not-allowed;
        }

        .user-info-panel {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 20px;
        }

        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            flex-wrap: wrap;
        }

        .apply-button, .save-button, .rollback-button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            color: white;
        }

        .apply-button {
            background: #28a745;
        }

        .apply-button:hover {
            background: #218838;
        }

        .save-button {
            background: #17a2b8;
        }

        .save-button:hover {
            background: #138496;
        }

        .rollback-button {
            background: #dc3545;
        }

        .rollback-button:hover {
            background: #c82333;
        }
    </style>
</head>
<body>
    <div id="app">
        <!-- Authentication Screens -->
        <div id="auth-screens" style="display: none;">
            <div class="auth-container">
                <div class="auth-form" id="login-form">
                    <h2>Login to AI Assistant</h2>
                    <input type="text" id="login-username" placeholder="Username" required>
                    <input type="password" id="login-password" placeholder="Password" required>
                    <button onclick="login()">Login</button>
                    <div class="auth-links">
                        <a href="#" onclick="showRegister()">Don't have an account? Register</a>
                        <br>
                        <a href="#" onclick="showForgotPassword()">Forgot Password?</a>
                    </div>
                </div>

                <div class="auth-form" id="register-form" style="display: none;">
                    <h2>Register for AI Assistant</h2>
                    <input type="text" id="register-username" placeholder="Username" required>
                    <input type="email" id="register-email" placeholder="Email" required>
                    <input type="password" id="register-password" placeholder="Password" required>
                    <button onclick="register()">Register</button>
                    <div class="auth-links">
                        <a href="#" onclick="showLogin()">Already have an account? Login</a>
                    </div>
                </div>

                <div class="auth-form" id="forgot-password-form" style="display: none;">
                    <h2>Reset Password</h2>
                    <input type="email" id="reset-email" placeholder="Enter your email" required>
                    <button onclick="forgotPassword()">Send Reset Instructions</button>
                    <div class="auth-links">
                        <a href="#" onclick="showLogin()">Back to Login</a>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Application -->
        <div id="main-app" style="display: none;">
            <div class="header">
                <h1>Multi-Project AI Assistant 🤖</h1>
                <div class="subtitle">Works with React and Ruby on Rails applications simultaneously!</div>
                <div class="user-info" id="user-info">
                    Welcome, <span id="username-display"></span>
                    <button class="logout-btn" onclick="logout()">Logout</button>
                </div>
            </div>

            <div class="container">
                <div class="chat-container">
                    <!-- Environment Setup Section -->
                    <div id="setup-section">
                        <div class="setup-form">
                            <h3>🚀 Setup Your Development Environment</h3>
                            <div class="form-group">
                                <label>React Port:</label>
                                <input type="number" id="react-port" placeholder="4000" min="3000" max="9999" value="4000">
                            </div>
                            <div class="form-group">
                                <label>Rails Port:</label>
                                <input type="number" id="rails-port" placeholder="3000" min="3000" max="9999" value="3000">
                            </div>
                            <div class="form-group">
                                <label>React App Name:</label>
                                <input type="text" id="react-path" placeholder="my-blue-app" value="my-blue-app">
                            </div>
                            <div class="form-group">
                                <label>Rails App Name:</label>
                                <input type="text" id="rails-path" placeholder="my_api_app" value="my_api_app">
                            </div>
                            <div class="form-group">
                                <label>Database Name:</label>
                                <input type="text" id="database-name" placeholder="user_app_development" value="user_app_development">
                                <small style="color: #666;">Will be automatically converted to user_{id}_app_development</small>
                            </div>
                            <button class="setup-button" id="setup-button" onclick="setupEnvironment()">Setup Environment</button>
                            <div id="setup-loader" class="setup-loader" style="display: none;">
                                <div class="loader"></div>
                                <p>Setting up your environment... This may take a few minutes.</p>
                            </div>
                        </div>
                    </div>

                    <!-- User Info Panel -->
                    <div id="user-info-panel" style="display: none;" class="user-info-panel">
                        <h4>Your Environment Details</h4>
                        <div id="user-setup-details"></div>
                    </div>

                    <div class="chat-messages" id="chat-messages">
                        <div class="message system-message">
                            Welcome! I can help you with both React and Ruby on Rails projects. What would you like to build?
                        </div>
                    </div>
                    <div class="input-area">
                        <div class="model-selector">
                            <label for="model-select">Select Model:</label>
                            <select id="model-select">
                                <option value="gpt-oss:20b-cloud">gpt-oss:20b-cloud</option>
                                <option value="gpt-oss:120b-cloud">gpt-oss:120b-cloud</option>
                                <option value="deepseek-v3.1:671b-cloud">deepseek-v3.1:671b-cloud</option>
                                <option value="qwen3-coder:480b-cloud" selected>qwen3-coder:480b-cloud</option>
                                <option value="kimi-k2:1t-cloud">kimi-k2:1t-cloud</option>
                            </select>
                        </div>
                        <div class="input-group">
                            <textarea
                                id="message-input"
                                placeholder="Describe what you want to build across your React and Rails projects (e.g., 'Add a contact form with API endpoint', 'Create user authentication system')..."
                                rows="3"
                            ></textarea>
                            <button id="send-button">Send</button>
                        </div>
                    </div>
                </div>

                <div class="results-panel">
                    <div class="projects-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <h3>Projects Info</h3>
                        <button class="rollback-button" onclick="rollbackChanges()">Rollback</button>
                    </div>

                    <div id="project-info">
                        <div class="file-item">Loading project information...</div>
                    </div>

                    <h3>Actions</h3>
                    <div class="action-buttons">
                        <button class="rollback-button" onclick="executeScript('rollback_migration_changes')">Rollback db changes</button>
                        <button class="apply-button" onclick="executeScript('migration_changes')">Db Migrate</button>
                        <button class="save-button" onclick="executeScript('restart_servers')">Restart all servers</button>
                        <button class="rollback-button" onclick="executeScript('reset_db')">Reset db changes</button>
                    </div>

                    <div id="user-app-links" style="margin-top: 15px;">
                        <!-- Dynamic app links will be inserted here -->
                    </div>

                    <h3>Chat History</h3>
                    <div class="history-container" id="history-container">
                        <div id="chat-history">
                            <div class="file-item">Loading history...</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let currentJsonResponse = '';
        let currentSessionId = '';
        let selectedConversationId = null;
        let currentUser = null;
        let currentToken = null;

        // Check if user is logged in on page load
        window.addEventListener('load', function() {
            const token = localStorage.getItem('authToken');
            const user = localStorage.getItem('currentUser');

            if (token && user) {
                currentToken = token;
                currentUser = JSON.parse(user);
                showMainApp();
            } else {
                showAuthScreens();
                showLogin();
            }
        });

        function showAuthScreens() {
            document.getElementById('auth-screens').style.display = 'block';
            document.getElementById('main-app').style.display = 'none';
        }

        function showMainApp() {
            document.getElementById('auth-screens').style.display = 'none';
            document.getElementById('main-app').style.display = 'block';
            document.getElementById('username-display').textContent = currentUser.username;

            // Initialize socket connection with auth
            if (socket.connected) {
                socket.disconnect();
            }
            socket.connect();
            socket.emit('authenticate', { token: currentToken, user_id: currentUser.id });

            // Check user setup status
            checkUserSetup();

            // Load user-specific data
            loadUserData();
        }

        function showLogin() {
            document.getElementById('login-form').style.display = 'block';
            document.getElementById('register-form').style.display = 'none';
            document.getElementById('forgot-password-form').style.display = 'none';
        }

        function showRegister() {
            document.getElementById('login-form').style.display = 'none';
            document.getElementById('register-form').style.display = 'block';
            document.getElementById('forgot-password-form').style.display = 'none';
        }

        function showForgotPassword() {
            document.getElementById('login-form').style.display = 'none';
            document.getElementById('register-form').style.display = 'none';
            document.getElementById('forgot-password-form').style.display = 'block';
        }

        async function login() {
            const username = document.getElementById('login-username').value;
            const password = document.getElementById('login-password').value;

            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json();

                if (response.ok) {
                    currentToken = data.token;
                    currentUser = data.user;
                    localStorage.setItem('authToken', currentToken);
                    localStorage.setItem('currentUser', JSON.stringify(currentUser));
                    showMainApp();
                } else {
                    alert(data.error || 'Login failed');
                }
            } catch (error) {
                alert('Login error: ' + error.message);
            }
        }

        async function register() {
            const username = document.getElementById('register-username').value;
            const email = document.getElementById('register-email').value;
            const password = document.getElementById('register-password').value;

            try {
                const response = await fetch('/api/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, email, password })
                });

                const data = await response.json();

                if (response.ok) {
                    alert('Registration successful! Please login.');
                    showLogin();
                } else {
                    alert(data.error || 'Registration failed');
                }
            } catch (error) {
                alert('Registration error: ' + error.message);
            }
        }

        function logout() {
            localStorage.removeItem('authToken');
            localStorage.removeItem('currentUser');
            currentToken = null;
            currentUser = null;
            socket.disconnect();
            showAuthScreens();
            showLogin();
        }

        // Environment setup functions
        function checkUserSetup() {
            fetch('/api/user-setup', {
                method: 'GET',
                headers: {
                    'Authorization': 'Bearer ' + currentToken,
                    'Content-Type': 'application/json'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.user_setup) {
                    // User has setup, show user info panel
                    document.getElementById('setup-section').style.display = 'none';
                    document.getElementById('user-info-panel').style.display = 'block';

                    const setupDetails = data.user_setup;
                    document.getElementById('user-setup-details').innerHTML = `
                        <p><strong>React App:</strong> Port ${setupDetails.react_port} - ${setupDetails.react_path}</p>
                        <p><strong>Rails API:</strong> Port ${setupDetails.rails_port} - ${setupDetails.rails_path}</p>
                        <p><strong>Database:</strong> ${setupDetails.database_name}</p>
                    `;

                    // Update app links
                    document.getElementById('user-app-links').innerHTML = `
                        <div class="react-app-section" style="margin: 10px 0;">
                            <a href="http://${window.location.hostname}:${setupDetails.react_port}/" target="_blank" style="
                                padding: 8px 16px;
                                background-color: #007bff;
                                color: white;
                                border: none;
                                border-radius: 4px;
                                cursor: pointer;
                                text-decoration: none;
                                display: inline-block;
                                font-size: 14px;
                                margin-right: 10px;
                            ">Open React App</a>
                            <a href="http://${window.location.hostname}:${setupDetails.rails_port}/" target="_blank" style="
                                padding: 8px 16px;
                                background-color: #dc3545;
                                color: white;
                                border: none;
                                border-radius: 4px;
                                cursor: pointer;
                                text-decoration: none;
                                display: inline-block;
                                font-size: 14px;
                            ">Open Rails API</a>
                        </div>
                    `;
                } else {
                    // User needs setup, show setup form
                    document.getElementById('setup-section').style.display = 'block';
                    document.getElementById('user-info-panel').style.display = 'none';
                }
            })
            .catch(error => {
                console.error('Error checking user setup:', error);
            });
        }

        function setupEnvironment() {
            const reactPort = document.getElementById('react-port').value;
            const railsPort = document.getElementById('rails-port').value;
            const reactPath = document.getElementById('react-path').value;
            const railsPath = document.getElementById('rails-path').value;
            let databaseName = document.getElementById('database-name').value;

            if (!reactPort || !railsPort || !reactPath || !railsPath || !databaseName) {
                alert('Please fill all fields');
                return;
            }

            // Show loader
            document.getElementById('setup-button').disabled = true;
            document.getElementById('setup-loader').style.display = 'block';

            fetch('/api/setup-environment', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + currentToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    react_port: parseInt(reactPort),
                    rails_port: parseInt(railsPort),
                    react_path: reactPath,
                    rails_path: railsPath,
                    database_name: databaseName
                })
            })
            .then(response => response.json())
            .then(data => {
                // Hide loader
                document.getElementById('setup-button').disabled = false;
                document.getElementById('setup-loader').style.display = 'none';

                if (data.message) {
                    alert(data.message);
                    checkUserSetup(); // Refresh the setup status
                } else {
                    alert(data.error || 'Setup failed');
                }
            })
            .catch(error => {
                console.error('Error setting up environment:', error);
                // Hide loader
                document.getElementById('setup-button').disabled = false;
                document.getElementById('setup-loader').style.display = 'none';
                alert('Setup failed: ' + error.message);
            });
        }

        function executeScript(scriptName) {
            if (!confirm(`Are you sure you want to execute ${scriptName}?`)) {
                return;
            }

            fetch('/api/execute-script', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + currentToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    script_name: scriptName
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.message) {
                    alert(data.message);
                    if (data.output) {
                        console.log('Script output:', data.output);
                    }
                } else {
                    alert(data.error || 'Script execution failed');
                    if (data.stderr) {
                        console.error('Script error:', data.stderr);
                    }
                }
            })
            .catch(error => {
                console.error('Error executing script:', error);
                alert('Script execution failed: ' + error.message);
            });
        }

        function loadUserData() {
            // Load project info
            socket.emit('get_project_info', { user_id: currentUser.id });

            // Load chat history
            socket.emit('get_user_conversations', { user_id: currentUser.id });
        }

        // Chat functionality
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        const chatMessages = document.getElementById('chat-messages');

        sendButton.addEventListener('click', sendMessage);

        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        function sendMessage() {
            const message = messageInput.value.trim();
            const selectedModel = document.getElementById('model-select').value;

            if (message) {
                addMessage('user', message);
                messageInput.value = '';

                // Show typing indicator
                showTypingIndicator();

                // Send to server with selected model and user info
                socket.emit('send_message', {
                    message: message,
                    model: selectedModel,
                    user_id: currentUser.id
                });

                // Disable input while processing
                sendButton.disabled = true;
                messageInput.disabled = true;
            }
        }

        function addMessage(sender, content) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${sender}-message`;

            if (sender === 'user') {
                messageDiv.innerHTML = `<strong>You:</strong> ${content}`;
            } else {
                messageDiv.innerHTML = `<strong>Assistant:</strong> ${content}`;
            }

            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function showTypingIndicator() {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message assistant-message loading-message';
            typingDiv.id = 'typing-indicator';
            typingDiv.innerHTML = `<div class="loader"></div>Assistant is thinking...`;
            chatMessages.appendChild(typingDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function hideTypingIndicator() {
            const typingIndicator = document.getElementById('typing-indicator');
            if (typingIndicator) {
                typingIndicator.remove();
            }
        }

        function rollbackChanges() {
            if (!confirm('Are you sure you want to rollback all changes? This will revert all uncommitted changes.')) {
                return;
            }
            socket.emit('rollback_changes', { user_id: currentUser.id });
        }

        // Socket event handlers
        socket.on('connect', function() {
            console.log('Connected to server');
            currentSessionId = socket.id;
        });

        socket.on('authenticated', function(data) {
            console.log('Socket authenticated for user:', data.user_id);
        });

        socket.on('assistant_response', function(data) {
            hideTypingIndicator();

            // Format JSON response for better readability
            let formattedResponse = data.json_response;
            if (typeof formattedResponse === 'object') {
                formattedResponse = JSON.stringify(formattedResponse, null, 2);
            }

            addMessage('assistant', `\`\`\`json
            ${formattedResponse}
            \`\`\``);



            // Re-enable input
            sendButton.disabled = false;
            messageInput.disabled = false;
            messageInput.focus();
        });

        socket.on('project_info', function(data) {
            const projectInfo = document.getElementById('project-info');
            if (data.projects && data.projects.length > 0) {
                let html = '';
                data.projects.forEach(project => {
                    html += `
                        <div class="project-item project-${project.type}">
                            <strong>${project.type.toUpperCase()} Project</strong><br>
                            <small>Path: ${project.root}</small><br>
                            <small>Files: ${project.file_count}</small>
                        </div>
                    `;
                });
                projectInfo.innerHTML = html;
            } else {
                projectInfo.innerHTML = '<div class="file-item">No projects found. Please setup your environment first.</div>';
            }
        });

        socket.on('user_conversations', function(data) {
            const chatHistory = document.getElementById('chat-history');
            if (data.conversations && data.conversations.length > 0) {
                let html = '';
                data.conversations.forEach(conv => {
                    const date = new Date(conv.created_at).toLocaleString();
                    html += `
                        <div class="history-item" onclick="toggleConversation(${conv.id})">
                            <strong>${date}</strong><br>
                            <small>${conv.query.substring(0, 50)}...</small>
                            <div class="history-actions">
                                <button class="apply-button" onclick="event.stopPropagation(); applyConversation(${conv.id})">Apply</button>
                                <button class="save-button" onclick="event.stopPropagation(); saveConversation(${conv.id})">Save</button>
                            </div>
                        </div>
                    `;
                });
                chatHistory.innerHTML = html;
            } else {
                chatHistory.innerHTML = '<div class="file-item">No conversation history yet.</div>';
            }
        });

        socket.on('error', function(data) {
            hideTypingIndicator();
            addMessage('system', `❌ Error: ${data.error}`);

            // Re-enable input
            sendButton.disabled = false;
            messageInput.disabled = false;
            messageInput.focus();
        });

        // Conversation management functions
        function toggleConversation(conversationId) {
            // Implementation for toggling conversation details
            console.log('Toggle conversation:', conversationId);
        }

        function applyConversation(conversationId) {
            if (!confirm('Apply this conversations changes?')) {
                return;
            }
            // Implementation for applying conversation changes
            console.log('Apply conversation:', conversationId);
        }

        function saveConversation(conversationId) {
            if (!confirm('Save this conversations changes to git?')) {
                return;
            }
            // Implementation for saving conversation changes
            console.log('Save conversation:', conversationId);
        }
    </script>
</body>
</html>
            '''

        # Authentication routes
        @self.app.route('/api/register', methods=['POST'])
        def register():
            try:
                data = request.get_json()
                username = data.get('username')
                email = data.get('email')
                password = data.get('password')

                if not all([username, email, password]):
                    return jsonify({'error': 'All fields are required'}), 400

                user_id = PostgresDB(**(self.db_config or {})).create_user(username, email, password)
                if user_id:
                    return jsonify({'message': 'User registered successfully', 'user_id': user_id}), 201
                else:
                    return jsonify({'error': 'Username or email already exists'}), 400
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/login', methods=['POST'])
        def login():
            try:
                data = request.get_json()
                username = data.get('username')
                password = data.get('password')

                if not all([username, password]):
                    return jsonify({'error': 'Username and password are required'}), 400

                user = PostgresDB(**(self.db_config or {})).authenticate_user(username, password)
                if user:
                    # Generate JWT token
                    token = jwt.encode({
                        'user_id': user['id'],
                        'username': user['username'],
                        'exp': datetime.utcnow() + Config.JWT_ACCESS_TOKEN_EXPIRES
                    }, Config.JWT_SECRET_KEY, algorithm='HS256')

                    return jsonify({
                        'message': 'Login successful',
                        'token': token,
                        'user': {
                            'id': user['id'],
                            'username': user['username'],
                            'email': user['email']
                        }
                    }), 200
                else:
                    return jsonify({'error': 'Invalid credentials'}), 401
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/forgot-password', methods=['POST'])
        def forgot_password():
            try:
                data = request.get_json()
                email = data.get('email')

                if not email:
                    return jsonify({'error': 'Email is required'}), 400

                user = PostgresDB(**(self.db_config or {})).get_user_by_email(email)
                if user:
                    # Generate reset token (in a real app, send email)
                    reset_token = str(uuid.uuid4())
                    expires_at = datetime.utcnow() + timedelta(hours=1)

                    if PostgresDB(**(self.db_config or {})).store_password_reset_token(user['id'], reset_token, expires_at):
                        # In production, send email with reset link
                        reset_link = f"http://{self.host}:{self.port}/reset-password?token={reset_token}"
                        print(f"Password reset link: {reset_link}")  # For development

                        return jsonify({
                            'message': 'Password reset instructions sent to your email',
                            'reset_token': reset_token  # Only for development
                        }), 200
                    else:
                        return jsonify({'error': 'Failed to generate reset token'}), 500
                else:
                    return jsonify({'error': 'Email not found'}), 404
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/reset-password', methods=['POST'])
        def reset_password():
            try:
                data = request.get_json()
                token = data.get('token')
                new_password = data.get('new_password')

                if not all([token, new_password]):
                    return jsonify({'error': 'Token and new password are required'}), 400

                # Validate token
                token_data = PostgresDB(**(self.db_config or {})).validate_reset_token(token)
                if token_data:
                    # Update password
                    if PostgresDB(**(self.db_config or {})).update_user_password(token_data['user_id'], new_password):
                        # Mark token as used
                        PostgresDB(**(self.db_config or {})).mark_token_used(token)
                        return jsonify({'message': 'Password reset successfully'}), 200
                    else:
                        return jsonify({'error': 'Failed to reset password'}), 500
                else:
                    return jsonify({'error': 'Invalid or expired token'}), 400
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/save-projects', methods=['POST'])
        @token_required
        def save_projects(current_user):
            try:
                data = request.get_json()
                frontend_path = data.get('frontend_path')
                backend_path = data.get('backend_path')

                if not frontend_path or not backend_path:
                    return jsonify({'error': 'Both frontend and backend paths are required'}), 400

                if PostgresDB(**(self.db_config or {})).save_user_projects(current_user, frontend_path, backend_path):
                    return jsonify({'message': 'Project paths saved successfully'}), 200
                else:
                    return jsonify({'error': 'Failed to save project paths'}), 500
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/get-projects', methods=['GET'])
        @token_required
        def get_projects(current_user):
            try:
                projects = PostgresDB(**(self.db_config or {})).get_user_projects(current_user)
                return jsonify({'projects': projects}), 200
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/setup-environment', methods=['POST'])
        @token_required
        def setup_environment(current_user):
            try:
                data = request.get_json()
                react_port = data.get('react_port')
                rails_port = data.get('rails_port')
                react_path = data.get('react_path')
                rails_path = data.get('rails_path')
                database_name = data.get('database_name')

                if not all([react_port, rails_port, react_path, rails_path, database_name]):
                    return jsonify({'error': 'All fields are required'}), 400

                # Generate database name based on user ID if not provided
                if not database_name or database_name == 'user_app_development':
                    database_name = f"user_{current_user}_app_development"

                # Setup user environment
                result = self.env_manager.setup_user_environment(
                    current_user, react_port, rails_port, react_path, rails_path, database_name
                )

                if result['success']:
                    # Update user assistant with new paths
                    if current_user in self.user_assistants:
                        del self.user_assistants[current_user]

                    return jsonify({
                        'message': result['message'],
                        'setup_details': {
                            'react_port': react_port,
                            'rails_port': rails_port,
                            'react_path': result['react_path'],
                            'rails_path': result['rails_path'],
                            'database_name': database_name
                        }
                    }), 200
                else:
                    return jsonify({'error': result['error']}), 400

            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/user-setup', methods=['GET'])
        @token_required
        def get_user_setup(current_user):
            try:
                user_setup = PostgresDB(**(self.db_config or {})).get_user_setup(current_user)
                return jsonify({'user_setup': user_setup}), 200
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/execute-script', methods=['POST'])
        @token_required
        def execute_script(current_user):
            try:
                data = request.get_json()
                script_name = data.get('script_name')  # reset_db, migrate, restart_servers, etc.

                if not script_name:
                    return jsonify({'error': 'Script name is required'}), 400

                result = self.env_manager.execute_user_script(current_user, script_name)

                if result['success']:
                    return jsonify({
                        'message': f'Script {script_name} executed successfully',
                        'output': result['stdout']
                    }), 200
                else:
                    return jsonify({'error': result['error'], 'stderr': result['stderr']}), 400

            except Exception as e:
                return jsonify({'error': str(e)}), 500

        # Socket event handlers
        @self.socketio.on('authenticate')
        def handle_authenticate(data):
            session_id = request.sid
            user_id = data.get('user_id')
            token = data.get('token')

            # Store session
            self.sessions[session_id] = {
                'user_id': user_id,
                'authenticated': True
            }

            # Create user-specific assistant instance
            assistant = self.get_user_assistant(user_id)

            emit('authenticated', {'user_id': user_id, 'session_id': session_id})

        @self.socketio.on('connect')
        def handle_connect():
            session_id = request.sid
            self.sessions[session_id] = {
                'current_json': '',
                'user_id': None,
                'authenticated': False
            }
            print(f"✅ Client connected: {session_id}")

        @self.socketio.on('send_message')
        def handle_message(data):
            @copy_current_request_context
            def process_message():
                try:
                    query = data['message']
                    model_name = data.get('model', 'qwen3-coder:480b-cloud')
                    session_id = request.sid
                    user_id = data.get('user_id')

                    # Check authentication
                    session_data = self.sessions.get(session_id, {})
                    if not session_data.get('authenticated') and user_id:
                        # Authenticate on first message if user_id provided
                        self.sessions[session_id] = {
                            'user_id': user_id,
                            'authenticated': True
                        }

                    print(f"📨 Processing query from user {user_id}: '{query}'")
                    print(f"🤖 Using model: {model_name}")

                    # Get user-specific assistant
                    assistant = self.get_user_assistant(user_id)

                    # Set the model before processing
                    assistant.set_model(model_name)

                    # Process the query using auto-generate mode with user context
                    json_response = assistant.process_query(query, user_id, session_id, use_auto_generate=True)

                    # Store the JSON response in session
                    self.sessions[session_id] = {'current_json': json_response, 'user_id': user_id}

                    # Send response back to client
                    emit('assistant_response', {
                        'json_response': json_response,
                        'session_id': session_id,
                        'model_used': model_name,
                        'execution_time': json_response.get('execution_time')
                    }, room=session_id)

                    # Refresh conversation history for this user
                    if user_id:
                        user_conversations = assistant.db.get_conversation_history(user_id, 50)
                        emit('user_conversations', {'conversations': user_conversations}, room=session_id)

                except Exception as e:
                    print(f"❌ Error processing message: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            # Run in thread to avoid blocking
            thread = threading.Thread(target=process_message)
            thread.daemon = True
            thread.start()

        @self.socketio.on('apply_changes')
        def handle_apply_changes(data):
            @copy_current_request_context
            def apply_changes_thread():
                try:
                    json_response = data['json_response']
                    session_id = request.sid
                    conversation_id = data.get('conversation_id')
                    user_id = data.get('user_id')
                    print(f"🔄 Applying changes from JSON response (Conversation ID: {conversation_id})...")

                    # Get user-specific assistant
                    assistant = self.get_user_assistant(user_id)

                    # Apply changes using existing logic
                    results = assistant.apply_changes(json_response)

                    # Store application results in PostgreSQL
                    if conversation_id and user_id:
                        # Update the specific conversation for this user
                        assistant.db.update_application_results(conversation_id, results)
                    else:
                        # For new conversations, update the latest one for this user
                        if user_id:
                            recent_conversations = assistant.db.get_conversation_history(user_id, 1)
                            if recent_conversations:
                                latest_conv = recent_conversations[0]
                                assistant.db.update_application_results(latest_conv['id'], results)

                    # Send results back to client
                    emit('application_results', {
                        'results': results,
                        'session_id': session_id
                    }, room=session_id)

                    # Refresh project info
                    project_info = assistant.get_project_info()
                    emit('project_info', project_info, room=session_id)

                except Exception as e:
                    print(f"❌ Error applying changes: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=apply_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('get_user_conversations')
        def handle_get_user_conversations(data):
            session_id = request.sid
            user_id = data.get('user_id')
            if user_id:
                assistant = self.get_user_assistant(user_id)
                user_conversations = assistant.db.get_conversation_history(user_id, 100)
                print(f"📤 Sending user conversations to client {session_id}: {len(user_conversations)} total")
                emit('user_conversations', {'conversations': user_conversations}, room=session_id)

        @self.socketio.on('get_project_info')
        def handle_get_project_info(data=None):
            session_id = request.sid
            user_id = data.get('user_id') if data else None

            if user_id:
                assistant = self.get_user_assistant(user_id)
                project_info = assistant.get_project_info()
                emit('project_info', project_info, room=session_id)
            else:
                emit('project_info', {'user_id': None, 'projects': []}, room=session_id)

    def run(self):
        """Start the web server"""
        print(f"🚀 Starting Multi-Project AI Assistant Web UI...")
        print(f"📁 Default Projects: {self.project_paths}")
        print(f"🌐 Web interface: http://{self.host}:{self.port}")
        print("💡 Open the above URL in your browser to start chatting!")
        print("🗄️  PostgreSQL database is active and storing all conversations")
        print("🎯 Using INTENT-AWARE AUTO-GENERATE mode with dynamic file finding across projects")
        print("🤖 Available models:", OllamaAnalyzer().get_available_models())
        print("🔐 Authentication system enabled")
        print("👥 Multi-user environment support enabled")
        print("🔑 User-specific project isolation in Redis")

        self.socketio.run(self.app, host=self.host, port=self.port, debug=True, allow_unsafe_werkzeug=True)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Multi-Project AI Assistant')
    parser.add_argument('project_paths', nargs='+', help='Paths to project directories (React and/or Rails)')
    parser.add_argument('--redis-host', default='localhost', help='Redis host')
    parser.add_argument('--redis-port', default=6379, type=int, help='Redis port')
    parser.add_argument('--ollama-url', default='http://localhost:11434', help='Ollama server URL')
    parser.add_argument('--host', default='0.0.0.0', help='Web server host')
    parser.add_argument('--port', default=5000, type=int, help='Web server port')

    # PostgreSQL configuration
    parser.add_argument('--db-host', default='localhost', help='PostgreSQL host')
    parser.add_argument('--db-port', default=5432, type=int, help='PostgreSQL port')
    parser.add_argument('--db-name', default='multi_project_ai_assistant_json', help='PostgreSQL database name')
    parser.add_argument('--db-user', default='postgres', help='PostgreSQL username')
    parser.add_argument('--db-password', default='root', help='PostgreSQL password')

    args = parser.parse_args()

    # Validate project paths
    for project_path in args.project_paths:
        if not os.path.exists(project_path):
            print(f"❌ Error: Project path '{project_path}' does not exist!")
            return

    # PostgreSQL configuration
    db_config = {
        'host': args.db_host,
        'port': args.db_port,
        'dbname': args.db_name,
        'user': args.db_user,
        'password': args.db_password
    }

    # Use the web interface
    chatbot = MultiProjectAIChatbotWebUI(
        args.project_paths,
        args.redis_host,
        args.redis_port,
        args.ollama_url,
        args.host,
        args.port,
        db_config
    )
    chatbot.run()

if __name__ == "__main__":
    main()