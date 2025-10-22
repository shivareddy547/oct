import threading
import time
import os
import shutil
import re
import subprocess
from datetime import datetime
import json
import requests
import zipfile
import io


class UploadManager:
    def __init__(self, webui):
        self.webui = webui
        self.upload_tasks = {}

    def _update_git_progress(self, user_id, redis_project_id, progress):
        """Update Git-specific progress in Redis - FIXED VERSION"""
        try:
            redis_client = self._get_redis_client()

            if redis_client:
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"

                # Ensure all required fields are present
                progress.setdefault('percentage', 0)
                progress.setdefault('status', 'unknown')
                progress.setdefault('message', 'Processing...')
                progress.setdefault('terminal_output', [])

                # Store in Redis
                redis_client.setex(
                    progress_key,
                    900,  # 15 minutes expiry
                    json.dumps(progress)
                )

                print(f"📊 Progress stored: {progress['status']} - {progress['percentage']}%")
            else:
                # Fallback to in-memory storage
                if not hasattr(self, 'progress_store'):
                    self.progress_store = {}
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"
                self.progress_store[progress_key] = progress
                print(f"⚠️ Using in-memory storage: {progress['status']} - {progress['percentage']}%")

        except Exception as e:
            print(f"❌ Error updating Git progress: {e}")

    def get_git_progress(self, user_id, redis_project_id):
        """Get Git-specific progress from Redis - FIXED VERSION"""
        try:
            redis_client = self._get_redis_client()

            # Check in-memory storage first
            if hasattr(self, 'progress_store'):
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"
                if progress_key in self.progress_store:
                    progress = self.progress_store[progress_key]
                    print(f"📊 Progress from memory: {progress.get('status', 'unknown')} - {progress.get('percentage', 0)}%")
                    return progress

            if redis_client:
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"
                progress_data = redis_client.get(progress_key)

                if progress_data:
                    progress = json.loads(progress_data)
                    print(f"📊 Progress from Redis: {progress.get('status', 'unknown')} - {progress.get('percentage', 0)}%")
                    return progress

        except Exception as e:
            print(f"❌ Error getting Git progress: {e}")

        # Return default progress if none found
        return {
            'status': 'unknown',
            'percentage': 0,
            'message': 'No progress data available',
            'terminal_output': ['Waiting for progress updates...']
        }

    def _get_redis_client(self):
        """Get Redis client from assistant or create direct connection"""
        try:
            # Try to get Redis client from assistant first
            if (hasattr(self.webui, 'get_user_assistant') and
                callable(self.webui.get_user_assistant)):

                # Try to get assistant for the current user (you might need to adjust this)
                assistant = self.webui.get_user_assistant(1, [])  # Adjust user_id as needed

                if (assistant and
                    hasattr(assistant, 'redis_manager') and
                    assistant.redis_manager and
                    hasattr(assistant.redis_manager, 'redis_client') and
                    assistant.redis_manager.redis_client):

                    print("✅ Using Redis client from assistant.redis_manager")
                    return assistant.redis_manager.redis_client

            # Fallback: direct connection
            print("⚠️ No Redis client found via assistant, trying direct connection...")
            try:
                redis_config = {
                    'host': 'localhost',
                    'port': 6379,
                    'db': 0
                }
                import redis
                redis_client = redis.Redis(
                    host=redis_config['host'],
                    port=redis_config['port'],
                    db=redis_config['db'],
                    decode_responses=True,
                    socket_connect_timeout=5
                )
                # Test connection
                redis_client.ping()
                print("✅ Direct Redis connection successful")
                return redis_client
            except Exception as e:
                print(f"❌ Direct Redis connection failed: {e}")
                return None

        except Exception as e:
            print(f"❌ Error getting Redis client: {e}")
            return None

    def _add_terminal_output(self, user_id, redis_project_id, message):
        """Add message to terminal output with timestamp - FIXED VERSION"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            terminal_line = f"[{timestamp}] {message}"
            print(f"📝 TERMINAL: {terminal_line}")  # Debug output

            # Get current progress WITHOUT updating it yet
            current_progress = self.get_git_progress(user_id, redis_project_id).copy()

            # Update terminal output
            terminal_output = current_progress.get('terminal_output', [])
            terminal_output.append(terminal_line)

            # Keep only last 20 lines
            if len(terminal_output) > 20:
                terminal_output = terminal_output[-20:]

            # Update progress with new terminal output
            current_progress['terminal_output'] = terminal_output

            # Preserve other important fields
            if 'percentage' not in current_progress:
                current_progress['percentage'] = 0
            if 'status' not in current_progress:
                current_progress['status'] = 'processing'
            if 'message' not in current_progress:
                current_progress['message'] = 'Processing...'

            # Save back to storage
            self._update_git_progress(user_id, redis_project_id, current_progress)

        except Exception as e:
            print(f"❌ Error adding terminal output: {e}")

    def start_git_clone_task(self, user_id, project_name, git_url, project_dir, redis_project_id, git_username='', git_token=''):
        """Start Git clone in background thread - FIXED VERSION"""
        task_id = f"git_{user_id}_{redis_project_id}"

        # Initialize progress with proper structure
        progress = {
            'status': 'starting',
            'percentage': 5,
            'user_id': user_id,
            'project_id': redis_project_id,
            'message': f'Starting Git clone from {self._mask_git_url(git_url)}...',
            'terminal_output': [f'🚀 Starting Git clone from {self._mask_git_url(git_url)}...']
        }
        self._update_git_progress(user_id, redis_project_id, progress)

        # Store task
        self.upload_tasks[task_id] = {
            'thread': None,
            'progress': progress
        }

        # Start background thread
        thread = threading.Thread(
            target=self._process_git_clone,
            args=(user_id, project_name, git_url, project_dir, redis_project_id, git_username, git_token)
        )
        thread.daemon = True
        thread.start()

        self.upload_tasks[task_id]['thread'] = thread
        return task_id

    def _process_git_clone(self, user_id, project_name, git_url, project_dir, redis_project_id, git_username='', git_token=''):
        """Process Git clone in background with REAL progress tracking"""
        import traceback
        from models.database import PostgresDB

        try:
            # STEP 1: Initial setup - 10%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'preparing',
                'percentage': 10,
                'message': '🧹 Preparing workspace...'
            })
            self._add_terminal_output(user_id, redis_project_id, f"🧹 Preparing workspace for '{project_name}'...")

            # Clean existing directory
            if os.path.exists(project_dir):
                try:
                    shutil.rmtree(project_dir)
                    self._add_terminal_output(user_id, redis_project_id, "✅ Cleaned existing directory")
                    time.sleep(1)
                except Exception as e:
                    self._add_terminal_output(user_id, redis_project_id, f"⚠️ Cleanup warning: {str(e)}")

            os.makedirs(project_dir, exist_ok=True)
            self._add_terminal_output(user_id, redis_project_id, "✅ Workspace ready")

            # STEP 2: Try direct download for public repos - 20%
            if not git_username and not git_token:
                self._update_git_progress(user_id, redis_project_id, {
                    'status': 'downloading',
                    'percentage': 20,
                    'message': '📥 Trying direct download...'
                })
                self._add_terminal_output(user_id, redis_project_id, "🔍 Checking if repository is public...")

                direct_success = self._download_public_repo(user_id, redis_project_id, git_url, project_dir)

                if direct_success:
                    self._add_terminal_output(user_id, redis_project_id, "✅ Successfully downloaded via direct method!")
                    # Skip to final stages if direct download worked
                    self._update_git_progress(user_id, redis_project_id, {
                        'status': 'processing',
                        'percentage': 80,
                        'message': '📦 Processing downloaded files...'
                    })
                    return self._analyze_and_save_project(user_id, project_name, git_url, project_dir, redis_project_id)
                else:
                    self._add_terminal_output(user_id, redis_project_id, "⚠️ Direct download failed, falling back to Git...")

            # STEP 3: Git clone process - 30%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 30,
                'message': '🌐 Connecting to Git repository...'
            })
            self._add_terminal_output(user_id, redis_project_id, "🔄 Using Git clone method...")
            time.sleep(1)

            # STEP 4: Actual Git clone - 40-60%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 40,
                'message': '📥 Starting clone process...'
            })
            self._add_terminal_output(user_id, redis_project_id, "📥 Starting Git clone...")

            git_success = self._git_clone_with_progress(
                user_id,
                redis_project_id,
                git_url,
                project_dir,
                git_username,
                git_token
            )

            if not git_success:
                raise Exception("Git clone failed")

            # STEP 5: Post-clone processing - 70%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'processing',
                'percentage': 70,
                'message': '📦 Processing cloned repository...'
            })
            self._add_terminal_output(user_id, redis_project_id, "📦 Processing cloned files...")

            return self._analyze_and_save_project(user_id, project_name, git_url, project_dir, redis_project_id)

        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            print(error_msg)
            print(traceback.format_exc())

            self._add_terminal_output(user_id, redis_project_id, error_msg)
            self._add_terminal_output(user_id, redis_project_id, "💥 Download failed!")

            # Cleanup on error
            if os.path.exists(project_dir):
                try:
                    shutil.rmtree(project_dir)
                    self._add_terminal_output(user_id, redis_project_id, "🧹 Cleaned up temporary files")
                except Exception as cleanup_error:
                    self._add_terminal_output(user_id, redis_project_id, f"⚠️ Cleanup warning: {str(cleanup_error)}")

            self._update_git_progress(user_id, redis_project_id, {
                'status': 'error',
                'percentage': 100,
                'message': f'Download failed: {str(e)}'
            })

    def _analyze_and_save_project(self, user_id, project_name, git_url, project_dir, redis_project_id):
        """Analyze and save the downloaded project with PROPER progress"""
        try:
            from models.database import PostgresDB
            db = PostgresDB(self.webui.db_config)

            self._add_terminal_output(user_id, redis_project_id, "✅ Repository downloaded successfully!")

            # Analyze project - 75%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'analyzing',
                'percentage': 75,
                'message': '🔍 Analyzing project structure...'
            })
            self._add_terminal_output(user_id, redis_project_id, "🔍 Analyzing project structure...")

            project_type = self._detect_project_type(project_dir)
            file_count = self._count_files(project_dir)

            self._add_terminal_output(user_id, redis_project_id, f"📋 Detected project type: {project_type}")
            self._add_terminal_output(user_id, redis_project_id, f"📊 Found {file_count} files in project")

            # Save to database - 85%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'saving',
                'percentage': 85,
                'message': '💾 Saving to database...'
            })
            self._add_terminal_output(user_id, redis_project_id, "💾 Saving project to database...")

            project_id = db.create_user_project(
                user_id=user_id,
                project_name=project_name,
                project_type=project_type,
                project_path=project_dir,
                redis_project_id=redis_project_id,
                git_url=git_url
            )

            if not project_id:
                raise Exception("Failed to create project in database")

            self._add_terminal_output(user_id, redis_project_id, "✅ Project saved to database!")

            # Index files for AI search - 95%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'indexing',
                'percentage': 95,
                'message': '📚 Indexing files for AI search...'
            })
            self._add_terminal_output(user_id, redis_project_id, "📚 Indexing files for AI search...")

            # Get assistant and index files in Redis for AI search
            indexed_count = 0
            try:
                if hasattr(self.webui, 'get_user_assistant') and callable(self.webui.get_user_assistant):
                    assistant = self.webui.get_user_assistant(user_id, [project_dir])

                    if (assistant and
                        hasattr(assistant, 'redis_manager') and
                        assistant.redis_manager):

                        self._add_terminal_output(user_id, redis_project_id, "🔍 Starting Redis indexing with assistant...")

                        # Use the Redis manager to index all project files
                        indexed_data = assistant.redis_manager.store_project_structure(
                            [project_dir], redis_project_id, user_id
                        )

                        # Count indexed files properly
                        if indexed_data and 'projects' in indexed_data:
                            for project_key, project_info in indexed_data['projects'].items():
                                if 'files' in project_info:
                                    indexed_count += len(project_info['files'])

                        self._add_terminal_output(user_id, redis_project_id, f"✅ Indexed {indexed_count} files in Redis for AI search")
                    else:
                        self._add_terminal_output(user_id, redis_project_id, "⚠️ Assistant or Redis manager not available for indexing")
                else:
                    self._add_terminal_output(user_id, redis_project_id, "⚠️ get_user_assistant method not available")

            except Exception as e:
                self._add_terminal_output(user_id, redis_project_id, f"⚠️ Indexing error: {str(e)}")
                # Don't fail the whole process if indexing fails

            self._add_terminal_output(user_id, redis_project_id, "✅ Files indexed successfully!")

            # Complete - 100%
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'completed',
                'percentage': 100,
                'message': f'🎉 Project "{project_name}" ready with {file_count} files!',
                'project_id': project_id,
                'total_files': file_count,
                'project_path': project_dir,
                'indexed_files': indexed_count
            })

            self._add_terminal_output(user_id, redis_project_id, "🎉 Project setup completed successfully!")
            self._add_terminal_output(user_id, redis_project_id, f"📁 Location: {project_dir}")
            self._add_terminal_output(user_id, redis_project_id, f"📊 Total files: {file_count}")
            self._add_terminal_output(user_id, redis_project_id, f"🔍 Indexed files: {indexed_count}")

            return True

        except Exception as e:
            self._add_terminal_output(user_id, redis_project_id, f"❌ Error in final setup: {str(e)}")
            raise

    def _git_clone_with_progress(self, user_id, redis_project_id, git_url, project_dir, git_username, git_token):
        """Clone Git repository with REAL progress tracking"""
        try:
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 45,
                'message': '🌐 Connecting to repository...'
            })
            self._add_terminal_output(user_id, redis_project_id, "🌐 Connecting to Git repository...")
            time.sleep(1)

            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 55,
                'message': '📥 Downloading repository data...'
            })
            self._add_terminal_output(user_id, redis_project_id, "📥 Downloading repository data...")

            # Use shallow clone for faster downloads
            clone_cmd = ['git', 'clone', '--depth', '1', git_url, project_dir]

            self._add_terminal_output(user_id, redis_project_id, f"⚡ Command: git clone --depth 1 {self._mask_git_url(git_url)}")

            # Execute clone with real-time output
            self._add_terminal_output(user_id, redis_project_id, "🔄 Executing Git clone...")

            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip()
                self._add_terminal_output(user_id, redis_project_id, f"❌ Git error: {error_msg}")
                # Also log stdout for more context
                if result.stdout.strip():
                    self._add_terminal_output(user_id, redis_project_id, f"ℹ️ Git output: {result.stdout.strip()}")
                return False

            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 65,
                'message': '✅ Repository downloaded!'
            })
            self._add_terminal_output(user_id, redis_project_id, "✅ Repository cloned successfully!")

            return True

        except subprocess.TimeoutExpired:
            self._add_terminal_output(user_id, redis_project_id, "⏰ Clone timeout - repository might be very large")
            return False
        except Exception as e:
            self._add_terminal_output(user_id, redis_project_id, f"❌ Clone error: {str(e)}")
            return False

    # Keep your existing methods for download_public_repo, detect_project_type, count_files, mask_git_url, etc.
    # ... (the rest of your existing methods remain the same)

    def _download_public_repo(self, user_id, redis_project_id, git_url, project_dir):
        """Download public repository directly as ZIP without Git"""
        try:
            # Convert GitHub URL to ZIP download URL
            if 'github.com' in git_url:
                if git_url.endswith('.git'):
                    git_url = git_url[:-4]

                parts = git_url.split('/')
                if len(parts) >= 5:
                    username = parts[-2]
                    repo_name = parts[-1]
                    zip_url = f"https://github.com/{username}/{repo_name}/archive/main.zip"
                else:
                    raise Exception("Invalid GitHub URL format")

            elif 'gitlab.com' in git_url:
                if git_url.endswith('.git'):
                    git_url = git_url[:-4]

                parts = git_url.split('/')
                if len(parts) >= 5:
                    username = parts[-2]
                    repo_name = parts[-1]
                    zip_url = f"https://gitlab.com/{username}/{repo_name}/-/archive/main/{repo_name}-main.zip"
                else:
                    raise Exception("Invalid GitLab URL format")

            else:
                raise Exception("Only GitHub and GitLab public repositories are supported for direct download")

            self._add_terminal_output(user_id, redis_project_id, f"📥 Downloading from: {zip_url}")

            # Download the ZIP file
            response = requests.get(zip_url, stream=True, timeout=30)
            response.raise_for_status()

            self._add_terminal_output(user_id, redis_project_id, "✅ ZIP downloaded, extracting...")

            # Extract ZIP file
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                zip_file.extractall(project_dir)

            self._add_terminal_output(user_id, redis_project_id, "✅ ZIP extracted successfully!")

            # Move files from subdirectory to main directory
            extracted_dirs = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
            if extracted_dirs:
                main_extracted_dir = os.path.join(project_dir, extracted_dirs[0])
                for item in os.listdir(main_extracted_dir):
                    shutil.move(os.path.join(main_extracted_dir, item), os.path.join(project_dir, item))
                shutil.rmtree(main_extracted_dir)

            return True

        except Exception as e:
            self._add_terminal_output(user_id, redis_project_id, f"❌ Direct download failed: {str(e)}")
            return False

    def _detect_project_type(self, project_dir):
        """Detect project type from directory"""
        if os.path.exists(os.path.join(project_dir, 'package.json')):
            return 'react'
        elif os.path.exists(os.path.join(project_dir, 'Gemfile')):
            return 'rails'
        elif os.path.exists(os.path.join(project_dir, 'requirements.txt')):
            return 'python'
        elif os.path.exists(os.path.join(project_dir, 'pom.xml')):
            return 'java'
        else:
            return 'generic'

    def _count_files(self, directory):
        """Count files in directory"""
        count = 0
        for root, dirs, files in os.walk(directory):
            if 'node_modules' in root or '.git' in root:
                continue
            count += len(files)
        return count

    def _mask_git_url(self, git_url):
        """Mask sensitive information in Git URLs"""
        if '@' in git_url:
            if '://' in git_url:
                return re.sub(r'://[^@]+@', '://***@', git_url)
        return git_url