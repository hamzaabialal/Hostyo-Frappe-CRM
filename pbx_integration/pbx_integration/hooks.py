app_name = "pbx_integration"
app_title = "Pbx Integration"
app_publisher = "Hostyo"
app_description = "PBX.IM Click2Call and call logging integration"
app_email = "support@hostyo.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "pbx_integration",
# 		"logo": "/assets/pbx_integration/logo.png",
# 		"title": "Pbx Integration",
# 		"route": "/pbx_integration",
# 		"has_permission": "pbx_integration.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/pbx_integration/css/pbx_integration.css"
# app_include_js = "/assets/pbx_integration/js/pbx_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/pbx_integration/css/pbx_integration.css"
# web_include_js = "/assets/pbx_integration/js/pbx_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "pbx_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "pbx_integration/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "pbx_integration.utils.jinja_methods",
# 	"filters": "pbx_integration.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "pbx_integration.install.before_install"
# after_install = "pbx_integration.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "pbx_integration.uninstall.before_uninstall"
# after_uninstall = "pbx_integration.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "pbx_integration.utils.before_app_install"
# after_app_install = "pbx_integration.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "pbx_integration.utils.before_app_uninstall"
# after_app_uninstall = "pbx_integration.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "pbx_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"pbx_integration.tasks.all"
# 	],
# 	"daily": [
# 		"pbx_integration.tasks.daily"
# 	],
# 	"hourly": [
# 		"pbx_integration.tasks.hourly"
# 	],
# 	"weekly": [
# 		"pbx_integration.tasks.weekly"
# 	],
# 	"monthly": [
# 		"pbx_integration.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "pbx_integration.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "pbx_integration.event.get_events"
# }
#

# frappe_appointment's book_time_slot builds an organizer attendee email
# from a User docname instead of a real lookup - see
# pbx_integration/overrides/personal_meet.py's module docstring for the full
# writeup. Path is frappe_appointment.api.personal_meet.book_time_slot (NOT
# frappe_appointment.frappe_appointment.api...) - confirmed against
# frappe_appointment's actual repo layout (api/ is a top-level dir, not
# nested under the doctype-module folder that only doctype controllers use).
#
# This alone only affects calls dispatched through Frappe's HTTP
# method-call layer (frappe.handler.execute_cmd) - it does NOT affect
# crm.api.meetings.book_meeting's own direct Python import of book_time_slot,
# which is the actual call path that hit this bug. That import was changed
# to point at pbx_integration.overrides.personal_meet.book_time_slot
# directly instead - this hook is a complementary fix for any other, genuine
# HTTP caller of the original endpoint (e.g. frappe_appointment's own
# personal-meeting booking page).
override_whitelisted_methods = {
	"frappe_appointment.api.personal_meet.book_time_slot": "pbx_integration.overrides.personal_meet.book_time_slot"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "pbx_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["pbx_integration.utils.before_request"]
# after_request = ["pbx_integration.utils.after_request"]

# Job Events
# ----------
# before_job = ["pbx_integration.utils.before_job"]
# after_job = ["pbx_integration.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"pbx_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


doc_events = {
	"Email Queue": {
		"after_insert": "pbx_integration.email_utils.flush_email_immediately"
	},
	"User": {
		"validate": "pbx_integration.telnyx.validate_unique_telnyx_did"
	},
	"Address": {
		"before_validate": "pbx_integration.overrides.address.set_address_title",
		"before_insert": "pbx_integration.overrides.address.set_address_title"
	}
}
