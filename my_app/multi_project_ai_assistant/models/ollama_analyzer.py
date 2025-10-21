import os
import json
import yaml
import re
import requests
from typing import List, Dict, Any
from openai import OpenAI
from datetime import datetime

class OllamaAnalyzer:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.model = "codellama:latest"
        self.project_roots = []
        self.provider = "ollama"  # Default provider

    def set_provider(self, provider: str):
        """Set the AI provider (ollama, openai, openrouter)"""
        self.provider = provider
        print(f"✅ Provider set to: {provider}")

    def set_model(self, model_name: str):
        """Set the model to use for analysis"""
        self.model = model_name
        print(f"✅ Model set to: {model_name}")

    def analyze_with_prompt(self, prompt: str, model: str = None, provider: str = None) -> str:
        """Analyze prompt using selected provider and model"""
        print("hehehehehehehehheheh")
        if model is None:
            model = self.model
        if provider is None:
            provider = self.provider

        print(f"🤖 Using provider: {provider}, model: {model}")

        try:
            if provider == "ollama":
                return self._analyze_with_ollama(prompt, model)
            elif provider == "openai":
                return self._analyze_with_openai(prompt, model)
            elif provider == "openrouter":
                return self._analyze_with_openrouter(prompt, model)
            else:
                raise Exception(f"Unsupported provider: {provider}")

        except Exception as e:
            print(f"❌ Error in analyze_with_prompt: {e}")
            # Store error in database
            self._store_error_in_db(str(e), provider, model, prompt)
            raise Exception(f"Analysis failed: {str(e)}")

    def _analyze_with_ollama(self, prompt: str, model: str) -> str:
        """Analyze using local Ollama instance"""
        print("===========full prprprprpprprprpr")
        print(prompt)

        try:
            # Make the request to Ollama
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }

            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=100000)


            print("rrrrrrrrrrrrrrrrrrrrrrrrrrrr")
            print(response)
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '')
                print("✅ Response received from Ollama")
                return self.clean_yaml_response(raw_response)
            else:
                error_msg = f"Ollama API error: {response.status_code} - {response.text}"
                print(f"❌ {error_msg}")
                raise Exception(error_msg)

        except Exception as e:
            print(f"❌ Error calling Ollama: {e}")
            raise Exception(f"Ollama service unavailable: {str(e)}")

    def _analyze_with_openai(self, prompt: str, model: str) -> str:
        """Analyze using OpenAI API"""
        try:
            # Get API key from environment or use a default
            api_key = os.getenv('OPENAI_API_KEY', 'your-openai-api-key-here')

            client = OpenAI(
                base_url="https://api.openai.com/v1",
                api_key=api_key,
            )

            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                timeout=60
            )

            raw_response = completion.choices[0].message.content
            print("✅ Response received from OpenAI")
            return self.clean_yaml_response(raw_response)

        except Exception as e:
            print(f"❌ Error calling OpenAI: {e}")
            raise Exception(f"OpenAI API error: {str(e)}")

    def _analyze_with_openrouter(self, prompt: str, model: str) -> str:
            """Analyze using OpenRouter API with enhanced error handling"""
            try:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key="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",
                )

                extra_headers = {
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "Multi-Project AI Assistant"
                }

                # Map common model names to OpenRouter models
                model_mapping = {
                    "llama3.1:latest": "meta-llama/llama-3.1-8b-instruct:free",
                    "codellama:latest": "codellama/codellama-34b-instruct:free",
                    "qwen3-coder:480b-cloud": "qwen/qwen-3-coder-32b-instruct:free",
                    "gpt-oss-20b:free": "openai/gpt-oss-20b:free"
                }

                openrouter_model = model_mapping.get(model, "openai/gpt-oss-20b:free")
                print(f"🔀 Using OpenRouter model: {openrouter_model}")

                print("beoererererrerere=========oprnrnrnnrnrnr--riririiriririri")
                print(prompt)
                completion = client.chat.completions.create(
                    extra_headers=extra_headers,
                    model=openrouter_model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    timeout=60
                )

                raw_response = completion.choices[0].message.content
                print("✅ Response received from OpenRouter")
                return self.clean_yaml_response(raw_response)

            except Exception as e:
                error_message = f"OpenRouter API error: {str(e)}"
                print(f"❌ Error calling OpenRouter: {error_message}")

                # Store error in database
                self._store_error_in_db(error_message, "openrouter", model, prompt)

                # Return error in YAML format
                return self._format_error_yaml(error_message, "openrouter", model)

    def _store_error_in_db(self, error_message: str, provider: str, model: str, prompt: str):
        """Store error information in database"""
        try:
            from models.database import PostgresDB
            # You'll need to pass db_config to OllamaAnalyzer or access it differently
            db_config = {
                'host': 'localhost',
                'database': 'ai_assistant',
                'user': 'postgres',
                'password': 'postgres'
            }

            db = PostgresDB(db_config)

            error_data = {
                "error_message": error_message,
                "provider": provider,
                "model": model,
                "prompt_preview": prompt[:500] if prompt else "",  # Store first 500 chars
                "user_id": 1,  # You'll need to get this from context
                "session_id": "system",  # You'll need to get this from context
                "created_at": datetime.now()
            }

            # Store error in database
            query = """
            INSERT INTO error_logs
            (error_message, provider, model, prompt_preview, user_id, session_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            db.execute_query(query, (
                error_data["error_message"],
                error_data["provider"],
                error_data["model"],
                error_data["prompt_preview"],
                error_data["user_id"],
                error_data["session_id"],
                error_data["created_at"]
            ))

            print(f"📝 Error stored in database: {error_message[:100]}...")

        except Exception as e:
            print(f"❌ Failed to store error in database: {e}")

    def _format_error_yaml(self, error_message: str, provider: str, model: str) -> str:
        """Format error response as YAML"""
        error_data = {
            'error': {
                'message': error_message,
                'provider': provider,
                'model': model,
                'timestamp': datetime.now().isoformat(),
                'type': 'api_error'
            },
            'projects': [],
            'install_commands': [
                'echo "Error occurred during analysis. Please try again or use a different provider."'
            ],
            'packages': {
                'rails_gems': [],
                'react_dependencies': [],
                'react_devDependencies': []
            }
        }

        return yaml.dump(error_data, default_flow_style=False, indent=2)

    def _get_current_timestamp(self):
        """Get current timestamp for error logging"""
        from datetime import datetime
        return datetime.now().isoformat()

    def clean_yaml_response(self, yaml_response: str) -> str:
        """
        Remove Markdown fences and extra explanations from YAML response.
        """
        if not yaml_response:
            return ""

        yaml_response = str(yaml_response)

        if yaml_response.strip().startswith('projects:'):
            return yaml_response.strip()

        lines = yaml_response.splitlines()
        cleaned_lines = []

        yaml_started = False

        for line in lines:
            if line.strip().startswith('```'):
                continue

            if line.strip().startswith('projects:'):
                yaml_started = True

            if yaml_started:
                cleaned_lines.append(line)

        if not yaml_started or len(cleaned_lines) == 0:
            return self._convert_code_blocks_to_yaml(yaml_response)

        cleaned = "\n".join(cleaned_lines).strip()

        if not cleaned.startswith('projects:'):
            projects_index = cleaned.find('projects:')
            if projects_index != -1:
                cleaned = cleaned[projects_index:]
            else:
                return self._convert_code_blocks_to_yaml(yaml_response)

        return cleaned

    def _convert_code_blocks_to_yaml(self, response: str) -> str:
        """
        Convert code blocks in the response to proper YAML format.
        """
        lines = response.splitlines()
        yaml_lines = ["projects:"]
        if self.project_roots:
            yaml_lines.append(f"  - project_path: \"{self.project_roots[0]}\"")
        else:
            yaml_lines.append("  - project_path: \"/default/path\"")
        yaml_lines.append("    project_type: \"react\"")
        yaml_lines.append("    files:")

        current_file = None
        current_content = []

        for line in lines:
            if '//' in line and ('src/' in line or 'components/' in line):
                if current_file and current_content:
                    yaml_lines.append(f"      - path: \"{current_file}\"")
                    yaml_lines.append("        content: |")
                    for content_line in current_content:
                        yaml_lines.append(f"          {content_line}")
                    current_content = []

                if '//' in line:
                    file_part = line.split('//')[-1].strip()
                    if 'src/' in file_part:
                        current_file = file_part
                    else:
                        current_file = f"src/{file_part}"

            elif current_file and line.strip() and not line.strip().startswith('//') and not line.strip().startswith('```'):
                current_content.append(line)

        if current_file and current_content:
            yaml_lines.append(f"      - path: \"{current_file}\"")
            yaml_lines.append("        content: |")
            for content_line in current_content:
                yaml_lines.append(f"          {content_line}")

        yaml_lines.append("")
        yaml_lines.append("install_commands:")
        yaml_lines.append("  - echo \"No additional packages required\"")
        yaml_lines.append("")
        yaml_lines.append("packages:")
        yaml_lines.append("  rails_gems: []")
        yaml_lines.append("  react_dependencies: []")
        yaml_lines.append("  react_devDependencies: []")

        return "\n".join(yaml_lines)

    def _get_component_code(self, component_name: str, component_data: dict) -> str:
        """
        Returns the code for a specific component.
        """
        requirement_text = component_data.get("requirement", "No specific requirement provided")
        print(f"🔍 Getting code for component: {component_name}")

        # Priority 1: Use appCode if available
        if component_data.get('appCode'):
            print(f"✅ Found appCode for {component_name}")
            return component_data['appCode']

        allowed_extensions = [".tsx", ".ts", ".js"]  # preference order
        found_paths = []

        # Search project roots for exact matches
        if self.project_roots:
            for project_root in self.project_roots:
                for root, dirs, files in os.walk(project_root):
                    for ext in allowed_extensions:
                        target_file = f"{component_name}{ext}"
                        if target_file in files:
                            full_path = os.path.join(root, target_file)
                            if full_path not in found_paths:
                                found_paths.append(full_path)

        # If no file found
        if not found_paths:
            print(f"⚠️ No code found for {component_name}, adding requirement explanation")
            return (
                f"// Component: {component_name}\n"
                f"// Requirement: {requirement_text}\n"
                f"// ⚠️ Code not found - component needs to be created or modified based on the requirement above"
            )

        # If multiple files found, ignore and instruct to refer manually
        if len(found_paths) > 1:
            print(f"⚠️ Multiple files found for {component_name}, ignoring to avoid duplicates")
            paths_list = "\n".join(found_paths)
            return (
                f"// Component: {component_name}\n"
                f"// ⚠️ Multiple files found, cannot select automatically. Please refer to the following paths manually:\n{paths_list}\n"
                f"// Requirement: {requirement_text}"
            )

        # Single unique file found, read and return code
        try:
            with open(found_paths[0], 'r', encoding='utf-8') as f:
                code = f.read()
                print(f"✅ Found code for {component_name} at {found_paths[0]}")
                return code
        except Exception as e:
            print(f"❌ Error reading {found_paths[0]}: {e}")
            return (
                f"// Component: {component_name}\n"
                f"// ⚠️ Error reading file: {e}\n"
                f"// Requirement: {requirement_text}"
            )

    def build_existing_components_prompt(self, requirements_data):
        """Build prompt specifically for modifying existing components."""
        print("==== Building EXISTING COMPONENTS Prompt ====")

        requirements = requirements_data.get("requirements", [])
        reference_components = requirements_data.get("referenceComponents", {})
        feature_details = requirements_data.get("feature_details", {})

        prompt_parts = []

        # === 1. FEATURE OVERVIEW ===
        prompt_parts.append(f"# FEATURE REQUEST: {feature_details.get('name', 'New Feature')}")
        prompt_parts.append(f"## Description: {feature_details.get('description', '')}\n")

        # === 2. ALL REQUIREMENTS SUMMARY ===
        prompt_parts.append("## ALL REQUIREMENTS:")
        for i, req in enumerate(requirements, 1):
            prompt_parts.append(f"{i}. {req['requirement']}")
        prompt_parts.append("")

        # === 3. REQUIREMENT DETAILS WITH REAL CODE ===
        for i, req in enumerate(requirements, 1):
            component_name = req.get("component")
            existing_code = self._get_component_code(component_name, req)

            if existing_code:
                prompt_parts.append(f"## 📝 EXISTING CODE FOR {component_name}:\n```javascript\n{existing_code}\n```")

            ref_comp_name = req.get("referenceComponent")
            prompt_parts.append(f"## REQUIREMENT {i}: {component_name}")
            prompt_parts.append(f"**Task:** {req.get('requirement', '')}")
            prompt_parts.append(f"**Reference Component:** {ref_comp_name or 'None'}\n")

            # Display the found code
            if existing_code and len(existing_code.strip()) > 10:
                prompt_parts.append(f"### EXISTING COMPONENT: {component_name}")
                prompt_parts.append(existing_code.strip() + "\n")
            else:
                prompt_parts.append(f"### ❗ COMPONENT NOT FOUND: {component_name}")
                prompt_parts.append(f"Please create this component based on the requirements.\n")

        # === 4. YAML OUTPUT FORMAT - FIXED STRUCTURE ===
        prompt_parts.append("## CRITICAL OUTPUT INSTRUCTIONS:")
        prompt_parts.append("""
    YOU MUST RESPOND WITH ONLY VALID YAML IN THIS EXACT STRUCTURE AND ORDER:

    projects:
      - project_path: "/media/shivareddy/E/oct-2025/15_evg/oct/my-blue-app"
        project_type: "react"
        files:
          - path: "src/components/ContactForm.js"
            content: |
              import React, { useState, useEffect } from 'react';
              // ... complete file content with proper indentation

    install_commands:
      - "cd /media/shivareddy/E/oct-2025/15_evg/oct/my-blue-app && npm install select2 jquery"

    packages:
      rails_gems: []
      react_dependencies:
        - "select2"
        - "jquery"
      react_devDependencies: []

    IMPORTANT RULES:
    1. 'projects' MUST COME FIRST in the YAML
    2. 'install_commands' MUST COME SECOND
    3. 'packages' MUST COME LAST
    4. Use proper YAML indentation (2 spaces)
    5. File content must use '|' for multi-line strings
    6. Package names must be quoted strings
    7. Only include necessary file changes
    8. Do NOT include both install command and echo statement - choose one

    CORRECT ORDER:
    1. projects
    2. install_commands
    3. packages

    WRONG ORDER (will break):
    1. install_commands
    2. packages
    3. projects

    DO NOT INCLUDE:
    - ```yaml or markdown fences
    - Explanations
    - Comments outside YAML
    - Any text before 'projects:' or after the YAML

    YOUR OUTPUT MUST START WITH 'projects:' AND FOLLOW THE EXACT ORDER SHOWN ABOVE.
    """)

        return "\n".join(prompt_parts)

    def build_new_components_prompt(self, requirements_data):
        """Build prompt specifically for creating new components."""
        print("==== Building NEW COMPONENTS Prompt ====")

        requirements = requirements_data.get("requirements", [])
        reference_components = requirements_data.get("referenceComponents", {})
        feature_request = requirements_data.get("feature_request", "")

        prompt_parts = []

        # === 1. FEATURE OVERVIEW ===
        prompt_parts.append("# FEATURE IMPLEMENTATION REQUEST")
        prompt_parts.append(f"## Feature Description: {feature_request}\n")

        # === 2. SEPARATE NEW AND EXISTING COMPONENTS ===
        new_components = [req for req in requirements if req.get('isNewComponent', False)]
        existing_components = [req for req in requirements if not req.get('isNewComponent', False)]

        if new_components:
            prompt_parts.append("## 🆕 NEW COMPONENTS TO CREATE:")
            for i, req in enumerate(new_components, 1):
                prompt_parts.append(f"{i}. {req['component']} ({req.get('componentType', 'component')}) - {req.get('requirement', '')}")
            prompt_parts.append("")

        if existing_components:
            prompt_parts.append("## ✏️ EXISTING COMPONENTS TO MODIFY:")
            for i, req in enumerate(existing_components, 1):
                prompt_parts.append(f"{i}. {req['component']} - {req.get('requirement', '')}")
            prompt_parts.append("")

        # === 3. INCLUDE ALL REFERENCE COMPONENTS FIRST ===
        if reference_components:
            prompt_parts.append("## 📚 REFERENCE COMPONENTS (Use for styling and patterns):")
            for comp_name, comp_data in reference_components.items():
                prompt_parts.append(f"### {comp_name}:")
                prompt_parts.append(f"**Description:** {comp_data.get('description', 'No description')}")

                # Include reference component code if available
                ref_code = self._get_component_code(comp_name, comp_data)
                if ref_code and len(ref_code.strip()) > 10:  # Only include if substantial code
                    prompt_parts.append("**Code:**")
                    prompt_parts.append(ref_code.strip())
                prompt_parts.append("")
            prompt_parts.append("")

        # === 4. HANDLE NEW COMPONENTS WITH REFERENCE STYLING ===
        for i, req in enumerate(new_components, 1):
            component_name = req.get("component")
            ref_comp_name = req.get("referenceComponent")
            component_type = req.get("componentType", "component")
            requirement_text = req.get('requirement', '')

            prompt_parts.append(f"## 🆕 NEW COMPONENT {i}: {component_name}")
            prompt_parts.append(f"**Type:** {component_type}")
            prompt_parts.append(f"**Requirements:** {requirement_text}")
            prompt_parts.append(f"**Reference Component:** {ref_comp_name or 'None'}\n")

            # Include specific reference component if provided
            if ref_comp_name and ref_comp_name in reference_components:
                ref_comp_data = reference_components[ref_comp_name]
                ref_code = self._get_component_code(ref_comp_name, ref_comp_data)
                if ref_code and len(ref_code.strip()) > 10:
                    prompt_parts.append(f"### REFERENCE STYLING FROM: {ref_comp_name}")
                    prompt_parts.append("**Use this component's styling, layout, and patterns:**")
                    prompt_parts.append(ref_code.strip() + "\n")

            # New component creation instructions
            prompt_parts.append("**CREATION INSTRUCTIONS:**")
            prompt_parts.append(f"- Create a NEW {component_type.upper()} component named '{component_name}'")
            prompt_parts.append("- Follow React best practices and use Tailwind CSS")
            prompt_parts.append("- If reference component provided, use similar styling/layout patterns")

            # Location guidance
            if component_type.lower() == 'page':
                prompt_parts.append("- Location: src/pages/ or src/views/")
                prompt_parts.append("- Include proper routing if needed")
            elif component_type.lower() == 'layout':
                prompt_parts.append("- Location: src/layouts/ or src/components/layout/")
            else:
                prompt_parts.append("- Location: src/components/")

            prompt_parts.append("")

        # === 5. HANDLE EXISTING COMPONENTS ===
        for i, req in enumerate(existing_components, 1):
            component_name = req.get("component")
            ref_comp_name = req.get("referenceComponent")
            requirement_text = req.get('requirement', '')

            prompt_parts.append(f"## ✏️ EXISTING COMPONENT {i}: {component_name}")
            prompt_parts.append(f"**Task:** {requirement_text}")
            prompt_parts.append(f"**Reference Component:** {ref_comp_name or 'None'}\n")

            # Include main component code
            component_code = self._get_component_code(component_name, req)
            if component_code and len(component_code.strip()) > 10:
                prompt_parts.append(f"### EXISTING COMPONENT CODE: {component_name}")
                prompt_parts.append(component_code.strip() + "\n")
            else:
                prompt_parts.append(f"⚠️ Could not locate complete code for {component_name}\n")

            # Include reference component if provided
            if ref_comp_name and ref_comp_name in reference_components:
                ref_comp_data = reference_components[ref_comp_name]
                ref_code = self._get_component_code(ref_comp_name, ref_comp_data)
                if ref_code and len(ref_code.strip()) > 10:
                    prompt_parts.append(f"### REFERENCE COMPONENT: {ref_comp_name}")
                    prompt_parts.append(ref_code.strip() + "\n")

            # Modification instructions
            prompt_parts.append("**MODIFICATION INSTRUCTIONS:**")
            prompt_parts.append("- Modify the above component by making MINIMAL changes")
            prompt_parts.append("- Output the COMPLETE modified component code")
            prompt_parts.append("- Preserve all existing logic, structure, and styling")
            prompt_parts.append("")

        # === 6. ROUTING UPDATES FOR NEW PAGES ===
        new_pages = [req for req in new_components if req.get('componentType', '').lower() == 'page']
        if new_pages:
            prompt_parts.append("## 🛣️ ROUTING UPDATES NEEDED:")
            prompt_parts.append("The following new pages need to be added to the routing configuration:")
            for page in new_pages:
                prompt_parts.append(f"- {page['component']}: Add route in App.js/main routing file")
            prompt_parts.append("")

        # === 7. TECHNICAL SPECIFICATIONS ===
        prompt_parts.append("## TECHNICAL SPECIFICATIONS:")
        prompt_parts.append("- Use React with Tailwind CSS (same as existing components)")
        prompt_parts.append("- Maintain consistent styling with existing application")
        prompt_parts.append("- Follow React best practices")
        prompt_parts.append("- For new components: Create in appropriate directories")
        prompt_parts.append("- For existing components: Preserve all existing imports, hooks, and logic")
        prompt_parts.append("")

        # === 8. YAML OUTPUT FORMAT ===
        prompt_parts.append("## CRITICAL OUTPUT INSTRUCTIONS:")
        prompt_parts.append("""
YOU MUST RESPOND WITH ONLY VALID YAML IN THIS EXACT FORMAT — NO EXPLANATIONS, NO MARKDOWN, NO CODE BLOCKS.

START YOUR RESPONSE WITH:
projects:
  - project_path: "/media/shivareddy/E/oct-2025/15_evg/oct/my-blue-app"
    project_type: "react"
    files:

INCLUDE ALL COMPONENTS THAT NEED CHANGES:
- Modified existing components (App.js for routing updates)
- New components (Dashboard.js)
- Any other files that need updates

YAML STRUCTURE EXAMPLE:
projects:
  - project_path: "/media/shivareddy/E/oct-2025/15_evg/oct/my-blue-app"
    project_type: "react"
    files:
      - path: "src/App.js"
        content: |
          import React from 'react';
          import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
          // ... complete component code
      - path: "src/pages/Dashboard.js"
        content: |
          import React from 'react';
          // ... complete new component code

install_commands:
  - echo "No additional packages required"

packages:
  rails_gems: []
  react_dependencies: []
  react_devDependencies: []

DO NOT INCLUDE:
- ```yaml or markdown fences
- Explanations like "I'll implement..."
- Comments outside the YAML
- Any text before or after the YAML

YOUR OUTPUT MUST START WITH 'projects:' AND END WITH THE LAST FILE CONTENT.
""")

        return "\n".join(prompt_parts)

    def auto_generate_file_changes(self, user_query: str, project_roots: List[str], model: str = None, provider: str = None):
        """
        Main entry point that automatically detects whether to use
        existing components or new components method
        """
        print(f"🎯 Auto-generating file changes for: '{user_query}'")
        print(f"📁 Projects: {project_roots}")
        print(f"🤖 Using provider: {provider or self.provider}, model: {model or self.model}")

        self.project_roots = project_roots

        # Parse the requirements data
        try:
            requirements_data = json.loads(user_query)

            # Check if we have any new components
            requirements = requirements_data.get("requirements", [])
            has_new_components = any(req.get('isNewComponent', False) for req in requirements)

            # Choose the appropriate prompt builder
            if has_new_components:
                print("🔍 Detected NEW COMPONENTS requirement - using new components method")
                system_prompt = self.build_new_components_prompt(requirements_data)
            else:
                print("🔍 Detected EXISTING COMPONENTS modification - using existing components method")
                system_prompt = self.build_existing_components_prompt(requirements_data)

        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {e}, using fallback")
            system_prompt = user_query

        print("===== Sending prompt to AI provider ===========")
        print(f"Provider: {provider or self.provider}")
        print(f"Model: {model or self.model}")
        print("=============================================")
        print(user_query)

        try:
            # Use the dynamic provider selection
            raw_response = self.analyze_with_prompt(user_query, model, provider)

            # Attempt YAML cleaning, fallback to raw text if parsing fails
            try:
                cleaned_response = self.clean_yaml_response(raw_response)
                print("✅ Cleaned YAML response ready")
            except Exception as e:
                print(f"⚠️  YAML cleaning failed, using raw response: {e}")
                cleaned_response = raw_response

            return cleaned_response

        except Exception as e:
            error_msg = f"Error in auto_generate_file_changes: {e}"
            print(f"❌ {error_msg}")
            return error_msg

    # Legacy method for backward compatibility
    def analyze_and_generate_changes(self, prompt: str, project_context: str, project_roots: List[str], intent: Dict[str, bool]) -> str:
        """Legacy method for backward compatibility"""
        self.project_roots = project_roots
        return self.auto_generate_file_changes(prompt, project_roots)