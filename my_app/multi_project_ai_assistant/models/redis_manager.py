# /media/shivareddy/E/oct-2025/15_evg/oct/my_app/multi_project_ai_assistant/models/redis_manager.py

import os
import json
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import redis
import uuid
from datetime import datetime

class MultiProjectRedisManager:
    def __init__(self, redis_config: Dict):
        try:
            self.redis_client = redis.Redis(
                host=redis_config['host'],
                port=redis_config['port'],
                db=redis_config['db'],
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
        self.user_key_prefix = "user:"

    def store_project_structure(self, project_paths: List[str], project_id: str = "default", user_id: int = None):
        """Store multiple project structures in Redis with user association"""
        if not self.redis_client:
            print("❌ Redis not available, skipping project storage")
            return {}

        all_project_data = {}
        upload_progress = {
            'total_files': 0,
            'processed_files': 0,
            'current_file': '',
            'status': 'starting',
            'user_id': user_id,
            'project_id': project_id
        }

        # Store upload progress
        self._update_upload_progress(user_id, project_id, upload_progress)

        total_files = 0
        # First pass: count total files
        for project_path in project_paths:
            project_path = Path(project_path)
            extensions = self._get_project_extensions(project_path)
            for root, _, file_list in os.walk(project_path):
                if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next', 'tmp', 'log', 'vendor/bundle']):
                    continue
                for file in file_list:
                    if any(fnmatch.fnmatch(file, pattern) for pattern in extensions):
                        total_files += 1

        upload_progress['total_files'] = total_files
        self._update_upload_progress(user_id, project_id, upload_progress)

        processed_files = 0

        for i, project_path in enumerate(project_paths):
            project_path = Path(project_path)
            project_type = self._detect_project_type(project_path)
            project_data = {
                'project_root': str(project_path),
                'project_type': project_type,
                'files': {},
                'user_id': user_id,
                'created_at': datetime.now().isoformat(),
                'project_id': f"{project_id}_project_{i}"
            }

            extensions = self._get_project_extensions(project_path)

            for root, _, file_list in os.walk(project_path):
                # Skip common directories
                if any(ignored in root for ignored in ['node_modules', '.git', 'build', 'dist', '.next', 'tmp', 'log', 'vendor/bundle']):
                    continue

                for file in file_list:
                    file_path = Path(root) / file
                    relative_path = str(file_path.relative_to(project_path))

                    if any(fnmatch.fnmatch(file, pattern) for pattern in extensions):
                        try:
                            # Update progress
                            upload_progress['current_file'] = relative_path
                            upload_progress['processed_files'] = processed_files
                            upload_progress['status'] = 'processing'
                            self._update_upload_progress(user_id, project_id, upload_progress)

                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            # Store file content with user association
                            file_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:file:{relative_path}"
                            self.redis_client.set(file_key, content)

                            # Store file metadata
                            file_meta_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:meta:{relative_path}"
                            file_metadata = {
                                'path': relative_path,
                                'size': len(content),
                                'hash': hashlib.md5(content.encode()).hexdigest(),
                                'project_type': project_type,
                                'user_id': user_id,
                                'project_id': project_id,
                                'created_at': datetime.now().isoformat()
                            }
                            self.redis_client.set(file_meta_key, json.dumps(file_metadata))

                            project_data['files'][relative_path] = file_metadata
                            processed_files += 1

                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")
                            upload_progress['status'] = f'error: {str(e)}'
                            self._update_upload_progress(user_id, project_id, upload_progress)

            # Store project structure
            structure_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:project_{i}:structure"
            self.redis_client.set(structure_key, json.dumps(project_data))
            all_project_data[f'project_{i}'] = project_data

        # Store main structure with user association
        main_structure_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:main_structure"
        main_structure_data = {
            'project_paths': project_paths,
            'projects': all_project_data,
            'user_id': user_id,
            'total_files': total_files,
            'created_at': datetime.now().isoformat(),
            'project_id': project_id
        }
        self.redis_client.set(main_structure_key, json.dumps(main_structure_data))

        # Add project to user's project list
        user_projects_key = f"{self.user_key_prefix}{user_id}:projects"
        self.redis_client.sadd(user_projects_key, project_id)

        # Update progress to completed
        upload_progress['status'] = 'completed'
        upload_progress['processed_files'] = processed_files
        self._update_upload_progress(user_id, project_id, upload_progress)

        return all_project_data

    def _update_upload_progress(self, user_id: int, project_id: str, progress: Dict):
        """Update upload progress in Redis"""
        if not self.redis_client:
            return

        progress_key = f"upload_progress:user:{user_id}:project:{project_id}"
        # Store for 15 minutes during upload process
        self.redis_client.setex(progress_key, 900, json.dumps(progress))
        print(f"📊 Progress updated: {progress.get('status', 'unknown')} - {progress.get('percentage', 0)}%")

    def get_upload_progress(self, user_id: int, project_id: str) -> Optional[Dict]:
        """Get current upload progress"""
        if not self.redis_client:
            return None

        progress_key = f"upload_progress:user:{user_id}:project:{project_id}"
        progress_data = self.redis_client.get(progress_key)
        if progress_data:
            return json.loads(progress_data)
        return None

    def set_progress(self, redis_project_id: str, data: dict):
        self.client.set(f"git_progress:{redis_project_id}", json.dumps(data), ex=3600)

    def get_progress(self, redis_project_id: str):
        data = self.client.get(f"git_progress:{redis_project_id}")
        if data:
            return json.loads(data)
        return None

    def delete_user_project(self, user_id: int, project_id: str):
        """Delete all project data for a specific user and project"""
        if not self.redis_client:
            return False

        try:
            # Get all keys for this user and project
            pattern = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:*"
            keys = self.redis_client.keys(pattern)

            if keys:
                self.redis_client.delete(*keys)
                print(f"✅ Deleted {len(keys)} Redis keys for user {user_id}, project {project_id}")

            # Remove from user's project list
            user_projects_key = f"{self.user_key_prefix}{user_id}:projects"
            self.redis_client.srem(user_projects_key, project_id)

            # Delete progress
            progress_key = f"upload_progress:user:{user_id}:project:{project_id}"
            self.redis_client.delete(progress_key)

            return True
        except Exception as e:
            print(f"❌ Error deleting project from Redis: {e}")
            return False

    def get_user_projects(self, user_id: int) -> List[str]:
        """Get all project IDs for a user"""
        if not self.redis_client:
            return []

        user_projects_key = f"{self.user_key_prefix}{user_id}:projects"
        return list(self.redis_client.smembers(user_projects_key))

    def get_project_files(self, user_id: int, project_id: str) -> List[Dict]:
        """Get all files for a user's project"""
        if not self.redis_client:
            return []

        files = []
        pattern = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:meta:*"
        meta_keys = self.redis_client.keys(pattern)

        for meta_key in meta_keys:
            meta_data = self.redis_client.get(meta_key)
            if meta_data:
                files.append(json.loads(meta_data))

        return files

    def get_file_content(self, user_id: int, project_id: str, file_path: str) -> Optional[str]:
        """Get specific file content for a user's project"""
        if not self.redis_client:
            return None

        file_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:file:{file_path}"
        return self.redis_client.get(file_key)

    def search_in_user_projects(self, user_id: int, query: str) -> List[Dict]:
        """Search for content in user's projects"""
        if not self.redis_client:
            return []

        results = []
        project_ids = self.get_user_projects(user_id)

        for project_id in project_ids:
            pattern = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:file:*"
            file_keys = self.redis_client.keys(pattern)

            for file_key in file_keys:
                content = self.redis_client.get(file_key)
                if content and query.lower() in content.lower():
                    # Extract file path from key
                    file_path = file_key.split(':file:')[-1]

                    # Get metadata
                    meta_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:meta:{file_path}"
                    meta_data = self.redis_client.get(meta_key)

                    if meta_data:
                        result = json.loads(meta_data)
                        result['content_snippet'] = self._get_content_snippet(content, query)
                        result['project_id'] = project_id
                        results.append(result)

        return results

    def _get_content_snippet(self, content: str, query: str, snippet_length: int = 100) -> str:
        """Get a snippet of content around the query"""
        query_lower = query.lower()
        content_lower = content.lower()

        index = content_lower.find(query_lower)
        if index == -1:
            return content[:snippet_length] + "..." if len(content) > snippet_length else content

        start = max(0, index - snippet_length // 2)
        end = min(len(content), index + len(query) + snippet_length // 2)

        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def _get_project_extensions(self, project_path: Path) -> List[str]:
        """Get file extensions based on project type"""
        project_type = self._detect_project_type(project_path)

        if project_type == 'react':
            return ['*.js', '*.jsx', '*.ts', '*.tsx', '*.css', '*.scss', '*.json', '*.html', '*.md']
        elif project_type == 'rails':
            return ['*.rb', '*.erb', '*.haml', '*.slim', '*.yml', '*.yaml', '*.json', '*.js', '*.css', '*.scss', '*.coffee', '*.html', '*.md']
        else:
            return ['*.js', '*.jsx', '*.ts', '*.tsx', '*.rb', '*.erb', '*.yml', '*.yaml', '*.json', '*.html', '*.md', '*.py', '*.java', '*.cpp', '*.c', '*.h']

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

    def get_project_structure(self, project_id: str = "default", user_id: int = None) -> Optional[Dict]:
        """Get main project structure from Redis with user association"""
        if not self.redis_client:
            return None

        if user_id:
            main_structure_key = f"{self.project_key_prefix}user:{user_id}:project:{project_id}:main_structure"
        else:
            main_structure_key = f"{self.project_key_prefix}{project_id}:main_structure"

        structure_data = self.redis_client.get(main_structure_key)
        if structure_data:
            return json.loads(structure_data)
        return None