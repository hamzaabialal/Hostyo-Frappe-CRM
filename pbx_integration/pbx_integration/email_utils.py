import frappe


def flush_email_immediately(doc, method):
	if doc.status == "Not Sent":
		frappe.enqueue(
			"frappe.email.queue.flush",
			queue="short",
			now=True,
		)
