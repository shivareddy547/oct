import os
import json
import requests
import subprocess
import yaml
from typing import List, Dict, Any
from models.database import PostgresDB
from models.redis_manager import MultiProjectRedisManager
from models.file_finder import MultiProjectFileFinder
from models.context_builder import MultiProjectContextBuilder
from models.ollama_analyzer import OllamaAnalyzer

class MultiProjectAIAssistant:
    def __init__(self, project_paths: List[str], redis_config: Dict, db_config: Dict):
        self.project_paths = project_paths
        self.redis_manager = MultiProjectRedisManager(redis_config)
        self.db = PostgresDB(db_config)
        self.file_finder = MultiProjectFileFinder(project_paths)  # Pass project_paths here
        self.context_builder = MultiProjectContextBuilder()
        self.ollama = OllamaAnalyzer()
        self.current_model = "qwen3-coder:480b-cloud"

        # Generate a unique project ID based on project paths
        self.project_id = self._generate_project_id()


        # To:


        # Initialize projects in Redis
        self.redis_manager.store_project_structure(self.project_paths, self.project_id)

    def _generate_project_id(self) -> str:
        """Generate a unique project ID based on project paths"""
        import hashlib
        project_string = "|".join(sorted(self.project_paths))
        return hashlib.md5(project_string.encode()).hexdigest()[:16]

    def initialize_projects(self) -> Dict[str, Any]:
        """Initialize all projects and store their structure"""
        project_data = {}

        for project_path in self.project_paths:
            if not os.path.exists(project_path):
                raise ValueError(f"Project path does not exist: {project_path}")

            # Get project structure
            project_structure = self.file_finder.get_project_structure(project_path)
            project_type = self.file_finder.get_project_type(project_path)

            project_data[project_path] = {
                'type': project_type,
                'structure': project_structure,
                'file_count': len(project_structure)
            }

        # Store in Redis
        self.redis_manager.store_project_structure(self.project_paths, self.project_id)

        return project_data

    def get_project_info(self) -> Dict[str, Any]:
        """Get information about all loaded projects"""
        projects = []
        total_files = 0

        for project_path in self.project_paths:
            project_type = self.file_finder.get_project_type(project_path)  # Fixed method name
            files = self.file_finder.get_project_structure(project_path)    # This should work now
            file_count = len(files)
            total_files += file_count

            projects.append({
                'root': project_path,
                'type': project_type,
                'file_count': file_count,
                'name': os.path.basename(project_path)
            })

        return {
            'project_id': self.project_id,
            'total_projects': len(projects),
            'total_files': total_files,
            'projects': projects
        }

    def set_model(self, model_name: str):
        """Set the current model to use"""
        self.current_model = model_name
        self.ollama.set_model(model_name)

    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models"""
        try:
            return self.ollama.get_available_models()
        except Exception as e:
            print(f"❌ Error getting available models: {e}")
            return ["qwen3-coder:480b-cloud", "codellama:latest", "llama3:8b"]

    def process_query(self, query: str, session_id: str, use_auto_generate: bool = True) -> str:
        """Process a user query and generate YAML response"""
        try:
            print(f"🔍 Processing query: {query}")

            # Build context from all projects
            context = self.context_builder.build_context_from_projects(self.project_paths)

            if use_auto_generate:
                # Use intent-aware auto-generation
                prompt = self._build_auto_generate_prompt(query, context)
            else:
                # Use standard analysis
                prompt = self._build_standard_prompt(query, context)

            # Get response from Ollama
            response = self.ollama.analyze_with_prompt(prompt, self.current_model)

            # Extract YAML from response
            yaml_response = self._extract_yaml_from_response(response)

            # Store conversation in database
            self.db.store_conversation(session_id, query, yaml_response, self.current_model, 'ollama')

            return yaml_response

        except Exception as e:
            print(f"❌ Error processing query: {e}")
            raise

    def _build_auto_generate_prompt(self, query: str, context: str) -> str:
        """Build prompt for intent-aware auto-generation"""
        return f"""You are a multi-project AI assistant. You have access to multiple codebases including React and Ruby on Rails projects.

PROJECT CONTEXT:
{context}

USER QUERY: {query}

Based on the user's intent and the existing project structure, generate a comprehensive implementation plan in YAML format.

YAML STRUCTURE:
- For each relevant project, specify:
  - files_to_create: [list of files with paths and content]
  - files_to_modify: [list of files with paths and changes]
  - packages_to_install: [list of dependencies]
  - commands_to_run: [list of terminal commands]
  - database_changes: [migrations, schema changes]

CRITICAL REQUIREMENTS:
1. Analyze the existing project structure and build upon it
2. Create complete, working code implementations
3. Ensure cross-project compatibility
4. Include all necessary imports and dependencies
5. Follow best practices for each technology stack
6. Generate actual file content, not just descriptions

RESPONSE FORMAT: Return ONLY valid YAML, no markdown formatting or additional text."""

    def _build_standard_prompt(self, query: str, context: str) -> str:
        """Build standard analysis prompt"""
        return f"""Analyze this multi-project codebase and provide implementation details for: {query}

PROJECT CONTEXT:
{context}

Provide a YAML response with:
- Files to create/modify
- Code changes needed
- Dependencies to add
- Commands to run

Focus on practical implementation across all relevant projects."""

    def _extract_yaml_from_response(self, response: str) -> str:
        """Extract YAML content from model response"""
        # Remove markdown code blocks if present
        if '```yaml' in response:
            response = response.split('```yaml')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]

        return response.strip()

    def process_with_openai(self, query: str, model: str, api_key: str, session_id: str) -> str:
        """Process query using OpenAI API"""
        try:
            # Build the context from projects
            context = self.context_builder.build_context_from_projects(self.project_paths)

            # Prepare the prompt
            prompt = f"""You are a multi-project AI assistant working with React and Ruby on Rails projects.

AVAILABLE PROJECTS CONTEXT:
{context}

USER QUERY: {query}

Generate a comprehensive YAML implementation plan that includes:

1. File creations/modifications across all relevant projects
2. Complete code implementations with proper syntax
3. Database migrations if needed
4. Package dependencies to install
5. Configuration changes
6. Terminal commands to execute

YAML FORMAT:
project_name:
  files:
    - path: "full/file/path"
      content: |
        complete file content here
  packages:
    - package_name
  commands:
    - command_to_run
  database:
    - migration_name

CRITICAL:
- Analyze existing project structure and build upon it
- Generate working, complete code
- Ensure React and Rails components work together
- Include all necessary imports
- Follow language/framework best practices

Return ONLY valid YAML, no additional text or markdown formatting."""

            # Call OpenAI API
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'You are an expert full-stack developer specializing in React and Ruby on Rails. You generate precise YAML implementations for multi-project development.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.1,
                'max_tokens': 8000
            }

            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=payload,
                timeout=120
            )

            if response.status_code != 200:
                error_msg = f"OpenAI API error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data.get('error', {}).get('message', 'Unknown error')}"
                except:
                    error_msg += f" - {response.text}"
                raise Exception(error_msg)

            result = response.json()
            yaml_response = result['choices'][0]['message']['content']

            # Clean the response
            yaml_response = self._extract_yaml_from_response(yaml_response)

            # Store in database
            self.db.store_conversation(session_id, query, yaml_response, model, 'openai')

            return yaml_response

        except Exception as e:
            print(f"❌ Error with OpenAI API: {e}")
            raise

    def process_with_openrouter(self, query: str, model: str, api_key: str, session_id: str) -> str:
        """Process query using OpenRouter API"""
        try:
            # Build the context from projects
            context = self.context_builder.build_context_from_projects(self.project_paths)

            # Prepare the prompt
            prompt = f"""You are a multi-project AI assistant working with React and Ruby on Rails projects.

AVAILABLE PROJECTS CONTEXT:
{context}

USER QUERY: {query}

Generate a comprehensive YAML implementation plan that includes:

1. File creations/modifications across all relevant projects
2. Complete code implementations with proper syntax
3. Database migrations if needed
4. Package dependencies to install
5. Configuration changes
6. Terminal commands to execute

YAML FORMAT:
project_name:
  files:
    - path: "full/file/path"
      content: |
        complete file content here
  packages:
    - package_name
  commands:
    - command_to_run
  database:
    - migration_name

CRITICAL:
- Analyze existing project structure and build upon it
- Generate working, complete code
- Ensure React and Rails components work together
- Include all necessary imports
- Follow language/framework best practices

Return ONLY valid YAML, no additional text or markdown formatting."""

            # Call OpenRouter API
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5000',
                'X-Title': 'Multi-Project AI Assistant'
            }

            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'You are an expert full-stack developer specializing in React and Ruby on Rails. You generate precise YAML implementations for multi-project development.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.1,
                'max_tokens': 8000
            }

            response = requests.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers=headers,
                json=payload,
                timeout=120
            )

            if response.status_code != 200:
                error_msg = f"OpenRouter API error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data.get('error', {}).get('message', 'Unknown error')}"
                except:
                    error_msg += f" - {response.text}"
                raise Exception(error_msg)

            result = response.json()
            yaml_response = result['choices'][0]['message']['content']

            # Clean the response
            yaml_response = self._extract_yaml_from_response(yaml_response)

            # Store in database
            self.db.store_conversation(session_id, query, yaml_response, model, 'openrouter')

            return yaml_response

        except Exception as e:
            print(f"❌ Error with OpenRouter API: {e}")
            raise

    def apply_changes(self, yaml_response: str) -> Dict[str, Any]:
        """Apply changes from YAML response to projects"""
        try:
            # Parse YAML
            changes = yaml.safe_load(yaml_response)
            if not changes:
                return {'error': 'Invalid YAML format'}

            results = {
                'files_created': [],
                'files_updated': [],
                'files_failed': [],
                'packages_installed': [],
                'install_output': [],
                'commands_executed': []
            }

            # Process each project in the YAML
            for project_name, project_changes in changes.items():
                # Find the actual project path
                project_path = self._find_project_path(project_name)
                if not project_path:
                    results['files_failed'].append(f"Project not found: {project_name}")
                    continue

                # Create files
                if 'files' in project_changes:
                    for file_info in project_changes['files']:
                        try:
                            file_path = os.path.join(project_path, file_info['path'])
                            os.makedirs(os.path.dirname(file_path), exist_ok=True)

                            if os.path.exists(file_path):
                                with open(file_path, 'w') as f:
                                    f.write(file_info['content'])
                                results['files_updated'].append(file_path)
                            else:
                                with open(file_path, 'w') as f:
                                    f.write(file_info['content'])
                                results['files_created'].append(file_path)

                        except Exception as e:
                            results['files_failed'].append(f"{file_info['path']}: {str(e)}")

                # Install packages
                if 'packages' in project_changes:
                    for package in project_changes['packages']:
                        try:
                            if project_name.lower().endswith('rails') or 'gemfile' in str(project_path).lower():
                                # Rails project - add to Gemfile
                                self._add_to_gemfile(project_path, package)
                                results['packages_installed'].append(f"{package} (Gemfile)")
                            else:
                                # React project - install with npm/yarn
                                result = subprocess.run(
                                    ['npm', 'install', package],
                                    cwd=project_path, capture_output=True, text=True, timeout=120
                                )
                                if result.returncode == 0:
                                    results['packages_installed'].append(package)
                                    results['install_output'].append(f"Installed {package} in {project_name}")
                                else:
                                    results['files_failed'].append(f"Failed to install {package}: {result.stderr}")
                        except Exception as e:
                            results['files_failed'].append(f"Package {package}: {str(e)}")

                # Run commands
                if 'commands' in project_changes:
                    for command in project_changes['commands']:
                        try:
                            result = subprocess.run(
                                command, shell=True, cwd=project_path,
                                capture_output=True, text=True, timeout=300
                            )
                            results['commands_executed'].append({
                                'command': command,
                                'output': result.stdout,
                                'error': result.stderr
                            })
                        except Exception as e:
                            results['files_failed'].append(f"Command {command}: {str(e)}")

            # Update Redis with new project structure
            self.redis_manager.store_project_structure(self.project_paths, self.project_id)

            return results

        except Exception as e:
            print(f"❌ Error applying changes: {e}")
            return {'error': str(e)}

    def _find_project_path(self, project_name: str) -> str:
        """Find the actual project path from project name in YAML"""
        for project_path in self.project_paths:
            if project_name.lower() in project_path.lower() or \
               project_name.lower() in os.path.basename(project_path).lower():
                return project_path
        return None

    def _add_to_gemfile(self, project_path: str, gem_name: str):
        """Add gem to Gemfile in Rails project"""
        gemfile_path = os.path.join(project_path, 'Gemfile')
        if os.path.exists(gemfile_path):
            with open(gemfile_path, 'a') as f:
                f.write(f"\ngem '{gem_name}'")
        else:
            with open(gemfile_path, 'w') as f:
                f.write(f"source 'https://rubygems.org'\n\ngem '{gem_name}'")

    def get_conversation_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get conversation history for a session"""
        return self.db.get_conversation_history(session_id, limit)

    def get_all_conversations(self, limit: int = 50) -> List[Dict]:
        """Get all conversations across all sessions"""
        return self.db.get_all_conversations(limit)