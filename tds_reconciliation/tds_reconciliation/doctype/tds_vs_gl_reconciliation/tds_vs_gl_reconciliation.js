// Copyright (c) 2026, divyansh and contributors
// For license information, please see license.txt

frappe.ui.form.on('TDS Vs GL Reconciliation', {

    generate_reconciliation(frm) {

        // ✅ Validation
        if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
            frappe.msgprint(__('Please fill Company, From Date and To Date'));
            return;
        }

        // ✅ Call server method
        frm.call({
            method: "generate_reconciliation",
            doc: frm.doc,
            freeze: true,
            freeze_message: __("Reconciling TDS vs GL...")
        }).then((r) => {

            if (r.message) {

                // ✅ Clear existing child rows
                frm.clear_table("tds_vs_gl_reconciliation_detail");

                // ✅ Populate child table with returned data
                r.message.child_rows.forEach((row) => {
                    let child = frm.add_child("tds_vs_gl_reconciliation_detail");
                    child.pan = row.pan;
                    child.tan = row.tan;
                    child.deductor_name = row.deductor_name;
                    child.posting_date = row.posting_date;
                    child.gl_voucher_no = row.gl_voucher_no;
                    child.gl_voucher_type = row.gl_voucher_type;
                    child.gl_amount = row.gl_amount;
                    child.as26_amount = row.as26_amount;
                    child.difference = row.difference;
                    child.match_status = row.match_status;
                    child.mismatch_reason = row.mismatch_reason;
                    child.as26_reference = row.as26_reference;
                    child.gl_reference = row.gl_reference;
                });

                // ✅ Update status field
                frm.set_value("status", r.message.status);

                // ✅ Refresh the child table in UI
                frm.refresh_field("tds_vs_gl_reconciliation_detail");

                // ✅ Mark form as dirty (unsaved changes)
                frm.dirty();

                // ✅ Show success message
                frappe.show_alert({
                    message: __(
                        `Reconciliation completed!<br>` +
                        `26AS: ${r.message.summary.tds_count} | ` +
                        `GL: ${r.message.summary.gl_count} | ` +
                        `Rows: ${r.message.summary.child_count}<br>` +
                        `<b>Please review and save the document.</b>`
                    ),
                    indicator: "green"
                }, 7);
            }
        });
    }
});







// // Copyright (c) 2026, divyansh and contributors
// // For license information, please see license.txt


// frappe.ui.form.on('TDS Vs GL Reconciliation', {
//     generate_reconciliation(frm) {

//         if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
//             frappe.msgprint(__('Please fill Company, From Date and To Date'));
//             return;
//         }

//         frm.call({
//             method: "generate_reconciliation",
//             doc: frm.doc,
//             freeze: true,
//             freeze_message: __("Reconciling TDS vs GL...")
//         }).then(() => {

//             // ✅ CRITICAL FIX
//             frm.reload_doc().then(() => {
//                 frm.refresh_field("tds_vs_gl_reconciliation_detail");
//             });

//             frappe.show_alert({
//                 message: __("Reconciliation completed"),
//                 indicator: "green"
//             });

//         });
//     }
// });





