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
    """Fetch available APIs using Google Discovery API."""
    try:
        service = build('discovery', 'v1')
        apis_response = service.apis().list(preferred=True).execute()
        if 'items' in apis_response:
            return apis_response['items']
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
    api_response = service.apis().getRest(api=api_name, version=api_version).execute()

    # API Overview
    pdf.chapter_title(f"{api_name} API Documentation")
    pdf.chapter_body(f"Version: {api_version}\n")
    if 'description' in api_response:
        pdf.chapter_body(api_response['description'])

    # Document endpoints
    for endpoint_name, endpoint in api_response.get('resources', {}).get('methods', {}).items():
        pdf.add_page()
        pdf.chapter_title(f"Endpoint: {endpoint_name}")
        
        # Basic endpoint info
        pdf.chapter_body(f"HTTP Method: {endpoint.get('httpMethod', 'N/A')}")
        pdf.chapter_body(f"Path: {endpoint.get('path', 'N/A')}")
        
        # AI-generated content
        ai_prompt = f"""
        For the {api_name} API endpoint: {endpoint['httpMethod']} {endpoint['id']}
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
        Service: service.{endpoint['id']}()
        Include realistic parameters and error handling.
        """
        code_example = generate_with_gemini(example_prompt, api_key)
        if code_example:
            pdf.chapter_title("Example Code")
            pdf.code_section(code_example)

    # Save to temporary file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    pdf.output(temp_file.name)
    return temp_file.name

@app.route('/', methods=['GET', 'POST'])
def index():
    message = None
    error = False
    apis = []
    pdf_path = None

    if request.method == 'POST':
        api_key = request.form.get('api_key')
        api_name = request.form.get('api_name')
        api_version = request.form.get('api_version', 'v1')
        output_format = request.form.get('output_format', 'colab')

        apis = get_api_list()
        if not apis:
            message = "Failed to fetch API list"
            error = True
        elif api_name:
            try:
                if output_format == 'colab':
                    notebook_filename = f"{api_name}_colab_notebook.ipynb"
                    generate_colab_notebook(api_name, api_version, notebook_filename, api_key)
                    message = "Colab notebook generated successfully!"
                else:
                    pdf_path = generate_pdf_documentation(api_name, api_version, api_key)
                    message = "PDF documentation generated successfully!"
            except Exception as e:
                message = f"Error: {str(e)}"
                error = True
        else:
            message = "Please select an API"
            error = True

    return render_template('index.html', 
                         message=message, 
                         error=error, 
                         apis=apis, 
                         pdf_path=pdf_path)

@app.route('/download_pdf/<api_name>')
def download_pdf(api_name):
    """Download generated PDF documentation."""
    try:
        pdf_path = f"/tmp/{api_name}_documentation.pdf"
        return send_file(pdf_path, 
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name=f"{api_name}_documentation.pdf")
    except Exception as e:
        logging.error(f"PDF download error: {str(e)}")
        return "Error downloading PDF", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
