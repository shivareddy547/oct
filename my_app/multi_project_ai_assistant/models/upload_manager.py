import threading
from flask import jsonify
import time
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

    def _process_upload(self, user_id, project_name, project_type, files, redis_project_id):
        """Process upload in background with better memory management"""
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
                time.sleep(1)  # Give OS time to clean up

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

            # Calculate total size for progress tracking
            total_size = sum(len(file.read()) for file in files)
            for file in files:
                file.seek(0)  # Reset file pointers

            uploaded_size = 0

            for i, file in enumerate(files):
                if file.filename and file.filename.strip():
                    relative_path = file.filename
                    file_path = os.path.join(project_dir, relative_path)

                    # Create directory if needed
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)

                    # Save file in chunks to handle large files
                    chunk_size = 8192  # 8KB chunks
                    file_size = 0

                    with open(file_path, 'wb') as f:
                        while True:
                            chunk = file.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            file_size += len(chunk)
                            uploaded_size += len(chunk)

                    processed_files += 1

                    # Update progress
                    percentage = 10 + int((uploaded_size / total_size) * 80) if total_size > 0 else 10
                    self._update_progress(user_id, redis_project_id, {
                        'status': 'uploading',
                        'total_files': total_files,
                        'processed_files': processed_files,
                        'current_file': relative_path,
                        'percentage': min(percentage, 90),
                        'message': f'Uploaded {processed_files}/{total_files} files ({uploaded_size//1024//1024}MB/{total_size//1024//1024}MB)'
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

    def _update_progress(self, user_id, redis_project_id, progress):
        """Update progress in Redis"""
        if hasattr(self.webui, 'assistant') and self.webui.assistant:
            self.webui.assistant.redis_manager._update_upload_progress(
                user_id, redis_project_id, progress
            )    self.upload_manager = UploadManager(self)