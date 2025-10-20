import threading
import uuid
import os
import subprocess
from typing import List, Dict
from flask import Flask, request, jsonify, copy_current_request_context
from flask_socketio import SocketIO, emit
import requests

from services.ai_assistant import MultiProjectAIAssistant

from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO
import os

class MultiProjectAIChatbotWebUI:
    def __init__(self, project_paths: List[str], redis_config: Dict, db_config: Dict,
                 ollama_url: str = 'http://localhost:11434', host: str = '0.0.0.0', port: int = 5000):
        self.assistant = MultiProjectAIAssistant(project_paths, redis_config, db_config)
        self.assistant.ollama.base_url = ollama_url
        self.host = host
        self.port = port

        # Paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        static_dir = os.path.join(base_dir, '..', 'static')
        template_dir = os.path.join(static_dir, 'templates')

        # ✅ Tell Flask where to find static and templates
        self.app = Flask(__name__,
                                static_folder=static_dir,
                                template_folder=template_dir)
        self.app.config['SECRET_KEY'] = 'multi-project-ai-assistant-secret-key'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # Store sessions
        self.sessions = {}

        self.setup_routes()
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
        """Setup Flask routes and SocketIO events"""
        import os

        # Resolve the path to index.html dynamically
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base_dir, "static", "templates", "index.html")
        profile_template_path = os.path.join(base_dir, "static", "templates", "profile.html")

        # Read the HTML file contents
        with open(template_path, "r", encoding="utf-8") as f:
            HTML_TEMPLATE = f.read()

        # Read profile HTML
        try:
            with open(profile_template_path, "r", encoding="utf-8") as f:
                PROFILE_TEMPLATE = f.read()
        except FileNotFoundError:
            PROFILE_TEMPLATE = "<h1>Profile page not found</h1><a href='/'>Back to Chat</a>"

        @self.app.route('/')
        def index():
            return HTML_TEMPLATE

        @self.app.route('/profile')
        def profile():
            return PROFILE_TEMPLATE

        # ---------------------------
        # API Routes for Profile Management
        # ---------------------------

        @self.app.route('/api/save_api_key', methods=['POST'])
        def api_save_api_key():
            try:
                data = request.get_json()
                user_id = data.get('user_id', 'default_user')
                provider = data.get('provider')
                api_key = data.get('api_key')

                if not all([user_id, provider, api_key]):
                    return jsonify({'success': False, 'error': 'Missing required fields'})

                success = self.assistant.db.save_api_key(user_id, provider, api_key)
                return jsonify({'success': success})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/delete_api_key', methods=['POST'])
        def api_delete_api_key():
            try:
                data = request.get_json()
                user_id = data.get('user_id', 'default_user')
                provider = data.get('provider')

                success = self.assistant.db.delete_api_key(user_id, provider)
                return jsonify({'success': success})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        @self.app.route('/api/get_user_api_keys')
        def api_get_user_api_keys():
            try:
                user_id = request.args.get('user_id', 'default_user')
                keys = self.assistant.db.get_user_api_keys(user_id)
                return jsonify({'keys': keys})
            except Exception as e:
                return jsonify({'keys': [], 'error': str(e)})

        @self.app.route('/api/get_all_conversations')
        def api_get_all_conversations():
            try:
                limit = request.args.get('limit', 50, type=int)
                conversations = self.assistant.db.get_all_conversations(limit)
                return jsonify({'conversations': conversations})
            except Exception as e:
                return jsonify({'conversations': [], 'error': str(e)})

        @self.app.route('/api/clear_conversations', methods=['POST'])
        def api_clear_conversations():
            try:
                # In a real application, you would implement actual conversation deletion here
                # For now, we'll return success but log that this is a placeholder
                print("⚠️ Clear conversations endpoint called - functionality would be implemented here")
                return jsonify({'success': True, 'message': 'Clear functionality would be implemented here'})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)})

        # ---------------------------
        # SocketIO Event Handlers
        # ---------------------------

        @self.socketio.on('get_models')
        def handle_get_models(data):
            provider = data.get('provider')
            api_key = data.get('api_key', '')

            try:
                if provider == 'ollama':
                    models = get_ollama_models()
                elif provider == 'openai':
                    models = get_openai_models(api_key)
                elif provider == 'openrouter':
                    models = get_openrouter_models(api_key)
                else:
                    models = []

                emit('models_list', {
                    'provider': provider,
                    'models': models
                })
            except Exception as e:
                emit('models_error', {
                    'provider': provider,
                    'error': str(e)
                })

        def get_ollama_models():
            # Run 'ollama list' command and parse output
            import subprocess
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            # Parse the output and return model list
            models = []
            for line in result.stdout.split('\n')[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 1:
                        models.append({'name': parts[0], 'id': parts[0]})
            return models

        def get_openai_models(api_key):
            # Fetch models from OpenAI API
            import requests
            headers = {'Authorization': f'Bearer {api_key}'}
            response = requests.get('https://api.openai.com/v1/models', headers=headers)
            models_data = response.json()
            return [{'name': model['id'], 'id': model['id']} for model in models_data.get('data', [])]

        def get_openrouter_models(api_key):
            # Fetch models from OpenRouter API
            import requests
            headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
            response = requests.get('https://openrouter.ai/api/v1/models', headers=headers)
            models_data = response.json()
            return [{'name': model['id'], 'id': model['id']} for model in models_data.get('data', [])]

        @self.app.route('/public/<path:filename>')
        def serve_public_files(filename):
            return send_from_directory(
                os.path.join(self.app.static_folder, 'public'),
                filename
            )

        # FIXED: Add the auth parameter that Flask-SocketIO expects
        @self.socketio.on('connect')
        def handle_connect(auth=None):  # Add auth parameter
            session_id = request.sid
            self.sessions[session_id] = {'current_yaml': ''}
            print(f"✅ Client connected: {session_id}")

            try:
                project_info = self.assistant.get_project_info()
                emit('project_info', project_info)

                all_conversations = self.assistant.db.get_all_conversations(50)
                emit('all_conversations', {'conversations': all_conversations})
            except Exception as e:
                print(f"❌ Error in handle_connect: {e}")
                emit('error', {'error': str(e)}, room=session_id)

        @self.socketio.on('send_message')
        def handle_message(data):
            @copy_current_request_context
            def process_message():
                try:
                    query = data['message']
                    model_name = data.get('model')
                    provider = data.get('provider', 'ollama')
                    session_id = request.sid
                    user_id = 'default_user'  # You can make this dynamic based on authentication

                    print(f"📨 Processing query: {query}")
                    print(f"🤖 Using provider: {provider}, model: {model_name}")

                    # Get API key from database if needed
                    api_key = None
                    if provider in ['openai', 'openrouter']:
                        api_key = self.assistant.db.get_api_key(user_id, provider)
                        if not api_key:
                            emit('error', {
                                'error': f'No API key found for {provider}. Please add it in your profile settings.'
                            }, room=session_id)
                            return
                        print(f"🔑 Using stored API key for {provider}")

                    # Set the model based on provider
                    if provider == 'ollama':
                        self.assistant.set_model(model_name)
                        yaml_response = self.assistant.process_query(query, session_id, use_auto_generate=True)
                    elif provider == 'openai':
                        yaml_response = self.assistant.process_with_openai(query, model_name, api_key, session_id)
                    elif provider == 'openrouter':
                        yaml_response = self.assistant.process_with_openrouter(query, model_name, api_key, session_id)
                    else:
                        raise ValueError(f"Unsupported provider: {provider}")

                    self.sessions[session_id] = {'current_yaml': yaml_response}

                    emit('assistant_response', {
                        'yaml_response': yaml_response,
                        'session_id': session_id,
                        'model_used': model_name,
                        'provider_used': provider
                    }, room=session_id)

                    all_conversations = self.assistant.db.get_all_conversations(50)
                    emit('all_conversations', {'conversations': all_conversations}, room=session_id)

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
                    yaml_response = data['yaml_response']
                    session_id = request.sid
                    conversation_id = data.get('conversation_id')
                    print(f"🔄 Applying changes from YAML response (Conversation ID: {conversation_id})...")

                    results = self.assistant.apply_changes(yaml_response)

                    if conversation_id:
                        self.assistant.db.update_application_results(conversation_id, results)
                    else:
                        recent_conversations = self.assistant.db.get_conversation_history(session_id, 1)
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
            @copy_current_request_context
            def save_changes_thread():
                try:
                    yaml_response = data['yaml_response']
                    conversation_id = data.get('conversation_id')
                    session_id = request.sid

                    print(f"💾 Saving changes with git (Conversation ID: {conversation_id})...")

                    commit_message = "AI-generated changes"
                    if conversation_id:
                        conversation = self.assistant.db.get_conversation_by_id(conversation_id)
                        if conversation and conversation.get('query'):
                            commit_message = f"AI: {conversation['query'][:50]}..."

                    results = {'commands_run': [], 'git_results': {}}

                    for project_path in self.assistant.project_paths:
                        try:
                            subprocess.run(['git', 'add', '.'], cwd=project_path, capture_output=True, text=True, timeout=30)
                            results['commands_run'].append(f'git add . in {os.path.basename(project_path)}')

                            result = subprocess.run(
                                ['git', 'commit', '-m', commit_message],
                                cwd=project_path, capture_output=True, text=True, timeout=30
                            )
                            results['commands_run'].append(f'git commit -m "{commit_message}" in {os.path.basename(project_path)}')

                            results['git_results'][project_path] = {
                                'commit': result.stdout if result.returncode == 0 else result.stderr
                            }

                            print(f"✅ Changes saved in {project_path}")

                        except Exception as e:
                            results['git_results'][project_path] = {'error': str(e)}
                            print(f"❌ Error saving changes in {project_path}: {e}")

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
                    print("🔄 Executing restart_servers.sh script...")

                    restart = subprocess.run(
                        ['/bin/bash', '/home/opc/ai/restart_servers.sh'],
                        capture_output=True, text=True, timeout=300
                    )

                    results['stdout'] = restart.stdout
                    results['stderr'] = restart.stderr
                    results['status'] = (
                        "script executed successfully" if restart.returncode == 0
                        else f"script failed with code {restart.returncode}"
                    )

                    emit('restart_servers_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ restart_servers.sh executed.")

                except Exception as e:
                    print(f"❌ Error executing restart_servers.sh: {e}")
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
                    print("🚀 Running Rails database migrations...")

                    for project_path in self.assistant.project_paths:
                        try:
                            if os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
                                print(f"🚀 Running migrations in {project_path}...")
                                rails_migrate = subprocess.run(
                                    ['bundle', 'exec', 'rails', 'db:migrate'],
                                    cwd=project_path, capture_output=True, text=True, timeout=120
                                )
                                results[project_path] = {
                                    'stdout': rails_migrate.stdout,
                                    'stderr': rails_migrate.stderr
                                }
                        except Exception as e:
                            results[project_path] = {'error': str(e)}

                    emit('migration_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ Migrations completed successfully.")

                except Exception as e:
                    print(f"❌ Error running migrations: {e}")
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
                    print("↩️ Rolling back Rails migrations...")

                    for project_path in self.assistant.project_paths:
                        try:
                            if os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
                                rails_rollback = subprocess.run(
                                    ['bundle', 'exec', 'rails', 'db:rollback', 'STEP=1'],
                                    cwd=project_path, capture_output=True, text=True, timeout=60
                                )
                                results[project_path] = {
                                    'stdout': rails_rollback.stdout,
                                    'stderr': rails_rollback.stderr
                                }
                        except Exception as e:
                            results[project_path] = {'error': str(e)}

                    emit('rollback_migration_results', {'results': results, 'session_id': session_id}, room=session_id)
                    print("✅ Migration rollback completed.")

                except Exception as e:
                    print(f"❌ Error in rollback: {e}")
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

                    results = {'commands_run': [], 'rollback_results': {}}

                    for project_path in self.assistant.project_paths:
                        try:
                            subprocess.run(['git', 'checkout', '.'], cwd=project_path, capture_output=True, text=True, timeout=30)
                            results['commands_run'].append(f'git checkout . in {os.path.basename(project_path)}')

                            subprocess.run(['git', 'clean', '-fd'], cwd=project_path, capture_output=True, text=True, timeout=30)
                            results['commands_run'].append(f'git clean -fd in {os.path.basename(project_path)}')

                        except Exception as e:
                            results['rollback_results'][project_path] = {'error': str(e)}

                    self.assistant.redis_manager.store_project_structure(self.assistant.project_paths, self.assistant.project_id)

                    emit('rollback_results', {'results': results, 'session_id': session_id}, room=session_id)

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
            emit('all_conversations', {'conversations': all_conversations}, room=session_id)

    def run(self):
        """Start the web server"""
        print(f"🚀 Starting Multi-Project AI Assistant Web UI...")
        print(f"📁 Projects: {self.assistant.project_paths}")
        print(f"🌐 Web interface: http://{self.host}:{self.port}")
        print("🗄️  PostgreSQL database active.")
        print("🎯 Auto-generate mode enabled.")
        print("🤖 Available models:", self.assistant.get_available_models())
        print("👤 Profile page: http://{self.host}:{self.port}/profile")

        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)