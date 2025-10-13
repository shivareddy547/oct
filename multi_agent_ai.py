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
from flask import Flask, request, jsonify, copy_current_request_context
from flask_socketio import SocketIO, emit
import threading
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import math
from difflib import SequenceMatcher

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

# PostgreSQL Database Manager (Updated for multi-project)
class PostgresDB:
    def __init__(self, dbname='multi_project_ai_assistant', user='postgres', password='root',
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

            # Create conversations table with project_type
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    query TEXT NOT NULL,
                    yaml_response TEXT NOT NULL,
                    project_type VARCHAR(50) NOT NULL,
                    project_paths JSONB NOT NULL,
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

    def store_conversation(self, session_id: str, query: str, yaml_response: str, project_paths: List[str]) -> int:
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
                INSERT INTO conversations (session_id, query, yaml_response, project_type, project_paths)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (session_id, query, yaml_response, project_type, json.dumps(project_paths)))

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

    def get_conversation_history(self, session_id: str, limit: int = 50) -> List[Dict]:
        """Get conversation history for a session"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get conversation history - no database connection")
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_type, project_paths, created_at, applied_at
                FROM conversations
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (session_id, limit))

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

    def get_all_conversations(self, limit: int = 100) -> List[Dict]:
        """Get all conversations across all sessions"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get all conversations - no database connection")
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_type, project_paths, created_at, applied_at
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

    def get_conversation_by_id(self, conversation_id: int) -> Optional[Dict]:
        """Get a specific conversation by ID"""
        conn = self.get_connection()
        if not conn:
            print("❌ Failed to get conversation by ID - no database connection")
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_type, project_paths, created_at, applied_at
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

    def store_project_structure(self, project_paths: List[str], project_id: str = "default"):
        """Store multiple project structures in Redis"""
        if not self.redis_client:
            print("❌ Redis not available, skipping project storage")
            return {}

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
            'projects': all_project_data
        }))

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

    def get_project_structure(self, project_id: str = "default") -> Optional[Dict]:
        """Get main project structure from Redis"""
        if not self.redis_client:
            return None

        main_structure_key = f"{self.project_key_prefix}{project_id}:main_structure"
        structure_data = self.redis_client.get(main_structure_key)
        if structure_data:
            return json.loads(structure_data)
        return None

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
        yaml_output = self.analyze_and_generate_changes(user_query, project_context, project_roots, intent)
        return yaml_output

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

    def analyze_and_generate_changes(self, prompt: str, project_context: str, project_roots: List[str], intent: Dict[str, bool]) -> str:
        """Use Ollama to analyze projects and generate specific file changes for multiple projects"""
        print(f"Analyzing {len(project_roots)} projects for: {prompt}")
        print(f"Intent: Frontend: {intent['frontend']}, Backend: {intent['backend']}")
        print(f"Using model: {self.model}")
        print(11111111111111111111)
        print(project_roots)

        # Find which projects are React and which are Rails
        react_projects = [p for p in project_roots if any(x in p.lower() for x in ['react', 'src/', 'components/'])]
        rails_projects = [p for p in project_roots if any(x in p.lower() for x in ['rails', 'app/', 'config/', 'db/'])]
        react_projects = ['my-blue-app/']
        rails_projects = ['my_api_app/']
        print(react_projects)
        print(rails_projects)
        print(333333333333)

        # If we can't determine, assume first is React, second is Rails
        if not react_projects and not rails_projects:
            if len(project_roots) >= 2:
                react_projects = [project_roots[0]]
                rails_projects = [project_roots[1]]
            else:
                react_projects = project_roots
                rails_projects = []

        print(react_projects)
        system_prompt = f"""You are an expert full-stack developer working with both React.js and Ruby on Rails applications.
Analyze the user's request and the current project structures, then provide ONLY the specific file changes and required packages in YAML format.

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

Respond ONLY with valid YAML in this exact format:

projects:
  - project_path: "{react_projects[0] if react_projects else '.'}"
    project_type: "react"
    files:
      - path: "src/components/Component.js"
        content: |
          // Full file content with changes
          import React from 'react';

          const Component = () => {{
            return <div>Content</div>;
          }};

          export default Component;

  - project_path: "{rails_projects[0] if rails_projects else ''}"
    project_type: "rails"
    files:
      - path: "app/controllers/some_controller.rb"
        content: |
          class SomeController < ApplicationController
            def index
              # Controller code here
            end
          end

packages:
  react_dependencies:
    - "package-name@version"
  react_devDependencies:
    - "@types/package@version"
  rails_gems:
    - "gem-name"

install_commands:
  - "cd {react_projects[0] if react_projects else '.'} && npm install package-name@version"
  - "cd {rails_projects[0] if rails_projects else '.'} && bundle add gem-name"

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

Do not include any explanations, analysis, or text outside the YAML format."""

        full_prompt = f"""MULTI-PROJECT CONTEXT:
{project_context}

USER REQUEST: {prompt}

QUERY INTENT:
- Frontend changes needed: {intent['frontend']}
- Backend changes needed: {intent['backend']}
- Fullstack feature: {intent['fullstack']}

Generate the appropriate file changes and required packages in YAML format:"""

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
            return response.json()["response"]
        except requests.exceptions.Timeout:
            return "Error: Request timeout - Ollama server took too long to respond"
        except Exception as e:
            return f"Error: {e}"

class MultiProjectAIAssistant:
    def __init__(self, project_paths: List[str], redis_host='localhost', redis_port=6379,
                 db_config=None):
        self.project_paths = project_paths
        self.redis_manager = MultiProjectRedisManager(redis_host, redis_port)
        self.ollama = OllamaAnalyzer()
        self.project_id = hashlib.md5("_".join(project_paths).encode()).hexdigest()[:8]

        # Initialize PostgreSQL database
        self.db = PostgresDB(**(db_config or {}))

    def set_model(self, model_name: str):
        """Set the model for the Ollama analyzer"""
        self.ollama.set_model(model_name)

    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        return self.ollama.get_available_models()

    def initialize_projects(self):
        """Initialize and store all projects in Redis"""
        print("🔍 Scanning and storing multiple project structures in Redis...")
        project_data = self.redis_manager.store_project_structure(self.project_paths, self.project_id)

        total_files = 0
        for project_key, data in project_data.items():
            file_count = len(data['files'])
            total_files += file_count
            print(f"✅ {data['project_type'].upper()} Project stored: {data['project_root']} with {file_count} files")

        print(f"🎉 All projects stored in Redis with {total_files} total files (Project ID: {self.project_id})")
        return project_data

    def extract_yaml_from_response(self, response: str) -> str:
        """Extract YAML content from Ollama response"""
        # Try to find YAML content between markers
        yaml_match = re.search(r'```yaml\n(.*?)\n```', response, re.DOTALL)
        if yaml_match:
            return yaml_match.group(1)

        # Try to find YAML content without markers
        yaml_match = re.search(r'^(projects:|files:|packages:|install_commands:)', response, re.MULTILINE)
        if yaml_match:
            return response

        # If no YAML found, return the original response wrapped in proper YAML structure
        return f'''projects:
  - project_path: "{self.project_paths[0]}"
    project_type: "unknown"
    files:
      - path: "response.txt"
        content: |
          {response}

packages:
  react_dependencies: []
  react_devDependencies: []
  rails_gems: []

install_commands:
  - "echo 'No additional packages required'"'''

    def validate_and_complete_yaml(self, yaml_content: str) -> str:
        """Validate YAML and ensure all required sections are present"""
        try:
            data = yaml.safe_load(yaml_content)

            # Ensure projects section exists
            if 'projects' not in data:
                data['projects'] = [{
                    'project_path': self.project_paths[0],
                    'project_type': 'unknown',
                    'files': []
                }]

            # Ensure packages section exists with proper structure
            if 'packages' not in data:
                data['packages'] = {
                    'react_dependencies': [],
                    'react_devDependencies': [],
                    'rails_gems': []
                }
            else:
                if 'react_dependencies' not in data['packages']:
                    data['packages']['react_dependencies'] = []
                if 'react_devDependencies' not in data['packages']:
                    data['packages']['react_devDependencies'] = []
                if 'rails_gems' not in data['packages']:
                    data['packages']['rails_gems'] = []

            # Ensure install_commands section exists
            if 'install_commands' not in data:
                data['install_commands'] = []

                # Generate install commands from packages if not provided
                react_deps = data['packages']['react_dependencies']
                react_dev_deps = data['packages']['react_devDependencies']
                rails_gems = data['packages']['rails_gems']

                # Find project paths for each type
                print(self.project_paths)
                print(2222222222222222222222)
                react_projects = [p for p in self.project_paths if 'react' in p.lower() or not any('rails' in rp.lower() for rp in self.project_paths)]
                rails_projects = [p for p in self.project_paths if 'rails' in p.lower()]

                if react_deps and react_projects:
                    for project in react_projects:
                        data['install_commands'].append(f"cd {project} && npm install {' '.join(react_deps)}")
                if react_dev_deps and react_projects:
                    for project in react_projects:
                        data['install_commands'].append(f"cd {project} && npm install --save-dev {' '.join(react_dev_deps)}")
                if rails_gems and rails_projects:
                    for project in rails_projects:
                        for gem in rails_gems:
                            data['install_commands'].append(f"cd {project} && bundle add {gem}")
                        data['install_commands'].append(f"cd {project} && bundle install")

                if not react_deps and not react_dev_deps and not rails_gems:
                    data['install_commands'].append("echo 'No additional packages required'")

            return yaml.dump(data, default_flow_style=False, indent=2, allow_unicode=True, width=1000)

        except yaml.YAMLError as e:
            # Return a basic valid YAML structure with the error
            return f'''projects:
  - project_path: "{self.project_paths[0]}"
    project_type: "unknown"
    files:
      - path: "error.txt"
        content: |
          Invalid YAML response: {e}
          Original response: {yaml_content}

packages:
  react_dependencies: []
  react_devDependencies: []
  rails_gems: []

install_commands:
  - "echo 'Error in YAML generation'"'''

    def apply_changes(self, yaml_response: str) -> Dict:
        """Apply changes from LLM YAML response to project files."""
        try:
            data = yaml.safe_load(yaml_response)
            results = {
                'files_created': [],
                'files_updated': [],
                'files_failed': [],
                'packages_installed': False,
                'install_output': []
            }

            projects = data.get('projects', [])

            for project_info in projects:
                # Determine project_path and project_type
                project_path = project_info.get('project_path')
                project_type = project_info.get('project_type', 'unknown')

                # Sometimes LLM nests project_path/type under first file
                if not project_path and 'files' in project_info and len(project_info['files']) > 0:
                    project_path = project_info['files'][0].get('project_path')
                    project_type = project_info['files'][0].get('project_type', project_type)

                if not project_path:
                    # fallback to first known project path
                    project_path = self.project_paths[0]

                print(f"🔄 Applying changes to project: {project_path} (type: {project_type})")

                for file_info in project_info.get('files', []):
                    file_path = file_info.get('path')
                    content = file_info.get('content', '')

                    # Decode escaped newlines (\n) into real newlines
                    content = content.encode('utf-8').decode('unicode_escape')

                    # Determine full file path
                    if "db/migrate/" in file_path:
                        from datetime import datetime
                        import re
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        base_name = os.path.basename(file_path)
                        base_name = re.sub(r'^\d+_', '', base_name)
                        base_name = re.sub(r'[^a-z0-9_]', '_', base_name.lower())
                        full_path = os.path.join(project_path, "db/migrate", f"{timestamp}_{base_name}")
                    else:
                        full_path = os.path.join(project_path, file_path)

                    try:
                        os.makedirs(os.path.dirname(full_path), exist_ok=True)
                        file_exists = os.path.exists(full_path)

                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write(content)

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

            # Handle package installation (optional)
            if 'install_commands' in data and data['install_commands']:
                for command in data['install_commands']:
                    # Run command logic (same as before)
                    pass  # keep your existing install logic

            # Update Redis cache with new file structure
            self.redis_manager.store_project_structure(self.project_paths, self.project_id)

            return results

        except Exception as e:
            return {
                'files_created': [],
                'files_updated': [],
                'files_failed': [f"Application error: {str(e)}"],
                'packages_installed': False,
                'install_output': [f"Application error: {str(e)}"]
            }


    def process_query(self, query: str, session_id: str = "default", use_auto_generate: bool = True) -> str:
        """Process user query and return YAML response"""
        print(f"🔄 Processing: {query}")
        print(f"🤖 Using model: {self.ollama.model}")

        if use_auto_generate:
            # Use the new auto-generate approach with dynamic file finding across all projects
            yaml_response = self.ollama.auto_generate_file_changes(query, self.project_paths)
        else:
            # For multi-project, we'll use auto-generate as default
            yaml_response = self.ollama.auto_generate_file_changes(query, self.project_paths)

        # Validate and complete the YAML structure
        final_yaml = self.validate_and_complete_yaml(yaml_response)

        # Store conversation in PostgreSQL
        conversation_id = self.db.store_conversation(session_id, query, final_yaml, self.project_paths)

        if conversation_id == -1:
            print("❌ Failed to store conversation in database!")
        else:
            print(f"✅ Successfully stored conversation with ID: {conversation_id}")

        return final_yaml

    def get_project_info(self) -> Dict:
        """Get project information for all projects"""
        structure = self.redis_manager.get_project_structure(self.project_id)
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
                'total_projects': len(projects_info),
                'projects': projects_info
            }
        return {}

# Web-based Chatbot UI (Updated for multi-project)
class MultiProjectAIChatbotWebUI:
    def __init__(self, project_paths: List[str], redis_host='localhost', redis_port=6379,
                 ollama_url='http://localhost:11434', host='0.0.0.0', port=5000,
                 db_config=None):
        self.assistant = MultiProjectAIAssistant(project_paths, redis_host, redis_port, db_config)
        self.assistant.ollama.base_url = ollama_url
        self.host = host
        self.port = port

        # Initialize Flask app
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'multi-project-ai-assistant-secret-key'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # Store sessions
        self.sessions = {}

        self.setup_routes()

        # Initialize assistant
        self.initialize_assistant()

    def initialize_assistant(self):
        """Initialize the assistant with all projects"""
        try:
            project_data = self.assistant.initialize_projects()
            project_info = self.assistant.get_project_info()
            print(f"✅ All projects initialized: {project_info}")
        except Exception as e:
            print(f"❌ Error initializing projects: {e}")

    def setup_routes(self):
        """Setup Flask routes"""
        HTML_TEMPLATE = '''
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
        .intent-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: bold;
            margin: 2px;
        }
        .intent-frontend {
            background: #61dafb;
            color: #000;
        }
        .intent-backend {
            background: #cc0000;
            color: white;
        }
        .intent-fullstack {
            background: #6f42c1;
            color: white;
        }
        .project-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: bold;
            margin-right: 8px;
        }
        .badge-react {
            background: #61dafb;
            color: #000;
        }
        .badge-rails {
            background: #cc0000;
            color: white;
        }
        .badge-unknown {
            background: #6c757d;
            color: white;
        }
        .code-container {
            background: #1e1e1e;
            border: 1px solid #333;
            border-radius: 8px;
            margin-top: 10px;
            overflow: hidden;
        }
        .code-header {
            background: #2d2d2d;
            padding: 8px 12px;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: #ccc;
        }
        .code-content {
            padding: 15px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.4;
            overflow-x: auto;
            background: #1e1e1e;
            color: #d4d4d4;
        }
        .yaml-key { color: #9cdcfe; }
        .yaml-string { color: #ce9178; }
        .yaml-number { color: #b5cea8; }
        .yaml-boolean { color: #569cd6; }
        .yaml-null { color: #569cd6; }
        .yaml-comment { color: #6a9955; font-style: italic; }
        .copy-button {
            background: #007bff;
            color: white;
            border: none;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
        }
        .copy-button:hover {
            background: #0056b3;
        }
        .copy-button.copied {
            background: #28a745;
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
        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            flex-wrap: wrap;
        }
        .apply-button {
            background: #28a745;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: background 0.3s;
        }
        .apply-button:hover {
            background: #218838;
        }
        .save-button {
            background: #17a2b8;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: background 0.3s;
        }
        .save-button:hover {
            background: #138496;
        }
        .rollback-button {
            background: #dc3545;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: background 0.3s;
        }
        .rollback-button:hover {
            background: #c82333;
        }
        .load-response-button {
            background: #6f42c1;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: background 0.3s;
        }
        .load-response-button:hover {
            background: #5a359c;
        }
        .typing-indicator {
            display: inline-block;
            padding: 10px 15px;
            background: white;
            border-radius: 15px;
            color: #6c757d;
            font-style: italic;
        }
        .dot-flashing {
            position: relative;
            width: 10px;
            height: 10px;
            border-radius: 5px;
            background-color: #007bff;
            color: #007bff;
            animation: dotFlashing 1s infinite linear alternate;
            animation-delay: 0.5s;
            display: inline-block;
            margin-left: 5px;
        }
        .dot-flashing::before, .dot-flashing::after {
            content: '';
            display: inline-block;
            position: absolute;
            top: 0;
        }
        .dot-flashing::before {
            left: -15px;
            width: 10px;
            height: 10px;
            border-radius: 5px;
            background-color: #007bff;
            color: #007bff;
            animation: dotFlashing 1s infinite alternate;
            animation-delay: 0s;
        }
        .dot-flashing::after {
            left: 15px;
            width: 10px;
            height: 10px;
            border-radius: 5px;
            background-color: #007bff;
            color: #007bff;
            animation: dotFlashing 1s infinite alternate;
            animation-delay: 1s;
        }
        @keyframes dotFlashing {
            0% { background-color: #007bff; }
            50%, 100% { background-color: #bee3f8; }
        }
        .results-panel {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            width: 400px;
            max-height: 700px;
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
        .history-yaml {
            display: none;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 10px;
            margin-top: 5px;
            font-family: 'Courier New', monospace;
            font-size: 10px;
            white-space: pre-wrap;
            color: #856404;
            max-height: 200px;
            overflow-y: auto;
        }
        .history-actions {
            display: flex;
            gap: 5px;
            margin-top: 5px;
            flex-wrap: wrap;
        }
        .history-actions button {
            padding: 4px 8px;
            font-size: 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .load-chat-btn {
            background: #007bff;
            color: white;
        }
        .load-chat-btn:hover {
            background: #0056b3;
        }
        .apply-history-btn {
            background: #28a745;
            color: white;
        }
        .apply-history-btn:hover {
            background: #218838;
        }
        .save-history-btn {
            background: #17a2b8;
            color: white;
        }
        .save-history-btn:hover {
            background: #138496;
        }
        .load-response-btn {
            background: #6f42c1;
            color: white;
        }
        .load-response-btn:hover {
            background: #5a359c;
        }
        .rollback-history-btn {
            background: #dc3545;
            color: white;
        }
        .rollback-history-btn:hover {
            background: #c82333;
        }
        .code-container {
            background: #1e1e1e;
            color: #f8f8f2;
            border-radius: 5px;
            margin-top: 5px;
            font-family: monospace;
            max-width: 100%;
            overflow: hidden; /* Hide overflow outside pre */
        }

        .code-content {
            white-space: pre;         /* Preserve indentation and line breaks */
            overflow-y: auto;         /* Vertical scroll */
            max-height: 500px;        /* Fixed height for scrolling */
            padding: 10px;
            margin: 0;
            overflow-x: auto;         /* Optional: horizontal scroll for very long lines */
        }

    </style>
</head>
<body>
    <div class="header">
        <h1>Multi-Project AI Assistant 🤖</h1>
        <div class="subtitle">Works with React and Ruby on Rails applications simultaneously!</div>
    </div>

    <div class="container">
        <div class="chat-container">
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
               <button class="rollback-button" onclick="rollbackMigrationChanges()">Rollback db changes</button></br>
                <button class="rollback-button" onclick="Migrations()">Db Migrate</button></br>
                <button class="rollback-button" onclick="restartServers()">Restart all servers</button>


            <h3>Chat History</h3>
            <div class="history-container" id="history-container">
                <div id="chat-history">
                    <div class="file-item">Loading history...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let currentYamlResponse = '';
        let currentSessionId = '';
        let selectedConversationId = null;

        // DOM elements
        const chatMessages = document.getElementById('chat-messages');
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        const modelSelect = document.getElementById('model-select');
        const projectInfo = document.getElementById('project-info');
        const recentChanges = document.getElementById('recent-changes');
        const chatHistory = document.getElementById('chat-history');

        // Auto-resize textarea
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });

        // Send message on button click
        sendButton.addEventListener('click', sendMessage);

        // Send message on Enter (but allow Shift+Enter for new line)
        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        function sendMessage() {
            const message = messageInput.value.trim();
            const selectedModel = modelSelect.value;

            if (message) {
                addMessage('user', message);
                messageInput.value = '';
                messageInput.style.height = 'auto';

                // Show typing indicator
                showTypingIndicator();

                // Send to server with selected model
                socket.emit('send_message', {
                    message: message,
                    model: selectedModel
                });

                // Disable input while processing
                sendButton.disabled = true;
                messageInput.disabled = true;
                modelSelect.disabled = true;
            }
        }

        function formatYAML(yamlContent) {
            if (!yamlContent) return '';

            // Simple YAML syntax highlighting
            return yamlContent
                .replace(/(^|\s)([a-zA-Z_][a-zA-Z0-9_]*):/g, '$1<span class="yaml-key">$2</span>:')
                .replace(/:(\s*)(["'])(.*?)\2/g, ':$1<span class="yaml-string">$2$3$2</span>')
                .replace(/:(\s*)([0-9]+(\.[0-9]+)?)/g, ':$1<span class="yaml-number">$2</span>')
                .replace(/:(\s*)(true|false)/g, ':$1<span class="yaml-boolean">$2</span>')
                .replace(/:(\s*)(null)/g, ':$1<span class="yaml-null">$2</span>')
                .replace(/#(.*)$/gm, '<span class="yaml-comment">#$1</span>');
        }

        function addMessage(sender, content, isYaml = false, conversationId = null, modelUsed = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${sender}-message`;
            if (conversationId) {
                messageDiv.setAttribute('data-conversation-id', conversationId);
            }

            if (isYaml) {
                const formattedYaml = formatYAML(content);
                messageDiv.innerHTML = `
                    <strong>${sender === 'user' ? 'You' : 'Assistant'}:</strong>
                    ${modelUsed ? `<small style="color: #666; font-style: italic;">(Using: ${modelUsed})</small>` : ''}
                    <div class="code-container">
                        <div class="code-header">
                            <span>Multi-Project YAML Configuration</span>
                        </div>
                        <div class="code-content">${formattedYaml}</div>
                    </div>
                    ${sender === 'assistant' ?
                        '<div class="action-buttons">' +
                            '<button class="apply-button" onclick="applyChanges()">Apply Changes</button>' +
                            '<button class="save-button" onclick="saveChanges()">Save Changes</button>' +
                            '<button class="rollback-button" onclick="rollbackChanges()">Rollback</button>' +
                            '<button class="load-response-button" onclick="loadResponse()">Load Response</button>' +
                        '</div>'
                    : ''}
                `;
            } else {
                messageDiv.innerHTML = `<strong>${sender === 'user' ? 'You' : 'Assistant'}:</strong> ${content}`;
            }

            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function copyToClipboard(button, text) {
            navigator.clipboard.writeText(text).then(() => {
                const originalText = button.textContent;
                button.textContent = 'Copied!';
                button.classList.add('copied');
                setTimeout(() => {
                    button.textContent = originalText;
                    button.classList.remove('copied');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        }

        function showTypingIndicator() {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message assistant-message typing-indicator';
            typingDiv.id = 'typing-indicator';
            typingDiv.innerHTML = `Assistant is thinking <span class="dot-flashing"></span>`;
            chatMessages.appendChild(typingDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function hideTypingIndicator() {
            const typingIndicator = document.getElementById('typing-indicator');
            if (typingIndicator) {
                typingIndicator.remove();
            }
        }

        function applyChanges() {
            if (currentYamlResponse) {
                socket.emit('apply_changes', {
                    yaml_response: currentYamlResponse,
                    conversation_id: selectedConversationId
                });
            }
        }

        function saveChanges() {
            if (currentYamlResponse) {
                socket.emit('save_changes', {
                    yaml_response: currentYamlResponse,
                    conversation_id: selectedConversationId
                });
            }
        }

        function rollbackChanges() {
            if (confirm('Are you sure you want to rollback all changes across all projects?')) {
                socket.emit('rollback_changes');
            }
        }

        function rollbackMigrationChanges() {
            if (confirm('Are you sure you want to rollback last changes of db?')) {
                socket.emit('rollback_migration_changes');
            }
        }
        function Migrations() {
            if (confirm('Are you sure you want to migrate tables db?')) {
                socket.emit('migration_changes');
            }
        }
        function restartServers() {
            if (confirm('Are you sure you want to restart all servers?')) {
                socket.emit('restart_servers');
            }
        }


        function loadResponse() {
            if (currentYamlResponse) {
                // This would typically parse the YAML and show a preview
                alert('Response loaded for review. You can now apply or save the changes.');
            }
        }

        function applyHistoryChanges(conversationId, yamlResponse) {
            if (yamlResponse && yamlResponse !== 'No YAML response') {
                socket.emit('apply_changes', {
                    yaml_response: yamlResponse,
                    conversation_id: conversationId
                });
            } else {
                alert('No YAML response found for this conversation');
            }
        }

        function saveHistoryChanges(conversationId, yamlResponse) {
            if (yamlResponse && yamlResponse !== 'No YAML response') {
                socket.emit('save_changes', {
                    yaml_response: yamlResponse,
                    conversation_id: conversationId
                });
            } else {
                alert('No YAML response found for this conversation');
            }
        }

        function rollbackHistoryChanges() {
            if (confirm('Are you sure you want to rollback all changes across all projects?')) {
                socket.emit('rollback_changes');
            }
        }

        function loadResponseToChat(conversationId, query, yamlResponse, modelUsed = null) {
            try {
                // Clear current chat
                chatMessages.innerHTML = '<div class="message system-message">Loaded from history:</div>';

                // Decode the parameters
                const decodedQuery = query ? decodeURIComponent(query) : '';
                const decodedYaml = yamlResponse && yamlResponse !== 'No YAML response' ?
                    decodeURIComponent(yamlResponse) : '';

                // Add the user query
                if(decodedQuery) {
                    addMessage('user', decodedQuery, false, conversationId);
                }

                // Add the assistant response
                if(decodedYaml) {
                    addMessage('assistant', decodedYaml, true, conversationId, modelUsed);
                    currentYamlResponse = decodedYaml;
                } else {
                    addMessage('assistant', 'No YAML response available', false, conversationId);
                }

                selectedConversationId = conversationId;
                chatMessages.scrollTop = chatMessages.scrollHeight;
            } catch (error) {
                console.error('Error loading chat from history:', error);
                addMessage('system', 'Error loading conversation from history');
            }
        }

        function updateProjectInfo(info) {
            if (info && info.projects) {
                let projectsHTML = '';
                info.projects.forEach(project => {
                    const badgeClass = `badge-${project.type}`;
                    projectsHTML += `
                        <div class="project-item project-${project.type}">
                            <span class="project-badge ${badgeClass}">${project.type.toUpperCase()}</span>
                            <strong>${project.root.split('/').pop()}</strong>
                            <div class="file-item">Files: ${project.file_count}</div>
                        </div>
                    `;
                });
                projectInfo.innerHTML = projectsHTML;
            }
        }

        function updateRecentChanges(results) {
            let changesHTML = '';

            if (results.files_created && results.files_created.length > 0) {
                changesHTML += '<div class="file-item success"><strong>Created:</strong></div>';
                results.files_created.forEach(file => {
                    changesHTML += `<div class="file-item success">📄 ${file}</div>`;
                });
            }

            if (results.files_updated && results.files_updated.length > 0) {
                changesHTML += '<div class="file-item warning"><strong>Updated:</strong></div>';
                results.files_updated.forEach(file => {
                    changesHTML += `<div class="file-item warning">✏️ ${file}</div>`;
                });
            }

            if (results.files_failed && results.files_failed.length > 0) {
                changesHTML += '<div class="file-item error"><strong>Failed:</strong></div>';
                results.files_failed.forEach(error => {
                    changesHTML += `<div class="file-item error">❌ ${error}</div>`;
                });
            }

            if (changesHTML === '') {
                changesHTML = '<div class="file-item">No changes yet</div>';
            }

            recentChanges.innerHTML = changesHTML;
        }

        function updateChatHistory(history) {
            if (history && history.length > 0) {
                let historyHTML = '';

                history.forEach(conv => {
                    const date = new Date(conv.created_at).toLocaleString();
                    const shortQuery = conv.query && conv.query.length > 50 ?
                        conv.query.substring(0, 50) + '...' : conv.query || 'No query';
                    const shortYaml = conv.yaml_response && conv.yaml_response.length > 100 ?
                        conv.yaml_response.substring(0, 100) + '...' : conv.yaml_response || 'No YAML response';

                    historyHTML += `
                        <div class="history-item"
                             data-conversation-id="${conv.id}"
                             data-query="${escapeHtml(conv.query || '')}"
                             data-yaml="${escapeHtml(conv.yaml_response || '')}">
                            <strong>${date}</strong><br>
                            <strong>Q:</strong> ${shortQuery}<br>
                            <strong>A:</strong> ${shortYaml}
                            <div class="history-actions">
                                <button class="load-chat-btn" onclick="loadResponseToChatFromData(this)">Load in Chat</button>
                                <button class="apply-history-btn" onclick="applyHistoryChangesFromData(this)">Apply Changes</button>
                                <button class="save-history-btn" onclick="saveHistoryChangesFromData(this)">Save Changes</button>
                                <button class="rollback-history-btn" onclick="rollbackHistoryChanges()">Rollback</button>
                            </div>
                        </div>
                    `;
                });

                chatHistory.innerHTML = historyHTML;
            } else {
                chatHistory.innerHTML = '<div class="file-item">No history yet</div>';
            }
        }

        // HTML escaping function
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        // Safe data extraction from attributes
        function getConversationData(button) {
            const historyItem = button.closest('.history-item');
            const conversationId = historyItem.getAttribute('data-conversation-id');
            const query = historyItem.getAttribute('data-query');
            const yamlResponse = historyItem.getAttribute('data-yaml');

            // Unescape HTML entities
            const unescapedQuery = unescapeHtml(query);
            const unescapedYaml = unescapeHtml(yamlResponse);

            return {
                conversationId: conversationId,
                query: unescapedQuery,
                yamlResponse: unescapedYaml
            };
        }

        function unescapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.innerHTML = text;
            return div.textContent;
        }

        // Updated handler functions
        function loadResponseToChatFromData(button) {
            const data = getConversationData(button);
            loadResponseToChat(data.conversationId, data.query, data.yamlResponse);
        }

        function applyHistoryChangesFromData(button) {
            const data = getConversationData(button);
            applyHistoryChanges(data.conversationId, data.yamlResponse);
        }

        function saveHistoryChangesFromData(button) {
            const data = getConversationData(button);
            saveHistoryChanges(data.conversationId, data.yamlResponse);
        }

        // Make the original functions more robust
        function loadResponseToChat(conversationId, query, yamlResponse, modelUsed = null) {
            try {
                // Clear current chat
                chatMessages.innerHTML = '<div class="message system-message">Loaded from history:</div>';

                // Add the user query
                if(query && query !== 'null' && query !== 'undefined') {
                    addMessage('user', query, false, conversationId);
                }

                // Add the assistant response
                if(yamlResponse && yamlResponse !== 'No YAML response' && yamlResponse !== 'null' && yamlResponse !== 'undefined') {
                    addMessage('assistant', yamlResponse, true, conversationId, modelUsed);
                    currentYamlResponse = yamlResponse;
                } else {
                    addMessage('assistant', 'No YAML response available', false, conversationId);
                }

                selectedConversationId = conversationId;
                chatMessages.scrollTop = chatMessages.scrollHeight;
            } catch (error) {
                console.error('Error loading chat from history:', error);
                addMessage('system', 'Error loading conversation from history: ' + error.message);
            }
        }

        function applyHistoryChanges(conversationId, yamlResponse) {
            if (yamlResponse && yamlResponse !== 'No YAML response' && yamlResponse !== 'null' && yamlResponse !== 'undefined') {
                socket.emit('apply_changes', {
                    yaml_response: yamlResponse,
                    conversation_id: conversationId
                });
            } else {
                alert('No valid YAML response found for this conversation');
            }
        }

        function saveHistoryChanges(conversationId, yamlResponse) {
            if (yamlResponse && yamlResponse !== 'No YAML response' && yamlResponse !== 'null' && yamlResponse !== 'undefined') {
                socket.emit('save_changes', {
                    yaml_response: yamlResponse,
                    conversation_id: conversationId
                });
            } else {
                alert('No valid YAML response found for this conversation');
            }
        }

        // Socket event handlers
        socket.on('connect', function() {
            console.log('Connected to server');
            currentSessionId = socket.id;
            socket.emit('get_project_info');
            socket.emit('get_all_conversations');
        });

        socket.on('project_info', function(data) {
            updateProjectInfo(data);
        });

        socket.on('assistant_response', function(data) {
            hideTypingIndicator();
            currentYamlResponse = data.yaml_response;
            selectedConversationId = null; // Reset for new conversation
            addMessage('assistant', data.yaml_response, true, null, data.model_used);

            // Refresh chat history to show the new conversation
            socket.emit('get_all_conversations');

            // Re-enable input
            sendButton.disabled = false;
            messageInput.disabled = false;
            modelSelect.disabled = false;
            messageInput.focus();
        });

        socket.on('application_results', function(data) {
            addMessage('system', '✅ Changes applied successfully across projects!');
            updateRecentChanges(data.results);

            // Refresh history to show applied status
            socket.emit('get_all_conversations');
        });

        socket.on('save_results', function(data) {
            addMessage('system', `✅ Changes saved with git! Commit: "${data.commit_message}"`);
        });

        socket.on('rollback_results', function(data) {
            addMessage('system', '✅ Rollback completed across all projects!');

            // Refresh project info to reflect rolled back state
            socket.emit('get_project_info');
        });

        socket.on('all_conversations', function(data) {
            updateChatHistory(data.conversations);
        });

        socket.on('error', function(data) {
            hideTypingIndicator();
            addMessage('system', `❌ Error: ${data.error}`);

            // Re-enable input
            sendButton.disabled = false;
            messageInput.disabled = false;
            modelSelect.disabled = false;
            messageInput.focus();
        });
    </script>
</body>
</html>
        '''

        @self.app.route('/')
        def index():
            return HTML_TEMPLATE

        @self.socketio.on('connect')
        def handle_connect():
            session_id = request.sid
            self.sessions[session_id] = {
                'current_yaml': ''
            }
            print(f"✅ Client connected: {session_id}")

            # Send project info to newly connected client
            project_info = self.assistant.get_project_info()
            emit('project_info', project_info)

            # Send initial conversation history
            all_conversations = self.assistant.db.get_all_conversations(50)
            emit('all_conversations', {'conversations': all_conversations})

        @self.socketio.on('send_message')
        def handle_message(data):
            @copy_current_request_context
            def process_message():
                try:
                    query = data['message']
                    model_name = data.get('model', 'qwen3-coder:480b-cloud')
                    session_id = request.sid

                    print(f"📨 Processing query: {query}")
                    print(f"🤖 Using model: {model_name}")

                    # Set the model before processing
                    self.assistant.set_model(model_name)

                    # Process the query using auto-generate mode
                    yaml_response = self.assistant.process_query(query, session_id, use_auto_generate=True)

                    # Store the YAML response in session
                    self.sessions[session_id] = {'current_yaml': yaml_response}

                    # Send response back to client
                    emit('assistant_response', {
                        'yaml_response': yaml_response,
                        'session_id': session_id,
                        'model_used': model_name
                    }, room=session_id)

                    # Refresh conversation history
                    all_conversations = self.assistant.db.get_all_conversations(50)
                    emit('all_conversations', {'conversations': all_conversations}, room=session_id)

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
                    yaml_response = data['yaml_response']
                    session_id = request.sid
                    conversation_id = data.get('conversation_id')
                    print(f"🔄 Applying changes from YAML response (Conversation ID: {conversation_id})...")

                    # Apply changes using existing logic
                    results = self.assistant.apply_changes(yaml_response)

                    # Store application results in PostgreSQL
                    if conversation_id:
                        # Update the specific conversation
                        self.assistant.db.update_application_results(conversation_id, results)
                    else:
                        # For new conversations, update the latest one
                        recent_conversations = self.assistant.db.get_conversation_history(session_id, 1)
                        if recent_conversations:
                            latest_conv = recent_conversations[0]
                            self.assistant.db.update_application_results(latest_conv['id'], results)

                    # Send results back to client
                    emit('application_results', {
                        'results': results,
                        'session_id': session_id
                    }, room=session_id)

                    # Refresh project info
                    project_info = self.assistant.get_project_info()
                    emit('project_info', project_info, room=session_id)

                except Exception as e:
                    print(f"❌ Error applying changes: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=apply_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('save_changes')
        def handle_save_changes(data):
            @copy_current_request_context
            def save_changes_thread():
                try:
                    yaml_response = data['yaml_response']
                    conversation_id = data.get('conversation_id')
                    session_id = request.sid

                    print(f"💾 Saving changes with git (Conversation ID: {conversation_id})...")

                    # Get the last applied query for the commit message
                    commit_message = "AI-generated changes"
                    if conversation_id:
                        conversation = self.assistant.db.get_conversation_by_id(conversation_id)
                        if conversation and conversation.get('query'):
                            commit_message = f"AI: {conversation['query'][:50]}..."

                    # Execute git commands for each project
                    results = {
                        'commands_run': [],
                        'git_results': {}
                    }

                    for project_path in self.assistant.project_paths:
                        try:
                            # Git add all changes
                            result = subprocess.run(
                                ['git', 'add', '.'],
                                cwd=project_path,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            results['commands_run'].append(f'git add . in {os.path.basename(project_path)}')

                            # Git commit
                            result = subprocess.run(
                                ['git', 'commit', '-m', commit_message],
                                cwd=project_path,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            results['commands_run'].append(f'git commit -m "{commit_message}" in {os.path.basename(project_path)}')

                            results['git_results'][project_path] = {
                                'add': result.stdout if result.returncode == 0 else result.stderr,
                                'commit': result.stdout if result.returncode == 0 else result.stderr
                            }

                            print(f"✅ Changes saved with git commit in {project_path}: {commit_message}")

                        except Exception as e:
                            results['git_results'][project_path] = {'error': str(e)}
                            print(f"❌ Error saving changes in {project_path}: {e}")

                    # Send results back to client
                    emit('save_results', {
                        'results': results,
                        'commit_message': commit_message,
                        'session_id': session_id
                    }, room=session_id)

                except Exception as e:
                    print(f"❌ Error saving changes: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=save_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('restart_servers')
        def handle_restart_servers(data=None):
            @copy_current_request_context
            def restart_servers_thread():
                session_id = request.sid
                results = {}

                try:
                    print("🔄 Restarting Rails and React servers...")

                    for project_path in self.assistant.project_paths:
                        try:
                            project_name = os.path.basename(project_path)

                            # Restart Rails if backend project
                            if os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
                                print(f"🛑 Stopping existing Rails processes in {project_name}...")
                                subprocess.run("pkill -9 -f 'rails s'", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                time.sleep(1)

                                print(f"🚀 Starting Rails server in {project_name} on port 3000...")
                                subprocess.Popen(
                                    ['bundle', 'exec', 'rails', 's', '-p', '3000', '-b', '0.0.0.0'],
                                    cwd=project_path
                                )
                                results[f"{project_name}_Rails"] = "restarted successfully"
                                time.sleep(3)

                            # Restart React if frontend project (detect by package.json without config/application.rb)
                            elif os.path.exists(os.path.join(project_path, 'package.json')):
                                print(f"🛑 Stopping existing React processes in {project_name}...")
                                subprocess.run("pkill -9 -f 'npm start'", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                time.sleep(1)

                                print(f"🚀 Starting React app in {project_name} on port 4000...")
                                subprocess.Popen(
                                    f"nohup bash -c 'PORT=4000 npm start -- --host 0.0.0.0' > ~/react_{project_name}.log 2>&1 &",
                                    cwd=project_path,
                                    shell=True
                                )
                                results[f"{project_name}_React"] = "restarted successfully"
                                time.sleep(5)

                        except Exception as e:
                            results[project_path] = {'error': str(e)}
                            print(f"❌ Error restarting servers in {project_path}: {e}")

                    # Flush Redis after restarting
                    try:
                        subprocess.run(["redis-cli", "FLUSHALL"], check=True)
                        print("🧹 Redis cache flushed.")
                    except Exception as e:
                        print(f"❌ Error flushing Redis: {e}")

                    emit('restart_servers_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ Rails and React servers restarted successfully.")

                except Exception as e:
                    print(f"❌ Error during servers restart: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=restart_servers_thread)
            thread.daemon = True
            thread.start()




        @self.socketio.on('migration_changes')
        def handle_migration_changes(data=None):
            @copy_current_request_context
            def migration_thread():
                session_id = request.sid
                results = {}

                try:
                    print("🚀 Running Rails database migrations for all backend projects...")

                    for project_path in self.assistant.project_paths:
                        try:
                            # Only run migrations if it's a Rails backend app
                            if os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
                                print(f"🚀 Running migrations in {os.path.basename(project_path)}...")

                                rails_migrate = subprocess.run(
                                    ['bundle', 'exec', 'rails', 'db:migrate'],
                                    cwd=project_path,
                                    capture_output=True,
                                    text=True,
                                    timeout=120
                                )

                                results[project_path] = {
                                    'stdout': rails_migrate.stdout,
                                    'stderr': rails_migrate.stderr
                                }
                                print(rails_migrate.stdout)

                        except Exception as e:
                            results[project_path] = {'error': str(e)}
                            print(f"❌ Error running migrations in {project_path}: {e}")

                    emit('migration_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ Migrations completed successfully.")

                except Exception as e:
                    print(f"❌ Error in migration execution: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=migration_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('rollback_migration_changes')
        def handle_rollback_migration_changes(data=None):
            @copy_current_request_context
            def rollback_migration_thread():
                session_id = request.sid
                results = {}

                try:
                    print("↩️ Rolling back Rails database migrations for all backend projects...")

                    for project_path in self.assistant.project_paths:
                        try:
                            # Only rollback if it's a Rails backend app
                            if os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
                                print(f"↩️ Rolling back migrations in {os.path.basename(project_path)}...")

                                rails_rollback = subprocess.run(
                                    ['bundle', 'exec', 'rails', 'db:rollback', 'STEP=1'],  # rollback last migration
                                    cwd=project_path,
                                    capture_output=True,
                                    text=True,
                                    timeout=60
                                )

                                results[project_path] = {
                                    'stdout': rails_rollback.stdout,
                                    'stderr': rails_rollback.stderr
                                }
                                print(rails_rollback.stdout)

                        except Exception as e:
                            results[project_path] = {'error': str(e)}
                            print(f"❌ Error rolling back migrations in {project_path}: {e}")

                    emit('rollback_migration_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ Migration rollback completed.")

                except Exception as e:
                    print(f"❌ Error in migration rollback: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=rollback_migration_thread)
            thread.daemon = True
            thread.start()


        @self.socketio.on('rollback_changes')
        def handle_rollback_changes(data=None):
            @copy_current_request_context
            def rollback_changes_thread():
                try:
                    session_id = request.sid
                    print("🔄 Rolling back changes across all projects...")

                    results = {
                        'commands_run': [],
                        'rollback_results': {}
                    }

                    for project_path in self.assistant.project_paths:
                        try:
                            # Rollback Rails migrations if any migrations have been applied


                            # Git checkout - revert all changes
                            git_checkout = subprocess.run(
                                ['git', 'checkout', '.'],
                                cwd=project_path,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            results['commands_run'].append(f'git checkout . in {os.path.basename(project_path)}')

                            # Git clean - remove untracked files
                            git_clean = subprocess.run(
                                ['git', 'clean', '-fd'],
                                cwd=project_path,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            results['commands_run'].append(f'git clean -fd in {os.path.basename(project_path)}')

                        except Exception as e:
                            results['rollback_results'][project_path] = {'error': str(e)}
                            print(f"❌ Error during rollback in {project_path}: {e}")


                    # Update Redis cache after rollback
                    self.assistant.redis_manager.store_project_structure(self.assistant.project_paths, self.assistant.project_id)

                    print("✅ Rollback completed successfully across all projects")

                    # Send results back to client
                    emit('rollback_results', {
                        'results': results,
                        'session_id': session_id
                    }, room=session_id)

                    # Refresh project info
                    project_info = self.assistant.get_project_info()
                    emit('project_info', project_info, room=session_id)

                except Exception as e:
                    print(f"❌ Error during rollback: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=rollback_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('get_project_info')
        def handle_get_project_info():
            session_id = request.sid
            project_info = self.assistant.get_project_info()
            emit('project_info', project_info, room=session_id)

        @self.socketio.on('get_all_conversations')
        def handle_get_all_conversations():
            session_id = request.sid
            all_conversations = self.assistant.db.get_all_conversations(100)
            print(f"📤 Sending ALL conversations to client {session_id}: {len(all_conversations)} total")
            emit('all_conversations', {'conversations': all_conversations}, room=session_id)

    def run(self):
        """Start the web server"""
        print(f"🚀 Starting Multi-Project AI Assistant Web UI...")
        print(f"📁 Projects: {self.assistant.project_paths}")
        print(f"🌐 Web interface: http://{self.host}:{self.port}")
        print("💡 Open the above URL in your browser to start chatting!")
        print("🗄️  PostgreSQL database is active and storing all conversations")
        print("🎯 Using INTENT-AWARE AUTO-GENERATE mode with dynamic file finding across projects")
        print("🤖 Available models:", self.assistant.get_available_models())

        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Multi-Project AI Assistant')
    parser.add_argument('project_paths', nargs='+', help='Paths to project directories (React and/or Rails)')
    parser.add_argument('--redis-host', default='localhost', help='Redis host')
    parser.add_argument('--redis-port', default=6379, type=int, help='Redis port')
    parser.add_argument('--ollama-url', default='http://localhost:11434', help='Ollama server URL')
    parser.add_argument('--web', action='store_true', default=True, help='Use web interface (default)')
    parser.add_argument('--cli', action='store_true', help='Use command line interface')
    parser.add_argument('--host', default='0.0.0.0', help='Web server host')
    parser.add_argument('--port', default=5000, type=int, help='Web server port')

    # PostgreSQL configuration
    parser.add_argument('--db-host', default='localhost', help='PostgreSQL host')
    parser.add_argument('--db-port', default=5432, type=int, help='PostgreSQL port')
    parser.add_argument('--db-name', default='multi_project_ai_assistant', help='PostgreSQL database name')
    parser.add_argument('--db-user', default='postgres', help='PostgreSQL username')
    parser.add_argument('--db-password', default='password', help='PostgreSQL password')

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

    if args.cli:
        # CLI interface
        assistant = MultiProjectAIAssistant(args.project_paths, args.redis_host, args.redis_port, db_config)
        assistant.ollama.base_url = args.ollama_url
        assistant.initialize_projects()

        # Show project info
        project_info = assistant.get_project_info()
        if project_info:
            print(f"\n📁 Projects ({project_info['total_projects']}):")
            for project in project_info['projects']:
                print(f"  - [{project['type'].upper()}] {project['root']} ({project['file_count']} files)")
            print(f"🔑 Project ID: {project_info['project_id']}")

        print("\n" + "="*60)
        print("🤖 Multi-Project AI Assistant Ready!")
        print("🗄️  PostgreSQL database active - storing all conversations")
        print("🎯 Using INTENT-AWARE AUTO-GENERATE mode with dynamic file finding across projects")
        print("🤖 Available models:", assistant.get_available_models())
        print("="*60)

        while True:
            try:
                user_input = input("\n💬 Enter your query: ").strip()

                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break

                if user_input:
                    # Process query using auto-generate mode
                    response = assistant.process_query(user_input, "cli_session", use_auto_generate=False)
                    print("\n" + "="*60)
                    print("📋 IMPLEMENTATION DETAILS:")
                    print("="*60)
                    print(response)

                    # Ask user if they want to apply changes
                    print("\n" + "="*60)
                    print("🚀 ACTION REQUIRED:")
                    print("="*60)
                    print("Do you want to apply these changes to your projects?")
                    print("1. Apply - Write files and install packages across all projects")
                    print("2. Cancel - Discard changes")

                    while True:
                        action = input("\nChoose action (1 for Apply, 2 for Cancel): ").strip()

                        if action == '1':
                            print("\n🔄 Applying changes across projects...")
                            results = assistant.apply_changes(response)

                            # Store application results in PostgreSQL
                            recent_conversations = assistant.db.get_conversation_history("cli_session", 1)
                            if recent_conversations:
                                latest_conv = recent_conversations[0]
                                assistant.db.update_application_results(latest_conv['id'], results)

                            print("\n" + "="*60)
                            print("📊 APPLICATION RESULTS:")
                            print("="*60)

                            if results['files_created']:
                                print("\n✅ FILES CREATED:")
                                for file in results['files_created']:
                                    print(f"  - {file}")

                            if results['files_updated']:
                                print("\n✏️  FILES UPDATED:")
                                for file in results['files_updated']:
                                    print(f"  - {file}")

                            if results['files_failed']:
                                print("\n❌ FAILED OPERATIONS:")
                                for error in results['files_failed']:
                                    print(f"  - {error}")

                            if results['install_output']:
                                print("\n📦 PACKAGE INSTALLATION:")
                                for output in results['install_output']:
                                    print(f"  - {output}")

                            if results['packages_installed']:
                                print("\n🎉 All changes applied successfully!")
                            else:
                                print("\n⚠️  Changes applied with some warnings.")

                            break

                        elif action == '2':
                            print("\n❌ Changes cancelled.")
                            break
                        else:
                            print("❌ Invalid choice. Please enter 1 for Apply or 2 for Cancel.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    else:
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