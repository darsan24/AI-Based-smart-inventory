import os
from fpdf import FPDF

def create_pdf():
    print("Gathering code and generating PDF, please wait...")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=8)

    base_dir = r"c:\Users\Selva\Documents\mini project"
    extensions = ('.py', '.html', '.css', '.js')
    
    for root, dirs, files in os.walk(base_dir):
        if 'venv' in root or '__pycache__' in root or '.git' in root or 'node_modules' in root:
            continue
        for file in files:
            if file.endswith(extensions):
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, base_dir)
                
                pdf.set_font("Courier", 'B', 10)
                pdf.cell(0, 10, f"--- File: {rel_path} ---", ln=True)
                pdf.set_font("Courier", size=8)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Replace tabs and characters that might not be supported by basic Courier font
                        clean_content = content.replace('\t', '    ').encode('latin-1', 'replace').decode('latin-1')
                        pdf.multi_cell(0, 4, clean_content)
                except Exception as e:
                    pdf.multi_cell(0, 4, f"Error reading file: {e}")
                
                pdf.ln(5)

    output_path = r"c:\Users\Selva\Desktop\mini_project_code.pdf"
    try:
        pdf.output(output_path)
        print(f"Successfully saved {output_path}")
    except Exception as e:
        print(f"Error saving PDF: {e}")

if __name__ == '__main__':
    create_pdf()
