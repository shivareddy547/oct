import os
import fnmatch
from typing import List, Dict, Any

class MultiProjectFileFinder:
    def __init__(self, project_roots: List[str]):
        self.project_roots = project_roots

    def get_project_structure(self, project_path: str) -> List[str]:
        """Get all files in a project directory"""
        files = []
        for root, dirs, filenames in os.walk(project_path):
            # Skip node_modules, .git, and other common directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']

            for filename in filenames:
                if not filename.startswith('.'):
                    full_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(full_path, project_path)
                    files.append(relative_path)
        return files

    def get_project_type(self, project_path: str) -> str:
        """Detect project type based on files present"""
        if os.path.exists(os.path.join(project_path, 'package.json')):
            return 'react'
        elif os.path.exists(os.path.join(project_path, 'Gemfile')):
            return 'rails'
        elif os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
            return 'rails'
        elif os.path.exists(os.path.join(project_path, 'app', 'models')):
            return 'rails'
        else:
            return 'unknown'

    def find_files_by_pattern(self, pattern: str) -> Dict[str, List[str]]:
        """Find files matching pattern across all projects"""
        results = {}
        for project_root in self.project_roots:
            project_files = []
            for root, dirs, filenames in os.walk(project_root):
                for filename in filenames:
                    if fnmatch.fnmatch(filename, pattern):
                        full_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(full_path, project_root)
                        project_files.append(relative_path)
            results[project_root] = project_files
        return results