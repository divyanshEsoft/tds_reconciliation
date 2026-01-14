# Copyright (c) 2026, Divyansh
# License: see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt
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
        # Fetch data
        # -----------------------------
        tds_rows = self.get_26as_entries()
        gl_rows = self.get_gl_entries()

        print(f"26AS Entries Found : {len(tds_rows)}")
        print(f"GL Entries Found   : {len(gl_rows)}")

        # -----------------------------
        # Group GL by PAN + MONTH
        # -----------------------------
        gl_map = defaultdict(list)
        for gl in gl_rows:
            key = (gl["pan"], gl["date"].year, gl["date"].month)
            gl_map[key].append(gl)

        used_gl_keys = set()

        # =====================================================
        # MATCHING LOGIC (PAN + MONTH ONLY)
        # =====================================================
        for tds in tds_rows:

            tds_key = (tds["pan"], tds["date"].year, tds["date"].month)
            matched_gls = gl_map.get(tds_key)

            if matched_gls:
                used_gl_keys.add(tds_key)

                for gl in matched_gls:
                    self.add_row(
                        tds=tds,
                        gl=gl,
                        status="Matched",
                        reason="Matched by PAN and Month"
                    )
            else:
                self.add_row(
                    tds=tds,
                    gl=None,
                    status="Missing in GL",
                    reason="No GL entry found for PAN in this month"
                )

        # -----------------------------
        # GL entries missing in 26AS
        # -----------------------------
        for key, gl_list in gl_map.items():
            if key in used_gl_keys:
                continue

            for gl in gl_list:
                self.add_row(
                    tds=None,
                    gl=gl,
                    status="Missing in 26AS",
                    reason="No 26AS entry found for PAN in this month"
                )

        # -----------------------------
        # Calculate overall status
        # -----------------------------
        self.calculate_status()

        # -----------------------------
        # Return data to UI (NO SAVE)
        # -----------------------------
        child_data = []
        for row in self.tds_vs_gl_reconciliation_detail:
            child_data.append({
                "pan": row.pan,
                "tan": row.tan,
                "deductor_name": row.deductor_name,
                "posting_date": row.posting_date,
                "gl_voucher_no": row.gl_voucher_no,
                "gl_voucher_type": row.gl_voucher_type,
                "gl_amount": row.gl_amount,
                "as26_amount": row.as26_amount,
                "difference": row.difference,
                "match_status": row.match_status,
                "mismatch_reason": row.mismatch_reason,
                "as26_reference": row.as26_reference,
                "gl_reference": row.gl_reference
            })

        print("\n--- SUMMARY ---")
        print("26AS Rows  :", len(tds_rows))
        print("GL Rows    :", len(gl_rows))
        print("Child Rows:", len(child_data))
        print("STATUS    :", self.status)

        print("=" * 70)
        print("RECONCILIATION COMPLETED (NOT SAVED)")
        print("=" * 70)

        return {
            "status": self.status,
            "child_rows": child_data,
            "summary": {
                "tds_count": len(tds_rows),
                "gl_count": len(gl_rows),
                "child_count": len(child_data)
            }
        }

    # =========================================================
    # FETCH 26AS ENTRIES
    # =========================================================
    def get_26as_entries(self):

        filters = {
            "transaction_date": ["between", [self.from_date, self.to_date]],
            "tds_deposited": [">", 0]
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

        return [{
            "ref": d.name,
            "pan": (d.pan or "").strip(),
            "tan": (d.tan or "").strip(),
            "name": d.deductor_name,
            "date": d.transaction_date,
            "tds": flt(d.tds_deposited)
        } for d in data]

    # =========================================================
    # FETCH GL ENTRIES
    # =========================================================
    def get_gl_entries(self):

        rows = frappe.db.sql("""
            SELECT
                gle.posting_date,
                gle.voucher_type,
                gle.voucher_no,
                c.pan,
                gle.debit,
                gle.credit
            FROM `tabGL Entry` gle
            JOIN `tabPayment Entry` pe ON pe.name = gle.voucher_no
            JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
            JOIN `tabSales Invoice` si ON si.name = per.reference_name
            JOIN `tabCustomer` c ON c.name = si.customer
            WHERE gle.company = %s
              AND gle.account = %s
              AND gle.is_cancelled = 0
              AND (%s IS NULL OR c.pan = %s)
            ORDER BY gle.posting_date
        """, (
            self.company,
            self.tds_account,
            self.pan,
            self.pan
        ), as_dict=True)

        result = []
        for r in rows:
            amount = flt(r.debit) if flt(r.debit) > 0 else flt(r.credit)
            result.append({
                "voucher_no": r.voucher_no,
                "voucher_type": r.voucher_type,
                "date": r.posting_date,
                "amount": amount,
                "pan": r.pan
            })

        return result

    # =========================================================
    # ADD CHILD ROW
    # =========================================================
    def add_row(self, tds=None, gl=None, status="", reason=""):

        row = self.append("tds_vs_gl_reconciliation_detail", {})

        if tds:
            row.pan = tds.get("pan")
            row.tan = tds.get("tan")
            row.deductor_name = tds.get("name")
            row.posting_date = tds.get("date")
            row.as26_amount = flt(tds.get("tds"))
            row.as26_reference = tds.get("ref")

        if gl:
            row.gl_voucher_no = gl.get("voucher_no")
            row.gl_voucher_type = gl.get("voucher_type")
            row.gl_amount = flt(gl.get("amount"))
            row.gl_reference = gl.get("voucher_no")

        row.difference = flt(row.as26_amount or 0) - flt(row.gl_amount or 0)
        row.match_status = status
        row.mismatch_reason = reason

    # =========================================================
    # CALCULATE STATUS
    # =========================================================
    def calculate_status(self):

        rows = self.get("tds_vs_gl_reconciliation_detail") or []

        if not rows:
            self.status = "Draft"
            return

        for r in rows:
            if r.match_status != "Matched":
                self.status = "Mismatch"
                return

        self.status = "Matched"









# # Copyright (c) 2026, Divyansh
# # License: see license.txt

# import frappe
# from frappe.model.document import Document
# from frappe.utils import flt, add_days
# from collections import defaultdict


# class TDSVsGLReconciliation(Document):

#     AMOUNT_TOLERANCE = 10  # ₹10 tolerance (industry standard)

#     # =========================================================
#     # MAIN ENTRY POINT
#     # =========================================================
#     @frappe.whitelist()
   
#     # def generate_reconciliation(self):
#     #     print("\n" + "=" * 70)
#     #     print("STARTING TDS vs GL RECONCILIATION")
#     #     print("=" * 70)

#     #     # -----------------------------
#     #     # Validations
#     #     # -----------------------------
#     #     if not self.company:
#     #         frappe.throw("Company is mandatory")

#     #     if not self.from_date or not self.to_date:
#     #         frappe.throw("From Date and To Date are mandatory")

#     #     if not self.tds_account:
#     #         frappe.throw("TDS Account is mandatory")

#     #     print(f"Company     : {self.company}")
#     #     print(f"Date Range  : {self.from_date} → {self.to_date}")
#     #     print(f"TDS Account : {self.tds_account}")
#     #     print(f"PAN Filter  : {self.pan or 'ALL'}")

#     #     # -----------------------------
#     #     # Clear old rows
#     #     # -----------------------------
        
#     #     self.set("tds_vs_gl_reconciliation_detail", [])


#     #     # REPLACE WITH

#     #     # self.set("tds_vs_gl_reconciliation_detail", [])
#     #     # self.flags.ignore_validate = True





#     #     # -----------------------------
#     #     # Fetch 26AS Entries
#     #     # -----------------------------
#     #     tds_rows = self.get_26as_entries()
#     #     print(f"26AS Entries Found : {len(tds_rows)}")

#     #     # -----------------------------
#     #     # Fetch GL Entries
#     #     # -----------------------------
#     #     gl_rows = self.get_gl_entries()
#     #     print(f"GL Entries Found : {len(gl_rows)}")

#     #     # -----------------------------
#     #     # Group GL by PAN + DATE
#     #     # -----------------------------
#     #     gl_map = defaultdict(list)
#     #     for gl in gl_rows:
#     #         key = (gl["pan"], gl["date"])
#     #         gl_map[key].append(gl)

#     #     used_gl_keys = set()

#     #     # =====================================================
#     #     # MATCHING LOGIC
#     #     # =====================================================
#     #     print("\n--- MATCHING 26AS → GL (PAN + ±5 DAYS + ₹10 TOLERANCE) ---")

#     #     for tds in tds_rows:

#     #         matched = False
#     #         matched_gls = []

#     #         for (pan, gl_date), gl_list in gl_map.items():

#     #             if pan != tds["pan"]:
#     #                 continue

#     #             if not self.date_within_range(tds["date"], gl_date, 5):
#     #                 continue

#     #             total_gl_amount = sum(flt(g["amount"]) for g in gl_list)
#     #             diff = round(flt(tds["tds"]) - total_gl_amount, 2)

#     #             if abs(diff) <= self.AMOUNT_TOLERANCE:
#     #                 matched = True
#     #                 matched_gls = gl_list
#     #                 used_gl_keys.add((pan, gl_date))
#     #                 break

#     #         if matched:
#     #             print(
#     #                 f"MATCH FOUND | PAN {tds['pan']} | "
#     #                 f"26AS {tds['tds']} | GL SUM {total_gl_amount} | "
#     #                 f"Diff {diff}"
#     #             )

#     #             for gl in matched_gls:
#     #                 self.add_row(
#     #                     tds=tds,
#     #                     gl=gl,
#     #                     status="Matched",
#     #                     reason=""
#     #                 )
#     #         else:
#     #             print(
#     #                 f"NO GL MATCH | PAN {tds['pan']} | "
#     #                 f"26AS {tds['tds']} | Date {tds['date']}"
#     #             )

#     #             self.add_row(
#     #                 tds=tds,
#     #                 gl=None,
#     #                 status="Missing in GL",
#     #                 reason="Present in 26AS but not found in GL"
#     #             )

#     #     # -----------------------------
#     #     # GL entries missing in 26AS
#     #     # -----------------------------
#     #     for (pan, gl_date), gl_list in gl_map.items():
#     #         if (pan, gl_date) in used_gl_keys:
#     #             continue

#     #         for gl in gl_list:
#     #             self.add_row(
#     #                 tds=None,
#     #                 gl=gl,
#     #                 status="Missing in 26AS",
#     #                 reason="Present in GL but not found in 26AS"
#     #             )

#     #     # -----------------------------
#     #     # Finalize
#     #     # -----------------------------
#     #     self.calculate_status()
#     #     self.save(ignore_permissions=True)
#     #     frappe.db.commit()

#     #     print("\n--- SUMMARY ---")
#     #     print("26AS Rows  :", len(tds_rows))
#     #     print("GL Rows    :", len(gl_rows))
#     #     print("Child Rows:", len(self.tds_vs_gl_reconciliation_detail))
#     #     print("STATUS    :", self.status)

#     #     print("=" * 70)
#     #     print("RECONCILIATION COMPLETED")
#     #     print("=" * 70)

#     #     frappe.msgprint(
#     #         f"Reconciliation completed<br>"
#     #         f"26AS Rows: {len(tds_rows)}<br>"
#     #         f"GL Rows: {len(gl_rows)}<br>"
#     #         f"Status: <b>{self.status}</b>"
#     #     )

#     #     return {
#     #         "name": self.name,
#     #         "status": self.status,
#     #         "child_count": len(self.tds_vs_gl_reconciliation_detail)
#     #     }


#     @frappe.whitelist()
#     def generate_reconciliation(self):
#         print("\n" + "=" * 70)
#         print("STARTING TDS vs GL RECONCILIATION")
#         print("=" * 70)

#         # -----------------------------
#         # Validations
#         # -----------------------------
#         if not self.company:
#             frappe.throw("Company is mandatory")

#         if not self.from_date or not self.to_date:
#             frappe.throw("From Date and To Date are mandatory")

#         if not self.tds_account:
#             frappe.throw("TDS Account is mandatory")

#         print(f"Company     : {self.company}")
#         print(f"Date Range  : {self.from_date} → {self.to_date}")
#         print(f"TDS Account : {self.tds_account}")
#         print(f"PAN Filter  : {self.pan or 'ALL'}")

#         # -----------------------------
#         # Clear old rows
#         # -----------------------------
#         self.set("tds_vs_gl_reconciliation_detail", [])
#         # ✅ REMOVED: self.flags.ignore_validate = True

#         # -----------------------------
#         # Fetch 26AS Entries
#         # -----------------------------
#         tds_rows = self.get_26as_entries()
#         print(f"26AS Entries Found : {len(tds_rows)}")

#         # -----------------------------
#         # Fetch GL Entries
#         # -----------------------------
#         gl_rows = self.get_gl_entries()
#         print(f"GL Entries Found : {len(gl_rows)}")

#         # -----------------------------
#         # Group GL by PAN + DATE
#         # -----------------------------
#         gl_map = defaultdict(list)
#         for gl in gl_rows:
#             key = (gl["pan"], gl["date"])
#             gl_map[key].append(gl)

#         used_gl_keys = set()

#         # =====================================================
#         # MATCHING LOGIC
#         # =====================================================
#         print("\n--- MATCHING 26AS → GL (PAN + ±5 DAYS + ₹10 TOLERANCE) ---")

#         for tds in tds_rows:

#             matched = False
#             matched_gls = []

#             for (pan, gl_date), gl_list in gl_map.items():

#                 if pan != tds["pan"]:
#                     continue

#                 if not self.date_within_range(tds["date"], gl_date, 5):
#                     continue

#                 total_gl_amount = sum(flt(g["amount"]) for g in gl_list)
#                 diff = round(flt(tds["tds"]) - total_gl_amount, 2)

#                 if abs(diff) <= self.AMOUNT_TOLERANCE:
#                     matched = True
#                     matched_gls = gl_list
#                     used_gl_keys.add((pan, gl_date))
#                     break


#             print("\n" + "=" * 70)
#             print("INPUT DATA BEFORE MATCHING")
#             print("=" * 70)

#             print("\n26AS DATA:")
#             for t in tds_rows:
#                 print(t)

#             print("\nGL DATA:")
#             for g in gl_rows:
#                 print(g)


#             if matched:
#                 print(
#                     f"MATCH FOUND | PAN {tds['pan']} | "
#                     f"26AS {tds['tds']} | GL SUM {total_gl_amount} | "
#                     f"Diff {diff}"
#                 )

#                 for gl in matched_gls:
#                     self.add_row(
#                         tds=tds,
#                         gl=gl,
#                         status="Matched",
#                         reason=""
#                     )
#             else:
#                 print(
#                     f"NO GL MATCH | PAN {tds['pan']} | "
#                     f"26AS {tds['tds']} | Date {tds['date']}"
#                 )

#                 self.add_row(
#                     tds=tds,
#                     gl=None,
#                     status="Missing in GL",
#                     reason="Present in 26AS but not found in GL"
#                 )

#         # -----------------------------
#         # GL entries missing in 26AS
#         # -----------------------------
#         for (pan, gl_date), gl_list in gl_map.items():
#             if (pan, gl_date) in used_gl_keys:
#                 continue

#             for gl in gl_list:
#                 self.add_row(
#                     tds=None,
#                     gl=gl,
#                     status="Missing in 26AS",
#                     reason="Present in GL but not found in 26AS"
#                 )

#         # -----------------------------
#         # Calculate status (but DON'T save yet)
#         # -----------------------------
#         self.calculate_status()
        
#         # ✅ NEW: Return data for JavaScript to populate
#         child_data = []
#         for row in self.tds_vs_gl_reconciliation_detail:
#             child_data.append({
#                 "pan": row.pan,
#                 "tan": row.tan,
#                 "deductor_name": row.deductor_name,
#                 "posting_date": row.posting_date,
#                 "gl_voucher_no": row.gl_voucher_no,
#                 "gl_voucher_type": row.gl_voucher_type,
#                 "gl_amount": row.gl_amount,
#                 "as26_amount": row.as26_amount,
#                 "difference": row.difference,
#                 "match_status": row.match_status,
#                 "mismatch_reason": row.mismatch_reason,
#                 "as26_reference": row.as26_reference,
#                 "gl_reference": row.gl_reference
#             })

#         print("\n--- SUMMARY ---")
#         print("26AS Rows  :", len(tds_rows))
#         print("GL Rows    :", len(gl_rows))
#         print("Child Rows:", len(child_data))
#         print("STATUS    :", self.status)

#         print("=" * 70)
#         print("RECONCILIATION COMPLETED (NOT SAVED YET)")
#         print("=" * 70)

#         # ✅ REMOVED: All save/commit logic
#         # ✅ NEW: Return data instead of saving
#         return {
#             "status": self.status,
#             "child_rows": child_data,
#             "summary": {
#                 "tds_count": len(tds_rows),
#                 "gl_count": len(gl_rows),
#                 "child_count": len(child_data)
#             }
#         }


#     # =========================================================
#     # DATE TOLERANCE
#     # =========================================================
#     def date_within_range(self, d1, d2, tolerance_days=5):
#         return add_days(d1, -tolerance_days) <= d2 <= add_days(d1, tolerance_days)

#     # =========================================================
#     # FETCH 26AS ENTRIES
#     # =========================================================
#     def get_26as_entries(self):

#         filters = {
#             "transaction_date": ["between", [self.from_date, self.to_date]],
#             "tds_deposited": [">", 0]
#         }

#         if self.pan:
#             filters["pan"] = self.pan

#         data = frappe.get_all(
#             "TDS 26AS Entry",
#             filters=filters,
#             fields=[
#                 "name",
#                 "pan",
#                 "tan",
#                 "deductor_name",
#                 "transaction_date",
#                 "tds_deposited"
#             ],
#             order_by="transaction_date"
#         )

#         print("\n" + "-" * 70)
#         print("RAW 26AS DB ROWS")
#         print("-" * 70)

#         for d in data:
#             print(d)

#         result = [{
#             "ref": d.name,
#             "pan": (d.pan or "").strip(),
#             "tan": (d.tan or "").strip(),
#             "name": d.deductor_name,
#             "date": d.transaction_date,
#             "tds": flt(d.tds_deposited)
#         } for d in data]

#         print("\nPROCESSED 26AS DATA (USED FOR MATCHING)")
#         print("-" * 70)
#         for r in result:
#             print(r)

#         return result

#         # return [{
#         #     "ref": d.name,
#         #     "pan": (d.pan or "").strip(),
#         #     "tan": (d.tan or "").strip(),
#         #     "name": d.deductor_name,
#         #     "date": d.transaction_date,
#         #     "tds": flt(d.tds_deposited)
#         # } for d in data]

#     # =========================================================
#     # FETCH GL ENTRIES
#     # =========================================================
#     def get_gl_entries(self):

#         rows = frappe.db.sql("""
#             SELECT
#                 gle.name            AS gl_entry,
#                 gle.posting_date,
#                 gle.voucher_type,
#                 gle.voucher_no,
#                 si.customer,
#                 c.pan,
#                 gle.debit,
#                 gle.credit
#             FROM `tabGL Entry` gle
#             JOIN `tabPayment Entry` pe ON pe.name = gle.voucher_no
#             JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
#             JOIN `tabSales Invoice` si ON si.name = per.reference_name
#             JOIN `tabCustomer` c ON c.name = si.customer
#             WHERE gle.company = %s
#               AND gle.account = %s
#               AND gle.is_cancelled = 0
#               AND (%s IS NULL OR c.pan = %s)
#             ORDER BY gle.posting_date
#         """, (
#             self.company,
#             self.tds_account,
#             self.pan,
#             self.pan
#         ), as_dict=True)

#         print("\n" + "-" * 70)
#         print("RAW GL SQL ROWS")
#         print("-" * 70)
#         for r in rows:
#             print(r)


#         result = []
#         for r in rows:
#             amount = flt(r.debit) if flt(r.debit) > 0 else flt(r.credit)

#             result.append({
#                 "voucher_no": r.voucher_no,
#                 "voucher_type": r.voucher_type,
#                 "date": r.posting_date,
#                 "amount": amount,
#                 "customer": r.customer,
#                 "pan": r.pan
#             })



#         print("\nPROCESSED GL DATA (USED FOR MATCHING)")
#         print("-" * 70)
#         for r in result:
#             print(r)


#         return result

#     # =========================================================
#     # ADD CHILD ROW
#     # =========================================================
  
#     # def add_row(self, tds=None, gl=None, status="", reason=""):

#     #     row = self.append("tds_vs_gl_reconciliation_detail", {})

#     #     if tds:
#     #         row.pan = tds["pan"]
#     #         row.tan = tds["tan"]
#     #         row.deductor_name = tds["name"]
#     #         row.posting_date = tds["date"]
#     #         row.as26_amount = tds["tds"]
#     #         row.as26_reference = tds["ref"]

#     #     if gl:
#     #         row.gl_voucher_no = gl["voucher_no"]
#     #         row.gl_voucher_type = gl["voucher_type"]
#     #         row.gl_amount = gl["amount"]

#     #     row.difference = round(
#     #         flt(row.as26_amount or 0) - flt(row.gl_amount or 0),
#     #         2
#     #     )
#     #     row.match_status = status
#     #     row.mismatch_reason = reason


#     def add_row(self, tds=None, gl=None, status="", reason=""):

#         row = self.append("tds_vs_gl_reconciliation_detail", {})

#         # -----------------------------
#         # 26AS side
#         # -----------------------------
#         if tds:
#             row.pan = tds.get("pan")
#             row.tan = tds.get("tan")
#             row.deductor_name = tds.get("name")
#             row.posting_date = tds.get("date")
#             row.as26_amount = flt(tds.get("tds"))
#             row.as26_reference = tds.get("ref")

#         # -----------------------------
#         # GL side
#         # -----------------------------
#         if gl:
#             row.gl_voucher_no = gl.get("voucher_no")
#             row.gl_voucher_type = gl.get("voucher_type")
#             row.gl_amount = flt(gl.get("amount"))
#             row.gl_reference = gl.get("voucher_no")

#         # -----------------------------
#         # Difference & Status
#         # -----------------------------
#         row.difference = flt(row.as26_amount or 0) - flt(row.gl_amount or 0)
#         row.match_status = status
#         row.mismatch_reason = reason


#     # =========================================================
#     # CALCULATE STATUS
#     # =========================================================
#     def calculate_status(self):

#         details = self.get("tds_vs_gl_reconciliation_detail") or []

#         if not details:
#             self.status = "Draft"
#             return

#         for row in details:
#             if row.match_status != "Matched":
#                 self.status = "Mismatch"
#                 return

#         self.status = "Matched"



