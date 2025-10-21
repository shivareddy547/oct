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

    def start_upload_task(self, user_id, project_name, project_type, files, redis_project_id):
        """Start upload in background thread"""
        task_id = f"{user_id}_{redis_project_id}"

        # Initialize progress
        progress = {
            'status': 'starting',
            'total_files': len(files),
            'processed_files': 0,
            'current_file': '',
            'percentage': 0,
            'user_id': user_id,
            'project_id': redis_project_id,
            'message': f'Starting upload of {len(files)} files...'
        }
        self._update_progress(user_id, redis_project_id, progress)

        # Store task
        self.upload_tasks[task_id] = {
            'thread': None,
            'progress': progress
        }

        # Start background thread
        thread = threading.Thread(
            target=self._process_upload,
            args=(user_id, project_name, project_type, files, redis_project_id)
        )
        thread.daemon = True
        thread.start()

        self.upload_tasks[task_id]['thread'] = thread
        return task_id

    def _download_public_repo(self, user_id, redis_project_id, git_url, project_dir):
        """Download public repository directly as ZIP without Git"""
        try:
            # Convert GitHub URL to ZIP download URL
            if 'github.com' in git_url:
                # Convert: https://github.com/username/repo.git
                # To: https://github.com/username/repo/archive/main.zip
                if git_url.endswith('.git'):
                    git_url = git_url[:-4]

                # Extract username and repo name
                parts = git_url.split('/')
                if len(parts) >= 5:
                    username = parts[-2]
                    repo_name = parts[-1]
                    zip_url = f"https://github.com/{username}/{repo_name}/archive/main.zip"
                else:
                    raise Exception("Invalid GitHub URL format")

            elif 'gitlab.com' in git_url:
                # Convert: https://gitlab.com/username/repo.git
                # To: https://gitlab.com/username/repo/-/archive/main/repo-main.zip
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

            # The extracted content will be in a subdirectory like repo-main/
            # Move all files to the main project directory
            extracted_dirs = [d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))]
            if extracted_dirs:
                main_extracted_dir = os.path.join(project_dir, extracted_dirs[0])
                # Move all files from subdirectory to main directory
                for item in os.listdir(main_extracted_dir):
                    shutil.move(os.path.join(main_extracted_dir, item), os.path.join(project_dir, item))
                # Remove the empty subdirectory
                shutil.rmtree(main_extracted_dir)

            return True

        except Exception as e:
            self._add_terminal_output(user_id, redis_project_id, f"❌ Direct download failed: {str(e)}")
            return False

    def start_git_clone_task(self, user_id, project_name, git_url, project_dir, redis_project_id, git_username='', git_token=''):
        """Start Git clone in background thread"""
        task_id = f"git_{user_id}_{redis_project_id}"

        # Initialize progress WITH TERMINAL OUTPUT
        progress = {
            'status': 'starting',
            'total_files': 0,
            'processed_files': 0,
            'current_file': '',
            'percentage': 0,
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

    def _process_upload(self, user_id, project_name, project_type, files, redis_project_id):
        """Process file upload in background"""
        try:
            from models.database import PostgresDB
            db = PostgresDB(self.webui.db_config)

            # Create user directory
            user_dir = os.path.join(self.webui.base_project_dir, str(user_id))
            os.makedirs(user_dir, exist_ok=True)

            # Create project directory path
            project_dir = os.path.join(user_dir, project_name)

            # Delete existing folder if it exists
            if os.path.exists(project_dir):
                self._update_progress(user_id, redis_project_id, {
                    'status': 'cleaning',
                    'message': 'Cleaning existing directory...',
                    'percentage': 5
                })
                shutil.rmtree(project_dir)
                time.sleep(1)

            # Create fresh project directory
            os.makedirs(project_dir, exist_ok=True)

            # Save files with progress updates
            total_files = len(files)
            processed_files = 0

            self._update_progress(user_id, redis_project_id, {
                'status': 'uploading',
                'total_files': total_files,
                'processed_files': 0,
                'percentage': 10,
                'message': f'Uploading {total_files} files...'
            })

            for i, file in enumerate(files):
                if file.filename and file.filename.strip():
                    relative_path = file.filename
                    file_path = os.path.join(project_dir, relative_path)

                    # Create directory if needed
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)

                    # Save file
                    file.save(file_path)
                    processed_files += 1

                    # Update progress every 10 files or when complete
                    if processed_files % 10 == 0 or processed_files == total_files:
                        percentage = 10 + int((processed_files / total_files) * 80)
                        self._update_progress(user_id, redis_project_id, {
                            'status': 'uploading',
                            'total_files': total_files,
                            'processed_files': processed_files,
                            'current_file': relative_path,
                            'percentage': min(percentage, 90),
                            'message': f'Uploaded {processed_files}/{total_files} files...'
                        })

            # Store in database
            self._update_progress(user_id, redis_project_id, {
                'status': 'saving',
                'percentage': 90,
                'message': 'Saving project to database...'
            })

            project_id = db.create_user_project(
                user_id, project_name, project_type, project_dir, redis_project_id
            )

            if project_id:
                # Store in Redis
                self._update_progress(user_id, redis_project_id, {
                    'status': 'analyzing',
                    'percentage': 95,
                    'message': 'Analyzing project structure...'
                })

                # Initialize Redis storage
                assistant = self.webui.get_user_assistant(user_id, [project_dir])
                if assistant:
                    assistant.redis_manager.store_project_structure(
                        [project_dir], redis_project_id, user_id
                    )

                # Complete
                self._update_progress(user_id, redis_project_id, {
                    'status': 'completed',
                    'percentage': 100,
                    'message': f'Project "{project_name}" uploaded successfully with {total_files} files!',
                    'project_id': project_id,
                    'total_files': total_files
                })
            else:
                raise Exception("Failed to create project in database")

        except Exception as e:
            print(f"❌ Upload error: {e}")
            self._update_progress(user_id, redis_project_id, {
                'status': 'error',
                'percentage': 100,
                'message': f'Upload failed: {str(e)}'
            })

    def _update_git_progress(self, user_id, redis_project_id, progress):
        """Update Git-specific progress in Redis"""
        try:
            if hasattr(self.webui, 'assistant') and self.webui.assistant:
                # Use a different key for Git progress to avoid conflicts with upload
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"
                self.webui.assistant.redis_client.setex(progress_key, 900, json.dumps(progress))
                print(f"🔍 DEBUG: Updated Git progress: {progress}")
        except Exception as e:
            print(f"❌ Error updating Git progress: {e}")

    def get_git_progress(self, user_id, redis_project_id):
        """Get Git-specific progress from Redis"""
        try:
            if hasattr(self.webui, 'assistant') and self.webui.assistant:
                progress_key = f"git_progress:user:{user_id}:project:{redis_project_id}"
                progress_data = self.webui.assistant.redis_client.get(progress_key)
                if progress_data:
                    return json.loads(progress_data)
        except Exception as e:
            print(f"❌ Error getting Git progress: {e}")
        return None

    def _add_terminal_output(self, user_id, redis_project_id, message):
        """Add message to terminal output with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        terminal_line = f"[{timestamp}] {message}"

        # Get current Git progress
        current_progress = self.get_git_progress(user_id, redis_project_id)
        if current_progress:
            terminal_output = current_progress.get('terminal_output', [])
            terminal_output.append(terminal_line)

            # Keep only last 20 lines to avoid too much data
            if len(terminal_output) > 20:
                terminal_output = terminal_output[-20:]

            # Update progress with new terminal output
            current_progress['terminal_output'] = terminal_output
            self._update_git_progress(user_id, redis_project_id, current_progress)
        else:
            # Create new progress entry
            new_progress = {
                'status': 'cloning',
                'percentage': 0,
                'message': 'Starting Git clone...',
                'terminal_output': [terminal_line]
            }
            self._update_git_progress(user_id, redis_project_id, new_progress)

    def _clean_existing_directory(self, project_dir, user_id, redis_project_id):
        """Safely delete existing directory if it exists"""
        try:
            if os.path.exists(project_dir):
                self._add_terminal_output(user_id, redis_project_id, f"🧹 Cleaning existing directory: {project_dir}")

                # Check if it's a directory
                if os.path.isdir(project_dir):
                    shutil.rmtree(project_dir)
                    self._add_terminal_output(user_id, redis_project_id, "✅ Existing directory deleted successfully")

                    # Wait a moment to ensure cleanup is complete
                    time.sleep(1)

                    # Double check it's gone
                    if os.path.exists(project_dir):
                        self._add_terminal_output(user_id, redis_project_id, "⚠️ Warning: Directory still exists after deletion")
                        return False
                    return True
                else:
                    # It's a file, not a directory
                    os.remove(project_dir)
                    self._add_terminal_output(user_id, redis_project_id, "✅ Existing file deleted successfully")
                    return True
            else:
                self._add_terminal_output(user_id, redis_project_id, "📁 No existing directory to clean")
                return True

        except Exception as e:
            self._add_terminal_output(user_id, redis_project_id, f"❌ Error cleaning directory: {str(e)}")
            return False

    import shutil
    import os

    def _process_git_clone(self, user_id, project_name, git_url, project_dir, redis_project_id, git_username='', git_token=''):
        """Process Git clone in background — always delete existing folder and DB record before cloning."""
        import os
        import shutil
        import subprocess
        import traceback
        from models.database import PostgresDB

        print(f"🔍 DEBUG: Starting Git clone process for user {user_id}")
        print(f"🔍 DEBUG: Project name: {project_name}")
        print(f"🔍 DEBUG: Git URL: {git_url}")
        print(f"🔍 DEBUG: Project directory: {project_dir}")

        try:
            db = PostgresDB(self.webui.db_config)

            # STEP 0: Remove any existing record or folder for same project
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cleaning',
                'percentage': 5,
                'message': f'🧹 Checking for existing project "{project_name}"...'
            })
            self._add_terminal_output(user_id, redis_project_id, f"🧹 Checking for existing project '{project_name}'...")

            # --- Remove from DB if exists ---
            try:
                existing_project = db.fetch_one(
                    "SELECT id FROM projects WHERE user_id = %s AND name = %s",
                    (user_id, project_name)
                )
                if existing_project:
                    db.execute("DELETE FROM projects WHERE id = %s", (existing_project["id"],))
                    self._add_terminal_output(user_id, redis_project_id, f"🗑️ Removed existing DB record for project: {project_name}")
            except Exception as db_err:
                self._add_terminal_output(user_id, redis_project_id, f"⚠️ Could not check/delete existing DB record: {db_err}")

            # --- Remove folder if exists ---
            if os.path.exists(project_dir):
                try:
                    shutil.rmtree(project_dir)
                    self._add_terminal_output(user_id, redis_project_id, f"🧹 Removed existing project folder: {project_dir}")
                except Exception as e:
                    raise Exception(f"Failed to remove existing project directory: {e}")

            # STEP 1: Create a fresh directory
            try:
                os.makedirs(project_dir, exist_ok=True)
                self._add_terminal_output(user_id, redis_project_id, f"✅ Created fresh directory: {project_dir}")
            except Exception as e:
                raise Exception(f"Failed to create project directory: {e}")

            # STEP 2: Initialize Git-specific progress
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'starting',
                'percentage': 10,
                'message': '🚀 Starting repository download...',
                'terminal_output': [
                    '🚀 Starting repository download...',
                    f'📁 Repository: {self._mask_git_url(git_url)}'
                ]
            })

            # STEP 3: Try direct download first (for public repos)
            if not git_username and not git_token:
                self._add_terminal_output(user_id, redis_project_id, "🔍 Checking if repository is public...")

                self._update_git_progress(user_id, redis_project_id, {
                    'status': 'downloading',
                    'percentage': 20,
                    'message': '📥 Trying direct download...'
                })

                self._add_terminal_output(user_id, redis_project_id, "📥 Attempting direct download (no Git required)...")

                direct_success = self._download_public_repo(user_id, redis_project_id, git_url, project_dir)

                if direct_success:
                    self._add_terminal_output(user_id, redis_project_id, "✅ Successfully downloaded via direct method!")
                    return self._analyze_and_save_project(user_id, project_name, git_url, project_dir, redis_project_id)
                else:
                    self._add_terminal_output(user_id, redis_project_id, "⚠️ Direct download failed, falling back to Git...")

            # STEP 4: Clone using Git
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 40,
                'message': '📥 Cloning repository using Git...'
            })
            self._add_terminal_output(user_id, redis_project_id, "🔄 Using Git clone method...")

            git_success = self._git_clone_with_progress(
                user_id,
                redis_project_id,
                git_url,
                project_dir,
                git_username,
                git_token
            )

            if not git_success:
                raise Exception("Both direct download and Git clone failed")

            # STEP 5: Analyze and save project
            return self._analyze_and_save_project(user_id, project_name, git_url, project_dir, redis_project_id)

        except Exception as e:
            print(f"❌ Git clone error: {e}")
            print(traceback.format_exc())

            self._add_terminal_output(user_id, redis_project_id, f"❌ Error: {str(e)}")
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
        """Analyze and save the downloaded project"""
        try:
            from models.database import PostgresDB
            db = PostgresDB(self.webui.db_config)

            self._add_terminal_output(user_id, redis_project_id, "✅ Repository downloaded successfully!")

            # Analyze the downloaded repository
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'analyzing',
                'percentage': 70,
                'message': '🔍 Analyzing project structure...'
            })

            self._add_terminal_output(user_id, redis_project_id, "🔍 Analyzing project structure...")

            # Detect project type
            project_type = self._detect_project_type(project_dir)
            self._add_terminal_output(user_id, redis_project_id, f"📋 Detected project type: {project_type}")

            # Count files
            file_count = self._count_files(project_dir)
            self._add_terminal_output(user_id, redis_project_id, f"📊 Found {file_count} files in project")

            # Store in database
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'saving',
                'percentage': 80,
                'message': '💾 Saving to database...'
            })

            self._add_terminal_output(user_id, redis_project_id, "💾 Saving project to database...")

            # Use the database method with FIXED parameters
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

            # Store in Redis
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'indexing',
                'percentage': 90,
                'message': '📚 Indexing files for AI...'
            })

            self._add_terminal_output(user_id, redis_project_id, "📚 Indexing files for AI analysis...")

            # Initialize Redis storage
            assistant = self.webui.get_user_assistant(user_id, [project_dir])
            if assistant:
                # Store project structure in Redis with user association
                assistant.redis_manager.store_project_structure(
                    [project_dir], redis_project_id, user_id
                )

            self._add_terminal_output(user_id, redis_project_id, "✅ Files indexed successfully!")

            # Complete
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'completed',
                'percentage': 100,
                'message': f'🎉 Project "{project_name}" ready with {file_count} files!',
                'project_id': project_id,
                'total_files': file_count,
                'project_path': project_dir
            })

            self._add_terminal_output(user_id, redis_project_id, "🎉 Project setup completed successfully!")
            self._add_terminal_output(user_id, redis_project_id, f"📁 Location: {project_dir}")
            self._add_terminal_output(user_id, redis_project_id, f"📊 Total files: {file_count}")
            self._add_terminal_output(user_id, redis_project_id, f"👤 User ID: {user_id}")

            print(f"🔍 DEBUG: Project download completed successfully!")
            return True

        except Exception as e:
            print(f"❌ Error in analyze and save: {e}")
            raise

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

    def _git_clone_with_progress(self, user_id, redis_project_id, git_url, project_dir, git_username, git_token):
        """Clone Git repository with real-time progress tracking"""
        try:
            # Update Git-specific progress
            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 15,
                'message': '🌐 Connecting to repository...'
            })
            self._add_terminal_output(user_id, redis_project_id, "🌐 Connecting to Git repository...")

            time.sleep(1)

            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 25,
                'message': '📥 Downloading repository data...'
            })
            self._add_terminal_output(user_id, redis_project_id, "📥 Downloading repository data...")

            # Use shallow clone for faster downloads
            clone_cmd = ['git', 'clone', '--depth', '1', git_url, project_dir]

            self._add_terminal_output(user_id, redis_project_id, f"⚡ Command: git clone --depth 1 {self._mask_git_url(git_url)}")

            # Execute clone
            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip()
                self._add_terminal_output(user_id, redis_project_id, f"❌ Git error: {error_msg}")
                return False

            self._update_git_progress(user_id, redis_project_id, {
                'status': 'cloning',
                'percentage': 60,
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

    def _update_progress(self, user_id, redis_project_id, progress):
        """Update progress in Redis"""
        if hasattr(self.webui, 'assistant') and self.webui.assistant:
            self.webui.assistant.redis_manager._update_upload_progress(
                user_id, redis_project_id, progress
            )