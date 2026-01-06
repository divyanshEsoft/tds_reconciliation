# Copyright (c) 2026, Divyansh
# License: see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, add_days
from collections import defaultdict


class TDSVsGLReconciliation(Document):

    # =========================================================
    # MAIN ENTRY POINT
    # =========================================================
    @frappe.whitelist()
    def generate_reconciliation(self):

        print("\n" + "=" * 70)
        print("STARTING TDS vs GL RECONCILIATION")
        print("=" * 70)

        # -----------------------------
        # Validations
        # -----------------------------
        if not self.company:
            frappe.throw("Company is mandatory")

        if not self.from_date or not self.to_date:
            frappe.throw("From Date and To Date are mandatory")

        if not self.tds_account:
            frappe.throw("TDS Account is mandatory")

        print(f"Company     : {self.company}")
        print(f"Date Range  : {self.from_date} → {self.to_date}")
        print(f"TDS Account : {self.tds_account}")
        print(f"PAN Filter  : {self.pan or 'ALL'}")

        # -----------------------------
        # Clear old rows
        # -----------------------------
        self.set("tds_vs_gl_reconciliation_detail", [])

        # -----------------------------
        # Fetch 26AS Entries
        # -----------------------------
        tds_rows = self.get_26as_entries()
        print(f"26AS Entries Found : {len(tds_rows)}")

        # -----------------------------
        # Fetch GL Entries
        # -----------------------------
        gl_rows = self.get_gl_entries()
        print(f"GL Entries Found : {len(gl_rows)}")

        # -----------------------------
        # Group GL by PAN + Date
        # -----------------------------
        gl_map = defaultdict(list)
        for gl in gl_rows:
            key = (gl["pan"], gl["date"])
            gl_map[key].append(gl)

        used_gl_keys = set()

        # =====================================================
        # MATCHING LOGIC
        # =====================================================
        print("\n--- MATCHING 26AS → GL (PAN + ±5 DAYS) ---")

        for tds in tds_rows:

            matched = False
            matched_gls = []

            for (pan, gl_date), gl_list in gl_map.items():

                if pan != tds["pan"]:
                    continue

                if not self.date_within_range(tds["date"], gl_date, 5):
                    continue

                total_gl_amount = sum(flt(g["amount"]) for g in gl_list)

                diff = flt(tds["tds"]) - total_gl_amount

                if abs(diff) <= 1:
                    matched = True
                    matched_gls = gl_list
                    used_gl_keys.add((pan, gl_date))
                    break

            if matched:
                print(
                    f"MATCH FOUND | PAN {tds['pan']} | "
                    f"26AS {tds['tds']} | GL SUM {total_gl_amount} | "
                    f"Date {tds['date']}"
                )

                for gl in matched_gls:
                    self.add_row(
                        tds=tds,
                        gl=gl,
                        status="Matched",
                        reason=""
                    )

            else:
                print(
                    f"NO GL MATCH | PAN {tds['pan']} | "
                    f"26AS {tds['tds']} | Date {tds['date']}"
                )

                self.add_row(
                    tds=tds,
                    gl=None,
                    status="Missing in GL",
                    reason="Present in 26AS but not found in GL"
                )

        # -----------------------------
        # GL entries missing in 26AS
        # -----------------------------
        for (pan, gl_date), gl_list in gl_map.items():
            if (pan, gl_date) in used_gl_keys:
                continue

            for gl in gl_list:
                self.add_row(
                    tds=None,
                    gl=gl,
                    status="Missing in 26AS",
                    reason="Present in GL but not found in 26AS"
                )

        # -----------------------------
        # Finalize
        # -----------------------------
        self.calculate_status()
        self.save(ignore_permissions=True)
        frappe.db.commit()

        print("\n--- SUMMARY ---")
        print("26AS Rows  :", len(tds_rows))
        print("GL Rows    :", len(gl_rows))
        print("Child Rows:", len(self.tds_vs_gl_reconciliation_detail))
        print("STATUS    :", self.status)

        print("=" * 70)
        print("RECONCILIATION COMPLETED")
        print("=" * 70)

        frappe.msgprint(
            f"Reconciliation completed<br>"
            f"26AS Rows: {len(tds_rows)}<br>"
            f"GL Rows: {len(gl_rows)}<br>"
            f"Status: <b>{self.status}</b>"
        )

    # =========================================================
    # DATE TOLERANCE
    # =========================================================
    def date_within_range(self, d1, d2, tolerance_days=5):
        return add_days(d1, -tolerance_days) <= d2 <= add_days(d1, tolerance_days)

    # =========================================================
    # FETCH 26AS ENTRIES
    # =========================================================
  
    # def get_26as_entries(self):

    #     filters = {
    #         "transaction_date": ["between", [self.from_date, self.to_date]]
    #     }

    #     if self.pan:
    #         filters["pan"] = self.pan

    #     data = frappe.get_all(
    #         "TDS 26AS Entry",
    #         filters=filters,
    #         fields=[
    #             "name",
    #             "pan",
    #             "tan",
    #             "deductor_name",
    #             "transaction_date",
    #             "tds_deposited"
    #         ],
    #         order_by="transaction_date"
    #     )

    #     return [{
    #         "ref": d.name,
    #         "pan": (d.pan or "").strip(),
    #         "tan": (d.tan or "").strip(),
    #         "name": d.deductor_name,
    #         "date": d.transaction_date,
    #         "tds": flt(d.tds_deposited)
    #     } for d in data]


    def get_26as_entries(self):

        filters = {
            "transaction_date": ["between", [self.from_date, self.to_date]],
            "tds_deposited": [">", 0]   # 🔥 CRITICAL FIX
        }

        if self.pan:
            filters["pan"] = self.pan

        data = frappe.get_all(
            "TDS 26AS Entry",
            filters=filters,
            fields=[
                "name",
                "pan",
                "tan",
                "deductor_name",
                "transaction_date",
                "tds_deposited"
            ],
            order_by="transaction_date"
        )

        print("\n--- VALID 26AS ROWS (TDS > 0) ---")
        for d in data:
            print(d.name, d.pan, d.transaction_date, d.tds_deposited)

        return [{
            "ref": d.name,
            "pan": (d.pan or "").strip(),
            "tan": (d.tan or "").strip(),
            "name": d.deductor_name,
            "date": d.transaction_date,
            "tds": flt(d.tds_deposited)
        } for d in data]



    # =========================================================
    # FETCH GL ENTRIES (PROVEN JOIN LOGIC)
    # =========================================================
    def get_gl_entries(self):

        print("\n--- FETCHING GL ENTRIES ---")
        print("Company :", self.company)
        print("Account :", self.tds_account)
        print("PAN     :", self.pan or "ALL")

        rows = frappe.db.sql("""
            SELECT
                gle.name            AS gl_entry,
                gle.posting_date,
                gle.voucher_type,
                gle.voucher_no      AS payment_entry,

                per.reference_name  AS sales_invoice,
                si.customer,
                c.pan,

                gle.debit,
                gle.credit

            FROM `tabGL Entry` gle

            JOIN `tabPayment Entry` pe
                ON pe.name = gle.voucher_no

            JOIN `tabPayment Entry Reference` per
                ON per.parent = pe.name
               AND per.reference_doctype = 'Sales Invoice'

            JOIN `tabSales Invoice` si
                ON si.name = per.reference_name

            JOIN `tabCustomer` c
                ON c.name = si.customer

            WHERE gle.company = %s
              AND gle.account = %s
              AND gle.is_cancelled = 0
              AND (%s IS NULL OR c.pan = %s)

            ORDER BY gle.posting_date, gle.name
        """, (
            self.company,
            self.tds_account,
            self.pan,
            self.pan
        ), as_dict=True)

        print(f"RAW ROWS FETCHED : {len(rows)}")

        result = []
        for r in rows:
            amount = flt(r.debit) if flt(r.debit) > 0 else flt(r.credit)

            print(
                "GL:", r.gl_entry,
                "| Date:", r.posting_date,
                "| PAN:", r.pan,
                "| Amount:", amount
            )

            result.append({
                "voucher_no": r.payment_entry,
                "voucher_type": r.voucher_type,
                "date": r.posting_date,
                "amount": amount,
                "customer": r.customer,
                "pan": r.pan
            })

        return result

    # =========================================================
    # ADD CHILD ROW
    # =========================================================
    def add_row(self, tds=None, gl=None, status="", reason=""):

        row = self.append("tds_vs_gl_reconciliation_detail", {})

        if tds:
            row.pan = tds["pan"]
            row.tan = tds["tan"]
            row.deductor_name = tds["name"]
            row.posting_date = tds["date"]
            row.as26_amount = tds["tds"]
            row.as26_reference = tds["ref"]

        if gl:
            row.gl_voucher_no = gl["voucher_no"]
            row.gl_voucher_type = gl["voucher_type"]
            row.gl_amount = gl["amount"]

        row.difference = flt(row.as26_amount or 0) - flt(row.gl_amount or 0)
        row.match_status = status
        row.mismatch_reason = reason

    # =========================================================
    # CALCULATE PARENT STATUS
    # =========================================================
    def calculate_status(self):

        details = self.get("tds_vs_gl_reconciliation_detail") or []

        if not details:
            self.status = "Draft"
            return

        for row in details:
            if row.match_status != "Matched":
                self.status = "Mismatch"
                return

        self.status = "Matched"




# import frappe
# from frappe.model.document import Document
# from frappe.utils import flt


# class TDSVsGLReconciliation(Document):

#     @frappe.whitelist()
#     def generate_reconciliation(self):

#         # Clear old rows
#         self.set("tds_vs_gl_reconciliation_detail", [])

#         print("\n===== USER INPUT VALUES =====")
#         print("Company        :", self.company)
#         print("Financial Year :", self.financial_year)
#         print("From Date      :", self.from_date)
#         print("To Date        :", self.to_date)
#         print("TDS Account    :", self.tds_account)

#         # Fetch data
#         tds_rows = self.get_26as_entries()
#         gl_map = self.get_gl_entries()

#         matched_keys = set()

#         # Compare 26AS → GL
#         for tds in tds_rows:
#             key = self.make_key(tds)

#             print("\n===== COMPARISON =====")
#             print("26AS KEY :", key)

#             gl = gl_map.get(key)
#             print("GL VALUE :", gl)

#             if gl:
#                 matched_keys.add(key)

#                 diff = flt(tds["tds"]) - flt(gl["amount"])
#                 status = "Matched" if diff == 0 else "Amount Mismatch"

#                 self.add_row(
#                     tds=tds,
#                     gl=gl,
#                     status=status,
#                     reason="" if diff == 0 else "Amount differs"
#                 )
#             else:
#                 self.add_row(
#                     tds=tds,
#                     gl=None,
#                     status="Missing in GL",
#                     reason="Present in 26AS but missing in GL"
#                 )

#         # GL entries not found in 26AS
#         for key, gl in gl_map.items():
#             if key not in matched_keys:
#                 self.add_row(
#                     tds=None,
#                     gl=gl,
#                     status="Missing in 26AS",
#                     reason="Present in GL but missing in 26AS"
#                 )

#         self.calculate_status()
#         self.save()

#     # ---------------------------------------------------------------------

#     def make_key(self, row):
#         """
#         TEMP KEY (PHASE-1)
#         PAN / TAN intentionally excluded
#         """
#         return (
#             row.get("date"),
#             flt(row.get("tds"))
#         )

#     # ---------------------------------------------------------------------

#     # def get_26as_entries(self):

#     #     filters = {
#     #         "financial_year": self.financial_year
#     #     }

#     #     data = frappe.get_all(
#     #         "TDS 26AS Entry",
#     #         filters=filters,
#     #         fields=[
#     #             "name",
#     #             "pan",
#     #             "tan",
#     #             "deductor_name",
#     #             "transaction_date",
#     #             "tds_deposited"
#     #         ]
#     #     )

#     #     print("\n--- RAW 26AS RECORDS ---")
#     #     for d in data:
#     #         print(d)

#     #     result = [{
#     #         "ref": d.name,
#     #         "pan": d.pan,
#     #         "tan": d.tan,
#     #         "name": d.deductor_name,
#     #         "date": d.transaction_date,
#     #         "tds": flt(d.tds_deposited)
#     #     } for d in data]

#     #     print("\n--- PROCESSED 26AS DATA ---")
#     #     for r in result:
#     #         print(r)

#     #     return result



#     def get_26as_entries(self):

#         data = frappe.get_all(
#             "TDS 26AS Entry",
#             fields=[
#                 "name",
#                 "pan",
#                 "tan",
#                 "deductor_name",
#                 "transaction_date",
#                 "tds_deposited"
#             ]
#         )

#         print("\n--- RAW 26AS RECORDS ---")
#         for d in data:
#             print(d)

#         result = [{
#             "ref": d.name,
#             "pan": d.pan,
#             "tan": d.tan,
#             "name": d.deductor_name,
#             "date": d.transaction_date,
#             "tds": flt(d.tds_deposited)
#         } for d in data]

#         print("\n--- PROCESSED 26AS DATA ---")
#         for r in result:
#             print(r)

#         return result


#     # ---------------------------------------------------------------------

#     def get_gl_entries(self):

#         print("\n===== FETCHING GL DATA =====")

#         rows = frappe.db.sql("""
#             SELECT
#                 voucher_no,
#                 voucher_type,
#                 posting_date,
#                 debit
#             FROM `tabGL Entry`
#             WHERE
#                 company = %s
#                 AND account = %s
#                 AND posting_date BETWEEN %s AND %s
#                 AND debit > 0
#                 AND is_cancelled = 0
#         """, (
#             self.company,
#             self.tds_account,
#             self.from_date,
#             self.to_date
#         ), as_dict=True)

#         print("\n--- RAW GL ROWS ---")
#         for r in rows:
#             print(r)

#         gl_map = {}

#         for r in rows:
#             key = (
#                 r.posting_date,
#                 flt(r.debit)
#             )

#             print("GL KEY CREATED :", key)

#             gl_map[key] = {
#                 "voucher_no": r.voucher_no,
#                 "voucher_type": r.voucher_type,
#                 "date": r.posting_date,
#                 "amount": flt(r.debit)
#             }

#         print("\n--- FINAL GL MAP ---")
#         for k, v in gl_map.items():
#             print("KEY :", k, "VAL :", v)

#         return gl_map

#     # ---------------------------------------------------------------------

#     def add_row(self, tds=None, gl=None, status=None, reason=None):

#         row = self.append("tds_vs_gl_reconciliation_detail", {})

#         if tds:
#             row.pan = tds.get("pan")
#             row.tan = tds.get("tan")
#             row.deductor_name = tds.get("name")
#             row.posting_date = tds.get("date")
#             row.as26_amount = tds.get("tds")
#             row.as26_ref = tds.get("ref")

#         if gl:
#             row.gl_voucher_no = gl.get("voucher_no")
#             row.gl_voucher_type = gl.get("voucher_type")
#             row.gl_amount = gl.get("amount")

#         row.difference = flt(row.as26_amount) - flt(row.gl_amount)
#         row.match_status = status
#         row.mismatch_reason = reason

#     # ---------------------------------------------------------------------

#     def calculate_status(self):

#         if not self.tds_vs_gl_reconciliation_detail:
#             self.status = "Draft"
#             return

#         mismatch_found = any(
#             row.match_status != "Matched"
#             for row in self.tds_vs_gl_reconciliation_detail
#         )

#         self.status = "Mismatch" if mismatch_found else "Matched"



#=------------------------------------------------------------------------

# to call the buttom we have to add the client script 


# below is the script given 


# frappe.ui.form.on('TDS Vs GL Reconciliation', {
#     generate_reconciliation(frm) {
#         if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
#             frappe.msgprint(__('Please fill Company, From Date and To Date'));
#             return;
#         }

#         frappe.call({
#             doc: frm.doc,
#             method: "generate_reconciliation",
#             freeze: true,
#             callback: function () {
#                 frm.reload_doc();
#                 frappe.msgprint(__('Reconciliation completed'));
#             }
#         });
#     }
# });



#=------------------------------------------------------------------------
