// Copyright (c) 2026, divyansh and contributors
// For license information, please see license.txt

frappe.ui.form.on('TDS Vs GL Reconciliation', {
    generate_reconciliation(frm) {

        // Optional validation (good to keep)
        if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
            frappe.msgprint(__('Please fill Company, From Date and To Date'));
            return;
        }

        frm.call({
            method: "generate_reconciliation",
            doc: frm.doc,
            freeze: true,
            freeze_message: __("Reconciling TDS vs GL...")
        }).then(() => {

            // 🔥 THIS LINE MAKES CHILD TABLE APPEAR
            frm.reload_doc();

            frappe.show_alert({
                message: __("Reconciliation completed"),
                indicator: "green"
            });
        });
    }
});
