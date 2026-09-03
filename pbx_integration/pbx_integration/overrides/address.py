def set_address_title(doc, method=None):
	"""Auto-fill Address.address_title when it's empty.

	The CRM frontend's Address popup doesn't send a title - it expects
	Frappe to derive one automatically, which doesn't happen - so the
	doctype's own `reqd` check on `address_title` throws "Address Title is
	mandatory" before the document ever saves. Registered (in hooks.py) on
	before_validate and before_insert, both of which run before that
	mandatory-field check, so a title set here satisfies it.

	Never overwrites an existing title. Preference order: the first linked
	document's name (Contact/Lead/Customer, whichever the popup linked this
	Address to), then address_line1, then city.
	"""
	if doc.address_title:
		return

	if doc.links and doc.links[0].link_name:
		doc.address_title = doc.links[0].link_name
	elif doc.address_line1:
		doc.address_title = doc.address_line1
	elif doc.city:
		doc.address_title = doc.city
