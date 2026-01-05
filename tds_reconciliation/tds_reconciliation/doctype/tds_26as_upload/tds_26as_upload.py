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


    def before_validate(self):
        if self.is_new():
            self._should_parse = True
            return

        old_file = frappe.db.get_value(
            self.doctype,
            self.name,
            "form_26as_file"
        )

        self._should_parse = (old_file != self.form_26as_file)



    # --------------------------------------------------
    # VALIDATE
    # --------------------------------------------------
    def validate(self):
        if not self.form_26as_file:
            frappe.throw("Please attach Form 26AS file.")

        if not getattr(self, "_should_parse", False):
            return  # ✅ No file change → do nothing

        # ✅ File changed → reset + parse
        self.clear()

        path = self.get_file_path()
        ext = os.path.splitext(path)[1].lower()

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

    # def normalize_header(self, h):
    #     return str(h).strip().lower()


    def normalize_header(self, h):
        return (
            str(h)
            .strip()
            .lower()
            .replace(" / ", "/")
            .replace("  ", " ")
        )


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
            lines = [l.rstrip("\n") for l in f if l.strip()]

        # Detect delimiter
        if "|" in lines[0]:
            delimiter = "|"
        elif "\t" in lines[0]:
            delimiter = "\t"
        else:
            delimiter = ","

        rows = []

        for line in lines:
            # IMPORTANT: strip each column individually
            # cols = [c.strip() for c in line.split(delimiter)]
            cols = [c.strip() for c in line.split(delimiter) if c.strip()]

            rows.append(cols)

        self.process_rows(rows)


    # --------------------------------------------------
    # PDF - SIMPLIFIED VERSION
    # --------------------------------------------------
    def parse_pdf(self):
        import pdfplumber
        import re

        # Extract all text from PDF
        all_text = ""
        with pdfplumber.open(self.get_file_path()) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"

        if not all_text:
            frappe.throw("No text could be extracted from the PDF. Please check the file.")

        # Extract header info with regex
        extracted_info = {}

        pan_match = re.search(r'Permanent Account Number \(PAN\)\s*([A-Z0-9]{10})', all_text, re.IGNORECASE)
        if pan_match:
            extracted_info['pan'] = pan_match.group(1).strip()

        # name_match = re.search(r'Name of Assessee\s*([\w\s]+)', all_text, re.IGNORECASE)
        # if name_match:
        #     extracted_info['assessee_name'] = name_match.group(1).strip()

        name_match = re.search(
            r'Name of Assessee\s*([A-Z\s]+?)(?=Address of Assessee|Permanent Account Number|\n)',
            all_text,
            re.IGNORECASE
        )
        if name_match:
            extracted_info['assessee_name'] = name_match.group(1).strip()

        address_match = re.search(r'Address of Assessee\s*([\w\s,]+?)\s*\d{6}', all_text, re.IGNORECASE)
        if address_match:
            extracted_info['address'] = address_match.group(1).strip()

        fy_match = re.search(r'Financial Year\s*(\d{4}-\d{2})', all_text, re.IGNORECASE)
        if fy_match:
            extracted_info['financial_year'] = fy_match.group(1).strip()
        else:
            extracted_info['financial_year'] = self.financial_year or ""

        ay_match = re.search(r'Assessment Year\s*(\d{4}-\d{2})', all_text, re.IGNORECASE)
        if ay_match:
            extracted_info['assessment_year'] = ay_match.group(1).strip()

        # Extract deductors with regex (assuming one or more)
        deductors = []
        deductor_pattern = r'(\d+)\s+([A-Z0-9.\s]+?)\s+([A-Z]{4}\d{5}[A-Z])\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)'
        for match in re.finditer(deductor_pattern, all_text):
            sr, name, tan, total_amount, total_tax, total_tds = match.groups()
            deductors.append({
                'name': name.strip(),
                'tan': tan.strip(),
                'total_amount': total_amount.strip(),
                'total_tax': total_tax.strip(),
                'total_tds': total_tds.strip()
            })

        if not deductors:
            deductors.append({
                'name': 'UNKNOWN',
                'tan': 'TAN_NOT_FOUND',
                'total_amount': '0.00',
                'total_tax': '0.00',
                'total_tds': '0.00'
            })

        # Extract transactions with regex
        transactions = []
        transaction_pattern = r'(\d+)\s+(\d{3})\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+(F)\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+(-)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)'
        for match in re.finditer(transaction_pattern, all_text):
            sr, section, txn_date, status, booking_date, remarks, amount, tax, tds = match.groups()
            transactions.append({
                'section': section,
                'transaction_date': txn_date,
                'status': status,
                'booking_date': booking_date,
                'remarks': remarks,
                'amount': amount.replace(',', ''),
                'tax': tax.replace(',', ''),
                'tds': tds.replace(',', '')
            })

        if not transactions:
            frappe.throw("No transaction data found in PDF. Please check if the PDF contains Form 26AS data.")

        # Use the first deductor (simple assumption)
        default_deductor = deductors[0]

        # Create processed rows
        processed_rows = []

        # Headers
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

        # Add rows for each transaction
        for txn in transactions:
            row = [
                default_deductor['name'],
                default_deductor['tan'],
                default_deductor['total_amount'],
                default_deductor['total_tax'],
                default_deductor['total_tds'],
                txn['section'],
                txn['transaction_date'],
                txn['status'],
                txn['booking_date'],
                txn['remarks'],
                txn['amount'],
                txn['tax'],
                txn['tds'],
                extracted_info.get('pan', ''),
                extracted_info.get('assessee_name', ''),
                extracted_info.get('financial_year', ''),
                extracted_info.get('assessment_year', ''),
                extracted_info.get('address', ''),
                "Form 26AS"
            ]
            processed_rows.append(row)

        # Process the rows
        self.process_rows(processed_rows)

    # --------------------------------------------------
    # CORE PROCESSOR - SIMPLIFIED VERSION
    # --------------------------------------------------
    def process_rows(self, rows):
        if len(rows) < 2:
            frappe.throw("File has no data")

        headers = [self.normalize_header(h) for h in rows[0]]

        # def col(*names):
        #     for n in names:
        #         n_lower = n.lower()
        #         for i, header in enumerate(headers):
        #             if n_lower in header:
        #                 return i
        #     return None

        def col(*names, exclude_total=False):
            for n in names:
                n_lower = n.lower()
                for i, header in enumerate(headers):
                    if exclude_total and "total" in header:
                        continue  # Skip headers containing "total"
                    if n_lower in header:
                        return i
            return None


        # idx = {
        #     "deductor": col("name of deductor"),
        #     "tan": col("tan of deductor"),
        #     "pan": col("permanent account number"),
        #     "assessee": col("name of assessee"),
        #     "financial_year": col("financial year"),
        #     "assessment_year": col("assessment year"),

        #     "total_amount": col("total amount paid", "total amount paid/ credited"),
        #     "total_tax": col("total tax deducted"),
        #     "total_tds": col("total tds deposited"),
        #     "section": col("section"),
        #     "txn_date": col("transaction date"),
        #     "booking_date": col("date of booking"),
        #     "remarks": col("remarks"),
            
        #     "amount": col("amount paid", "amount paid/ credited"),
        #     "tax": col("tax deducted"),
        #     "tds": col("tds deposited"),
        # }

        idx = {
            "deductor": col("name of deductor"),
            "tan": col("tan of deductor"),
            "pan": col("permanent account number"),
            "assessee": col("name of assessee"),
            "financial_year": col("financial year"),
            "assessment_year": col("assessment year"),

            "total_amount": col("total amount paid", "total amount paid/ credited"),
            "total_tax": col("total tax deducted"),
            "total_tds": col("total tds deposited"),
            "section": col("section"),
            "txn_date": col("transaction date"),
            "booking_date": col("date of booking"),
            "remarks": col("remarks"),
            
            # FIX: Search for more specific patterns that DON'T include "total"
            # "amount": col("amount paid/ credited", "amount paid"),  # Reversed order - more specific first
            # "tax": col("tax deducted"),  # This will now match ONLY "Tax Deducted", not "Total Tax Deducted"
            # "tds": col("tds deposited"),  # This will now match ONLY "TDS Deposited", not "Total TDS Deposited"

            "address": col("address of assessee"),


            "amount": col("amount paid", "amount paid/ credited", exclude_total=True),
            "tax": col("tax deducted", exclude_total=True),
            "tds": col("tds deposited", exclude_total=True),
        }

        self.clear()

        for i, row in enumerate(rows[1:], start=1):  # Skip header
            # Skip empty rows
            if not any(row):
                continue

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

            for key, col_idx in idx.items():
                if col_idx is not None and col_idx < len(row):
                    value_str = str(row[col_idx]).strip()
                    if not value_str:
                        continue

                    if key == "deductor":
                        row_data["name_of_deductor"] = value_str
                    elif key == "tan":
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
                        date_value = self.parse_date(value_str)
                        if date_value:
                            row_data["transaction_date"] = date_value
                    elif key == "booking_date":
                        date_value = self.parse_date(value_str)
                        if date_value:
                            row_data["date_of_booking"] = date_value
                    elif key == "total_amount":
                        val = value_str.replace(',', '')
                        row_data["total_amount_paid_credited"] = flt(val) if val else 0.0
                    elif key == "total_tax":
                        val = value_str.replace(',', '')
                        row_data["total_tax_deducted"] = flt(val) if val else 0.0
                    elif key == "total_tds":
                        val = value_str.replace(',', '')
                        row_data["total_tds_deposited"] = flt(val) if val else 0.0
                    
                    elif key == "address":
                        row_data["address_of_assessee"] = value_str                    

                    # elif key == "amount":
                    #     val = value_str.replace(',', '')
                    #     row_data["amount_paid_credited"] = flt(val) if val else 0.0
                    #     if row_data["total_amount_paid_credited"] == 0.0:
                    #         row_data["total_amount_paid_credited"] = row_data["amount_paid_credited"]
                    # elif key == "tax":
                    #     val = value_str.replace(',', '')
                    #     row_data["tax_deducted"] = flt(val) if val else 0.0
                    #     if row_data["total_tax_deducted"] == 0.0:
                    #         row_data["total_tax_deducted"] = row_data["tax_deducted"]
                    # elif key == "tds":
                    #     val = value_str.replace(',', '')
                    #     row_data["tds_deposited"] = flt(val) if val else 0.0
                    #     if row_data["total_tds_deposited"] == 0.0:
                    #         row_data["total_tds_deposited"] = row_data["tds_deposited"]
                    # elif key == "remarks":
                    #     row_data["remarks"] = value_str


                    # elif key == "amount":
                    #     val = value_str.replace(',', '')
                    #     row_data["amount_paid_credited"] = flt(val) if val else 0.0
                    #     if row_data["amount_paid_credited"] == 0.0:
                    #         row_data["amount_paid_credited"] = row_data["amount_paid_credited"]
                    # elif key == "tax":
                    #     val = value_str.replace(',', '')
                    #     row_data["tax_deducted"] = flt(val) if val else 0.0
                    #     if row_data["tax_deducted"] == 0.0:
                    #         row_data["tax_deducted"] = row_data["tax_deducted"]
                    # elif key == "tds":
                    #     val = value_str.replace(',', '')
                    #     row_data["tds_deposited"] = flt(val) if val else 0.0
                    #     if row_data["tds_deposited"] == 0.0:
                    #         row_data["tds_deposited"] = row_data["tds_deposited"]
                    # elif key == "remarks":
                    #     row_data["remarks"] = value_str


                # elif key == "amount":
                #     val = value_str.replace(',', '')
                #     row_data["amount_paid_credited"] = flt(val) if val else 0.0
                    elif key == "amount":
                        print("DEBUG AMOUNT → raw value_str:", repr(value_str))
                        val = value_str.replace(',', '')
                        print("DEBUG AMOUNT → parsed val:", val)
                        row_data["amount_paid_credited"] = flt(val) if val else 0.0


                    elif key == "tax":
                        val = value_str.replace(',', '')
                        row_data["tax_deducted"] = flt(val) if val else 0.0

                    elif key == "tds":
                        val = value_str.replace(',', '')
                        row_data["tds_deposited"] = flt(val) if val else 0.0

                    elif key == "remarks":
                        row_data["remarks"] = value_str


            # Calculate assessment year if missing
            if not row_data["assessment_year"] and row_data["financial_year"]:
                try:
                    parts = row_data["financial_year"].split('-')
                    start_year = int(parts[0])
                    row_data["assessment_year"] = f"{start_year + 1}-{str(start_year + 2)[-2:]}"
                except:
                    pass

            # Default dates
            if not self.is_valid_date(row_data["transaction_date"]):
                row_data["transaction_date"] = frappe.utils.nowdate()
            if not self.is_valid_date(row_data["date_of_booking"]):
                row_data["date_of_booking"] = row_data["transaction_date"]

            # Add if valid data
            if row_data["amount_paid_credited"] != 0.0 or row_data["tax_deducted"] != 0.0 or row_data["section"]:
                self.append("table_qmbr", row_data)

        if not self.table_qmbr:
            frappe.msgprint(
                "PDF parsed but no transaction data was extracted. "
                "This could be because all amounts are zero or the PDF format is not recognized.",
                alert=True
            )

    def parse_date(self, date_str):
        if not date_str:
            return None

        date_str = str(date_str).strip()
        date_formats = [
            '%d-%b-%Y',
            '%d/%b/%Y',
            '%d-%m-%Y',
            '%d/%m/%Y',
            '%Y-%m-%d',
            '%d.%m.%Y',
        ]

        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue

        return None

    
    def is_valid_date(self, date_str):
        if not date_str:
            return False
        try:
            datetime.strptime(str(date_str), '%Y-%m-%d')
            return True
        except ValueError:
            return False
        


    def compare_with_other_tax(self, other_docname):
        other_doc = frappe.get_doc("OtherTaxDoctype", other_docname)

        # Clear old mismatches for this upload
        frappe.db.delete(
            "TDS26ASData",
            {"reference_26as": self.name}
        )

        # Build lookup for Other Tax file
        other_map = {}

        for row in other_doc.table_other_tax:
            key = (
                row.pan,
                row.tan,
                row.section,
                row.transaction_date
            )
            other_map[key] = row

        # Compare with 26AS rows
        for row in self.table_qmbr:
            key = (
                row.permanent_account_number_pan,
                row.tan_of_deductor,
                row.section,
                row.transaction_date
            )

            other_row = other_map.get(key)

            if not other_row:
                self.create_mismatch(
                    row, None, "Missing in Other File"
                )
                continue

            # Amount mismatch
            if flt(row.amount_paid_credited) != flt(other_row.amount):
                self.create_mismatch(
                    row, other_row, "Amount Mismatch"
                )

            # TDS mismatch
            if flt(row.tds_deposited) != flt(other_row.tds):
                self.create_mismatch(
                    row, other_row, "TDS Mismatch"
                )

        # Check rows present in Other file but missing in 26AS
        self_keys = {
            (
                r.permanent_account_number_pan,
                r.tan_of_deductor,
                r.section,
                r.transaction_date
            )
            for r in self.table_qmbr
        }

        for key, other_row in other_map.items():
            if key not in self_keys:
                self.create_mismatch(
                    None, other_row, "Missing in 26AS"
                )
    


#------------------------------------------------------------------

#  creatin Entry in the TDS 26AS Entry 

#------------------------------------------------------------------

    def on_submit(self):
        self.create_26as_entries()



    def create_26as_entries(self):
        # Remove old entries if re-uploaded
        frappe.db.delete(
            "TDS 26AS Entry",
            {"upload_ref": self.name}
        )

        for row in self.table_qmbr:
            frappe.get_doc({
                "doctype": "TDS 26AS Entry",
                "upload_ref": self.name,

                "pan": row.permanent_account_number_pan,
                "tan": row.tan_of_deductor,
                "deductor_name": row.name_of_deductor,
                "assessee_name": row.name_of_assessee,

                "section": row.section,
                "transaction_date": row.transaction_date,
                "booking_date": row.date_of_booking,

                "amount_paid": row.amount_paid_credited,
                "tax_deducted": row.tax_deducted,
                "tds_deposited": row.tds_deposited,

                "financial_year": row.financial_year,
                "assessment_year": row.assessment_year,

                "status": "Unprocessed",
                "matched": 0
            }).insert(ignore_permissions=True)
