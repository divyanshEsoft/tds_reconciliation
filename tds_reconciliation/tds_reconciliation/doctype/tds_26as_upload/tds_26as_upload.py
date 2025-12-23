# Copyright (c) 2025, divyansh and contributors
# For license information, please see license.txt


# TDS 26AS Upload (SAVE)
#  ├─ validate_file_type
#  ├─ detect_file_type
#  ├─ parse_file
#  │   ├─ Excel → rows
#  │   ├─ CSV → rows
#  │   ├─ PDF → lines
#  │   └─ TXT → lines
#  └─ store in child table (raw_rows)


import os
import csv
import frappe
from frappe.model.document import Document
from frappe.utils import flt
from openpyxl import load_workbook


class TDS26ASUpload(Document):

    # --------------------------------------------------
    # VALIDATE
    # --------------------------------------------------
    def validate(self):
        if not self.form_26as_file:
            frappe.throw("Please attach Form 26AS file.")

        # Do not re-parse if already parsed
        if self.table_qmbr:
            return

        path = self.get_file_path()
        ext = os.path.splitext(path)[1].lower()

        #  Block deprecated format
        if ext == ".xls":
            frappe.throw(
                "The .xls (old Excel) format is deprecated.\n"
                "Please upload .xlsx, .csv, .txt or .pdf file."
            )

        if ext == ".xlsx":
            self.parse_xlsx()
        elif ext == ".csv":
            self.parse_csv()
        elif ext == ".txt":
            self.parse_txt()
        elif ext == ".pdf":
            self.parse_pdf()
        else:
            frappe.throw(f"Unsupported file type: {ext}")

    # --------------------------------------------------
    # FILE PATH
    # --------------------------------------------------
    def get_file_path(self):
        file_doc = frappe.get_doc("File", {"file_url": self.form_26as_file})
        return file_doc.get_full_path()

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------
    def normalize(self, v):
        return str(v).strip() if v is not None else ""

    def normalize_header(self, h):
        return str(h).strip().lower()

    def clear(self):
        self.set("table_qmbr", [])

    # --------------------------------------------------
    # XLSX
    # --------------------------------------------------
    def parse_xlsx(self):
        wb = load_workbook(self.get_file_path(), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        self.process_rows(rows)

    # --------------------------------------------------
    # CSV
    # --------------------------------------------------


    def parse_csv(self):
        with open(self.get_file_path(), newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            rows = []
            rows.append(reader.fieldnames)  # headers

            for r in reader:
                rows.append([r.get(h) for h in reader.fieldnames])

        self.process_rows(rows)


    # def parse_csv(self):
    #     with open(self.get_file_path(), newline="", encoding="utf-8") as f:
    #         rows = list(csv.reader(f))
    #     self.process_rows(rows)

    # --------------------------------------------------
    # TXT
    # --------------------------------------------------
    def parse_txt(self):
        with open(self.get_file_path(), encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        delimiter = "|" if "|" in lines[0] else "\t" if "\t" in lines[0] else ","
        rows = [l.split(delimiter) for l in lines]
        self.process_rows(rows)

    # --------------------------------------------------
    # PDF
    # --------------------------------------------------
    def parse_pdf(self):
        import pdfplumber

        rows = []
        with pdfplumber.open(self.get_file_path()) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    rows.extend(table)

        if not rows:
            frappe.throw("No table found in PDF")

        self.process_rows(rows)

    # --------------------------------------------------
    # CORE PROCESSOR
    # --------------------------------------------------
    def process_rows(self, rows):
        if len(rows) < 2:
            frappe.throw("File has no data")

        headers = [self.normalize_header(h) for h in rows[0]]

        def col(*names):
            for n in names:
                if n.lower() in headers:
                    return headers.index(n.lower())
            return None

        idx = {
            "deductor": col("name of deductor"),
            "tan": col("tan of deductor"),
            "pan": col("permanent account number (pan)", "pan"),
            "assessee": col("name of assessee"),
            "financial_year": col("financial year"),
            "assessment_year": col("assessment year"),
            "statement_type": col("statement type"),
            "total_amount": col("total amount paid / credited"),
            "total_tax": col("total tax deducted"),
            "total_tds": col("total tds deposited"),
            "address": col("address of assessee"),
            "section": col("section"),
            "txn_date": col("transaction date"),
            "booking_date": col("date of booking"),
            "amount": col("amount paid / credited"),
            "tax": col("tax deducted"),
            "tds": col("tds deposited"),
            "remarks": col("remarks"),
        }

        # Mandatory columns
        required_cols = [
            "deductor", "tan", "financial_year", "assessment_year",
            "total_amount", "total_tax", "total_tds",
            "section", "txn_date", "booking_date",
            "amount", "tax", "tds"
        ]

        for c in required_cols:
            if idx[c] is None:
                frappe.throw(f"Missing required column: {c.replace('_',' ').title()}")

        self.clear()

        for i, row in enumerate(rows[1:], start=1):
            if not row or not row[idx["tan"]]:
                continue

            self.append("table_qmbr", {
                "no": i,
                "name_of_deductor": self.normalize(row[idx["deductor"]]),
                "tan_of_deductor": self.normalize(row[idx["tan"]]),
                "permanent_account_number_pan": self.normalize(row[idx["pan"]]),
                "name_of_assessee": self.normalize(row[idx["assessee"]]),
                "financial_year": self.normalize(row[idx["financial_year"]]),
                "assessment_year": self.normalize(row[idx["assessment_year"]]),
                "statement_type": self.normalize(row[idx["statement_type"]]),
                "total_amount_paid_credited": flt(row[idx["total_amount"]]),
                "total_tax_deducted": flt(row[idx["total_tax"]]),
                "total_tds_deposited": flt(row[idx["total_tds"]]),
                "address_of_assessee": self.normalize(row[idx["address"]]),
                "section": self.normalize(row[idx["section"]]),
                "transaction_date": row[idx["txn_date"]],
                "date_of_booking": row[idx["booking_date"]],
                "amount_paid_credited": flt(row[idx["amount"]]),
                "tax_deducted": flt(row[idx["tax"]]),
                "tds_deposited": flt(row[idx["tds"]]),
                "remarks": self.normalize(row[idx["remarks"]]),
            })

        if not self.table_qmbr:
            frappe.throw("No valid rows found.")

#=------------------------------------------------------------------------------

# -====================================================================


# -==========================================================


#     def validate(self):
#         """Validate before saving"""
#         # Access field using getattr or direct dictionary access
#         if hasattr(self, '26as_file') and self.get('26as_file') and not self.file_type:
#             self.detect_file_type()
    
#     def on_submit(self):
#         """Process file when document is submitted"""
#         self.process_26as_file()
#         self.create_tds_entries()
    
#     def detect_file_type(self):
#         """Auto-detect file type from extension"""
#         # Access field using get method
#         file_url = self.get('26as_file')
#         if file_url:
#             ext = os.path.splitext(file_url)[1].lower()
#             if ext == '.pdf':
#                 self.file_type = 'PDF'
#             elif ext == '.csv':
#                 self.file_type = 'CSV'
#             elif ext == '.xlsx' or ext == '.xls':
#                 self.file_type = 'Excel'
#             elif ext == '.txt':
#                 self.file_type = 'TXT'
    
#     def process_26as_file(self):
#         """Main method to process 26AS file"""
#         try:
#             # Get file path - access field using get()
#             file_url = self.get('26as_file')
#             if not file_url:
#                 frappe.throw("26AS File not attached. Please attach a file.")
            
#             file_path = self.get_file_path(file_url)
            
#             if not file_path:
#                 frappe.throw("File not found. Please check file attachment.")
            
#             # Set status to processing
#             self.status = "Processing"
#             self.save()
#             frappe.db.commit()
            
#             # Process based on file type
#             if self.file_type == "Excel":
#                 data = self.read_excel(file_path)
#             elif self.file_type == "CSV":
#                 data = self.read_csv(file_path)
#             elif self.file_type == "PDF":
#                 data = self.read_pdf(file_path)
#             elif self.file_type == "TXT":
#                 data = self.read_txt(file_path)
#             else:
#                 frappe.throw(f"Unsupported file type: {self.file_type}")
            
#             # Parse 26AS specific data
#             parsed_data = self.parse_26as_data(data)
            
#             # Store parsed data
#             self.parsed_data = json.dumps(parsed_data, indent=2, default=str)
#             self.parsed_date = frappe.utils.now()
            
#             # Update summary
#             self.update_summary(parsed_data)
            
#             # Set status to completed
#             self.status = "Completed"
#             self.save()
#             frappe.db.commit()
            
#             frappe.msgprint(f"Successfully processed {self.file_type} file. Found {len(parsed_data.get('entries', []))} TDS entries.")
            
#         except Exception as e:
#             self.status = "Failed"
#             self.error_log = str(e)
#             self.save()
#             frappe.db.commit()
#             frappe.log_error(f"TDS 26AS Processing Failed: {str(e)}")
#             frappe.throw(f"Failed to process file: {str(e)}")
    
#     def get_file_path(self, file_url=None):
#         """Get full file path from attachment"""
#         if not file_url:
#             file_url = self.get('26as_file')
            
#         try:
#             if file_url.startswith('/private/'):
#                 site_path = frappe.get_site_path()
#                 # Remove leading slash from file_url for private files
#                 private_path = file_url[1:] if file_url.startswith('/private/') else file_url
#                 return os.path.join(site_path, private_path)
#             elif file_url.startswith('/files/'):
#                 site_path = frappe.get_site_path()
#                 return os.path.join(site_path, 'public', file_url[1:])
#             else:
#                 # Try to get file doc
#                 file_doc = frappe.get_doc("File", {"file_url": file_url})
#                 return file_doc.get_full_path()
#         except Exception as e:
#             frappe.log_error(f"Error getting file path for {file_url}: {str(e)}")
#             return None
    
#     def read_excel(self, file_path):
#         """Read Excel file"""
#         try:
#             # Try different engines for compatibility
#             try:
#                 df = pd.read_excel(file_path, engine='openpyxl')
#             except:
#                 df = pd.read_excel(file_path, engine='xlrd')
            
#             # Convert to dictionary
#             return df.to_dict('records')
#         except Exception as e:
#             frappe.throw(f"Error reading Excel file: {str(e)}")
    
#     def read_csv(self, file_path):
#         """Read CSV file"""
#         try:
#             # Handle different encodings
#             encodings = ['utf-8', 'latin-1', 'iso-8859-1']
            
#             for encoding in encodings:
#                 try:
#                     df = pd.read_csv(file_path, encoding=encoding)
#                     return df.to_dict('records')
#                 except UnicodeDecodeError:
#                     continue
            
#             # If above fails, try manual reading
#             with open(file_path, 'r', encoding='utf-8-sig') as file:
#                 reader = csv.DictReader(file)
#                 return list(reader)
#         except Exception as e:
#             frappe.throw(f"Error reading CSV file: {str(e)}")
    
#     def read_pdf(self, file_path):
#         """Read PDF file - specific for 26AS format"""
#         try:
#             with open(file_path, 'rb') as file:
#                 pdf_reader = PyPDF2.PdfReader(file)
#                 text_content = ""
                
#                 # Extract text from all pages
#                 for page_num, page in enumerate(pdf_reader.pages, 1):
#                     text = page.extract_text()
#                     text_content += f"\n--- Page {page_num} ---\n{text}"
                
#                 return self.parse_26as_pdf_text(text_content)
#         except Exception as e:
#             frappe.throw(f"Error reading PDF file: {str(e)}")
    
#     def read_txt(self, file_path):
#         """Read Text file"""
#         try:
#             with open(file_path, 'r', encoding='utf-8') as file:
#                 content = file.read()
#                 return content
#         except Exception as e:
#             frappe.throw(f"Error reading Text file: {str(e)}")
    
#     def parse_26as_pdf_text(self, text):
#         """Parse 26AS specific PDF text format"""
#         # Common patterns in 26AS PDF
#         patterns = {
#             'tan': r'TAN[\s:]*([A-Z]{4}\d{5}[A-Z])',
#             'pan': r'PAN[\s:]*([A-Z]{5}\d{4}[A-Z])',
#             'assessment_year': r'Assessment Year[\s:]*(\d{4}-\d{2})',
#             'deductor_name': r'Name of Deductor[\s:]*([^\n]+)',
#             'total_amount': r'Total Amount[\s:]*([\d,]+\.?\d*)',
#         }
        
#         parsed_data = {}
#         for key, pattern in patterns.items():
#             match = re.search(pattern, text, re.IGNORECASE)
#             if match:
#                 parsed_data[key] = match.group(1).strip()
        
#         # Extract table data (simplified)
#         entries = []
#         lines = text.split('\n')
        
#         # Look for transaction patterns
#         for line in lines:
#             if re.search(r'\d{2}-[A-Z]{3}-\d{4}', line):  # Date pattern DD-MMM-YYYY
#                 parts = line.split()
#                 if len(parts) >= 5:
#                     entry = {
#                         'date_of_deduction': parts[0],
#                         'section_code': parts[1] if len(parts) > 1 else '',
#                         'tds_amount': parts[-1] if len(parts) > 2 else '0'
#                     }
#                     entries.append(entry)
        
#         parsed_data['entries'] = entries
#         return parsed_data
    
#     def parse_26as_data(self, data):
#         """Parse and structure 26AS data"""
#         parsed_data = {
#             'tan': '',
#             'pan': '',
#             'assessment_year': '',
#             'deductor_name': '',
#             'financial_year': self.financial_year,
#             'total_tds_amount': 0,
#             'total_entries': 0,
#             'entries': []
#         }
        
#         if isinstance(data, dict):
#             # Already parsed PDF data
#             parsed_data.update(data)
        
#         elif isinstance(data, list):
#             # Excel/CSV data
#             for row in data:
#                 entry = self.parse_26as_row(row)
#                 if entry:
#                     parsed_data['entries'].append(entry)
        
#         elif isinstance(data, str):
#             # Text data
#             parsed_data = self.parse_26as_text_data(data)
        
#         # Calculate totals
#         parsed_data['total_entries'] = len(parsed_data.get('entries', []))
        
#         # Calculate total TDS amount
#         total_amount = 0
#         for entry in parsed_data.get('entries', []):
#             try:
#                 # Clean amount string (remove commas, etc.)
#                 amount_str = str(entry.get('tds_amount', 0)).replace(',', '').strip()
#                 total_amount += float(amount_str) if amount_str else 0
#             except:
#                 continue
        
#         parsed_data['total_tds_amount'] = total_amount
        
#         return parsed_data
    
#     def parse_26as_row(self, row):
#         """Parse individual row from Excel/CSV"""
#         try:
#             # Map common column names found in 26AS statements
#             entry = {}
            
#             # Try to find date in various column names
#             date_keys = ['Date of Deduction', 'Date', 'Deduction Date', 'Transaction Date', 
#                         'date_of_deduction', 'Date of Payment', 'Payment Date']
#             for key in date_keys:
#                 if row.get(key):
#                     entry['date_of_deduction'] = row.get(key)
#                     break
            
#             # Try to find section code
#             section_keys = ['Section Code', 'Section', 'Section 194', 'section_code', 
#                           'TDS Section', 'Chapter']
#             for key in section_keys:
#                 if row.get(key):
#                     entry['section_code'] = row.get(key)
#                     break
            
#             # Try to find TDS amount
#             amount_keys = ['TDS Amount', 'Amount', 'TDS', 'tds_amount', 'TDS Deducted',
#                           'Tax Deducted', 'Deducted Amount']
#             for key in amount_keys:
#                 if row.get(key):
#                     entry['tds_amount'] = row.get(key)
#                     break
            
#             # Try to find deposited amount
#             deposited_keys = ['Deposited Amount', 'Deposited', 'Amount Deposited', 
#                             'Tax Deposited', 'Deposit Amount']
#             for key in deposited_keys:
#                 if row.get(key):
#                     entry['deposited_amount'] = row.get(key)
#                     break
            
#             # Try to find deductor name
#             deductor_keys = ['Deductor Name', 'Name of Deductor', 'Deductor', 
#                            'Company Name', 'Employer Name']
#             for key in deductor_keys:
#                 if row.get(key):
#                     entry['deductor_name'] = row.get(key)
#                     break
            
#             # Try to find TAN
#             tan_keys = ['Deductor TAN', 'TAN', 'Tax Deduction Account Number', 'TAN Number']
#             for key in tan_keys:
#                 if row.get(key):
#                     entry['deductor_tan'] = row.get(key)
#                     break
            
#             # Try to find challan number
#             challan_keys = ['Challan No', 'Challan Number', 'Challan', 'BSR Code & Challan No']
#             for key in challan_keys:
#                 if row.get(key):
#                     entry['challan_no'] = row.get(key)
#                     break
            
#             # Try to find BSR code
#             bsr_keys = ['BSR Code', 'BSR', 'Bank Branch Code']
#             for key in bsr_keys:
#                 if row.get(key):
#                     entry['bsr_code'] = row.get(key)
#                     break
            
#             # Try to find cheque details
#             cheque_keys = ['Cheque/DD No', 'Cheque No', 'DD No', 'Instrument No', 
#                           'Cheque Number']
#             for key in cheque_keys:
#                 if row.get(key):
#                     entry['cheque_dd_no'] = row.get(key)
#                     break
            
#             # Try to find rate
#             rate_keys = ['Rate', 'TDS Rate', 'Tax Rate', 'Deduction Rate']
#             for key in rate_keys:
#                 if row.get(key):
#                     entry['rate'] = row.get(key)
#                     break
            
#             # Clean up data
#             for key in entry:
#                 if isinstance(entry[key], str):
#                     entry[key] = entry[key].strip()
            
#             return entry if entry else None
            
#         except Exception as e:
#             frappe.log_error(f"Error parsing row: {str(e)}")
#             return None
    
#     def parse_26as_text_data(self, text):
#         """Parse text data for 26AS"""
#         parsed = {'entries': []}
        
#         # Split into lines and parse
#         lines = text.split('\n')
#         current_entry = {}
        
#         for line in lines:
#             line = line.strip()
#             if not line:
#                 if current_entry:
#                     parsed['entries'].append(current_entry)
#                     current_entry = {}
#                 continue
            
#             # Parse key-value pairs
#             if ':' in line:
#                 key, value = line.split(':', 1)
#                 key = key.strip().lower().replace(' ', '_')
#                 current_entry[key] = value.strip()
        
#         # Add last entry if exists
#         if current_entry:
#             parsed['entries'].append(current_entry)
        
#         return parsed
    
#     def update_summary(self, parsed_data):
#         """Update summary fields in doctype"""
#         self.total_entries = parsed_data.get('total_entries', 0)
#         self.total_tds_amount = parsed_data.get('total_tds_amount', 0)
        
#         # Extract key information
#         self.tan_number = parsed_data.get('tan', '')
#         self.pan_number = parsed_data.get('pan', '')
        
#         # Set financial year if not set
#         if not self.financial_year and parsed_data.get('assessment_year'):
#             self.financial_year = parsed_data.get('assessment_year')
    
#     def create_tds_entries(self):
#         """Create TDS Entry child records"""
#         if not self.parsed_data:
#             return
        
#         parsed_data = json.loads(self.parsed_data)
#         entries = parsed_data.get('entries', [])
        
#         # Clear existing entries if any
#         self.tds_entries = []
        
#         # Create new entries
#         for idx, entry_data in enumerate(entries, 1):
#             child_entry = {
#                 'date_of_deduction': entry_data.get('date_of_deduction'),
#                 'section_code': entry_data.get('section_code'),
#                 'tds_amount': entry_data.get('tds_amount', 0),
#                 'deposited_amount': entry_data.get('deposited_amount', 0),
#                 'deductor_name': entry_data.get('deductor_name'),
#                 'deductor_tan': entry_data.get('deductor_tan'),
#                 'challan_no': entry_data.get('challan_no'),
#                 'bsr_code': entry_data.get('bsr_code'),
#                 'cheque_dd_no': entry_data.get('cheque_dd_no'),
#                 'rate': entry_data.get('rate', 0),
#                 'status': 'Pending'
#             }
            
#             # Add to child table
#             self.append('tds_entries', child_entry)
        
#         # Save the document
#         self.save()
    
#     @frappe.whitelist()
#     def preview_data(self):
#         """Preview parsed data without saving"""
#         try:
#             # Access field using get()
#             file_url = self.get('26as_file')
#             if not file_url:
#                 return {"error": "26AS File not attached"}
            
#             file_path = self.get_file_path(file_url)
#             if not file_path:
#                 return {"error": "File not found"}
            
#             # Process file
#             if self.file_type == "Excel":
#                 data = self.read_excel(file_path)
#             elif self.file_type == "CSV":
#                 data = self.read_csv(file_path)
#             elif self.file_type == "PDF":
#                 data = self.read_pdf(file_path)
#             elif self.file_type == "TXT":
#                 data = self.read_txt(file_path)
#             else:
#                 return {"error": f"Unsupported file type: {self.file_type}"}
            
#             # Parse data
#             parsed_data = self.parse_26as_data(data)
            
#             return {
#                 "success": True,
#                 "total_entries": len(parsed_data.get('entries', [])),
#                 "total_amount": parsed_data.get('total_tds_amount', 0),
#                 "sample_entries": parsed_data.get('entries', [])[:5],  # First 5 entries
#                 "file_type": self.file_type
#             }
#         except Exception as e:
#             return {"error": str(e)}
    
#     @frappe.whitelist()
#     def export_to_excel(self):
#         """Export parsed data to Excel"""
#         if not self.parsed_data:
#             frappe.throw("No data to export. Please process the file first.")
        
#         parsed_data = json.loads(self.parsed_data)
#         entries = parsed_data.get('entries', [])
        
#         if not entries:
#             frappe.throw("No entries found to export.")
        
#         # Create DataFrame
#         df = pd.DataFrame(entries)
        
#         # Create filename
#         timestamp = frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')
#         filename = f"TDS_26AS_{self.name}_{timestamp}.xlsx"
#         file_path = os.path.join(frappe.get_site_path(), 'public', 'files', filename)
        
#         # Ensure directory exists
#         os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
#         # Save to Excel
#         df.to_excel(file_path, index=False)
        
#         # Create File document
#         file_url = f"/files/{filename}"
#         file_doc = frappe.get_doc({
#             "doctype": "File",
#             "file_name": filename,
#             "file_url": file_url,
#             "attached_to_doctype": self.doctype,
#             "attached_to_name": self.name,
#             "folder": "Home"
#         })
#         file_doc.insert()
        
#         return file_url




# # # Copyright (c) 2025, divyansh and contributors
# # # For license information, please see license.txt

# # import frappe
# # from frappe.model.document import Document


# # import pandas as pd
# # import csv
# # import PyPDF2
# # import json
# # import os
# # import re
# # from datetime import datetime
# # from io import StringIO


# # class TDS26ASUpload(Document):
# #     def validate(self):
# #         """Validate before saving"""
# #         if self.26as_file and not self.file_type:
# #             self.detect_file_type()
