#!/usr/bin/env python3

import os
import argparse
from config import Config
from services.ai_assistant import MultiProjectAIAssistant
from services.web_ui import MultiProjectAIChatbotWebUI

def main():
    parser = argparse.ArgumentParser(description='Multi-Project AI Assistant')
    parser.add_argument('project_paths', nargs='*', help='Paths to project directories (React and/or Rails) - Optional for web interface')
    parser.add_argument('--redis-host', default=Config.REDIS_HOST, help='Redis host')
    parser.add_argument('--redis-port', default=Config.REDIS_PORT, type=int, help='Redis port')
    parser.add_argument('--ollama-url', default=Config.OLLAMA_BASE_URL, help='Ollama server URL')
    parser.add_argument('--web', action='store_true', default=True, help='Use web interface (default)')
    parser.add_argument('--cli', action='store_true', help='Use command line interface')
    parser.add_argument('--host', default=Config.HOST, help='Web server host')
    parser.add_argument('--port', default=Config.PORT, type=int, help='Web server port')

    # PostgreSQL configuration
    parser.add_argument('--db-host', default=Config.DB_HOST, help='PostgreSQL host')
    parser.add_argument('--db-port', default=Config.DB_PORT, type=int, help='PostgreSQL port')
    parser.add_argument('--db-name', default=Config.DB_NAME, help='PostgreSQL database name')
    parser.add_argument('--db-user', default=Config.DB_USER, help='PostgreSQL username')
    parser.add_argument('--db-password', default=Config.DB_PASSWORD, help='PostgreSQL password')

    # User authentication and project management
    parser.add_argument('--base-project-dir', default=Config.BASE_PROJECT_DIR, help='Base directory for user projects')
    parser.add_argument('--jwt-secret', default=Config.JWT_SECRET_KEY, help='JWT secret key')

    args = parser.parse_args()

    # Configuration
    db_config = {
        'host': args.db_host,
        'port': args.db_port,
        'dbname': args.db_name,
        'user': args.db_user,
        'password': args.db_password
    }

    redis_config = {
        'host': args.redis_host,
        'port': args.redis_port,
        'db': Config.REDIS_DB
    }

    # For CLI mode, require project paths
    if args.cli:
        if not args.project_paths:
            print("❌ Error: Project paths are required for CLI mode!")
            parser.print_help()
            return

        # Validate project paths for CLI
        for project_path in args.project_paths:
            if not os.path.exists(project_path):
                print(f"❌ Error: Project path '{project_path}' does not exist!")
                return

        # CLI interface
        assistant = MultiProjectAIAssistant(args.project_paths, redis_config, db_config)
        assistant.ollama.base_url = args.ollama_url
        assistant.initialize_projects()

        # Show project info
        project_info = assistant.get_project_info()
        if project_info:
            print(f"\n📁 Projects ({project_info['total_projects']}):")
            for project in project_info['projects']:
                print(f"  - [{project['type'].upper()}] {project['root']} ({project['file_count']} files)")
            print(f"🔑 Project ID: {project_info['project_id']}")

        print("\n" + "="*60)
        print("🤖 Multi-Project AI Assistant Ready!")
        print("🗄️  PostgreSQL database active - storing all conversations")
        print("🎯 Using INTENT-AWARE AUTO-GENERATE mode with dynamic file finding across projects")
        print("🤖 Available models:", assistant.get_available_models())
        print("="*60)

        # CLI interaction loop
        while True:
            try:
                user_input = input("\n💬 Enter your query: ").strip()

                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break

                if user_input:
                    # Process query using auto-generate mode
                    response = assistant.process_query(user_input, "cli_session", use_auto_generate=False)
                    print("\n" + "="*60)
                    print("📋 IMPLEMENTATION DETAILS:")
                    print("="*60)
                    print(response)

                    # Ask user if they want to apply changes
                    print("\n" + "="*60)
                    print("🚀 ACTION REQUIRED:")
                    print("="*60)
                    print("Do you want to apply these changes to your projects?")
                    print("1. Apply - Write files and install packages across all projects")
                    print("2. Cancel - Discard changes")

                    while True:
                        action = input("\nChoose action (1 for Apply, 2 for Cancel): ").strip()

                        if action == '1':
                            print("\n🔄 Applying changes across projects...")
                            results = assistant.apply_changes(response)

                            # Store application results in PostgreSQL
                            recent_conversations = assistant.db.get_conversation_history("cli_session", 1)
                            if recent_conversations:
                                latest_conv = recent_conversations[0]
                                assistant.db.update_application_results(latest_conv['id'], results)

                            print("\n" + "="*60)
                            print("📊 APPLICATION RESULTS:")
                            print("="*60)

                            if results['files_created']:
                                print("\n✅ FILES CREATED:")
                                for file in results['files_created']:
                                    print(f"  - {file}")

                            if results['files_updated']:
                                print("\n✏️  FILES UPDATED:")
                                for file in results['files_updated']:
                                    print(f"  - {file}")

                            if results['files_failed']:
                                print("\n❌ FAILED OPERATIONS:")
                                for error in results['files_failed']:
                                    print(f"  - {error}")

                            if results['install_output']:
                                print("\n📦 PACKAGE INSTALLATION:")
                                for output in results['install_output']:
                                    print(f"  - {output}")

                            if results['packages_installed']:
                                print("\n🎉 All changes applied successfully!")
                            else:
                                print("\n⚠️  Changes applied with some warnings.")

                            break

                        elif action == '2':
                            print("\n❌ Changes cancelled.")
                            break
                        else:
                            print("❌ Invalid choice. Please enter 1 for Apply or 2 for Cancel.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    else:
        # Web interface - project paths are optional as they'll be loaded per user
        # For backward compatibility, if project paths are provided, use them
        # Otherwise, the web UI will handle user-specific project loading

        chatbot = MultiProjectAIChatbotWebUI(
            args.project_paths,  # Can be empty for user-specific projects
            redis_config,
            db_config,
            args.ollama_url,
            args.host,
            args.port
        )
        chatbot.run()

if __name__ == "__main__":
    main()