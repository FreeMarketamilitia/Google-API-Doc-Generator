from flask import Flask, render_template, request, redirect, url_for, send_file
import google.auth
from googleapiclient.discovery import build
import google.generativeai as genai
import os
from rich.console import Console
from rich.table import Table
from fpdf import FPDF
import json
import tempfile
import logging

app = Flask(__name__)
console = Console()

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Set up the API keys for Google services
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyCIpaomykk6kw0EXh2xcZ5Abbz-cb4y9KE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini safety settings
GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

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
        logging.error(f"Gemini API error: {str(e)}")
        return None

def get_api_list():
    """Fetch all available APIs using Google Discovery API with pagination."""
    try:
        service = build('discovery', 'v1')
        all_apis = []
        page_token = None
        
        while True:
            # Get current page of results
            request = service.apis().list(preferred=True, fields='items,nextPageToken')
            if page_token:
                request = service.apis().list(preferred=True, pageToken=page_token, fields='items,nextPageToken')
            apis_response = request.execute()
            
            # Add items from current page
            if 'items' in apis_response:
                all_apis.extend(apis_response['items'])
            
            # Check if there are more pages
            page_token = apis_response.get('nextPageToken')
            if not page_token:
                break
        
        # Sort APIs by name
        if all_apis:
            all_apis.sort(key=lambda x: x.get('title', '').lower())
            return all_apis
            
        logging.warning("No APIs found in response")
        return None
    except Exception as e:
        logging.error(f"Error fetching API list: {str(e)}")
        return None

def generate_pdf_documentation(api_name, api_version, api_key):
    """Generate PDF documentation for the specified API."""
    pdf = APIDocumentationPDF()
    pdf.add_page()

    # Fetch API details
    service = build('discovery', 'v1')
    
    # First get the API info to get the correct version
    api_list = get_api_list()
    selected_api = next((api for api in api_list if api['name'] == api_name), None)
    
    if not selected_api:
        raise Exception(f"API {api_name} not found")
        
    correct_version = selected_api['version']
    
    # Get complete API description with all resources
    api_response = service.apis().getRest(
        api=api_name,
        version=correct_version,
        fields='*'
    ).execute()

    # API Overview
    pdf.chapter_title(f"{api_name} API Documentation")
    pdf.chapter_body(f"Version: {api_version}\n")
    if 'description' in api_response:
        pdf.chapter_body(api_response['description'])

    def document_resource(resource_data, resource_name=""):
        # Document methods in current resource
        for method_name, method in resource_data.get('methods', {}).items():
            pdf.add_page()
            endpoint_path = f"{resource_name}.{method_name}" if resource_name else method_name
            pdf.chapter_title(f"Endpoint: {endpoint_path}")

            # Basic endpoint info
            pdf.chapter_body(f"HTTP Method: {method.get('httpMethod', 'N/A')}")
            pdf.chapter_body(f"Path: {method.get('path', 'N/A')}")
            if method.get('description'):
                pdf.chapter_body(f"Description: {method['description']}")

            # AI documentation for this endpoint
            ai_prompt = f"""
            For the {api_name} API endpoint: {method['httpMethod']} {method['id']}
            Generate:
            1. A friendly technical description with common use cases.
            2. Example request with placeholder values.
            3. Common parameters and their purposes.
            """
            ai_content = generate_with_gemini(ai_prompt, api_key)
            if ai_content:
                pdf.chapter_title("AI-Generated Documentation")
                pdf.chapter_body(ai_content)

            # Example code
            example_prompt = f"""
            Create a practical Python code example for this API endpoint:
            Service: {method['id']}
            Include realistic parameters and error handling.
            """
            code_example = generate_with_gemini(example_prompt, api_key)
            if code_example:
                pdf.chapter_title("Example Code")
                pdf.code_section(code_example)

        # Recursively process nested resources
        for nested_name, nested_resource in resource_data.get('resources', {}).items():
            new_resource_name = f"{resource_name}.{nested_name}" if resource_name else nested_name
            document_resource(nested_resource, new_resource_name)

    # Start documenting from root resources
    for resource_name, resource in api_response.get('resources', {}).items():
        document_resource(resource, resource_name)

    # Create output directory if it doesn't exist
    output_dir = os.path.join(os.getcwd(), 'generated_docs')
    os.makedirs(output_dir, exist_ok=True)

    # Save PDF file
    pdf_filename = os.path.join(output_dir, f"{api_name}_documentation.pdf")
    pdf.output(pdf_filename)
    return pdf_filename

def generate_colab_notebook(api_name, api_version, notebook_filename, api_key):
    #Implementation for generating colab notebook.  This function was not provided in the original code, but is referenced.  A placeholder implementation is provided below, but a full implementation would be needed for a production-ready application
    with open(notebook_filename, 'w') as f:
        json.dump({"cells":[{"cell_type":"markdown", "metadata":{},"source":["# Colab Notebook for "+api_name]}]}, f)
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
                # Create output directory
                output_dir = os.path.join(os.getcwd(), 'generated_docs')
                os.makedirs(output_dir, exist_ok=True)

                # Generate both formats
                notebook_filename = os.path.join(output_dir, f"{api_name}_colab_notebook.ipynb")
                pdf_filename = generate_pdf_documentation(api_name, api_version, api_key)
                generate_colab_notebook(api_name, api_version, notebook_filename, api_key)

                generated_files = {
                    'notebook': notebook_filename,
                    'pdf': pdf_filename
                }
                message = "Documentation generated successfully in both formats!"
            except Exception as e:
                message = f"Error: {str(e)}"
                error = True
                logging.error(f"Documentation generation error: {str(e)}")
        else:
            message = "Please select an API"
            error = True

    return render_template('index.html', 
                         message=message, 
                         error=error, 
                         apis=apis,
                         generated_files=generated_files)

@app.route('/download/<doc_type>/<api_name>')
def download_doc(doc_type, api_name):
    """Download generated documentation."""
    try:
        output_dir = os.path.join(os.getcwd(), 'generated_docs')
        if doc_type == 'pdf':
            file_path = os.path.join(output_dir, f"{api_name}_documentation.pdf")
            mimetype = 'application/pdf'
            download_name = f"{api_name}_documentation.pdf"
        else:  # notebook
            file_path = os.path.join(output_dir, f"{api_name}_colab_notebook.ipynb")
            mimetype = 'application/json'
            download_name = f"{api_name}_colab_notebook.ipynb"

        return send_file(file_path, 
                        mimetype=mimetype,
                        as_attachment=True,
                        download_name=download_name)
    except Exception as e:
        logging.error(f"Download error: {str(e)}")
        return "Error downloading file", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)