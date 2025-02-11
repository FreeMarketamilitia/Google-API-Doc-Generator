from flask import Flask, render_template, request, send_file
import os
from googleapiclient.discovery import build
import logging
import time
import json
from fpdf import FPDF
from mistralai import Mistral

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Use the mistral-small-latest model
MISTRAL_MODEL = "mistral-small-latest"

class APIDocumentationPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Google API Documentation', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 6, title, 0, 1, 'L', True)
        self.ln(4)

    def chapter_body(self, body):
        self.set_font('Arial', '', 10)
        self.multi_cell(0, 5, body)
        self.ln()

    def code_section(self, code):
        self.set_font('Courier', '', 8)
        self.set_fill_color(245, 245, 245)
        self.multi_cell(0, 5, code, fill=True)
        self.ln(5)

def generate_with_mistral(prompt, api_key):
    """
    Generate content using the Mistral API (mistral-small-latest).
    This function adds a short sleep to meet rate-limit requirements and
    post-processes the response to remove any extraneous introductory text.
    """
    if not api_key:
        return None

    try:
        time.sleep(1.5)  # Respect rate limiting
        client = Mistral(api_key=api_key)
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            # Optionally you can add a "stop" parameter if needed:
            # stop=["\n\n"]
        )
        content = response.choices[0].message.content.strip()
        # Remove unwanted lines (e.g. greetings or extraneous commentary)
        lines = content.splitlines()
        if lines and lines[0].strip().lower().startswith("okay"):
            content = "\n".join(lines[1:]).strip()
        return content
    except Exception as e:
        logging.error(f"Mistral API error: {str(e)}; API Key: {api_key}")
        return None

def get_api_list():
    """
    Fetch all available APIs using Google Discovery API with pagination.
    """
    try:
        service = build('discovery', 'v1', developerKey=None)
        all_apis = []
        page_token = None

        while True:
            request_obj = service.apis().list(preferred=True, pageToken=page_token) if page_token else service.apis().list(preferred=True)
            apis_response = request_obj.execute()

            if 'items' in apis_response:
                all_apis.extend(apis_response['items'])
            
            page_token = apis_response.get('nextPageToken')
            if not page_token:
                break

        if all_apis:
            all_apis.sort(key=lambda x: x.get('title', '').lower())
            return all_apis
        
        logging.warning("No APIs found in response")
        return None
    except Exception as e:
        logging.error(f"Error fetching API list: {str(e)}")
        return None

def generate_pdf_documentation(api_name, api_version, api_key):
    """
    Generate PDF documentation for the specified API.
    Uses Mistral to generate technical descriptions and code examples.
    """
    pdf = APIDocumentationPDF()
    pdf.add_page()

    # Fetch API details
    service = build('discovery', 'v1')
    api_list = get_api_list()
    selected_api = next((api for api in api_list if api['name'] == api_name), None)
    
    if not selected_api:
        raise Exception(f"API {api_name} not found")
    
    correct_version = selected_api['version']
    
    api_response = service.apis().getRest(
        api=api_name,
        version=correct_version,
        fields='',
        key=None
    ).execute()

    # Overview
    pdf.chapter_title(f"{api_name} API Documentation")
    pdf.chapter_body(f"Version: {api_version}\n")
    if 'description' in api_response:
        pdf.chapter_body(api_response['description'])

    def document_resource(resource_data, resource_name=""):
        for method_name, method in resource_data.get('methods', {}).items():
            pdf.add_page()
            endpoint_path = f"{resource_name}.{method_name}" if resource_name else method_name
            pdf.chapter_title(f"Endpoint: {endpoint_path}")

            # Basic endpoint details
            pdf.chapter_body(f"HTTP Method: {method.get('httpMethod', 'N/A')}")
            pdf.chapter_body(f"Path: {method.get('path', 'N/A')}")
            if method.get('description'):
                pdf.chapter_body(f"Description: {method['description']}")

            # Generate technical documentation via Mistral
            ai_prompt = f"""Generate a concise technical description for the following API endpoint:
Endpoint: {method['httpMethod']} {method['id']}
Requirements:
1. Provide common use cases.
2. Include an example request with placeholder values.
3. List common parameters with brief explanations.
Return only the requested content without any greetings or extra commentary."""
            ai_content = generate_with_mistral(ai_prompt, api_key)
            if ai_content:
                pdf.chapter_title("AI-Generated Documentation")
                pdf.chapter_body(ai_content)

            # Generate code example via Mistral
            code_prompt = f"""Generate a practical Python code example for the following API endpoint:
Service: {method['id']}
Requirements:
- Use realistic parameter names and values.
- Include proper error handling.
- Return only the Python code and inline explanation as comments (no extra text).
"""
            code_example = generate_with_mistral(code_prompt, api_key)
            if code_example:
                pdf.chapter_title("Example Code")
                pdf.code_section(code_example)

        # Process nested resources recursively
        for nested_name, nested_resource in resource_data.get('resources', {}).items():
            new_resource_name = f"{resource_name}.{nested_name}" if resource_name else nested_name
            document_resource(nested_resource, new_resource_name)

    for resource_name, resource in api_response.get('resources', {}).items():
        document_resource(resource, resource_name)

    output_dir = os.path.join(os.getcwd(), 'generated_docs')
    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = os.path.join(output_dir, f"{api_name}_documentation.pdf")
    pdf.output(pdf_filename)
    return pdf_filename

def generate_colab_notebook(api_name, api_version, notebook_filename, api_key):
    """
    Generate an interactive Colab notebook with dynamic parameter handling, 
    AI-generated explanations, and enhanced interactivity.
    """
    service = build('discovery', 'v1')
    api_response = service.apis().getRest(api=api_name, version=api_version).execute()

    def extract_method_details(response):
        methods = []
        def traverse(resources, prefix=""):
            for resource_name, resource in resources.items():
                if 'methods' in resource:
                    for method_name, method in resource['methods'].items():
                        full_name = f"{prefix}{resource_name}.{method_name}"
                        methods.append({
                            'name': full_name,
                            'httpMethod': method.get('httpMethod', 'GET'),
                            'path': method.get('path', ''),
                            'parameters': method.get('parameters', {}),
                            'description': method.get('description', '')
                        })
                if 'resources' in resource:
                    new_prefix = f"{prefix}{resource_name}."
                    traverse(resource['resources'], new_prefix)
        if 'resources' in response:
            traverse(response['resources'])
        return methods

    methods_list = extract_method_details(api_response)

    # Generate AI-powered documentation for the API
    ai_intro_prompt = f"""Generate a comprehensive introduction for the {api_name} API covering:
    - Main capabilities and typical use cases
    - Key resources and operations
    - Security requirements
    - Common error patterns
    Keep it professional but approachable for developers."""
    ai_intro = generate_with_mistral(ai_intro_prompt, api_key) or ""

    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"# 🚀 {api_name} API Interactive Notebook ({api_version})\n",
                    "\n## AI-Generated Overview\n",
                    ai_intro
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "# Setup Environment\n",
                    "!pip install -q google-api-python-client ipywidgets pandas\n",
                    "from googleapiclient.discovery import build\n",
                    "import ipywidgets as widgets\n",
                    "from IPython.display import display, Markdown\n",
                    "import json\n",
                    "import pandas as pd\n",
                    "\n",
                    "# Initialize API Service\n",
                    f"service = build('{api_name}', '{api_version}')\n",
                    "print('✅ API service initialized')"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "# Interactive Method Explorer\n",
                    "method_selector = widgets.Dropdown(\n",
                    "    options=[(m['name'], m) for m in methods_list],\n",
                    "    description='Select Method:',\n",
                    "    layout={'width': '70%'}\n",
                    ")\n",
                    "\n",
                    "param_inputs = widgets.VBox([])\n",
                    "response_output = widgets.Output()\n",
                    "\n",
                    "def generate_param_fields(change):\n",
                    "    global param_inputs\n",
                    "    children = []\n",
                    "    method = change['new']\n",
                    "    \n",
                    "    # Generate AI documentation for the method\n",
                    "    ai_prompt = f\"\"\"Generate detailed documentation for API method {method['name']}:\n",
                    "    - Typical usage scenarios\n",
                    "    - Required parameters and their formats\n",
                    "    - Example values for parameters\n",
                    "    - Common error conditions\"\"\"\n",
                    "    ai_docs = generate_with_mistral(ai_prompt, api_key) or \"No AI documentation available\"\n",
                    "    \n",
                    "    children.append(widgets.HTML(\n",
                    "        value=f\"<h3>{method['name']}</h3>\"\n",
                    "              f\"<p><b>HTTP Method:</b> {method['httpMethod']}</p>\"\n",
                    "              f\"<p><b>Path:</b> {method['path']}</p>\"\n",
                    "              f\"<details><summary>AI Documentation</summary>{ai_docs}</details>\"\n",
                    "    ))\n",
                    "    \n",
                    "    # Create dynamic parameter inputs\n",
                    "    for param, details in method['parameters'].items():\n",
                    "        input_field = widgets.Text(\n",
                    "            description=param,\n",
                    "            placeholder=details.get('description', ''),\n",
                    "            style={'description_width': '150px'}\n",
                    "        )\n",
                    "        if details.get('required', False):\n",
                    "            input_field.style = {'description_width': '150px', 'font_weight': 'bold'}\n",
                    "        children.append(input_field)\n",
                    "    \n",
                    "    param_inputs.children = children\n",
                    "\n",
                    "method_selector.observe(generate_param_fields, names='value')\n",
                    "\n",
                    "# Initial display\n",
                    "display(widgets.VBox([method_selector, param_inputs]))"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "# Interactive API Call Section\n",
                    "execute_button = widgets.Button(description=\"Execute API Call\", button_style='success')\n",
                    "code_output = widgets.Output()\n",
                    "\n",
                    "def on_execute(b):\n",
                    "    with code_output:\n",
                    "        code_output.clear_output()\n",
                    "        method = method_selector.value\n",
                    "        params = {}\n",
                    "        \n",
                    "        # Collect parameters\n",
                    "        for child in param_inputs.children:\n",
                    "            if isinstance(child, widgets.Text):\n",
                    "                if child.value:\n",
                    "                    params[child.description] = child.value\n",
                    "        \n",
                    "        try:\n",
                    "            # Build the method call dynamically\n",
                    "            parts = method['name'].split('.')\n",
                    "            resource = service\n",
                    "            for part in parts[:-1]:\n",
                    "                resource = getattr(resource, part)()\n",
                    "            method_call = getattr(resource, parts[-1])(**params)\n",
                    "            \n",
                    "            # Execute and display results\n",
                    "            response = method_call.execute()\n",
                    "            display(Markdown(f\"### Successful Response ({method['httpMethod']})\"))\n",
                    "            if isinstance(response, dict):\n",
                    "                display(pd.DataFrame.from_dict(response, orient='index'))\n",
                    "            else:\n",
                    "                print(json.dumps(response, indent=2))\n",
                    "        except Exception as e:\n",
                    "            display(Markdown(\"### ❌ Error Details\"))\n",
                    "            print(f\"Error Type: {type(e).__name__}\")\n",
                    "            print(f\"Details: {str(e)}\")\n",
                    "            display(Markdown(\"**Troubleshooting Tips:**\"))\n",
                    "            print(\"- Check required parameters\\n- Verify parameter formats\\n- Check API quotas\")\n",
                    "\n",
                    "execute_button.on_click(on_execute)\n",
                    "display(execute_button, code_output)"
                ]
            },
            {
                "cell_type": "code",
                "metadata": {},
                "source": [
                    "# AI-Powered Quiz Section\n",
                    "quiz_questions = [\n",
                    "    {\n",
                    "        \"question\": \"Which HTTP method is typically used for creating resources?\",\n",
                    "        \"options\": ['GET', 'POST', 'PUT', 'DELETE'],\n",
                    "        \"answer\": 'POST'\n",
                    "    },\n",
                    "    {\n",
                    "        \"question\": \"What does a 403 status code indicate?\",\n",
                    "        \"options\": ['Not Found', 'Forbidden', 'Bad Request', 'Server Error'],\n",
                    "        \"answer\": 'Forbidden'\n",
                    "    }\n",
                    "]\n",
                    "\n",
                    "# Generate API-specific questions using Mistral\n",
                    "quiz_prompt = f\"\"\"Generate 2 multiple choice questions about working with the {api_name} API\n",
                    "Focus on:\n",
                    "- Common error scenarios\n",
                    "- Best practices\n",
                    "- Security considerations\n",
                    "Return as JSON array with question, options, and answer\"\"\"\n",
                    "ai_quiz = generate_with_mistral(quiz_prompt, api_key)\n",
                    "try:\n",
                    "    if ai_quiz:\n",
                    "        quiz_questions += json.loads(ai_quiz)\n",
                    "except json.JSONDecodeError:\n",
                    "    pass\n",
                    "\n",
                    "# Quiz Widgets\n",
                    "quiz_container = widgets.Accordion([widgets.VBox()] * len(quiz_questions), \n",
                    "                                  titles=[q['question'] for q in quiz_questions])\n",
                    "\n",
                    "for i, question in enumerate(quiz_questions):\n",
                    "    options = widgets.RadioButtons(\n",
                    "        options=question['options'],\n",
                    "        description='Answer:',\n",
                    "        disabled=False\n",
                    "    )\n",
                    "    result = widgets.Output()\n",
                    "    \n",
                    "    def check_answer(change, q=question, r=result):\n",
                    "        with r:\n",
                    "            r.clear_output()\n",
                    "            if change['new'] == q['answer']:\n",
                    "                print(\"✅ Correct!\")\n",
                    "            else:\n",
                    "                print(f\"❌ Incorrect. Correct answer: {q['answer']}\")\n",
                    "    \n",
                    "    options.observe(check_answer, names='value')\n",
                    "    quiz_container.children[i].children = [options, result]\n",
                    "\n",
                    "display(widgets.HTML(\"<h2>📚 API Knowledge Check</h2>\"))\n",
                    "display(quiz_container)"
                ]
            }
        ],
        "metadata": {
            "colab": {
                "name": f"{api_name} Interactive Notebook",
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

    # Save the notebook
    with open(notebook_filename, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=2, ensure_ascii=False)
    
    return notebook_filename


@app.route('/', methods=['GET', 'POST'])
def index():
    message = None
    error = False
    apis = []
    generated_files = {}

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
                output_dir = os.path.join(os.getcwd(), 'generated_docs')
                os.makedirs(output_dir, exist_ok=True)

                notebook_filename = os.path.join(output_dir, f"{api_name}_colab_notebook.ipynb")
                pdf_filename = generate_pdf_documentation(api_name, api_version, api_key)
                generate_colab_notebook(api_name, api_version, notebook_filename, api_key)

                generated_files = {'notebook': notebook_filename, 'pdf': pdf_filename}
                message = "Documentation generated successfully in both formats!"
            except Exception as e:
                message = f"Error: {str(e)}"
                error = True
                logging.error(f"Documentation generation error: {str(e)}")
        else:
            message = "Please select an API"
            error = True

    return render_template('index.html', message=message, error=error, apis=apis, generated_files=generated_files)

@app.route('/download/<doc_type>/<api_name>')
def download_doc(doc_type, api_name):
    try:
        output_dir = os.path.join(os.getcwd(), 'generated_docs')
        if doc_type == 'pdf':
            file_path = os.path.join(output_dir, f"{api_name}_documentation.pdf")
            mimetype = 'application/pdf'
            download_name = f"{api_name}_documentation.pdf"
        else:
            file_path = os.path.join(output_dir, f"{api_name}_colab_notebook.ipynb")
            mimetype = 'application/x-ipynb+json'
            download_name = f"{api_name}_colab_notebook.ipynb"

        return send_file(file_path, mimetype=mimetype, as_attachment=True, download_name=download_name)
    except Exception as e:
        logging.error(f"Download error: {str(e)}")
        return "Error downloading file", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
