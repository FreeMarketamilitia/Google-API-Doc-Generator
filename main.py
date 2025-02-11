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
    Generate a professional PDF documentation for the specified API.
    Handles Unicode characters and ensures compatibility with the FPDF library.
    """
    pdf = APIDocumentationPDF()
    pdf.add_page()

    def sanitize_text(text):
        """
        Replace unsupported characters with ASCII equivalents or remove them.
        """
        return text.encode('latin-1', 'replace').decode('latin-1')

    def format_code_block(code):
        """
        Formats code as a monospaced block with a shaded background.
        """
        pdf.set_font('Courier', '', 9)
        pdf.set_fill_color(245, 245, 245)
        sanitized_code = sanitize_text(code)
        pdf.multi_cell(0, 6, sanitized_code, border=1, fill=True)
        pdf.ln(4)

    def add_table(headers, rows):
        """
        Adds a simple table to the PDF.
        """
        pdf.set_fill_color(200, 220, 255)
        pdf.set_font('Arial', 'B', 10)
        col_width = pdf.w / len(headers) - 10
        for header in headers:
            pdf.cell(col_width, 8, sanitize_text(header), 1, 0, 'C', fill=True)
        pdf.ln()
        pdf.set_font('Arial', '', 9)
        for row in rows:
            for cell in row:
                pdf.cell(col_width, 8, sanitize_text(str(cell)), 1)
            pdf.ln()

    try:
        # Fetch API details
        service = build('discovery', 'v1', developerKey=api_key)
        api_response = service.apis().getRest(api=api_name, version=api_version).execute()

        pdf.chapter_title(sanitize_text(f"{api_name} API Documentation"))
        pdf.chapter_body(sanitize_text(f"Version: {api_version}\n"))

        if 'description' in api_response:
            pdf.chapter_body(sanitize_text(api_response['description']))

        def document_method(method):
            """
            Adds a detailed section for each method.
            """
            pdf.add_page()
            pdf.chapter_title(sanitize_text(f"Method: {method['name']}"))
            pdf.chapter_body(sanitize_text(f"HTTP Method: {method.get('httpMethod', 'N/A')}"))
            pdf.chapter_body(sanitize_text(f"Path: {method.get('path', 'N/A')}"))
            if method.get('description'):
                pdf.chapter_body(sanitize_text(f"Description: {method['description']}"))

            # Add parameters as a table
            if method['parameters']:
                headers = ["Parameter", "Description", "Required"]
                rows = [
                    [param, details.get("description", "No description"), str(details.get("required", False))]
                    for param, details in method['parameters'].items()
                ]
                pdf.chapter_body("Parameters:")
                add_table(headers, rows)

            # Add AI-generated best use cases
            try:
                use_case_prompt = f"Provide best use cases for the following API method:\n\n{json.dumps(method, indent=2)}"
                best_use_cases = generate_with_mistral(use_case_prompt, api_key)
                pdf.chapter_body("Best Use Cases:")
                pdf.chapter_body(sanitize_text(best_use_cases or "No AI-generated content available."))
            except Exception as ex:
                logging.error(f"Error generating best use cases: {ex}")
                pdf.chapter_body("Best Use Cases: Error generating content.")

            # Add AI-generated common errors
            try:
                error_prompt = f"List common errors for the following API method:\n\n{json.dumps(method, indent=2)}"
                common_errors = generate_with_mistral(error_prompt, api_key)
                pdf.chapter_body("Common Errors:")
                pdf.chapter_body(sanitize_text(common_errors or "No AI-generated content available."))
            except Exception as ex:
                logging.error(f"Error generating common errors: {ex}")
                pdf.chapter_body("Common Errors: Error generating content.")

            # Add example code
            try:
                example_params = ", ".join(
                    [f"{param}='PLACEHOLDER_VALUE'" for param in method['parameters'].keys()]
                )
                example_code = f"""# Example for method: {method['name']}
try:
    # Build and execute the API request
    response = service.{method['name'].replace('.', '().')}({example_params}).execute()
    
    # Print the JSON response in a readable format
    print(json.dumps(response, indent=2))
except Exception as ex:
    # Handle and print any errors that occur
    print(f"Error calling API: {{ex}}")
"""
                pdf.chapter_body("Example Code:")
                format_code_block(example_code)
            except Exception as ex:
                logging.error(f"Error generating example code: {ex}")
                pdf.chapter_body("Example Code: Error generating content.")

        # Extract methods from API response
        def extract_method_details(response):
            methods = []
            def traverse(resources, prefix=""):
                for resource_name, resource in resources.items():
                    if 'methods' in resource:
                        for method_name, method in resource['methods'].items():
                            full_name = f"{prefix}{resource_name}.{method_name}" if prefix else f"{resource_name}.{method_name}"
                            methods.append({
                                'name': full_name,
                                'httpMethod': method.get('httpMethod', 'GET'),
                                'path': method.get('path', ''),
                                'parameters': method.get('parameters', {}),
                                'description': method.get('description', 'No description available.')
                            })
                    if 'resources' in resource:
                        traverse(resource['resources'], f"{prefix}{resource_name}.")
            if 'resources' in response:
                traverse(response['resources'])
            return methods

        # Process and document each method
        methods_list = extract_method_details(api_response)
        for method in methods_list:
            document_method(method)

        # Save the PDF
        output_dir = os.path.join(os.getcwd(), 'generated_docs')
        os.makedirs(output_dir, exist_ok=True)
        pdf_filename = os.path.join(output_dir, f"{api_name}_documentation.pdf")
        pdf.output(pdf_filename)
        return pdf_filename

    except Exception as e:
        logging.error(f"Error generating PDF: {str(e)}")
        raise





def generate_colab_notebook(api_name, api_version, notebook_filename, api_key):
    """
    Generate an interactive Colab notebook with Markdown tables and Mistral-enhanced content.
    """
    service = build('discovery', 'v1', developerKey=api_key)
    api_response = service.apis().getRest(api=api_name, version=api_version).execute()

    def extract_method_details(response):
        methods = []
        def traverse(resources, prefix=""):
            for resource_name, resource in resources.items():
                if 'methods' in resource:
                    for method_name, method in resource['methods'].items():
                        full_name = f"{prefix}{resource_name}.{method_name}" if prefix else f"{resource_name}.{method_name}"
                        methods.append({
                            'name': full_name,
                            'httpMethod': method.get('httpMethod', 'GET'),
                            'path': method.get('path', ''),
                            'parameters': method.get('parameters', {}),
                            'description': method.get('description', 'No description available.')
                        })
                if 'resources' in resource:
                    traverse(resource['resources'], f"{prefix}{resource_name}.")
        if 'resources' in response:
            traverse(response['resources'])
        return methods

    methods_list = extract_method_details(api_response)

    def generate_with_mistral(prompt):
        """
        Use Mistral to generate additional content for each method.
        """
        try:
            time.sleep(1.5)  # Respect rate-limiting
            client = Mistral(api_key=api_key)
            response = client.chat.complete(
                model=MISTRAL_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"Mistral API error: {e}")
            return "No AI-generated content available."

    notebook_cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"# {api_name} API Interactive Notebook ({api_version})\n",
                f"This notebook allows you to explore methods in the {api_name} API interactively.\n",
                "Each method is documented with its HTTP method, endpoint path, parameters, and an example call.\n\n"
            ]
        },
        {
            "cell_type": "code",
            "metadata": {},
            "source": [
                "from googleapiclient.discovery import build\n",
                "import json\n",
                f"service = build('{api_name}', '{api_version}', developerKey='{api_key}')\n",
                "print('✅ API Service Initialized')"
            ]
        }
    ]

    # Add a cell for each method with Mistral-enhanced content
    for method in methods_list:
        # Generate Mistral content
        use_case_prompt = f"Provide best use cases for the following API method:\n\n{json.dumps(method, indent=2)}"
        best_use_cases = generate_with_mistral(use_case_prompt).splitlines()

        error_prompt = f"List common errors for the following API method:\n\n{json.dumps(method, indent=2)}"
        common_errors = generate_with_mistral(error_prompt).splitlines()

        quiz_prompt = f"Create a quiz question for the following API method:\n\n{json.dumps(method, indent=2)}"
        quiz_question = generate_with_mistral(quiz_prompt)

        # Create Markdown tables
        param_table = "| Parameter | Description | Required |\n|---|---|---|\n" + "\n".join(
            f"| {param} | {details.get('description', 'No description')} | {details.get('required', False)} |"
            for param, details in method['parameters'].items()
        )

        use_case_table = "| Use Case |\n|---|\n" + "\n".join(
            f"| {use_case.strip()} |" for use_case in best_use_cases if use_case.strip()
        )

        error_table = "| Common Error |\n|---|\n" + "\n".join(
            f"| {error.strip()} |" for error in common_errors if error.strip()
        )

        # Add a markdown cell with all details
        method_markdown_cell = {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"## Method: {method['name']}\n",
                f"**HTTP Method:** `{method['httpMethod']}`\n",
                f"**Path:** `{method['path']}`\n",
                f"**Description:** {method['description']}\n\n",
                "### Parameters:\n",
                param_table + "\n\n",
                "### Best Use Cases:\n",
                use_case_table + "\n\n",
                "### Common Errors:\n",
                error_table + "\n\n",
                f"### Quiz:\n{quiz_question}\n",
            ]
        }
        notebook_cells.append(method_markdown_cell)

        # Add an example code cell
        example_params = ", ".join([f"{param}='PLACEHOLDER'" for param in method['parameters'].keys()])
        example_code_cell = {
            "cell_type": "code",
            "metadata": {},
            "source": [
                f"# Example for method: {method['name']}\n",
                "try:\n",
                f"    response = service.{method['name'].replace('.', '().')}({example_params}).execute()\n",
                "    print(json.dumps(response, indent=2))\n",
                "except Exception as e:\n",
                "    print(f'Error calling API: {e}')"
            ]
        }
        notebook_cells.append(example_code_cell)

    notebook = {
        "cells": notebook_cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "name": "python3"
            },
            "colab": {
                "name": f"{api_name} API Notebook",
                "provenance": []
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }

    # Save the notebook
    with open(notebook_filename, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=2)
    
    logging.info(f"Colab notebook saved: {notebook_filename}")
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
        
def home():
    return render_template("index.html")  
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

