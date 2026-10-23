import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Run after app installation"""
    create_custom_fields_for_lms()
    frappe.db.commit()


def before_tests():
    """Run before tests"""
    frappe.flags.in_test = True
    frappe.local.conf.rate_limit = False
    # Disable user creation throttle for tests
    frappe.local.conf.throttle_user_limit = 1000000


def create_custom_fields_for_lms():
    """Add custom fields to LMS DocTypes"""

    # LMS Course custom fields
    lms_course_fields = {
        "LMS Course": [
            {
                "fieldname": "course_code",
                "label": "Course Code",
                "fieldtype": "Data",
                "unique": 1,
                "reqd": 1,
                "insert_after": "title",
            },
            {
                "fieldname": "validity_period_months",
                "label": "Validity Period (Months)",
                "fieldtype": "Int",
                "default": 24,
                "insert_after": "course_code",
            },
            {
                "fieldname": "regulatory_body",
                "label": "Regulatory Body",
                "fieldtype": "Select",
                "options": "CCAA\nICAO\nEASA\nFAA\nOther",
                "default": "CCAA",
                "insert_after": "validity_period_months",
            },
            {
                "fieldname": "ccaa_approval_ref",
                "label": "CCAA Approval Reference",
                "fieldtype": "Data",
                "insert_after": "regulatory_body",
            },
            {
                "fieldname": "ccaa_approval_expiry",
                "label": "CCAA Approval Expiry",
                "fieldtype": "Date",
                "insert_after": "ccaa_approval_ref",
            },
            {
                "fieldname": "course_type",
                "label": "Course Type",
                "fieldtype": "Select",
                "options": "PPL/CPL Ground Theory\nMER\nIR\nCRM/HF\nSMS\nDG\nAELP",
                "reqd": 1,
                "insert_after": "ccaa_approval_expiry",
            },
        ]
    }

    # LMS Enrollment custom fields
    lms_enrollment_fields = {
        "LMS Enrollment": [
            {
                "fieldname": "final_grade",
                "label": "Final Grade",
                "fieldtype": "Select",
                "options": "A\nB\nC\nD\nF\nPass\nFail",
                "insert_after": "progress",
            },
            {
                "fieldname": "grade_points",
                "label": "Grade Points",
                "fieldtype": "Float",
                "insert_after": "final_grade",
            },
            {
                "fieldname": "exam_score",
                "label": "Exam Score",
                "fieldtype": "Float",
                "insert_after": "grade_points",
            },
            {
                "fieldname": "attendance_score",
                "label": "Attendance Score",
                "fieldtype": "Float",
                "insert_after": "exam_score",
            },
            {
                "fieldname": "examiner_decision",
                "label": "Examiner Decision",
                "fieldtype": "Select",
                "options": "PASS\nFAIL\nPENDING",
                "default": "PENDING",
                "insert_after": "attendance_score",
            },
            {
                "fieldname": "certificate_issued",
                "label": "Certificate Issued",
                "fieldtype": "Check",
                "default": 0,
                "insert_after": "examiner_decision",
            },
            {
                "fieldname": "certificate_expiry",
                "label": "Certificate Expiry",
                "fieldtype": "Date",
                "insert_after": "certificate_issued",
            },
            {
                "fieldname": "exam_session",
                "label": "Examination Session",
                "fieldtype": "Link",
                "options": "Examination Session",
                "insert_after": "certificate_expiry",
            },
        ]
    }

    # LMS Certificate custom fields
    lms_certificate_fields = {
        "LMS Certificate": [
            {
                "fieldname": "examiner_result",
                "label": "Examiner Result",
                "fieldtype": "Link",
                "options": "Examiner Result",
                "insert_after": "course",
            },
            {
                "fieldname": "qm_approved_at",
                "label": "QM Approved At",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "examiner_result",
            },
            {
                "fieldname": "qm_approved_by",
                "label": "QM Approved By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "qm_approved_at",
            },
            {
                "fieldname": "hot_approved_at",
                "label": "HOT Approved At",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "qm_approved_by",
            },
            {
                "fieldname": "hot_approved_by",
                "label": "HOT Approved By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "hot_approved_at",
            },
            {
                "fieldname": "certificate_number",
                "label": "Certificate Number",
                "fieldtype": "Data",
                "unique": 1,
                "read_only": 1,
                "insert_after": "hot_approved_by",
            },
            {
                "fieldname": "qr_payload",
                "label": "QR Payload",
                "fieldtype": "Long Text",
                "read_only": 1,
                "insert_after": "certificate_number",
            },
            {
                "fieldname": "distributed_at",
                "label": "Distributed At",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "qr_payload",
            },
            {
                "fieldname": "distributed_by",
                "label": "Distributed By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "distributed_at",
            },
        ]
    }

    create_custom_fields(lms_course_fields)
    create_custom_fields(lms_enrollment_fields)
    create_custom_fields(lms_certificate_fields)
    print("Created custom fields for LMS DocTypes")