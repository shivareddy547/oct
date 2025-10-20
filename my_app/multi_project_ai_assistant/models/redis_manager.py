import os
import json
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional
import redis

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