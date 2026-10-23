app_name = "aatc_learning"
app_title = "AATC Learning"
app_publisher = "Desmond Wangki"
app_description = "AATC LMS Extensions for TMPM"
app_email = "admin@aatc.localhost"
app_license = "mit"

required_apps = ["frappe", "lms", "aatc"]

fixtures = [
    {"doctype": "Custom Field", "filters": [["dt", "in", ["LMS Enrollment"]]]},
    {"doctype": "DocType", "filters": [["name", "in", ["Student Transcript"]]]},
    {"doctype": "Virtual DocType", "filters": [["module", "=", "AATC Learning"]]},
    {"doctype": "Print Format", "filters": [["module", "=", "AATC Learning"]]},
    {"doctype": "Notification", "filters": [["module", "=", "AATC Learning"]]},
]

# Import controllers after app is installed
after_install = "aatc_learning.install.after_install"

# Testing
before_tests = "aatc_learning.install.before_tests"

# Export Python type annotations
export_python_type_annotations = True
require_type_annotated_api_methods = True