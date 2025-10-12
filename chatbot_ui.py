#!/usr/bin/env python3
import os
import json
import yaml
import requests
import redis
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional
import re
import subprocess
from flask import Flask, render_template, request, jsonify, copy_current_request_context
from flask_socketio import SocketIO, emit
import threading
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import math
from difflib import SequenceMatcher

class DynamicFileFinder:
    def __init__(self, project_root="."):
        self.project_root = project_root
        self.allowed_ext = (".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".json", ".html")

    def get_all_files(self):
        files = []
        for root, _, file_list in os.walk(self.project_root):
            # Skip common directories that don't contain source code
            if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next']):
                continue

            for file in file_list:
                if file.endswith(self.allowed_ext):
                    files.append(os.path.join(root, file))
        return files

    def relevance_score(self, filename, query):
        """Compute similarity between filename/path and user query"""
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

        # Combine scores with weights
        final_score = (base_ratio * 0.6) + (path_ratio * 0.3) + min(keyword_bonus, 0.4)

        return min(final_score, 1.0)

    def find_relevant_files(self, query, top_n=8):
        """Return most relevant files based on query, filename, and content."""
        if not query or not query.strip():
            return []

        all_files = self.get_all_files()
        if not all_files:
            return []

        query_lower = query.lower().strip()
        query_words = set(query_lower.split())

        ranked = []

        for f in all_files:
            file_name = os.path.basename(f).lower()
            file_path = f.lower()

            # Base score
            base_score = self.relevance_score(f, query)
            keyword_boost = 0
            content_boost = 0

            # Boost for filename/path match
            for word in query_words:
                if word in file_name or word in file_path:
                    keyword_boost += 1.0

            # Check file content
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as file:
                    content = file.read().lower()
                    for w in query_words:
                        if w in content:
                            content_boost += 0.5
            except Exception as e:
                print(f"⚠️ Could not read {f}: {e}")

            # 🔒 Strict filtering when “contact” (or other specific keyword) is mentioned
            if "contact" in query_lower:
                # If contact is neither in filename, path, nor content → skip early
                if "contact" not in file_name and "contact" not in file_path and "contact" not in content:
                    continue  # skip irrelevant forms

            final_score = base_score + keyword_boost + content_boost
            ranked.append((f, final_score))

        # Sort and filter
        ranked = sorted(ranked, key=lambda x: x[1], reverse=True)
        relevant_files = [f for f, _ in ranked[:top_n]]

        print(f"🔍 Found {len(relevant_files)} relevant files for query: '{query}'")
        for file, score in ranked[:8]:
            print(f"   - {os.path.basename(file)}: {score:.3f}")

        return relevant_files


class ProjectContextBuilder:
    def __init__(self, max_file_size=50000):  # 50KB max per file
        self.max_file_size = max_file_size

    def build_context(self, file_paths):
        """Combine contents of found files into one unified context"""
        context_parts = []
        total_size = 0

        for path in file_paths:
            try:
                file_size = os.path.getsize(path)
                if file_size > self.max_file_size:
                    print(f"⚠️  Skipping large file: {path} ({file_size} bytes)")
                    context_parts.append(f"\n--- FILE: {path} (SKIPPED - Too large: {file_size} bytes) ---\n")
                    continue

                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                context_parts.append(f"\n--- FILE: {path} ---\n{content}\n")
                total_size += len(content)

                # Limit total context size to prevent overwhelming the model
                if total_size > 100000:  # ~100KB total context
                    print(f"⚠️  Context size limit reached ({total_size} bytes), truncating...")
                    break

            except UnicodeDecodeError:
                # Try with different encoding
                try:
                    with open(path, "r", encoding="latin-1") as f:
                        content = f.read()
                    context_parts.append(f"\n--- FILE: {path} (latin-1 encoding) ---\n{content}\n")
                except Exception as e:
                    context_parts.append(f"\n--- FILE: {path} (Error reading: {e}) ---\n")
            except Exception as e:
                context_parts.append(f"\n--- FILE: {path} (Error: {e}) ---\n")

        final_context = "\n".join(context_parts)
        print(f"📚 Built context with {len(file_paths)} files, total size: {len(final_context)} bytes")
        return final_context

# PostgreSQL Database Manager
class PostgresDB:
    def __init__(self, dbname='react_ai_assistant', user='postgres', password='root',
                 host='localhost', port=5432):
        self.db_config = {
            'dbname': dbname,
            'user': user,
            'password': password,
            'host': host,
            'port': port
        }
        self.init_database()

    def init_database(self):
        """Initialize database and create tables if they don't exist"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # Create conversations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    query TEXT NOT NULL,
                    yaml_response TEXT NOT NULL,
                    project_id VARCHAR(100) NOT NULL,
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
            conn.close()
            print("✅ PostgreSQL database initialized successfully")

        except Exception as e:
            print(f"❌ Error initializing PostgreSQL database: {e}")

    def store_conversation(self, session_id: str, query: str, yaml_response: str, project_id: str) -> int:
        """Store a conversation in the database and return the conversation ID"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO conversations (session_id, query, yaml_response, project_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            ''', (session_id, query, yaml_response, project_id))

            conversation_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()

            print(f"✅ Conversation stored in PostgreSQL with ID: {conversation_id}")
            return conversation_id

        except Exception as e:
            print(f"❌ Error storing conversation in PostgreSQL: {e}")
            import traceback
            traceback.print_exc()
            return -1

    def update_application_results(self, conversation_id: int, results: Dict):
        """Update conversation with application results"""
        try:
            conn = psycopg2.connect(**self.db_config)
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
            conn.close()

            print(f"✅ Application results stored for conversation ID: {conversation_id}")

        except Exception as e:
            print(f"❌ Error storing application results in PostgreSQL: {e}")

    def get_conversation_history(self, session_id: str, limit: int = 50) -> List[Dict]:
        """Get conversation history for a session"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_id, created_at, applied_at
                FROM conversations
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (session_id, limit))

            conversations = cursor.fetchall()
            cursor.close()
            conn.close()

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

    def get_all_conversations(self, limit: int = 100) -> List[Dict]:
        """Get all conversations across all sessions"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_id, created_at, applied_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT %s
            ''', (limit,))

            conversations = cursor.fetchall()
            cursor.close()
            conn.close()

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

    def get_conversations_with_pagination(self, page: int = 1, per_page: int = 20) -> Dict:
        """Get conversations with pagination"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            offset = (page - 1) * per_page

            cursor.execute('SELECT COUNT(*) as total FROM conversations')
            total_count = cursor.fetchone()['total']

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_id, created_at, applied_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            ''', (per_page, offset))

            conversations = cursor.fetchall()
            cursor.close()
            conn.close()

            result = []
            for conv in conversations:
                conv_dict = dict(conv)
                if conv_dict['created_at'] and isinstance(conv_dict['created_at'], datetime):
                    conv_dict['created_at'] = conv_dict['created_at'].isoformat()
                if conv_dict['applied_at'] and isinstance(conv_dict['applied_at'], datetime):
                    conv_dict['applied_at'] = conv_dict['applied_at'].isoformat()
                result.append(conv_dict)

            return {
                'conversations': result,
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }

        except Exception as e:
            print(f"❌ Error fetching paginated conversations from PostgreSQL: {e}")
            return {'conversations': [], 'total_count': 0, 'page': page, 'per_page': per_page, 'total_pages': 0}

    def get_conversation_by_id(self, conversation_id: int) -> Optional[Dict]:
        """Get a specific conversation by ID"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute('''
                SELECT id, session_id, query, yaml_response, project_id, created_at, applied_at
                FROM conversations
                WHERE id = %s
            ''', (conversation_id,))

            conversation = cursor.fetchone()
            cursor.close()
            conn.close()

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

class RedisProjectManager:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True
        )
        self.project_key_prefix = "react_project:"

    def store_project_structure(self, project_path: str, project_id: str = "default"):
        """Store entire project structure in Redis"""
        project_path = Path(project_path)
        project_data = {
            'project_root': str(project_path),
            'files': {}
        }

        react_extensions = ['*.js', '*.jsx', '*.ts', '*.tsx', '*.css', '*.scss', '*.json', '*.html']

        for root, dirs, files in os.walk(project_path):
            if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next']):
                continue

            for file in files:
                file_path = Path(root) / file
                relative_path = str(file_path.relative_to(project_path))

                if any(fnmatch.fnmatch(file, pattern) for pattern in react_extensions):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        file_key = f"{self.project_key_prefix}{project_id}:file:{relative_path}"
                        self.redis_client.set(file_key, content)

                        project_data['files'][relative_path] = {
                            'path': relative_path,
                            'size': len(content),
                            'hash': hashlib.md5(content.encode()).hexdigest()
                        }

                    except Exception as e:
                        print(f"Error reading {file_path}: {e}")

        structure_key = f"{self.project_key_prefix}{project_id}:structure"
        self.redis_client.set(structure_key, json.dumps(project_data))

        return project_data

    def get_project_structure(self, project_id: str = "default") -> Optional[Dict]:
        """Get project structure from Redis"""
        structure_key = f"{self.project_key_prefix}{project_id}:structure"
        structure_data = self.redis_client.get(structure_key)
        if structure_data:
            return json.loads(structure_data)
        return None

    def get_file_content(self, relative_path: str, project_id: str = "default") -> Optional[str]:
        """Get file content from Redis"""
        file_key = f"{self.project_key_prefix}{project_id}:file:{relative_path}"
        return self.redis_client.get(file_key)

    def get_all_files_content(self, project_id: str = "default") -> Dict[str, str]:
        """Get all files content from Redis"""
        structure = self.get_project_structure(project_id)
        if not structure:
            return {}

        files_content = {}
        for relative_path in structure['files']:
            content = self.get_file_content(relative_path, project_id)
            if content:
                files_content[relative_path] = content

        return files_content

    def search_files(self, search_term: str, project_id: str = "default") -> List[str]:
        """Search files containing specific terms"""
        structure = self.get_project_structure(project_id)
        if not structure:
            return []

        matching_files = []
        for relative_path in structure['files']:
            content = self.get_file_content(relative_path, project_id)
            if content and search_term.lower() in content.lower():
                matching_files.append(relative_path)

        return matching_files

class OllamaAnalyzer:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.model = "gpt-oss:120b-cloud"

    def auto_generate_file_changes(self, user_query: str, project_root: str):
        """Automatically generate file changes based on user query and project context"""
        print(f"🎯 Auto-generating file changes for: '{user_query}'")

        # Step 1: Dynamically find relevant files
        finder = DynamicFileFinder(project_root)
        relevant_files = finder.find_relevant_files(user_query)
        print(relevant_files)

        if not relevant_files:
            print("⚠️  No relevant files found. Using default project context.")
            # Fallback to key files if no relevant files found
            key_files_to_try = [
                'package.json',
                'src/App.js', 'src/App.jsx', 'src/App.tsx',
                'src/index.js', 'src/index.jsx', 'src/index.tsx',
                'src/main.js', 'src/main.jsx', 'src/main.tsx'
            ]

            for file in key_files_to_try:
                potential_path = os.path.join(project_root, file)
                if os.path.exists(potential_path):
                    relevant_files.append(potential_path)
                    if len(relevant_files) >= 3:  # Limit fallback files
                        break

        # Step 2: Build project context from them
        context_builder = ProjectContextBuilder()
        project_context = context_builder.build_context(relevant_files)
        print("=====project_contextproject_context")
        print(project_context)

        # Step 3: Send to Ollama
        yaml_output = self.analyze_and_generate_changes(user_query, project_context)
        return yaml_output

    def analyze_and_generate_changes(self, prompt: str, project_context: str) -> str:
        """Use Ollama to analyze project and generate specific file changes"""
        print(prompt)

        system_prompt = """You are an expert React.js developer. Analyze the user's request and the current project structure, then provide ONLY the specific file changes and required packages in YAML format.

IMPORTANT: Respond ONLY with valid YAML in this exact format:

files:
  - path: "file/path/here.js"
    content: |
      // Full file content with changes
      import React from 'react';
      import { SomeExternalLibrary } from 'some-library';

      const Component = () => {
        return <div>Content</div>;
      };

      export default Component;

  - path: "another/file/path.js"
    content: |
      // Full file content
      // with all changes included

packages:
  dependencies:
    - "package-name@version"
    - "another-package@^1.2.3"
  devDependencies:
    - "@types/package@version"

install_commands:
  - "npm install package-name@version another-package@^1.2.3"
  - "npm install --save-dev @types/package@version"

Rules:
1. Only include files that need to be created or modified
2. Provide COMPLETE file content, not just diffs
3. For existing files, include the entire content with changes
4. Use proper file paths relative to project root
5. Include all necessary imports and dependencies
6. Make sure the code is syntactically correct
7. If creating new components, include proper React patterns
8. For bug fixes, provide the corrected complete file
9. Include required packages in the packages section
10. Provide exact npm install commands in install_commands section
11. Only include packages that are actually needed for the implementation
12. Check if packages are already in package.json before including

Do not include any explanations, analysis, or text outside the YAML format."""

        full_prompt = f"""PROJECT CONTEXT:
{project_context}

USER REQUEST: {prompt}

Generate the file changes and required packages in YAML format:"""


        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "system": system_prompt,
                    "stream": False
                },
                timeout=120  # 2 minute timeout
            )
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.Timeout:
            return "Error: Request timeout - Ollama server took too long to respond"
        except Exception as e:
            return f"Error: {e}"

class ReactAIAssistant:
    def __init__(self, project_path: str, redis_host='localhost', redis_port=6379,
                 db_config=None):
        self.project_path = project_path
        self.redis_manager = RedisProjectManager(redis_host, redis_port)
        self.ollama = OllamaAnalyzer()
        self.project_id = hashlib.md5(project_path.encode()).hexdigest()[:8]

        # Initialize PostgreSQL database
        self.db = PostgresDB(**(db_config or {}))

    def initialize_project(self):
        """Initialize and store project in Redis"""
        print("🔍 Scanning and storing project structure in Redis...")
        project_data = self.redis_manager.store_project_structure(self.project_path, self.project_id)
        file_count = len(project_data['files'])
        print(f"✅ Project stored in Redis with {file_count} files (Project ID: {self.project_id})")
        return project_data

    def create_project_context(self) -> str:
        """Create comprehensive project context for Ollama"""
        structure = self.redis_manager.get_project_structure(self.project_id)
        if not structure:
            return "Project structure not found in Redis."

        context_parts = []
        context_parts.append(f"PROJECT ROOT: {structure['project_root']}")
        context_parts.append(f"TOTAL FILES: {len(structure['files'])}")

        # Add key files content
        key_files = [
            'package.json', 'src/App.js', 'src/App.jsx', 'src/App.tsx',
            'src/main.js', 'src/main.jsx', 'src/main.tsx', 'src/index.js',
            'src/index.jsx', 'src/index.tsx'
        ]

        for file_path in key_files:
            content = self.redis_manager.get_file_content(file_path, self.project_id)
            if content:
                context_parts.append(f"\n--- {file_path} ---\n{content}")

        # Add component files (first 5)
        component_files = [f for f in structure['files'] if any(f.endswith(ext) for ext in ['.jsx', '.tsx'])]
        for file_path in component_files[:5]:
            content = self.redis_manager.get_file_content(file_path, self.project_id)
            if content:
                context_parts.append(f"\n--- {file_path} ---\n{content[:500]}...")

        # Add complete dependencies info
        package_json = self.redis_manager.get_file_content('package.json', self.project_id)
        if package_json:
            try:
                package_data = json.loads(package_json)
                context_parts.append(f"\n--- CURRENT PACKAGE.JSON DEPENDENCIES ---")
                context_parts.append(f"Dependencies: {json.dumps(package_data.get('dependencies', {}), indent=2)}")
                context_parts.append(f"DevDependencies: {json.dumps(package_data.get('devDependencies', {}), indent=2)}")
            except:
                pass

        return "\n".join(context_parts)

    def extract_yaml_from_response(self, response: str) -> str:
        """Extract YAML content from Ollama response"""
        # Try to find YAML content between markers
        yaml_match = re.search(r'```yaml\n(.*?)\n```', response, re.DOTALL)
        if yaml_match:
            return yaml_match.group(1)

        # Try to find YAML content without markers
        yaml_match = re.search(r'^(files:|packages:|install_commands:)', response, re.MULTILINE)
        if yaml_match:
            return response

        # If no YAML found, return the original response wrapped in proper YAML structure
        return f'''files:
  - path: "response.txt"
    content: |
      {response}

packages:
  dependencies: []
  devDependencies: []

install_commands:
  - "echo 'No additional packages required'"'''

    def validate_and_complete_yaml(self, yaml_content: str) -> str:
        """Validate YAML and ensure all required sections are present"""
        try:
            data = yaml.safe_load(yaml_content)

            # Ensure files section exists
            if 'files' not in data:
                data['files'] = []

            # Ensure packages section exists with proper structure
            if 'packages' not in data:
                data['packages'] = {
                    'dependencies': [],
                    'devDependencies': []
                }
            else:
                if 'dependencies' not in data['packages']:
                    data['packages']['dependencies'] = []
                if 'devDependencies' not in data['packages']:
                    data['packages']['devDependencies'] = []

            # Ensure install_commands section exists
            if 'install_commands' not in data:
                data['install_commands'] = []

                # Generate install commands from packages if not provided
                deps = data['packages']['dependencies']
                dev_deps = data['packages']['devDependencies']

                if deps:
                    data['install_commands'].append(f"npm install {' '.join(deps)}")
                if dev_deps:
                    data['install_commands'].append(f"npm install --save-dev {' '.join(dev_deps)}")

                if not deps and not dev_deps:
                    data['install_commands'].append("echo 'No additional packages required'")

            return yaml.dump(data, default_flow_style=False, indent=2, allow_unicode=True, width=1000)

        except yaml.YAMLError as e:
            # Return a basic valid YAML structure with the error
            return f'''files:
  - path: "error.txt"
    content: |
      Invalid YAML response: {e}
      Original response: {yaml_content}

packages:
  dependencies: []
  devDependencies: []

install_commands:
  - "echo 'Error in YAML generation'"'''

    def apply_changes(self, yaml_response: str) -> Dict:
        """Apply the changes from YAML response to the actual project files"""
        try:
            data = yaml.safe_load(yaml_response)
            results = {
                'files_created': [],
                'files_updated': [],
                'files_failed': [],
                'packages_installed': False,
                'install_output': []
            }

            # Apply file changes
            if 'files' in data:
                for file_info in data['files']:
                    file_path = file_info['path']
                    content = file_info['content']

                    full_path = os.path.join(self.project_path, file_path)

                    try:
                        # Create directory if it doesn't exist
                        os.makedirs(os.path.dirname(full_path), exist_ok=True)

                        # Check if file exists
                        file_exists = os.path.exists(full_path)

                        # Write the file
                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write(content)

                        if file_exists:
                            results['files_updated'].append(file_path)
                            print(f"✅ Updated: {file_path}")
                        else:
                            results['files_created'].append(file_path)
                            print(f"✅ Created: {file_path}")

                    except Exception as e:
                        results['files_failed'].append(f"{file_path}: {str(e)}")
                        print(f"❌ Failed to write {file_path}: {e}")

            # Install packages if requested and confirmed
            if 'install_commands' in data and data['install_commands']:
                print("\n📦 Installing packages...")
                for command in data['install_commands']:
                    if command.startswith('npm install') and 'echo' not in command:
                        try:
                            print(f"🚀 Running: {command}")
                            # Run the install command in the project directory
                            result = subprocess.run(
                                command.split(),
                                cwd=self.project_path,
                                capture_output=True,
                                text=True,
                                timeout=120  # 2 minute timeout
                            )

                            if result.returncode == 0:
                                results['packages_installed'] = True
                                results['install_output'].append(f"✅ {command}: Success")
                                print(f"✅ Package installation successful: {command}")
                            else:
                                results['install_output'].append(f"❌ {command}: {result.stderr}")
                                print(f"❌ Package installation failed: {command}")
                                print(f"Error: {result.stderr}")

                        except subprocess.TimeoutExpired:
                            error_msg = f"❌ {command}: Timeout after 2 minutes"
                            results['install_output'].append(error_msg)
                            print(error_msg)
                        except Exception as e:
                            error_msg = f"❌ {command}: {str(e)}"
                            results['install_output'].append(error_msg)
                            print(error_msg)
                    else:
                        print(f"ℹ️  Skipping: {command}")

            # Update Redis cache with new file contents
            self.redis_manager.store_project_structure(self.project_path, self.project_id)

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

        if use_auto_generate:
            # Use the new auto-generate approach with dynamic file finding
            yaml_response = self.ollama.auto_generate_file_changes(query, self.project_path)
        else:
            # Use the old approach with Redis-based context
            project_context = self.create_project_context()
            ollama_response = self.ollama.analyze_and_generate_changes(query, project_context)
            yaml_response = self.extract_yaml_from_response(ollama_response)

        # Validate and complete the YAML structure
        final_yaml = self.validate_and_complete_yaml(yaml_response)

        # Store conversation in PostgreSQL
        conversation_id = self.db.store_conversation(session_id, query, final_yaml, self.project_id)

        if conversation_id == -1:
            print("❌ Failed to store conversation in database!")
        else:
            print(f"✅ Successfully stored conversation with ID: {conversation_id}")

        return final_yaml

    def get_project_info(self) -> Dict:
        """Get project information"""
        structure = self.redis_manager.get_project_structure(self.project_id)
        if structure:
            return {
                'project_id': self.project_id,
                'root': structure['project_root'],
                'file_count': len(structure['files']),
                'files': list(structure['files'].keys())[:10]  # First 10 files
            }
        return {}

# Web-based Chatbot UI
class ReactAIChatbotWebUI:
    def __init__(self, project_path: str, redis_host='localhost', redis_port=6379,
                 ollama_url='http://localhost:11434', host='0.0.0.0', port=5000,
                 db_config=None):
        self.assistant = ReactAIAssistant(project_path, redis_host, redis_port, db_config)
        self.assistant.ollama.base_url = ollama_url
        self.host = host
        self.port = port

        # Initialize Flask app
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'react-ai-assistant-secret-key'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # Store sessions
        self.sessions = {}

        self.setup_routes()

        # Initialize assistant
        self.initialize_assistant()

    def initialize_assistant(self):
        """Initialize the assistant"""
        try:
            project_data = self.assistant.initialize_project()
            project_info = self.assistant.get_project_info()
            print(f"✅ Project initialized: {project_info}")
        except Exception as e:
            print(f"❌ Error initializing project: {e}")

    def setup_routes(self):
        """Setup Flask routes"""
        @self.app.route('/')
        def index():
            return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>React AI Assistant 🤖</title>
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
                    max-width: 1200px;
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
                    width: 350px;
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
                .file-item {
                    padding: 8px 12px;
                    margin: 5px 0;
                    background: #f8f9fa;
                    border-radius: 8px;
                    font-size: 12px;
                    border-left: 3px solid #007bff;
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
                .pagination {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-top: 10px;
                    padding: 10px 0;
                    border-top: 1px solid #e9ecef;
                }
                .pagination button {
                    padding: 5px 10px;
                    background: #007bff;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 12px;
                }
                .pagination button:disabled {
                    background: #6c757d;
                    cursor: not-allowed;
                }
                .pagination-info {
                    font-size: 11px;
                    color: #6c757d;
                }
                .load-more {
                    width: 100%;
                    padding: 8px;
                    background: #28a745;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-top: 10px;
                }
                .load-more:hover {
                    background: #218838;
                }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>React AI Assistant 🤖</h1>
                <div class="subtitle">Describe what you want to build and I'll generate the code!</div>
            </div>

            <div class="container">
                <div class="chat-container">
                    <div class="chat-messages" id="chat-messages">
                        <div class="message system-message">
                            Welcome! I'm ready to help you with your React project. What would you like to build?
                        </div>
                    </div>
                    <div class="input-area">
                        <div class="input-group">
                            <textarea
                                id="message-input"
                                placeholder="Describe what you want to build (e.g., 'Add a contact form with validation', 'Create a navigation header')..."
                                rows="3"
                            ></textarea>
                            <button id="send-button">Send</button>
                        </div>
                    </div>
                </div>

                <div class="results-panel">
                    <h3>Project Info</h3>
                    <div id="project-info">
                        <div class="file-item">Loading project information...</div>
                    </div>
                    <h3>Recent Changes</h3>
                    <div id="recent-changes">
                        <div class="file-item">No changes yet</div>
                    </div>
                    <h3>Chat History</h3>
                    <div class="history-container" id="history-container">
                        <div id="chat-history">
                            <div class="file-item">Loading history...</div>
                        </div>
                    </div>
                    <div class="pagination" id="pagination" style="display: none;">
                        <button id="prev-page" disabled>Previous</button>
                        <span class="pagination-info" id="page-info">Page 1 of 1</span>
                        <button id="next-page" disabled>Next</button>
                    </div>
                    <button class="load-more" id="load-more" style="display: none;">Load More</button>
                </div>
            </div>

            <script>
                const socket = io();
                let currentYamlResponse = '';
                let currentSessionId = '';
                let currentPage = 1;
                let totalPages = 1;
                const perPage = 20;
                let selectedConversationId = null;

                // DOM elements
                const chatMessages = document.getElementById('chat-messages');
                const messageInput = document.getElementById('message-input');
                const sendButton = document.getElementById('send-button');
                const projectInfo = document.getElementById('project-info');
                const recentChanges = document.getElementById('recent-changes');
                const chatHistory = document.getElementById('chat-history');
                const pagination = document.getElementById('pagination');
                const prevPageBtn = document.getElementById('prev-page');
                const nextPageBtn = document.getElementById('next-page');
                const pageInfo = document.getElementById('page-info');
                const loadMoreBtn = document.getElementById('load-more');
                const historyContainer = document.getElementById('history-container');

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

                // Pagination event listeners
                prevPageBtn.addEventListener('click', () => loadPage(currentPage - 1));
                nextPageBtn.addEventListener('click', () => loadPage(currentPage + 1));
                loadMoreBtn.addEventListener('click', loadMoreConversations);

                function sendMessage() {
                    const message = messageInput.value.trim();
                    if (message) {
                        addMessage('user', message);
                        messageInput.value = '';
                        messageInput.style.height = 'auto';

                        // Show typing indicator
                        showTypingIndicator();

                        // Send to server
                        socket.emit('send_message', { message: message });

                        // Disable input while processing
                        sendButton.disabled = true;
                        messageInput.disabled = true;
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

                function addMessage(sender, content, isYaml = false, conversationId = null) {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = `message ${sender}-message`;
                    if (conversationId) {
                        messageDiv.setAttribute('data-conversation-id', conversationId);
                    }

                    if (isYaml) {
                        const formattedYaml = formatYAML(content);
                        messageDiv.innerHTML = `
                            <strong>${sender === 'user' ? 'You' : 'Assistant'}:</strong>
                            <div class="code-container">
                                <div class="code-header">
                                    <span>YAML Configuration</span>
                                    <button class="copy-button" onclick="copyToClipboard(this, ${JSON.stringify(content).replace(/"/g, '&quot;')})">Copy</button>
                                </div>
                                <div class="code-content">${formattedYaml}</div>
                            </div>
                            ${sender === 'assistant' ?
                                '<div class="action-buttons">' +
                                    '<button class="apply-button" onclick="applyChanges()">Apply Changes</button>' +
                                    '<button class="save-button" onclick="saveChanges()">Save Changes</button>' +
                                    '<button class="rollback-button" onclick="rollbackChanges()">Rollback</button>' +
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
                        socket.emit('apply_changes', { yaml_response: currentYamlResponse });
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
                    if (confirm('Are you sure you want to rollback all changes? This will run: git checkout . && git clean -f && nvm use 20 && npm run dev')) {
                        socket.emit('rollback_changes');
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

                function loadConversationToChat(conversationId, query, yamlResponse) {
                    // Clear current chat
                    chatMessages.innerHTML = '<div class="message system-message">Loaded from history:</div>';

                    // Add the conversation to chat
                    addMessage('user', query, false, conversationId);
                    if (yamlResponse && yamlResponse !== 'No YAML response') {
                        addMessage('assistant', yamlResponse, true, conversationId);
                    } else {
                        addMessage('assistant', 'No YAML response available', false, conversationId);
                    }

                    // Set current YAML response for applying changes
                    currentYamlResponse = yamlResponse;
                    selectedConversationId = conversationId;

                    // Scroll to bottom
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }

                function updateProjectInfo(info) {
                    if (info && info.root) {
                        projectInfo.innerHTML = `
                            <div class="file-item success">
                                <strong>Project:</strong> ${info.root.split('/').pop()}
                            </div>
                            <div class="file-item">
                                <strong>Files:</strong> ${info.file_count}
                            </div>
                            <div class="file-item">
                                <strong>ID:</strong> ${info.project_id}
                            </div>
                        `;
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
                    console.log('Updating chat history with:', history);

                    if (history && history.length > 0) {
                        let historyHTML = '';

                        history.forEach(conv => {
                            const date = new Date(conv.created_at).toLocaleString();
                            const shortQuery = conv.query && conv.query.length > 50 ?
                                conv.query.substring(0, 50) + '...' : conv.query || 'No query';
                            const shortYaml = conv.yaml_response && conv.yaml_response.length > 100 ?
                                conv.yaml_response.substring(0, 100) + '...' : conv.yaml_response || 'No YAML response';

                            historyHTML += `
                                <div class="history-item" data-conversation-id="${conv.id}">
                                    <strong>${date}</strong><br>
                                    <strong>Q:</strong> ${shortQuery}<br>
                                    <strong>A:</strong> ${shortYaml}
                                    <div class="history-yaml">${conv.yaml_response || 'No YAML response'}</div>
                                    <div class="history-actions">
                                        <button class="load-chat-btn" onclick="loadConversationToChat(${conv.id}, ${JSON.stringify(conv.query).replace(/"/g, '&quot;')}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Load in Chat</button>
                                        <button class="apply-history-btn" onclick="applyHistoryChanges(${conv.id}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Apply Changes</button>
                                        <button class="save-history-btn" onclick="saveHistoryChanges(${conv.id}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Save Changes</button>
                                    </div>
                                </div>
                            `;
                        });

                        chatHistory.innerHTML = historyHTML;

                        // Add click event listeners to history items
                        document.querySelectorAll('.history-item').forEach(item => {
                            item.addEventListener('click', function(e) {
                                // Don't trigger if clicking on buttons
                                if (!e.target.classList.contains('load-chat-btn') && !e.target.classList.contains('apply-history-btn') && !e.target.classList.contains('save-history-btn')) {
                                    // Toggle active state
                                    document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
                                    this.classList.add('active');

                                    // Toggle actions visibility
                                    const actions = this.querySelector('.history-actions');
                                    if (actions) {
                                        actions.style.display = actions.style.display === 'flex' ? 'none' : 'flex';
                                    }

                                    // Toggle YAML preview
                                    const yamlDiv = this.querySelector('.history-yaml');
                                    if (yamlDiv) {
                                        yamlDiv.style.display = yamlDiv.style.display === 'block' ? 'none' : 'block';
                                    }
                                }
                            });
                        });
                    } else {
                        chatHistory.innerHTML = '<div class="file-item">No history yet</div>';
                    }
                }

                function updatePagination(totalCount, page, totalPages) {
                    pageInfo.textContent = `Page ${page} of ${totalPages} (${totalCount} total)`;
                    prevPageBtn.disabled = page <= 1;
                    nextPageBtn.disabled = page >= totalPages;

                    if (totalPages > 1) {
                        pagination.style.display = 'flex';
                    } else {
                        pagination.style.display = 'none';
                    }
                }

                function loadPage(page) {
                    socket.emit('get_paginated_conversations', { page: page, per_page: perPage });
                }

                function loadMoreConversations() {
                    currentPage++;
                    socket.emit('get_paginated_conversations', { page: currentPage, per_page: perPage, append: true });
                }

                // Socket event handlers
                socket.on('connect', function() {
                    console.log('Connected to server');
                    currentSessionId = socket.id;
                    socket.emit('get_project_info');
                    // Load all conversations by default instead of just session-specific
                    socket.emit('get_all_conversations');
                });

                socket.on('project_info', function(data) {
                    updateProjectInfo(data);
                });

                socket.on('assistant_response', function(data) {
                    hideTypingIndicator();
                    currentYamlResponse = data.yaml_response;
                    addMessage('assistant', data.yaml_response, true);

                    // Refresh chat history to show the new conversation
                    socket.emit('get_all_conversations');

                    // Re-enable input
                    sendButton.disabled = false;
                    messageInput.disabled = false;
                    messageInput.focus();
                });

                socket.on('application_results', function(data) {
                    addMessage('system', '✅ Changes applied successfully!');
                    updateRecentChanges(data.results);

                    // Refresh history to show applied status
                    socket.emit('get_all_conversations');
                });

                socket.on('save_results', function(data) {
                    addMessage('system', `✅ Changes saved with git! Commit: "${data.commit_message}"`);

                    // Show detailed results
                    if (data.results.commands_run && data.results.commands_run.length > 0) {
                        let details = 'Commands executed:\\n' + data.results.commands_run.join('\\n');
                        addMessage('system', details);
                    }
                });

                socket.on('rollback_results', function(data) {
                    addMessage('system', '✅ Rollback completed! All changes reverted and dev server restarted.');

                    // Show detailed results
                    if (data.results.commands_run && data.results.commands_run.length > 0) {
                        let details = 'Rollback commands:\\n' + data.results.commands_run.join('\\n');
                        addMessage('system', details);
                    }

                    // Refresh project info to reflect rolled back state
                    socket.emit('get_project_info');
                });

                socket.on('chat_history', function(data) {
                    console.log('Received session chat history:', data.history);
                    updateChatHistory(data.history);
                });

                socket.on('all_conversations', function(data) {
                    console.log('Received all conversations:', data.conversations);
                    updateChatHistory(data.conversations);

                    // Show load more button if there are many conversations
                    if (data.conversations.length >= 50) {
                        loadMoreBtn.style.display = 'block';
                    } else {
                        loadMoreBtn.style.display = 'none';
                    }
                });

                socket.on('paginated_conversations', function(data) {
                    console.log('Received paginated conversations:', data);
                    currentPage = data.page;
                    totalPages = data.total_pages;

                    if (data.append) {
                        // Append to existing history
                        let existingHTML = chatHistory.innerHTML;
                        let newHTML = '';

                        data.conversations.forEach(conv => {
                            const date = new Date(conv.created_at).toLocaleString();
                            const shortQuery = conv.query && conv.query.length > 50 ?
                                conv.query.substring(0, 50) + '...' : conv.query || 'No query';
                            const shortYaml = conv.yaml_response && conv.yaml_response.length > 100 ?
                                conv.yaml_response.substring(0, 100) + '...' : conv.yaml_response || 'No YAML response';

                            newHTML += `
                                <div class="history-item" data-conversation-id="${conv.id}">
                                    <strong>${date}</strong><br>
                                    <strong>Q:</strong> ${shortQuery}<br>
                                    <strong>A:</strong> ${shortYaml}
                                    <div class="history-yaml">${conv.yaml_response || 'No YAML response'}</div>
                                    <div class="history-actions">
                                        <button class="load-chat-btn" onclick="loadConversationToChat(${conv.id}, ${JSON.stringify(conv.query).replace(/"/g, '&quot;')}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Load in Chat</button>
                                        <button class="apply-history-btn" onclick="applyHistoryChanges(${conv.id}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Apply Changes</button>
                                        <button class="save-history-btn" onclick="saveHistoryChanges(${conv.id}, ${JSON.stringify(conv.yaml_response || '').replace(/"/g, '&quot;')})">Save Changes</button>
                                    </div>
                                </div>
                            `;
                        });

                        chatHistory.innerHTML = existingHTML + newHTML;
                    } else {
                        // Replace history
                        updateChatHistory(data.conversations);
                    }

                    updatePagination(data.total_count, data.page, data.total_pages);
                });

                socket.on('error', function(data) {
                    hideTypingIndicator();
                    addMessage('system', `❌ Error: ${data.error}`);

                    // Re-enable input
                    sendButton.disabled = false;
                    messageInput.disabled = false;
                    messageInput.focus();
                });
            </script>
        </body>
        </html>
            """

        @self.socketio.on('connect')
        def handle_connect():
            session_id = request.sid
            self.sessions[session_id] = {
                'current_yaml': ''
            }
            print(f"Client connected: {session_id}")
            # Send project info to newly connected client
            project_info = self.assistant.get_project_info()
            emit('project_info', project_info)

        @self.socketio.on('send_message')
        def handle_message(data):
            @copy_current_request_context
            def process_message():
                try:
                    query = data['message']
                    session_id = request.sid
                    print(f"Processing query: {query}")

                    # Process the query using auto-generate mode
                    yaml_response = self.assistant.process_query(query, session_id, use_auto_generate=False)

                    # Store the YAML response in session
                    self.sessions[session_id] = {'current_yaml': yaml_response}

                    # Send response back to client
                    emit('assistant_response', {
                        'yaml_response': yaml_response
                    })

                except Exception as e:
                    print(f"Error processing message: {e}")
                    emit('error', {'error': str(e)})

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
                    print(f"Applying changes from YAML response (Conversation ID: {conversation_id})...")

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
                        'results': results
                    })

                except Exception as e:
                    print(f"Error applying changes: {e}")
                    emit('error', {'error': str(e)})

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

                    print(f"Saving changes with git (Conversation ID: {conversation_id})...")

                    # Get the last applied query for the commit message
                    commit_message = "commit files with last which is applied query"
                    if conversation_id:
                        conversation = self.assistant.db.get_conversation_by_id(conversation_id)
                        if conversation and conversation.get('query'):
                            commit_message = f"Applied: {conversation['query'][:50]}..."

                    # Execute git commands
                    results = {
                        'git_add': '',
                        'git_commit': '',
                        'commands_run': []
                    }

                    try:
                        # Git add all changes
                        result = subprocess.run(
                            ['git', 'add', '.'],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        results['git_add'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append('git add .')

                        # Git commit
                        result = subprocess.run(
                            ['git', 'commit', '-m', commit_message],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        results['git_commit'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append(f'git commit -m "{commit_message}"')

                        print(f"✅ Changes saved with git commit: {commit_message}")

                    except Exception as e:
                        results['error'] = str(e)
                        print(f"❌ Error saving changes with git: {e}")

                    # Send results back to client
                    emit('save_results', {
                        'results': results,
                        'commit_message': commit_message
                    })

                except Exception as e:
                    print(f"Error saving changes: {e}")
                    emit('error', {'error': str(e)})

            thread = threading.Thread(target=save_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('rollback_changes')
        def handle_rollback_changes():
            @copy_current_request_context
            def rollback_changes_thread():
                try:
                    print("Rolling back changes...")

                    results = {
                        'git_checkout': '',
                        'git_clean': '',
                        'nvm_use': '',
                        'npm_dev': '',
                        'commands_run': []
                    }

                    try:
                        # Git checkout - revert all changes
                        result = subprocess.run(
                            ['git', 'checkout', '.'],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        results['git_checkout'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append('git checkout .')

                        # Git clean - remove untracked files
                        result = subprocess.run(
                            ['git', 'clean', '-f'],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        results['git_clean'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append('git clean -f')

                        # NVM use 20
                        result = subprocess.run(
                            ['nvm', 'use', '20'],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30,
                            shell=True  # nvm is a shell function
                        )
                        results['nvm_use'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append('nvm use 20')

                        # npm run dev
                        result = subprocess.run(
                            ['npm', 'run', 'dev'],
                            cwd=self.assistant.project_path,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        results['npm_dev'] = result.stdout if result.returncode == 0 else result.stderr
                        results['commands_run'].append('npm run dev')

                        print("✅ Rollback completed successfully")

                    except Exception as e:
                        results['error'] = str(e)
                        print(f"❌ Error during rollback: {e}")

                    # Update Redis cache after rollback
                    self.assistant.redis_manager.store_project_structure(self.assistant.project_path, self.assistant.project_id)

                    # Send results back to client
                    emit('rollback_results', {
                        'results': results
                    })

                except Exception as e:
                    print(f"Error during rollback: {e}")
                    emit('error', {'error': str(e)})

            thread = threading.Thread(target=rollback_changes_thread)
            thread.daemon = True
            thread.start()

        @self.socketio.on('get_project_info')
        def handle_get_project_info():
            project_info = self.assistant.get_project_info()
            emit('project_info', project_info)

        @self.socketio.on('get_chat_history')
        def handle_get_chat_history():
            session_id = request.sid
            history = self.assistant.db.get_conversation_history(session_id, 10)
            emit('chat_history', {'history': history})

        @self.socketio.on('get_all_conversations')
        def handle_get_all_conversations():
            """Get all conversations across all sessions"""
            all_conversations = self.assistant.db.get_all_conversations(100)
            print(f"📤 Sending ALL conversations to client: {len(all_conversations)} total")
            emit('all_conversations', {'conversations': all_conversations})

        @self.socketio.on('get_paginated_conversations')
        def handle_get_paginated_conversations(data):
            """Get conversations with pagination"""
            page = data.get('page', 1)
            per_page = data.get('per_page', 20)
            append = data.get('append', False)

            paginated_data = self.assistant.db.get_conversations_with_pagination(page, per_page)
            print(f"📤 Sending paginated conversations: page {page}, {len(paginated_data['conversations'])} items")

            response_data = {
                'conversations': paginated_data['conversations'],
                'total_count': paginated_data['total_count'],
                'page': paginated_data['page'],
                'per_page': paginated_data['per_page'],
                'total_pages': paginated_data['total_pages'],
                'append': append
            }

            emit('paginated_conversations', response_data)

        @self.socketio.on('get_conversation_by_id')
        def handle_get_conversation_by_id(data):
            """Get a specific conversation by ID"""
            conversation_id = data.get('conversation_id')
            if conversation_id:
                conversation = self.assistant.db.get_conversation_by_id(conversation_id)
                if conversation:
                    emit('conversation_loaded', {'conversation': conversation})
                else:
                    emit('error', {'error': f'Conversation with ID {conversation_id} not found'})

    def run(self):
        """Start the web server"""
        print(f"🚀 Starting React AI Assistant Web UI...")
        print(f"📁 Project: {self.assistant.project_path}")
        print(f"🌐 Web interface: http://{self.host}:{self.port}")
        print("💡 Open the above URL in your browser to start chatting!")
        print("🗄️  PostgreSQL database is active and storing all conversations")
        print("🎯 Using AUTO-GENERATE mode with dynamic file finding")

        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='React AI Assistant')
    parser.add_argument('project_path', help='Path to React project directory')
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
    parser.add_argument('--db-name', default='react_ai_assistant', help='PostgreSQL database name')
    parser.add_argument('--db-user', default='postgres', help='PostgreSQL username')
    parser.add_argument('--db-password', default='password', help='PostgreSQL password')

    args = parser.parse_args()

    if not os.path.exists(args.project_path):
        print(f"❌ Error: Project path '{args.project_path}' does not exist!")
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
        assistant = ReactAIAssistant(args.project_path, args.redis_host, args.redis_port, db_config)
        assistant.ollama.base_url = args.ollama_url
        assistant.initialize_project()

        # Show project info
        project_info = assistant.get_project_info()
        if project_info:
            print(f"\n📁 Project: {project_info['root']}")
            print(f"📊 Files: {project_info['file_count']}")
            print(f"🔑 Project ID: {project_info['project_id']}")

        print("\n" + "="*60)
        print("🤖 React AI Assistant Ready!")
        print("🗄️  PostgreSQL database active - storing all conversations")
        print("🎯 Using AUTO-GENERATE mode with dynamic file finding")
        print("="*60)

        while True:
            try:
                user_input = input("\n💬 Enter your query: ").strip()

                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break

                if user_input:
                    # Process query using auto-generate mode
                    response = assistant.process_query(user_input, "cli_session", use_auto_generate=True)
                    print("\n" + "="*60)
                    print("📋 IMPLEMENTATION DETAILS:")
                    print("="*60)
                    print(response)

                    # Ask user if they want to apply changes
                    print("\n" + "="*60)
                    print("🚀 ACTION REQUIRED:")
                    print("="*60)
                    print("Do you want to apply these changes to your project?")
                    print("1. Apply - Write files and install packages")
                    print("2. Cancel - Discard changes")

                    while True:
                        action = input("\nChoose action (1 for Apply, 2 for Cancel): ").strip()

                        if action == '1':
                            print("\n🔄 Applying changes...")
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
        chatbot = ReactAIChatbotWebUI(
            args.project_path,
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