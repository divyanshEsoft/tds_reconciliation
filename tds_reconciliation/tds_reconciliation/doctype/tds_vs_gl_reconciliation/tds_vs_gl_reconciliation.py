# Copyright (c) 2026, Divyansh
# License: see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, add_days
from collections import defaultdict


class TDSVsGLReconciliation(Document):

    AMOUNT_TOLERANCE = 10  # ₹10 tolerance (industry standard)

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
        # Group GL by PAN + DATE
        # -----------------------------
        gl_map = defaultdict(list)
        for gl in gl_rows:
            key = (gl["pan"], gl["date"])
            gl_map[key].append(gl)

        used_gl_keys = set()

        # =====================================================
        # MATCHING LOGIC
        # =====================================================
        print("\n--- MATCHING 26AS → GL (PAN + ±5 DAYS + ₹10 TOLERANCE) ---")

        for tds in tds_rows:

            matched = False
            matched_gls = []

            for (pan, gl_date), gl_list in gl_map.items():

                if pan != tds["pan"]:
                    continue

                if not self.date_within_range(tds["date"], gl_date, 5):
                    continue

                total_gl_amount = sum(flt(g["amount"]) for g in gl_list)
                diff = round(flt(tds["tds"]) - total_gl_amount, 2)

                if abs(diff) <= self.AMOUNT_TOLERANCE:
                    matched = True
                    matched_gls = gl_list
                    used_gl_keys.add((pan, gl_date))
                    break

            if matched:
                print(
                    f"MATCH FOUND | PAN {tds['pan']} | "
                    f"26AS {tds['tds']} | GL SUM {total_gl_amount} | "
                    f"Diff {diff}"
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

        return {
            "name": self.name,
            "status": self.status,
            "child_count": len(self.tds_vs_gl_reconciliation_detail)
        }

    # =========================================================
    # DATE TOLERANCE
    # =========================================================
    def date_within_range(self, d1, d2, tolerance_days=5):
        return add_days(d1, -tolerance_days) <= d2 <= add_days(d1, tolerance_days)

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
                gle.name            AS gl_entry,
                gle.posting_date,
                gle.voucher_type,
                gle.voucher_no,
                si.customer,
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

        row.difference = round(
            flt(row.as26_amount or 0) - flt(row.gl_amount or 0),
            2
        )
        row.match_status = status
        row.mismatch_reason = reason

    # =========================================================
    # CALCULATE STATUS
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
