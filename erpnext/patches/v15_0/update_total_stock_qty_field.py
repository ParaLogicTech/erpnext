import frappe


def execute():
	doctypes = ["Sales Invoice"]

	for doctype in doctypes:
		total_stock_qty = frappe.db.sql('''
			SELECT
				parent, SUM(stock_qty) as qty
			FROM
				`tab{0} Item`
			where parenttype = '{0}'
			GROUP BY parent
		'''.format(doctype), as_dict = True)

		batch_size = 100000
		for i in range(0, len(total_stock_qty), batch_size):
			batch_transactions = total_stock_qty[i:i + batch_size]
			values = []
			for d in batch_transactions:
				values.append("({0}, {1})".format(frappe.db.escape(d.parent), d.qty))
			conditions = ",".join(values)
			frappe.db.sql("""
				INSERT INTO `tab{}` (name, total_stock_qty) VALUES {}
				ON DUPLICATE KEY UPDATE name = VALUES(name), total_stock_qty = VALUES(total_stock_qty)
			""".format(doctype, conditions))
