from flask import Flask, render_template_string, request, redirect, url_for
import google.auth
from googleapiclient.discovery import build
import google.generativeai as genai
import os
from rich.console import Console
from rich.table import Table
from fpdf import FPDF
import json

app = Flask(__name__)
console = Console()

# Set up the API keys for Google services
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyCIpaomykk6kw0EXh2xcZ5Abbz-cb4y9KE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # This needs to be set separately

# Existing configuration and functions...
GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

def generate_with_gemini(prompt, api_key):
    """Generate content using Gemini API."""
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-pro')
    try:
        response = model.generate_content(
            prompt,
            safety_settings=GEMINI_SAFETY_SETTINGS,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                top_p=0.95,
                top_k=40,
                max_output_tokens=512
            )
        )
        return response.text
    except Exception as e:
        return None

def get_api_list():
    """Fetch available APIs using Google Discovery API."""
    try:
        service = build('discovery', 'v1')
        apis_response = service.apis().list(preferred=True).execute()
        if 'items' in apis_response:
            return apis_response['items']
        print("No APIs found in response:", apis_response)
        return None
    except Exception as e:
        print(f"Error fetching API list: {str(e)}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    message = None
    error = False
    apis = []

    if request.method == 'POST':
        api_key = request.form.get('api_key')
        api_name = request.form.get('api_name')
        api_version = request.form.get('api_version', 'v1')

        apis = get_api_list()
        if not apis:
            message = "Failed to fetch API list"
            error = True
        elif api_name:
            try:
                notebook_filename = f"{api_name}_colab_notebook.ipynb"
                generate_colab_notebook(api_name, api_version, notebook_filename, api_key)
                message = "Documentation generated successfully! Check the generated files."
            except Exception as e:
                message = f"Error: {str(e)}"
                error = True
        else:
            message = "Please select an API"
            error = True

    return render_template_string(HTML_TEMPLATE, message=message, error=error, apis=apis)

def generate_colab_notebook(api_name, api_version, filename, google_api_key, gemini_api_key=None):
    """Generate a Colab notebook with AI-powered content based on selected API."""

    # Fetch API details using Discovery API
    service = build('discovery', 'v1')  # No API key needed for discovery API
    api_response = service.apis().getRest(api=api_name, version=api_version).execute()

    # Notebook structure
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"# 🚀 {api_name} API Interactive Notebook ({api_version})\n",
                    "<div style='border-left: 4px solid #4285f4; padding-left: 1em; margin: 2em 0;'>\n",
                    "  <h3 style='color: #1a73e8;'>AI-Powered API Exploration</h3>\n",
                    "  <p>This notebook combines official API documentation with AI-generated explanations and examples powered by Google Gemini.</p>\n",
                    "</div>"
                ]
            },
            # Setup Section with Gemini
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 🛠️ Environment Setup",
                    "### Install required packages:"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "!pip install -q google-auth google-auth-oauthlib google-auth-httplib2 \\\n",
                    "  google-api-python-client google-generativeai\n",
                    "print('📦 Packages installed successfully!')"
                ]
            },
            # Authentication Section
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 🔐 Authentication Flow",
                    "<div class='alert'>\n",
                    "  <div class='alert-icon'>ℹ️</div>\n",
                    "  <div class='alert-content'>\n",
                    "    Complete the authentication flow when prompted to enable API access\n",
                    "  </div>\n",
                    "</div>"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "from google.colab import auth\n",
                    "from googleapiclient.discovery import build\n",
                    "import google.auth\n",
                    "import google.generativeai as genai\n",
                    "from pprint import pprint\n",
                    "\n",
                    "# Authenticate user\n",
                    "auth.authenticate_user()\n",
                    "credentials, _ = google.auth.default()\n",
                    f"service = build('{api_name}', '{api_version}', developerKey=api_key)\n",
                    "\n",
                    "print('🔓 Authentication successful!')"
                ]
            }
        ],
        "metadata": {
            "colab": {
                "name": f"{api_name} AI-Assisted Demo",
                "provenance": [],
                "toc_visible": True
            },
            "kernelspec": {
                "display_name": "Python 3",
                "name": "python3"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }

    # AI-powered documentation for each endpoint
    for endpoint in api_response.get('resources', {}).get('methods', {}).values():
        ai_description = None
        ai_example = None

        ai_prompt = f"""
        For the {api_name} API endpoint: {endpoint['httpMethod']} {endpoint['id']}
        Generate:
        1. A friendly technical description with common use cases.
        2. Example request with placeholder values.
        3. Common parameters and their purposes.
        """
        ai_description = generate_with_gemini(ai_prompt, api_key)

        example_prompt = f"""
        Create a practical Python code example for this API endpoint:
        Service: service.{endpoint['id']}()
        Include realistic parameters and error handling.
        """
        ai_example = generate_with_gemini(example_prompt, api_key)

        # Add endpoint to notebook
        endpoint_card = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"### 🔍 Endpoint: {endpoint['id']}",
                    f"**{endpoint['httpMethod']} {endpoint['path']}**\n",
                    f"**Original Description:** {endpoint.get('description', 'No description available.')}\n",
                    "<details>",
                    "<summary>🤖 AI-Powered Documentation</summary>",
                    ai_description or "*AI explanation unavailable*",
                    "</details>"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "# Basic Request\n",
                    f"request = service.{endpoint['id']}()\n",
                    "\n# AI-Generated Example" if ai_example else "",
                    ai_example or "# Enable Gemini API key for AI examples",
                    "\n\n# Execute request\n",
                    "try:\n",
                    "    response = request.execute()\n",
                    "    pprint(response)\n",
                    "except Exception as e:\n",
                    "    print(f'❌ Error: {str(e)}')"
                ]
            }
        ]
        notebook["cells"].extend(endpoint_card)

    # Save Colab Notebook
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=4)
    console.print(f"\n✨ AI-enhanced notebook saved as {filename}", style="bold green")

    return notebook

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Google API Documentation Generator</title>
    <script>
        function updateApiList() {
            document.getElementById('apiForm').submit();
        }
    </script>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .form-group {
            margin-bottom: 15px;
        }
        input[type="text"], select {
            width: 100%;
            padding: 8px;
            margin-top: 5px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        button {
            background-color: #4285f4;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        button:hover {
            background-color: #357abd;
        }
        .message {
            margin-top: 15px;
            padding: 10px;
            border-radius: 4px;
        }
        .success { background-color: #d4edda; color: #155724; }
        .error { background-color: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Google API Documentation Generator</h1>
        <form id="apiForm" method="POST">
            <div class="form-group">
                <label for="api_key">Google API Key:</label>
                <input type="text" id="api_key" name="api_key" required 
                       placeholder="Enter your Google API key"
                       value="{{ request.form.get('api_key', '') }}"
                       onchange="updateApiList()">
            </div>
            {% if apis %}
            <div class="form-group">
                <label for="api_name">Select API:</label>
                <select id="api_name" name="api_name" required>
                    <option value="">Choose an API...</option>
                    {% for api in apis %}
                    <option value="{{ api.name }}">{{ api.title }}</option>
                    {% endfor %}
                </select>
            </div>
            <button type="submit">Generate Documentation</button>
            {% endif %}
        </form>
        {% if message %}
        <div class="message {% if error %}error{% else %}success{% endif %}">
            {{ message }}
        </div>
        {% endif %}
    </div>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)