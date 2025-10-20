import os
import fnmatch
from typing import List, Dict, Any

class MultiProjectContextBuilder:
    def __init__(self):
        self.ignored_dirs = {'.git', 'node_modules', '__pycache__', '.vscode', '.idea', 'tmp', 'log'}
        self.ignored_files = {'.DS_Store', '.gitignore', 'package-lock.json', 'yarn.lock'}
        self.max_file_size = 10000  # 10KB max file size to read

    def build_context_from_projects(self, project_paths: List[str]) -> str:
        """Build comprehensive context from all projects"""
        context_parts = []

        for project_path in project_paths:
            if not os.path.exists(project_path):
                continue

            project_name = os.path.basename(project_path)
            project_type = self._detect_project_type(project_path)

            context_parts.append(f"=== PROJECT: {project_name} ({project_type.upper()}) ===")
            context_parts.append(f"Path: {project_path}")

            # Get project structure
            structure = self._get_project_structure(project_path)
            context_parts.append(f"Structure:\n{structure}")

            # Get key files content
            key_files_content = self._get_key_files_content(project_path, project_type)
            if key_files_content:
                context_parts.append(f"Key Files Content:\n{key_files_content}")

            context_parts.append("")  # Empty line between projects

        return "\n".join(context_parts)

    def _detect_project_type(self, project_path: str) -> str:
        """Detect the type of project"""
        if os.path.exists(os.path.join(project_path, 'package.json')):
            return 'react'
        elif os.path.exists(os.path.join(project_path, 'Gemfile')):
            return 'rails'
        elif os.path.exists(os.path.join(project_path, 'config', 'application.rb')):
            return 'rails'
        elif os.path.exists(os.path.join(project_path, 'app', 'models')):
            return 'rails'
        elif os.path.exists(os.path.join(project_path, 'pom.xml')):
            return 'java'
        elif os.path.exists(os.path.join(project_path, 'requirements.txt')):
            return 'python'
        else:
            return 'unknown'

    def _get_project_structure(self, project_path: str, max_depth: int = 3) -> str:
        """Get project structure as string"""
        structure_lines = []

        def build_tree(current_path, depth=0):
            if depth > max_depth:
                return

            try:
                items = os.listdir(current_path)
                items.sort()

                for item in items:
                    if item.startswith('.') and item not in ['.env', '.gitignore']:
                        continue

                    full_path = os.path.join(current_path, item)
                    relative_path = os.path.relpath(full_path, project_path)

                    if os.path.isdir(full_path):
                        if item in self.ignored_dirs:
                            continue
                        structure_lines.append("  " * depth + f"📁 {item}/")
                        build_tree(full_path, depth + 1)
                    else:
                        if item in self.ignored_files:
                            continue
                        structure_lines.append("  " * depth + f"📄 {item}")
            except (PermissionError, OSError):
                pass

        build_tree(project_path)
        return "\n".join(structure_lines)

    def _get_key_files_content(self, project_path: str, project_type: str) -> str:
        """Get content of key configuration files"""
        key_files_content = []
        key_patterns = self._get_key_file_patterns(project_type)

        for pattern in key_patterns:
            files = self._find_files(project_path, pattern)
            for file_path in files[:3]:  # Limit to 3 files per pattern
                content = self._read_file_safely(file_path)
                if content:
                    relative_path = os.path.relpath(file_path, project_path)
                    key_files_content.append(f"--- {relative_path} ---")
                    key_files_content.append(content)
                    key_files_content.append("")  # Empty line between files

        return "\n".join(key_files_content)

    def _get_key_file_patterns(self, project_type: str) -> List[str]:
        """Get key file patterns based on project type"""
        if project_type == 'react':
            return [
                'package.json',
                'src/App.*',  # App.js, App.jsx, App.ts, App.tsx
                'src/index.*',
                'src/components/*.js',
                'src/components/*.jsx',
                'src/components/*.ts',
                'src/components/*.tsx',
                'public/index.html'
            ]
        elif project_type == 'rails':
            return [
                'Gemfile',
                'config/routes.rb',
                'app/models/*.rb',
                'app/controllers/*.rb',
                'app/views/**/*.html.erb',
                'config/database.yml',
                'db/schema.rb'
            ]
        else:
            return [
                '*.json',
                '*.yml',
                '*.yaml',
                '*.xml',
                '*.md',
                'README*'
            ]

    def _find_files(self, directory: str, pattern: str) -> List[str]:
        """Find files matching pattern in directory"""
        matches = []

        for root, dirs, files in os.walk(directory):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in self.ignored_dirs]

            for filename in files:
                if filename.startswith('.'):
                    continue

                if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(os.path.join(root, filename), pattern):
                    full_path = os.path.join(root, filename)
                    matches.append(full_path)

        return matches

    def _read_file_safely(self, file_path: str) -> str:
        """Read file content safely with size limits"""
        try:
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                return f"[File too large: {file_size} bytes]"

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().strip()
                if not content:
                    return "[Empty file]"
                return content

        except (PermissionError, UnicodeDecodeError, OSError) as e:
            return f"[Error reading file: {str(e)}]"

    def get_project_summary(self, project_paths: List[str]) -> Dict[str, Any]:
        """Get summary information about all projects"""
        summary = {
            'total_projects': len(project_paths),
            'projects': []
        }

        for project_path in project_paths:
            if not os.path.exists(project_path):
                continue

            project_type = self._detect_project_type(project_path)
            file_count = self._count_files(project_path)

            summary['projects'].append({
                'name': os.path.basename(project_path),
                'path': project_path,
                'type': project_type,
                'file_count': file_count
            })

        return summary

    def _count_files(self, directory: str) -> int:
        """Count files in directory (excluding ignored files/dirs)"""
        count = 0

        for root, dirs, files in os.walk(directory):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in self.ignored_dirs]

            for filename in files:
                if not filename.startswith('.') and filename not in self.ignored_files:
                    count += 1

        return count