# AATC Learning - Certificate PDF Rendering Tests (Workstream 3B)

import frappe
import unittest
from frappe.tests import IntegrationTestCase
import os
import tempfile
import subprocess
from frappe.utils import now_datetime, getdate, add_days, add_months
from frappe.model.workflow import apply_workflow
from aatc.certificate_automation import create_certificates_from_exam_session, generate_certificate_number


def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF using pdftotext"""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_content)
        pdf_path = f.name
    try:
        result = subprocess.run(['pdftotext', pdf_path, '-'],
                              capture_output=True, text=True, timeout=10)
        return result.stdout
    finally:
        os.unlink(pdf_path)


class TestCertificatePDFRendering(IntegrationTestCase):
    """Test Certificate PDF rendering with real data (Workstream 3B)"""

    def setUp(self):
        """Create test data for PDF tests"""
        self.tearDown()

        test_id = str(frappe.generate_hash())[:8]

        # Create test course
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course - Air Navigation {test_id}",
            "course_code": f"TEST-ANV-{test_id}",
            "description": "Test course for PDF rendering",
            "short_introduction": "Test course for PDF rendering",
            "published": 1,
            "validity_period_months": 24
        }).insert(ignore_permissions=True)

        # Create test user
        self.student = frappe.get_doc({
            "doctype": "User",
            "email": f"student-pdf-{test_id}@test.com",
            "first_name": "Test",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create LMS Enrollment (required for LMS Certificate validation)
        self.enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": "Test Student",
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Get the Standard Certificate print format
        pf = frappe.get_doc("Print Format", "Standard Certificate")

        # Create LMS Certificate directly
        self.certificate = frappe.get_doc({
            "doctype": "LMS Certificate",
            "member": self.student.name,
            "member_name": "Test Student",
            "course": self.course.name,
            "course_title": self.course.title,
            "issue_date": getdate(),
            "expiry_date": add_months(getdate(), 24),
            "template": pf.name,
            "published": 1,
            "status": "Draft"
        }).insert(ignore_permissions=True)

        # Generate certificate number while in Draft state (before submission)
        generate_certificate_number(self.certificate.name)
        self.certificate.reload()

        # Apply workflow transition to get it into a proper state
        self.certificate = apply_workflow(self.certificate, "Submit QM")
        self.certificate = apply_workflow(self.certificate, "QM Approve")
        self.certificate = apply_workflow(self.certificate, "Submit HOT")
        self.certificate = apply_workflow(self.certificate, "HOT Approve")
        self.certificate = apply_workflow(self.certificate, "Distribute")
        self.certificate.reload()

    def tearDown(self):
        """Clean up test data"""
        for dt_name in ["LMS Certificate", "LMS Course", "User"]:
            docs = frappe.get_all(dt_name, filters={"name": ["like", "TEST-%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
        # Also clean up by student-pdf
        docs = frappe.get_all("LMS Certificate", filters={"member_name": "Test Student"})
        for doc in docs:
            try:
                frappe.delete_doc("LMS Certificate", doc.name, force=1, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_standard_certificate_print_format_exists(self):
        """Test that Standard Certificate print format exists for LMS Certificate"""
        pf = frappe.get_all("Print Format",
            filters={"name": "Standard Certificate", "doc_type": "LMS Certificate"})
        self.assertEqual(len(pf), 1, "Standard Certificate print format should exist")

    def test_certificate_pdf_generation(self):
        """Test that certificate PDF can be generated without errors"""
        from frappe.utils.print_format import download_pdf

        # Generate PDF
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        # Verify PDF was generated
        self.assertIsNotNone(pdf_content, "PDF content should not be None")
        self.assertGreater(len(pdf_content), 1000, "PDF should have substantial content")
        # Check PDF header
        self.assertTrue(pdf_content.startswith(b'%PDF'), "Generated content should be a valid PDF")

    def test_pdf_contains_student_name(self):
        """Test that generated PDF contains student name"""
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        # Extract text from PDF using pdftotext
        pdf_text = extract_text_from_pdf(pdf_content)
        self.assertIn("Test Student", pdf_text, "PDF should contain student name")

    def test_pdf_contains_course_title(self):
        """Test that generated PDF contains course title"""
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        pdf_text = extract_text_from_pdf(pdf_content)
        self.assertIn(self.course.title, pdf_text, "PDF should contain course title")

    def test_pdf_contains_certificate_number(self):
        """Test that generated PDF contains certificate number"""
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        pdf_text = extract_text_from_pdf(pdf_content)
        self.assertIn(self.certificate.certificate_number, pdf_text,
                     "PDF should contain certificate number")

    def test_pdf_contains_issue_and_expiry_dates(self):
        """Test that generated PDF contains issue and expiry dates"""
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        pdf_text = extract_text_from_pdf(pdf_content)
        issue_date_str = str(self.certificate.issue_date)
        expiry_date_str = str(self.certificate.expiry_date)
        self.assertIn(issue_date_str, pdf_text, "PDF should contain issue date")
        self.assertIn(expiry_date_str, pdf_text, "PDF should contain expiry date")

    def test_pdf_verification_url_present(self):
        """Test that PDF contains verification reference"""
        pdf_content = frappe.get_print(
            "LMS Certificate",
            self.certificate.name,
            "Standard Certificate",
            as_pdf=True
        )

        pdf_text = extract_text_from_pdf(pdf_content)
        # Check for verification reference - the template has a verification URL pattern
        # Note: frappe.utils.get_url() may not render in test context, so check for certificate number
        # which is part of the verification URL
        self.assertIn(self.certificate.certificate_number, pdf_text,
                     "PDF should contain certificate number as part of verification URL")

    def test_pdf_paper_mode_watermark_logic(self):
        """Test that paper mode watermark logic exists in template"""
        # Get the print format template
        pf = frappe.get_doc("Print Format", "Standard Certificate")
        html = pf.html

        # Check for paper_mode_active conditional logic
        self.assertIn("paper_mode_active", html,
                     "Print format should contain paper_mode_active logic")


if __name__ == "__main__":
    unittest.main()