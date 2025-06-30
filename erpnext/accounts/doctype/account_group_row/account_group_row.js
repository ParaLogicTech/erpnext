frappe.ui.form.on('Account Group Row', {
    party_type: function(frm, cdt, cdn) {
        // Clear 'party' if 'party_type' changes
        frappe.model.set_value(cdt, cdn, 'party', '');
    }
});

// Set query for party_type in the Account Group Row child table
frm.set_query("party_type", function() {
    return {
        filters: {
            "name": ["in", Object.keys(frappe.boot.party_account_types)],
        }
    };
});