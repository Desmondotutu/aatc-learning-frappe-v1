import frappe
import unittest
from frappe.tests import IntegrationTestCase
from unittest.mock import patch, MagicMock
from frappe.utils import now_datetime, add_days, getdate


class TestTrainingPayment(IntegrationTestCase):
    """Test training fee payments (5C)"""

    def setUp(self):
        """Set up test data"""
        # Create a test student user
        self.student_email = f"test-payment-student-{frappe.generate_hash()[:6]}@test.com"
        if not frappe.db.exists("User", self.student_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.student_email,
                "first_name": "Test",
                "last_name": "Student",
                "send_welcome_email": 0,
                "enabled": 1,
            })
            user.insert(ignore_permissions=True)
            user.add_roles("LMS Student")

        # Create a test course
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "course_code": f"TEST-PAY-COURSE-{frappe.generate_hash()[:6]}",
            "title": f"Test Payment Course {frappe.generate_hash()[:6]}",
            "short_introduction": "Test course for payment testing",
            "description": "Test course description",
            "published": 1,
        })
        self.course.insert(ignore_permissions=True)

        # Create enrollment
        self.enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student_email,
            "course": self.course.name,
        })
        self.enrollment.insert(ignore_permissions=True)

        # Configure AATC Settings for mock payments
        self.settings = frappe.get_single("AATC Settings")
        self.settings.payment_enabled = 1
        self.settings.payment_gateway = "Mock"
        self.settings.payment_mock_success_rate = 100
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        """Clean up test data"""
        # Delete enrollment
        if self.enrollment:
            try:
                frappe.delete_doc("LMS Enrollment", self.enrollment.name, force=1, ignore_permissions=True)
            except Exception:
                pass

        # Delete course
        if self.course:
            try:
                frappe.delete_doc("LMS Course", self.course.name, force=1, ignore_permissions=True)
            except Exception:
                pass

        # Delete student user
        if self.student_email:
            try:
                frappe.delete_doc("User", self.student_email, force=1, ignore_permissions=True)
            except Exception:
                pass

        # Reset payment settings
        settings = frappe.get_single("AATC Settings")
        settings.payment_enabled = 0
        settings.payment_gateway = "Mock"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def test_mock_payment_sets_payment_status_paid(self):
        """Test that successful mock payment sets enrollment payment_status to 'Paid'"""
        from aatc_learning.payment import process_training_payment

        result = process_training_payment(self.enrollment.name, gateway="Mock")

        self.enrollment.reload()
        self.assertEqual(self.enrollment.payment_status, "Paid")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["enrollment"], self.enrollment.name)
        self.assertEqual(result["gateway"], "Mock")

    def test_payment_fails_when_disabled(self):
        """Test that payment fails when disabled in settings"""
        from aatc_learning.payment import process_training_payment

        # Disable payments
        settings = frappe.get_single("AATC Settings")
        settings.payment_enabled = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            process_training_payment(self.enrollment.name)

    def test_payment_fails_when_already_paid(self):
        """Test that payment fails for already paid enrollments"""
        from aatc_learning.payment import process_training_payment

        # Set enrollment as already paid
        self.enrollment.payment_status = 'Paid'
        self.enrollment.save(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            process_training_payment(self.enrollment.name)

    def test_mock_payment_failure_simulation(self):
        """Test that mock payment can simulate failures"""
        from aatc_learning.payment import process_training_payment

        # Set success rate to 0% (always fail)
        settings = frappe.get_single("AATC Settings")
        settings.payment_mock_success_rate = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            process_training_payment(self.enrollment.name, gateway="Mock")


if __name__ == "__main__":
    unittest.main()