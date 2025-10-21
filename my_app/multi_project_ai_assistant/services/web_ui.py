import threading
import uuid
import os
import subprocess
import shutil
from typing import List, Dict
from flask import Flask, request, jsonify, copy_current_request_context, make_response, redirect, url_for
from flask_socketio import SocketIO, emit
import requests
import json
from datetime import datetime
import re

from services.ai_assistant import MultiProjectAIAssistant
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO
import os
from openai import OpenAI
from models.upload_manager import UploadManager


class MultiProjectAIChatbotWebUI:
    def __init__(self, project_paths: List[str], redis_config: Dict, db_config: Dict,
                 ollama_url: str = 'http://localhost:11434', host: str = '0.0.0.0', port: int = 5000):
        self.base_project_dir = "/media/shivareddy/E/oct-2025/15_evg/oct/user_projects"
        self.assistant = None
        self.redis_config = redis_config
        self.db_config = db_config
        self.ollama_url = ollama_url
        self.host = host
        self.port = port

        # Create base project directory if it doesn't exist
        os.makedirs(self.base_project_dir, exist_ok=True)

        # Paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        static_dir = os.path.join(base_dir, '..', 'static')
        template_dir = os.path.join(static_dir, 'templates')

        self.app = Flask(__name__,
                        static_folder=static_dir,
                        template_folder=template_dir)

        # REMOVE upload limits
        self.app.config['MAX_CONTENT_LENGTH'] = None  # Remove file size limit
        self.app.config['SECRET_KEY'] = 'multi-project-ai-assistant-secret-key'

        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # === INITIALIZE UPLOAD MANAGER ===
        self.upload_manager = UploadManager(self)
        print("✅ UploadManager initialized")

        # Store user sessions
        self.user_sessions = {}

        self.setup_routes()

    def get_ollama_models(self):
        """Get available models from Ollama"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models_data = response.json()
                models = [model['name'] for model in models_data.get('models', [])]
                print(f"📋 Found {len(models)} Ollama models")
                return models
            else:
                print(f"❌ Failed to fetch Ollama models: {response.status_code}")
                return []
        except Exception as e:
            print(f"❌ Error fetching Ollama models: {e}")
            return []

    def get_openai_models(self, api_key):
        """Get available models from OpenAI"""
        try:
            client = OpenAI(api_key=api_key)
            models = client.models.list()
            model_names = [model.id for model in models.data]
            # Filter for chat models
            chat_models = [model for model in model_names if any(x in model for x in ['gpt', 'claude', 'chat'])]
            print(f"📋 Found {len(chat_models)} OpenAI models")
            return chat_models
        except Exception as e:
            print(f"❌ Error fetching OpenAI models: {e}")
            return []

    def get_openrouter_models(self, api_key, free_only=True):
        """Fetch OpenRouter models (optionally only free ones)."""
        import requests

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            response = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=10)
            response.raise_for_status()

            models = response.json().get("data", [])

            if free_only:
                # Filter models that are likely free
                free_models = [
                    m["id"] for m in models
                    if m.get("id", "").endswith(":free")
                    or float(m.get("pricing", {}).get("prompt", "0")) == 0.0
                ]
                print(f"✅ Found {len(free_models)} free OpenRouter models")
                return free_models
            else:
                all_models = [m["id"] for m in models]
                print(f"📋 Found {len(all_models)} total OpenRouter models")
                return all_models

        except Exception as e:
            print(f"❌ Error fetching OpenRouter models: {e}")
            return []

    def get_anthropic_models(self, api_key):
        """Get available models from Anthropic"""
        try:
            # Anthropic models are typically fixed
            models = [
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-2.1",
                "claude-2.0",
                "claude-instant-1.2"
            ]
            print(f"📋 Found {len(models)} Anthropic models")
            return models
        except Exception as e:
            print(f"❌ Error fetching Anthropic models: {e}")
            return []

    def get_user_assistant(self, user_id: int, project_paths: List[str]):
        """Get or create AI assistant for user"""
        if not project_paths:
            return None

        # Create new assistant instance for user
        assistant = MultiProjectAIAssistant(project_paths, self.redis_config, self.db_config)
        assistant.ollama.base_url = self.ollama_url

        try:
            project_data = assistant.initialize_projects()
            print(f"✅ User {user_id} projects initialized: {len(project_paths)} projects")
            return assistant
        except Exception as e:
            print(f"❌ Error initializing user {user_id} projects: {e}")
            return None

    def serialize_user_data(self, user_data):
        """Convert datetime objects to strings for JSON serialization"""
        if isinstance(user_data, dict):
            return {key: self.serialize_user_data(value) for key, value in user_data.items()}
        elif isinstance(user_data, list):
            return [self.serialize_user_data(item) for item in user_data]
        elif isinstance(user_data, datetime):
            return user_data.isoformat()
        else:
            return user_data

    def serialize_conversation(self, conversation):
        """Serialize a single conversation for JSON"""
        serialized = {
            'id': conversation['id'],
            'session_id': conversation['session_id'],
            'query': conversation['query'],
            'yaml_response': conversation['yaml_response'],
            'model_used': conversation['model_used'],
            'provider': conversation['provider']
        }

        # Add created_at only if it exists
        if 'created_at' in conversation and conversation['created_at']:
            serialized['created_at'] = conversation['created_at'].isoformat()
        else:
            serialized['created_at'] = None

        return serialized

    def serialize_project(self, project):
        """Serialize a project for JSON"""
        serialized = {
            'id': project['id'],
            'project_name': project['project_name'],
            'project_type': project['project_type'],
            'project_path': project['project_path'],
            'port_number': project['port_number']
        }

        # Add created_at only if it exists
        if 'created_at' in project and project['created_at']:
            serialized['created_at'] = project['created_at'].isoformat()
        else:
            serialized['created_at'] = None

        return serialized

    def setup_routes(self):
        """Setup Flask routes and SocketIO events"""
        import os
        from werkzeug.exceptions import RequestEntityTooLarge

        @self.app.before_request
        def disable_content_length_check():
            # Bypass content length checking for upload endpoint
            if request.endpoint == 'api_upload_project':
                # Disable the content length check for file uploads
                pass

        # Helper to get user from token
        def get_current_user():
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not token:
                # Also check cookies for token
                token = request.cookies.get('token')
            if not token:
                return None

            try:
                from models.database import PostgresDB
                db = PostgresDB(self.db_config)
                user_id = db.verify_token(token)
                if user_id:
                    return db.get_user_by_id(user_id)
                return None
            except Exception as e:
                print(f"Error getting current user: {e}")
                return None

        # ---------------------------
        # Page Routes - FIXED REDIRECTS
        # ---------------------------

        @self.app.route('/')
        def index():
            """Main route - fixed to prevent redirect loops"""
            user = get_current_user()
            if user:
                print(f"✅ User {user['username']} authenticated, showing main app")
                return render_template('index.html')
            else:
                print("🔐 User not authenticated, showing auth page")
                return render_template('auth.html')

        @self.app.route('/auth')
        def auth():
            """Auth page - redirect to main if already authenticated"""
            user = get_current_user()
            if user:
                print(f"✅ User already authenticated, redirecting to main app")
                return redirect('/')
            return render_template('auth.html')

        @self.app.route('/projects')
        def projects():
            """Projects page - redirect to auth if not authenticated"""
            user = get_current_user()
            if not user:
                print("🔐 User not authenticated, redirecting to auth")
                return redirect('/auth')
            return render_template('projects.html')

        @self.app.route('/profile')
        def profile():
            """Profile page - redirect to auth if not authenticated"""
            user = get_current_user()
            if not user:
                print("🔐 User not authenticated, redirecting to auth")
                return redirect('/auth')
            return render_template('profile.html')

        # Debug route to check authentication status
        @self.app.route('/debug/auth')
        def debug_auth():
            user = get_current_user()
            token = request.cookies.get('token')
            return jsonify({
                'has_user': bool(user),
                'has_token': bool(token),
                'user_agent': request.headers.get('User-Agent')
            })

        # ---------------------------
        # API Routes for Authentication
        # ---------------------------

        @self.app.route('/api/signup', methods=['POST'])
        def api_signup():
            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                username = data.get('username')
                email = data.get('email')
                password = data.get('password')

                if not all([username, email, password]):
                    return jsonify({'success': False, 'error': 'All fields are required'})

                user_id = db.create_user(username, email, password)
                if user_id:
                    token = db.generate_token(user_id)
                    user = db.get_user_by_id(user_id)

                    # Safely serialize user data
                    serialized_user = {
                        'id': user['id'],
                        'username': user['username'],
                        'email': user['email']
                    }

                    # Add created_at only if it exists
                    if 'created_at' in user:
                        serialized_user['created_at'] = user['created_at'].isoformat() if user['created_at'] else None

                    response = jsonify({
                        'success': True,
                        'token': token,
                        'user': serialized_user
                    })
                    # Set token as cookie for automatic authentication
                    response.set_cookie('token', token, httponly=True, max_age=7*24*60*60)  # 7 days
                    return response
                else:
                    return jsonify({'success': False, 'error': 'Username or email already exists'})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/login', methods=['POST'])
        def api_login():
            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                email = data.get('email')
                password = data.get('password')

                print(f"🔐 Login attempt for email: {email}")

                if not email or not password:
                    return jsonify({'success': False, 'error': 'Email and password are required'})

                user = db.authenticate_user(email, password)
                if user:
                    token = db.generate_token(user['id'])

                    # Safely serialize user data
                    user_info = {
                        'id': user['id'],
                        'username': user['username'],
                        'email': user['email']
                    }

                    # Add created_at only if it exists
                    if 'created_at' in user:
                        user_info['created_at'] = user['created_at'].isoformat() if user['created_at'] else None

                    print(f"✅ Login successful for user: {user['username']}")

                    response = jsonify({
                        'success': True,
                        'token': token,
                        'user': user_info
                    })
                    # Set token as cookie for automatic authentication
                    response.set_cookie('token', token, httponly=True, max_age=7*24*60*60)  # 7 days
                    return response
                else:
                    print(f"❌ Login failed for email: {email}")
                    return jsonify({'success': False, 'error': 'Invalid email or password'})
            except Exception as e:
                print(f"❌ Login error: {e}")
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/logout', methods=['POST'])
        def api_logout():
            response = jsonify({'success': True, 'message': 'Logged out successfully'})
            response.set_cookie('token', '', expires=0)
            return response

        @self.app.route('/api/check_auth')
        def api_check_auth():
            """Check if user is authenticated"""
            user = get_current_user()
            if user:
                serialized_user = {
                    'id': user['id'],
                    'username': user['username'],
                    'email': user['email']
                }

                # Add created_at only if it exists
                if 'created_at' in user:
                    serialized_user['created_at'] = user['created_at'].isoformat() if user['created_at'] else None

                return jsonify({
                    'authenticated': True,
                    'user': serialized_user
                })
            return jsonify({'authenticated': False})

        @self.app.route('/api/forgot_password', methods=['POST'])
        def api_forgot_password():
            # Implementation for forgot password
            return jsonify({'success': True, 'message': 'Reset link would be sent to email'})

        @self.app.route('/api/reset_password', methods=['POST'])
        def api_reset_password():
            # Implementation for reset password
            return jsonify({'success': True, 'message': 'Password reset successfully'})

        # ---------------------------
        # API Routes for Project Management
        # ---------------------------

        @self.app.route('/api/clone_project', methods=['POST'])
        def api_clone_project():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            import subprocess
            import shutil
            import os
            import re
            from datetime import datetime

            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                git_url = data.get('git_url')
                project_name = data.get('project_name')
                project_type = data.get('project_type', 'auto')
                git_username = data.get('git_username', '')
                git_token = data.get('git_token', '')

                if not git_url:
                    return jsonify({'success': False, 'error': 'Git URL is required'})

                # Check if Git is available
                try:
                    result = subprocess.run(['git', '--version'], capture_output=True, text=True)
                    if result.returncode != 0:
                        return jsonify({'success': False, 'error': 'Git is not installed or not available on the system'})
                except Exception as e:
                    return jsonify({'success': False, 'error': f'Git is not available: {str(e)}'})

                # Validate Git URL format
                if not (git_url.startswith('http') or git_url.startswith('git@')):
                    return jsonify({'success': False, 'error': 'Invalid Git URL format. Use http://, https://, or git@'})

                # Extract project name if not provided
                if not project_name:
                    if git_url.endswith('.git'):
                        project_name = git_url.split('/')[-1].replace('.git', '')
                    else:
                        project_name = git_url.split('/')[-1]
                    if not project_name:
                        project_name = f"project_{int(datetime.now().timestamp())}"

                # Clean name
                project_name = re.sub(r'[^\w\-_.]', '_', project_name)

                # Build directories
                user_dir = os.path.join(self.base_project_dir, str(user['id']))
                os.makedirs(user_dir, exist_ok=True)
                project_dir = os.path.join(user_dir, project_name)

                # --- Check and handle existing project record ---
                existing_project = db.execute_query(
                    "SELECT id FROM user_projects WHERE user_id = %s AND project_name = %s",
                    (user['id'], project_name),
                    fetch=True
                )
                if existing_project:
                    print(f"⚠️ Project '{project_name}' already exists — removing old record and folder.")
                    db.execute_query(
                        "DELETE FROM user_projects WHERE user_id = %s AND project_name = %s",
                        (user['id'], project_name)
                    )
                    if os.path.exists(project_dir):
                        try:
                            shutil.rmtree(project_dir)
                            print(f"🧹 Removed old project folder: {project_dir}")
                        except Exception as e:
                            print(f"⚠️ Failed to remove old folder: {e}")

                # Ensure directory clean
                if os.path.exists(project_dir):
                    shutil.rmtree(project_dir)
                os.makedirs(project_dir, exist_ok=True)

                # Generate unique Redis project ID
                redis_project_id = f"user_{user['id']}_{project_name}_{int(datetime.now().timestamp())}"

                print(f"🔍 DEBUG: Starting Git clone task...")

                # Start background Git clone process
                task_id = self.upload_manager.start_git_clone_task(
                    user['id'], project_name, git_url, project_dir, redis_project_id, git_username, git_token
                )

                return jsonify({
                    'success': True,
                    'redis_project_id': redis_project_id,
                    'message': 'Git clone started in background',
                    'task_id': task_id,
                    'project_name': project_name,
                    'project_path': project_dir
                })

            except Exception as e:
                print(f"❌ Error starting git clone: {e}")
                return jsonify({'success': False, 'error': f'Git clone failed: {str(e)}'})


        @self.app.route('/api/git_progress/<redis_project_id>')
        def api_git_progress(redis_project_id):
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            try:
                # Get progress from Git-specific storage
                if hasattr(self, 'upload_manager'):
                    progress = self.upload_manager.get_git_progress(user['id'], redis_project_id)
                    if progress:
                        return jsonify({'success': True, 'progress': progress})

                return jsonify({'success': True, 'progress': {
                    'status': 'starting',
                    'percentage': 0,
                    'message': '🚀 Preparing Git clone...',
                    'terminal_output': ['> Initializing Git clone process...']
                }})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/delete_project', methods=['POST'])
        def api_delete_project():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                project_id = data.get('project_id')

                # Get project info first - WORKS FOR BOTH UPLOAD AND CLONE
                project = db.get_project_by_id(project_id, user['id'])
                if not project:
                    return jsonify({'success': False, 'error': 'Project not found'})

                # Get Redis project ID - WORKS FOR BOTH
                redis_project_id = project.get('redis_project_id')

                # Delete from Redis if we have an assistant and Redis project ID - WORKS FOR BOTH
                if redis_project_id and self.assistant:
                    self.assistant.redis_manager.delete_user_project(user['id'], redis_project_id)
                    print(f"✅ Deleted project from Redis: {redis_project_id}")

                # Delete from database - WORKS FOR BOTH
                query = "DELETE FROM user_projects WHERE id = %s AND user_id = %s"
                rows_affected = db.execute_query(query, (project_id, user['id']))

                if rows_affected > 0:
                    # Delete project directory - WORKS FOR BOTH
                    project_path = project['project_path']
                    if os.path.exists(project_path):
                        shutil.rmtree(project_path)
                        print(f"✅ Deleted project directory: {project_path}")
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': 'Failed to delete project'})

            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.errorhandler(413)
        def too_large(e):
            return jsonify({
                'success': False,
                'error': 'File too large. Maximum upload size is 500MB. Please upload smaller projects or split your project.'
            }), 413

        @self.app.route('/api/create_project', methods=['POST'])
        def api_create_project():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                project_name = data.get('project_name')
                project_type = data.get('project_type')

                # Create user directory
                user_dir = os.path.join(self.base_project_dir, str(user['id']))
                os.makedirs(user_dir, exist_ok=True)

                # Create project directory
                project_dir = os.path.join(user_dir, project_name)

                if project_type == 'react':
                    # Create React app
                    subprocess.run(['npx', 'create-react-app', project_name], cwd=user_dir, check=True)
                elif project_type == 'node':
                    # Create Node.js app
                    os.makedirs(project_dir)
                    package_json = {
                        "name": project_name,
                        "version": "1.0.0",
                        "main": "index.js",
                        "scripts": {
                            "start": "node index.js"
                        }
                    }
                    with open(os.path.join(project_dir, 'package.json'), 'w') as f:
                        json.dump(package_json, f, indent=2)
                    with open(os.path.join(project_dir, 'index.js'), 'w') as f:
                        f.write('console.log("Hello from Node.js!");')
                elif project_type == 'rails':
                    # Create Rails API
                    subprocess.run(['rails', 'new', project_name, '--api'], cwd=user_dir, check=True)

                # Store project in database
                project_id = db.create_user_project(user['id'], project_name, project_type, project_dir)

                if project_id:
                    return jsonify({'success': True, 'project_id': project_id})
                else:
                    # Clean up on failure
                    shutil.rmtree(project_dir, ignore_errors=True)
                    return jsonify({'success': False, 'error': 'Failed to create project'})

            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/get_user_projects')
        def api_get_user_projects():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                projects = db.get_user_projects(user['id'])
                serialized_projects = [self.serialize_project(project) for project in projects]
                return jsonify({'success': True, 'projects': serialized_projects})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/load_project', methods=['POST'])
        def api_load_project():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                project_id = data.get('project_id')

                project = db.get_project_by_id(project_id, user['id'])
                if project:
                    serialized_project = self.serialize_project(project)
                    return jsonify({'success': True, 'project': serialized_project})
                else:
                    return jsonify({'success': False, 'error': 'Project not found'})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        # ---------------------------
        # API Routes for Profile Management
        # ---------------------------

        @self.app.route('/api/save_api_key', methods=['POST'])
        def api_save_api_key():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                provider = data.get('provider')
                api_key = data.get('api_key')

                success = db.save_api_key(user['id'], provider, api_key)
                return jsonify({'success': success})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/get_user_api_keys')
        def api_get_user_api_keys():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                keys = db.get_user_api_keys(user['id'])
                serialized_keys = []
                for key in keys:
                    serialized_key = {
                        'provider': key['provider']
                    }

                    # Add created_at only if it exists
                    if 'created_at' in key and key['created_at']:
                        serialized_key['created_at'] = key['created_at'].isoformat()
                    else:
                        serialized_key['created_at'] = None

                    # Add updated_at only if it exists
                    if 'updated_at' in key and key['updated_at']:
                        serialized_key['updated_at'] = key['updated_at'].isoformat()
                    else:
                        serialized_key['updated_at'] = None

                    serialized_keys.append(serialized_key)

                return jsonify({'keys': serialized_keys})
            except Exception as e:
                return jsonify({'keys': [], 'error': str(e)})

        @self.app.route('/api/get_all_conversations')
        def api_get_all_conversations():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                limit = request.args.get('limit', 50, type=int)
                conversations = db.get_all_conversations(user['id'], limit)
                serialized_conversations = [self.serialize_conversation(conv) for conv in conversations]
                return jsonify({'conversations': serialized_conversations})
            except Exception as e:
                return jsonify({'conversations': [], 'error': str(e)})

        @self.app.route('/api/get_user_profile')
        def api_get_user_profile():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            serialized_user = {
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'created_at': user['created_at'].isoformat() if user['created_at'] else None
            }
            return jsonify({'user': serialized_user})

        @self.app.route('/api/delete_api_key', methods=['POST'])
        def api_delete_api_key():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)

            try:
                data = request.get_json()
                provider = data.get('provider')

                query = "DELETE FROM user_api_keys WHERE user_id = %s AND provider = %s"
                rows_affected = db.execute_query(query, (user['id'], provider))

                return jsonify({'success': rows_affected > 0})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/upload_progress/<redis_project_id>')
        def api_upload_progress(redis_project_id):
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            try:
                # Get progress from Redis
                if hasattr(self, 'assistant') and self.assistant:
                    progress = self.assistant.redis_manager.get_upload_progress(user['id'], redis_project_id)
                    if progress:
                        return jsonify({'success': True, 'progress': progress})

                return jsonify({'success': True, 'progress': {
                    'status': 'unknown',
                    'percentage': 0,
                    'message': 'Waiting for upload to start...'
                }})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/upload_project', methods=['POST'])
        def api_upload_project():
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Authentication required'})

            try:
                # Get form data
                project_name = request.form.get('project_name')
                project_type = request.form.get('project_type', 'generic')

                if not project_name:
                    return jsonify({'success': False, 'error': 'Project name is required'})

                # Get files
                if 'files' not in request.files:
                    return jsonify({'success': False, 'error': 'No files selected'})

                files = request.files.getlist('files')
                if not files or all(not f.filename for f in files):
                    return jsonify({'success': False, 'error': 'No valid files selected'})

                print(f"📁 Received {len(files)} files for upload")

                # Generate unique project ID for Redis
                redis_project_id = f"user_{user['id']}_{project_name}_{int(datetime.now().timestamp())}"

                # Start background upload
                task_id = self.upload_manager.start_upload_task(
                    user['id'], project_name, project_type, files, redis_project_id
                )

                return jsonify({
                    'success': True,
                    'redis_project_id': redis_project_id,
                    'message': 'Upload started in background',
                    'task_id': task_id
                })

            except Exception as e:
                print(f"❌ Error starting upload: {e}")
                return jsonify({'success': False, 'error': f'Upload failed: {str(e)}'})

        # ---------------------------
        # SocketIO Event Handlers
        # ---------------------------

        @self.socketio.on('connect')
        def handle_connect(auth=None):
            session_id = request.sid
            print(f"✅ Client connected: {session_id}")

            # Initialize with empty user session
            self.user_sessions[session_id] = {
                'user_id': None,
                'current_project': None,
                'current_yaml': ''
            }

        @self.socketio.on('authenticate')
        def handle_authenticate(data):
            session_id = request.sid
            token = data.get('token')

            from models.database import PostgresDB
            db = PostgresDB(self.db_config)
            user_id = db.verify_token(token)

            if user_id:
                user = db.get_user_by_id(user_id)
                if user:
                    self.user_sessions[session_id]['user_id'] = user_id

                    # Load user's projects
                    projects = db.get_user_projects(user_id)
                    if projects:
                        project_paths = [p['project_path'] for p in projects]
                        self.user_sessions[session_id]['current_project'] = projects[0]

                        # Initialize assistant for user
                        assistant = self.get_user_assistant(user_id, project_paths)
                        if assistant:
                            self.assistant = assistant

                            # Send project info
                            project_info = assistant.get_project_info()
                            emit('project_info', project_info, room=session_id)

                            # Send conversation history
                            conversations = db.get_all_conversations(user_id, 50)
                            serialized_conversations = [self.serialize_conversation(conv) for conv in conversations]
                            emit('all_conversations', {'conversations': serialized_conversations}, room=session_id)

                    # Serialize user data before emitting
                    serialized_user = {
                        'id': user['id'],
                        'username': user['username'],
                        'email': user['email'],
                        'created_at': user['created_at'].isoformat() if user['created_at'] else None
                    }

                    emit('authentication_success', {'user': serialized_user}, room=session_id)
                    print(f"✅ Socket authentication successful for user: {user['username']}")
                    return

            emit('authentication_failed', {'error': 'Invalid token'}, room=session_id)
            print("❌ Socket authentication failed")

        @self.socketio.on('send_message')
        def handle_message(data):
            @copy_current_request_context
            def process_message():
                try:
                    session_id = request.sid
                    user_session = self.user_sessions.get(session_id)

                    if not user_session or not user_session['user_id']:
                        emit('error', {'error': 'Authentication required'}, room=session_id)
                        return

                    if not self.assistant:
                        emit('error', {'error': 'No project loaded'}, room=session_id)
                        return

                    query = data['message']
                    model_name = data.get('model')
                    provider = data.get('provider', 'ollama')
                    user_id = user_session['user_id']

                    print(f"📨 User {user_id} processing query: {query}")

                    # Use user-specific query processing
                    yaml_response = self.assistant.process_query_with_user_context(
                        query, session_id, user_id, use_auto_generate=True
                    )

                    user_session['current_yaml'] = yaml_response

                    emit('assistant_response', {
                        'yaml_response': yaml_response,
                        'session_id': session_id,
                        'model_used': model_name,
                        'provider_used': provider,
                        'user_specific': True  # Flag to indicate user-specific results
                    }, room=session_id)

                except Exception as e:
                    print(f"❌ Error processing message: {e}")
                    emit('error', {'error': str(e)}, room=session_id)

            thread = threading.Thread(target=process_message)
            thread.daemon = True
            thread.start()

        @self.socketio.on('apply_changes')
        def handle_apply_changes(data):
            @copy_current_request_context
            def apply_changes_thread():
                try:
                    session_id = request.sid
                    user_session = self.user_sessions.get(session_id)

                    if not user_session or not user_session['user_id']:
                        emit('error', {'error': 'Authentication required'}, room=session_id)
                        return

                    yaml_response = data['yaml_response']
                    conversation_id = data.get('conversation_id')
                    user_id = user_session['user_id']

                    print(f"🔄 User {user_id} applying changes...")

                    results = self.assistant.apply_changes(yaml_response)

                    if conversation_id:
                        self.assistant.db.update_application_results(conversation_id, results)
                    else:
                        recent_conversations = self.assistant.db.get_conversation_history(user_id, session_id, 1)
                        if recent_conversations:
                            latest_conv = recent_conversations[0]
                            self.assistant.db.update_application_results(latest_conv['id'], results)

                    emit('application_results', {'results': results, 'session_id': session_id}, room=session_id)

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
            try:
                session_id = request.sid
                user_session = self.user_sessions.get(session_id)

                if not user_session or not user_session['user_id']:
                    emit('error', {'error': 'Authentication required'}, room=session_id)
                    return

                yaml_response = data['yaml_response']
                filename = data.get('filename', f'changes-{uuid.uuid4().hex[:8]}.yaml')

                # Save YAML to file
                save_path = os.path.join(self.base_project_dir, filename)
                with open(save_path, 'w') as f:
                    f.write(yaml_response)

                emit('save_success', {
                    'message': f'Changes saved to {filename}',
                    'filepath': save_path
                }, room=session_id)

            except Exception as e:
                emit('error', {'error': f'Failed to save changes: {str(e)}'}, room=session_id)

        @self.socketio.on('get_models')
        def handle_get_models(data):
            try:
                session_id = request.sid
                user_session = self.user_sessions.get(session_id)

                if not user_session or not user_session['user_id']:
                    emit('error', {'error': 'Authentication required'}, room=session_id)
                    return

                provider = data.get('provider', 'ollama')
                user_id = user_session['user_id']

                print(f"📋 Fetching models for provider: {provider}, user: {user_id}")

                from models.database import PostgresDB
                db = PostgresDB(self.db_config)

                models = []

                if provider == 'ollama':
                    print("🦙 Fetching Ollama models...")
                    models = self.get_ollama_models()
                    if not models:
                        # Fallback to default Ollama models
                        models = ["llama3.1:latest", "codellama:latest", "mistral:latest", "llama2:latest"]
                        print("⚠️ Using fallback Ollama models")

                elif provider in ['openai', 'openrouter', 'anthropic']:
                    api_key = db.get_api_key(user_id, provider)
                    if api_key:
                        print(f"🔑 API key found for {provider}")
                        if provider == 'openai':
                            print("🤖 Fetching OpenAI models...")
                            models = self.get_openai_models(api_key)
                        elif provider == 'openrouter':
                            print("🌐 Fetching OpenRouter models...")
                            models = self.get_openrouter_models(api_key)
                        elif provider == 'anthropic':
                            print("🧠 Fetching Anthropic models...")
                            models = self.get_anthropic_models(api_key)

                        if not models:
                            models = [f"{provider}-default-model"]
                            print(f"⚠️ Using fallback for {provider}")
                    else:
                        # Return empty list if no API key
                        print(f"❌ No API key found for {provider}")
                        models = []

                print(f"✅ Sending {len(models)} models for {provider}")
                emit('models_list', {'models': models}, room=session_id)

            except Exception as e:
                print(f"❌ Error getting models for {provider}: {e}")
                emit('error', {'error': f'Failed to get models: {str(e)}'}, room=session_id)

        @self.socketio.on('restart_servers')
        def handle_restart_servers():
            try:
                session_id = request.sid
                user_session = self.user_sessions.get(session_id)

                if not user_session or not user_session['user_id']:
                    emit('error', {'error': 'Authentication required'}, room=session_id)
                    return

                if self.assistant:
                    self.assistant.restart_servers()
                    emit('servers_restarted', {'message': 'All project servers restarted'}, room=session_id)
                else:
                    emit('error', {'error': 'No assistant loaded to restart servers'}, room=session_id)

            except Exception as e:
                emit('error', {'error': f'Failed to restart servers: {str(e)}'}, room=session_id)

        @self.socketio.on('check_api_key')
        def handle_check_api_key(data):
            try:
                session_id = request.sid
                user_session = self.user_sessions.get(session_id)

                if not user_session or not user_session['user_id']:
                    emit('error', {'error': 'Authentication required'}, room=session_id)
                    return

                provider = data.get('provider')
                from models.database import PostgresDB
                db = PostgresDB(self.db_config)
                api_key = db.get_api_key(user_session['user_id'], provider)

                emit('api_key_status', {
                    'provider': provider,
                    'has_key': api_key is not None
                }, room=session_id)

            except Exception as e:
                emit('error', {'error': f'Failed to check API key: {str(e)}'}, room=session_id)

    def run(self):
        """Start the web server"""
        # Increase Werkzeug limits for file uploads


        print(f"🚀 Starting Multi-Project AI Assistant Web UI...")
        print(f"🌐 Web interface: http://{self.host}:{self.port}")
        print("📁 File upload limits: DISABLED (unlimited file size)")

        self.socketio.run(
            self.app,
            host=self.host,
            port=self.port,
            debug=False,
            allow_unsafe_werkzeug=True
        )