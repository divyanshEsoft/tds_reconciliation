# Copyright (c) 2025, divyansh and contributors
# For license information, please see license.txt


from datetime import datetime
import os
import csv
from frappe.utils import flt
import frappe
from frappe.model.document import Document
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
    # PDF - SIMPLIFIED VERSION
    # --------------------------------------------------
 
  
 
    def parse_pdf(self):
        import pdfplumber
        import re
        
        print("\n" + "="*60)
        print("STARTING PDF PARSING")
        print("="*60)
        
        # Extract all text first to get header info
        all_text = ""
        with pdfplumber.open(self.get_file_path()) as pdf:
            for page in pdf.pages:
                all_text += page.extract_text() + "\n"
        
        print("\nExtracted text from PDF (first 1000 chars):")
        print("-"*60)
        print(all_text[:1000] + "..." if len(all_text) > 1000 else all_text)
        print("-"*60)
        
        # Extract key information using regex
        extracted_info = {}
        
        # PAN
        pan_match = re.search(r'Permanent Account Number\s*\(PAN\)\s*:?\s*([A-Z]{5}\d{4}[A-Z])', all_text, re.IGNORECASE)
        if pan_match:
            extracted_info['pan'] = pan_match.group(1).strip()
            print(f"Found PAN: {extracted_info['pan']}")
        
        # Assessee Name
        name_match = re.search(r'Name of Assessee\s*:?\s*(.+?)(?:\n|Address)', all_text, re.IGNORECASE)
        if name_match:
            extracted_info['assessee_name'] = name_match.group(1).strip()
            print(f"Found Assessee Name: {extracted_info['assessee_name']}")
        
        # Financial Year
        fy_match = re.search(r'Financial Year\s*:?\s*(\d{4}-\d{2})', all_text, re.IGNORECASE)
        if fy_match:
            extracted_info['financial_year'] = fy_match.group(1).strip()
            print(f"Found Financial Year: {extracted_info['financial_year']}")
        else:
            extracted_info['financial_year'] = self.financial_year or ""
        
        # Assessment Year
        ay_match = re.search(r'Assessment Year\s*:?\s*(\d{4}-\d{2})', all_text, re.IGNORECASE)
        if ay_match:
            extracted_info['assessment_year'] = ay_match.group(1).strip()
            print(f"Found Assessment Year: {extracted_info['assessment_year']}")
        
        # Initialize storage for deductors and transactions
        deductors = []
        transactions = []
        current_deductor = None
        
        # Now extract tables
        with pdfplumber.open(self.get_file_path()) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                
                for table_num, table in enumerate(tables):
                    if not table or len(table) < 2:
                        continue
                    
                    print(f"\n--- Table {table_num + 1} on page {page_num + 1} ---")
                    
                    # Clean the table
                    cleaned_table = []
                    for row in table:
                        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
                        cleaned_table.append(cleaned_row)
                    
                    # Debug: Print first few rows
                    print(f"  First 3 rows of table:")
                    for i, row in enumerate(cleaned_table[:3]):
                        print(f"    Row {i}: {row}")
                    
                    # Process each row in the table
                    mode = None  # Can be 'deductor' or 'transaction'
                    
                    for row_num, row in enumerate(cleaned_table):
                        row_text = ' '.join(row).lower()
                        
                        # Check if this row is a header for deductor summary
                        if 'name of deductor' in row_text and 'tan' in row_text:
                            mode = 'deductor'
                            print(f"  Row {row_num}: Switching to DEDUCTOR mode")
                            continue
                        
                        # Check if this row is a header for transaction details
                        if 'section' in row_text and 'transaction date' in row_text:
                            mode = 'transaction'
                            print(f"  Row {row_num}: Switching to TRANSACTION mode")
                            continue
                        
                        # Skip empty rows
                        if not any(row) or not row[0] or row[0].strip() == "":
                            continue
                        
                        # Process based on current mode
                        if mode == 'deductor':
                            # Check if first column is a number (Sr. No.)
                            if row[0].isdigit():
                                deductor = {
                                    'name': row[1] if len(row) > 1 else "",
                                    'tan': row[2] if len(row) > 2 else "TAN_NOT_FOUND",
                                    'total_amount': row[3] if len(row) > 3 else "0.00",
                                    'total_tax': row[4] if len(row) > 4 else "0.00",
                                    'total_tds': row[5] if len(row) > 5 else "0.00",
                                }
                                
                                # Only add if name looks valid (not a number)
                                if deductor['name'] and not deductor['name'].isdigit():
                                    deductors.append(deductor)
                                    current_deductor = deductor
                                    print(f"  Row {row_num}: Added deductor: {deductor['name']}, TAN: {deductor['tan']}")
                        
                        elif mode == 'transaction':
                            # Check if first column is a number (Sr. No.)
                            if row[0].isdigit():
                                # Normalize the row
                                cleaned_row = self.normalize_pdf_row(row)
                                
                                print(f"  Row {row_num}: Processing transaction: {cleaned_row}")
                                
                                transaction = {
                                    'section': cleaned_row[1] if len(cleaned_row) > 1 else "",
                                    'transaction_date': cleaned_row[2] if len(cleaned_row) > 2 else "",
                                    'status': cleaned_row[3] if len(cleaned_row) > 3 else "",
                                    'booking_date': cleaned_row[4] if len(cleaned_row) > 4 else "",
                                    'remarks': cleaned_row[5] if len(cleaned_row) > 5 else "",
                                    'amount': cleaned_row[6] if len(cleaned_row) > 6 else "0.00",
                                    'tax': cleaned_row[7] if len(cleaned_row) > 7 else "0.00",
                                    'tds': cleaned_row[8] if len(cleaned_row) > 8 else "0.00",
                                }
                                
                                # Only add if section looks valid (3 digits like 192, 194A, etc.)
                                if transaction['section'] and (transaction['section'].isdigit() or re.match(r'\d{3}[A-Z]*', transaction['section'])):
                                    transactions.append(transaction)
                                    print(f"    ✓ Added: Section={transaction['section']}, Date={transaction['transaction_date']}, Amount={transaction['amount']}")
                                else:
                                    print(f"    ✗ Skipped: Invalid section '{transaction['section']}'")
        
        print(f"\n{'='*60}")
        print(f"Found {len(deductors)} deductors and {len(transactions)} transactions")
        print(f"{'='*60}")
        
        if not transactions:
            frappe.throw("No transaction data found in PDF. Please check if the PDF contains Form 26AS data.")
        
        # Use the first deductor for all transactions (typical case)
        default_deductor = deductors[0] if deductors else {
            'name': 'Employer/Company',
            'tan': 'TAN_NOT_FOUND',
            'total_amount': '0.00',
            'total_tax': '0.00',
            'total_tds': '0.00'
        }
        
        print(f"\nUsing deductor: {default_deductor['name']}")
        
        # Create processed rows for process_rows
        processed_rows = []
        
        # Create headers
        headers = [
            "Name of Deductor",
            "TAN of Deductor",
            "Total Amount Paid/ Credited",
            "Total Tax Deducted",
            "Total TDS Deposited",
            "Section",
            "Transaction Date",
            "Status of Booking",
            "Date of Booking",
            "Remarks",
            "Amount Paid/ Credited",
            "Tax Deducted",
            "TDS Deposited",
            "Permanent Account Number (PAN)",
            "Name of Assessee",
            "Financial Year",
            "Assessment Year",
            "Address of Assessee",
            "Statement Type"
        ]
        
        processed_rows.append(headers)
        
        # Add each transaction as a row
        for i, txn in enumerate(transactions):
            # Clean amount values
            amount = txn['amount'].replace(',', '') if txn['amount'] else "0.00"
            tax = txn['tax'].replace(',', '') if txn['tax'] else "0.00"
            tds = txn['tds'].replace(',', '') if txn['tds'] else "0.00"
            
            # Create the row with all required fields
            row = [
                default_deductor['name'],  # Name of Deductor
                default_deductor['tan'],  # TAN of Deductor
                default_deductor['total_amount'],  # Total Amount Paid/ Credited
                default_deductor['total_tax'],  # Total Tax Deducted
                default_deductor['total_tds'],  # Total TDS Deposited
                txn['section'],  # Section
                txn['transaction_date'],  # Transaction Date
                txn['status'],  # Status of Booking
                txn['booking_date'],  # Date of Booking
                txn['remarks'],  # Remarks
                amount,  # Amount Paid/ Credited
                tax,  # Tax Deducted
                tds,  # TDS Deposited
                extracted_info.get('pan', ''),  # PAN
                extracted_info.get('assessee_name', ''),  # Name of Assessee
                extracted_info.get('financial_year', self.financial_year or ''),  # Financial Year
                extracted_info.get('assessment_year', ''),  # Assessment Year
                "",  # Address of Assessee
                "Form 26AS",  # Statement Type
            ]
            
            processed_rows.append(row)
        
        print(f"\nCreated {len(processed_rows) - 1} processed rows for process_rows")
        
        # Call process_rows with our processed data
        self.process_rows(processed_rows)

    # --------------------------------------------------
    # CORE PROCESSOR - SIMPLIFIED VERSION
    # --------------------------------------------------
    def process_rows(self, rows):
        if len(rows) < 2:
            frappe.throw("File has no data")

        headers = [self.normalize_header(h) for h in rows[0]]
        
        print("\n" + "="*60)
        print("PROCESSING ROWS IN process_rows")
        print("="*60)
        print(f"Total rows to process: {len(rows)}")
        print(f"Headers found: {headers}")
        
        def col(*names):
            for n in names:
                n_lower = n.lower()
                for i, header in enumerate(headers):
                    if n_lower in header:
                        print(f"  Found column '{n}' at index {i}")
                        return i
            print(f"  Column not found: {names}")
            return None
        
        # Map column indices - using simplified matching
        # idx = {
        #     "deductor": col("name of deductor"),
        #     "tan": col("tan of deductor"),
        #     "pan": col("permanent account number (pan)", "pan"),
        #     "assessee": col("name of assessee", "assessee"),
        #     "financial_year": col("financial year"),
        #     "assessment_year": col("assessment year"),
        #     "total_amount": col("total amount paid / credited"),
        #     "total_tax": col("total tax deducted"),
        #     "total_tds": col("total tds deposited"),
        #     "section": col("section"),
        #     "txn_date": col("transaction date"),
        #     "booking_date": col("date of booking"),
        #     "amount": col("amount paid / credited"),
        #     "tax": col("tax deducted"),
        #     "tds": col("tds deposited"),
        #     "remarks": col("remarks"),
        # }
        


        idx = {
            "deductor": col("name of deductor"),
            "tan": col("tan of deductor"),
            "pan": col("permanent account number"),
            "assessee": col("name of assessee"),
            "financial_year": col("financial year"),
            "assessment_year": col("assessment year"),

            # SUMMARY (deductor level)
            "total_amount": col("total amount paid", "total amount paid/ credited"),
            "total_tax": col("total tax deducted"),
            "total_tds": col("total tds deposited"),

            # TRANSACTION LEVEL (THIS WAS BROKEN)
            "section": col("section"),
            "txn_date": col("transaction date"),
            "booking_date": col("date of booking"),
            "remarks": col("remarks"),
            "amount": col("amount paid", "amount paid/ credited"),
            "tax": col("tax deducted##", "tax deducted"),
            "tds": col("tds deposited"),
        }

        print("\nColumn mapping summary:")
        for key, value in idx.items():
            if value is not None:
                print(f"  {key}: {value} ('{headers[value]}')")
            else:
                print(f"  {key}: NOT FOUND")
        
        self.clear()
        rows_added = 0
        
        for i, row in enumerate(rows[1:], start=1):  # Skip header row
            print(f"\n--- Processing row {i} ---")
            
            # Skip empty rows
            if not row or all(not cell or str(cell).strip() == "" for cell in row):
                print("  Skipping empty row")
                continue
            
            # Create row data with sensible defaults
            row_data = {
                "no": i,
                "name_of_deductor": "",
                "tan_of_deductor": "TAN_NOT_FOUND",
                "permanent_account_number_pan": "",
                "name_of_assessee": "",
                "financial_year": self.financial_year or "",
                "assessment_year": "",
                "statement_type": "Form 26AS",
                "total_amount_paid_credited": 0.0,
                "total_tax_deducted": 0.0,
                "total_tds_deposited": 0.0,
                "address_of_assessee": "",
                "section": "",
                "transaction_date": frappe.utils.nowdate(),
                "date_of_booking": frappe.utils.nowdate(),
                "amount_paid_credited": 0.0,
                "tax_deducted": 0.0,
                "tds_deposited": 0.0,
                "remarks": "",
            }
            
            # Fill data from row using column indices
            for key, col_idx in idx.items():
                if col_idx is not None and col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        value_str = str(value).strip()
                        
                        if not value_str:
                            continue
                        
                        print(f"  Processing {key}: '{value_str}'")
                        
                        # Handle different field types
                        if key == "deductor":
                            row_data["name_of_deductor"] = value_str
                        elif key == "tan":
                            if value_str and value_str != "TAN_NOT_FOUND":
                                row_data["tan_of_deductor"] = value_str
                        elif key == "pan":
                            row_data["permanent_account_number_pan"] = value_str
                        elif key == "assessee":
                            row_data["name_of_assessee"] = value_str
                        elif key == "financial_year":
                            row_data["financial_year"] = value_str
                        elif key == "assessment_year":
                            row_data["assessment_year"] = value_str
                        elif key == "section":
                            row_data["section"] = value_str
                        elif key == "txn_date":
                            # Try to parse date from common formats
                            date_value = self.parse_date(value_str)
                            if date_value:
                                row_data["transaction_date"] = date_value
                        elif key == "booking_date":
                            date_value = self.parse_date(value_str)
                            if date_value:
                                row_data["date_of_booking"] = date_value
                        elif key == "total_amount":
                            try:
                                val = value_str.replace(',', '')
                                row_data["total_amount_paid_credited"] = flt(val) if val else 0.0
                            except:
                                pass
                        elif key == "total_tax":
                            try:
                                val = value_str.replace(',', '')
                                row_data["total_tax_deducted"] = flt(val) if val else 0.0
                            except:
                                pass
                        elif key == "total_tds":
                            try:
                                val = value_str.replace(',', '')
                                row_data["total_tds_deposited"] = flt(val) if val else 0.0
                            except:
                                pass
                        elif key == "amount":
                            try:
                                val = value_str.replace(',', '')
                                row_data["amount_paid_credited"] = flt(val) if val else 0.0
                                # Also set total amount if not already set
                                if row_data["total_amount_paid_credited"] == 0.0:
                                    row_data["total_amount_paid_credited"] = row_data["amount_paid_credited"]
                            except:
                                pass
                        elif key == "tax":
                            try:
                                val = value_str.replace(',', '')
                                row_data["tax_deducted"] = flt(val) if val else 0.0
                                if row_data["total_tax_deducted"] == 0.0:
                                    row_data["total_tax_deducted"] = row_data["tax_deducted"]
                            except:
                                pass
                        elif key == "tds":
                            try:
                                val = value_str.replace(',', '')
                                row_data["tds_deposited"] = flt(val) if val else 0.0
                                if row_data["total_tds_deposited"] == 0.0:
                                    row_data["total_tds_deposited"] = row_data["tds_deposited"]
                            except:
                                pass
                        elif key == "remarks":
                            row_data["remarks"] = value_str
            
            # Calculate assessment year if not provided
            if not row_data["assessment_year"] and row_data["financial_year"]:
                try:
                    # Financial year format: 2025-26 or 2025-2026
                    parts = row_data["financial_year"].split('-')
                    if len(parts) >= 2:
                        start_year = int(parts[0])
                        # Handle both 2-digit and 4-digit year formats
                        if len(parts[1]) == 2:
                            row_data["assessment_year"] = f"{start_year + 1}-{str(start_year + 2)[-2:]}"
                        else:
                            end_year = int(parts[1])
                            row_data["assessment_year"] = f"{end_year}-{str(end_year + 1)[-2:]}"
                except:
                    pass
            
            # Ensure dates are valid
            if not self.is_valid_date(row_data["transaction_date"]):
                row_data["transaction_date"] = frappe.utils.nowdate()
            
            if not self.is_valid_date(row_data["date_of_booking"]):
                row_data["date_of_booking"] = row_data["transaction_date"]
            
            print(f"  Extracted data: Section={row_data['section']}, Date={row_data['transaction_date']}, Amount={row_data['amount_paid_credited']}")
            
            # Only add if we have at least some data
            if row_data["section"] or row_data["amount_paid_credited"] != 0.0 or row_data["tax_deducted"] != 0.0:
                self.append("table_qmbr", row_data)
                rows_added += 1
                print(f"  ✓ Added to table_qmbr (total: {rows_added})")
            else:
                print(f"  ✗ Skipped - no valid data")
        
        print(f"\n" + "="*60)
        print(f"PROCESSING COMPLETE")
        print(f"Added {rows_added} rows to table_qmbr")
        print("="*60)
        
        if not self.table_qmbr:
            frappe.msgprint(
                "PDF parsed but no transaction data was extracted. "
                "This could be because all amounts are zero or the PDF format is not recognized.",
                alert=True
            )
    
    def parse_date(self, date_str):
        """Parse date from string using common formats"""
        if not date_str:
            return None
        
        date_str = str(date_str).strip()
        
        # Skip if it looks like a header
        if any(keyword in date_str.lower() for keyword in ['date', 'transaction', 'booking']):
            return None
        
        # Common date formats in Form 26AS
        date_formats = [
            '%d-%b-%Y',    # 30-Sep-2025
            '%d/%b/%Y',    # 30/Sep/2025
            '%d-%m-%Y',    # 30-09-2025
            '%d/%m/%Y',    # 30/09/2025
            '%Y-%m-%d',    # 2025-09-30
            '%d.%m.%Y',    # 30.09.2025
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except:
                continue
        
        # If we get here, try to parse with fuzzy logic
        try:
            # Try to extract date parts
            import re
            # Look for patterns like 30-Sep-2025
            match = re.search(r'(\d{1,2})[-/\.](\w{3})[-/\.](\d{4})', date_str, re.IGNORECASE)
            if match:
                day, month_str, year = match.groups()
                month_dict = {
                    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                }
                month = month_dict.get(month_str.lower()[:3])
                if month:
                    return f"{year}-{month:02d}-{int(day):02d}"
        except:
            pass
        
        return None
    
    def is_valid_date(self, date_str):
        """Check if a string is a valid date in YYYY-MM-DD format"""
        if not date_str:
            return False
        
        try:
            datetime.strptime(str(date_str), '%Y-%m-%d')
            return True
        except:
            return False
        





    def normalize_pdf_row(self, row):
        """
        Normalizes Form 26AS PART-I transaction rows to:
        [Sr, Section, Txn Date, Status, Booking Date, Remarks, Amount, Tax, TDS]
        """
        row = [str(c).strip() if c else "" for c in row]

        # Remove leading empty column after Sr No (very common in TRACES PDFs)
        if len(row) > 1 and row[1] == "":
            row.pop(1)

        # Remove extra empties anywhere
        row = [c for c in row if c != ""]

        # Pad to fixed length
        while len(row) < 9:
            row.append("")

        return row[:9]



        