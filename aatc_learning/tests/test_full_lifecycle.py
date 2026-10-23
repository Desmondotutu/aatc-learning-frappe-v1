# AATC Learning - Full LMS Lifecycle End-to-End Test

import frappe
import unittest
from frappe.tests import IntegrationTestCase
import uuid
from frappe.utils import nowdate, add_days, getdate, now_datetime
from frappe.model.workflow import apply_workflow
from aatc.certificate_automation import (
    create_certificates_from_exam_session,
    auto_approve_certificate,
    generate_certificate_number
)


class TestFullLMSLifecycle(IntegrationTestCase):
    """End-to-end test of the complete LMS lifecycle"""

    def setUp(self):
        """Create test data for the lifecycle test"""
        # Clean up first
        self.tearDown()

        # Create test infrastructure (Company, Gender)
        if not frappe.db.exists("Company", "Test Company"):
            self.company = frappe.get_doc({
                "doctype": "Company",
                "company_name": "Test Company",
                "abbr": "TC",
                "default_currency": "USD",
                "country": "United States"
            }).insert(ignore_permissions=True)
        else:
            self.company = frappe.get_doc("Company", "Test Company")

        if not frappe.db.exists("Gender", "Male"):
            self.gender = frappe.get_doc({
                "doctype": "Gender",
                "gender": "Male"
            }).insert(ignore_permissions=True)
        else:
            self.gender = frappe.get_doc("Gender", "Male")

        # Create a test user (student) - use a unique email
        import uuid
        test_id = str(uuid.uuid4())[:8]

        self.student = frappe.get_doc({
            "doctype": "User",
            "email": f"student-{test_id}@test.com",
            "first_name": "Test",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create employee for student
        self.student_employee = frappe.get_doc({
            "doctype": "Employee",
            "first_name": self.student.first_name,
            "last_name": self.student.last_name,
            "user_id": self.student.name,
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
            "company": "Test Company",
            "employment_type": "Full-time",
            "status": "Active"
        }).insert(ignore_permissions=True)

        # Create a test course with unique code
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course - Air Navigation {test_id}",
            "course_code": f"TEST-ANV-{test_id}",
            "description": "Test course for end-to-end lifecycle",
            "short_introduction": "Test course for end-to-end lifecycle",
            "published": 1,
            "validity_period_months": 24
        }).insert(ignore_permissions=True)

        # Create a classroom
        self.classroom = frappe.get_doc({
            "doctype": "Classroom",
            "room_code": f"TEST-CR-{test_id}",
            "room_name": f"Test Classroom 1 {test_id}",
            "capacity": 20,
            "location": "Test Building",
            "inspection_status": "Inspected",
            "last_inspected_at": now_datetime()
        }).insert(ignore_permissions=True)

        # Create an instructor - use Administrator employee (should exist from test infrastructure)
        admin_employee = frappe.get_all("Employee", filters={"user_id": "Administrator"}, fields=["name"])
        if not admin_employee:
            admin_employee = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "Admin",
                "last_name": "User",
                "user_id": "Administrator",
                "gender": "Male",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "company": "Test Company",
                "employment_type": "Full-time",
                "status": "Active"
            }).insert(ignore_permissions=True)
        else:
            admin_employee = frappe.get_doc("Employee", admin_employee[0].name)

        self.instructor = frappe.get_doc({
            "doctype": "Instructor",
            "instructor_id": f"INST-TEST-{test_id}",
            "employee": admin_employee.name,
            "instructor_type": "Ground",
            "compliance_status": "Active",
            "certificate_expiry": add_days(getdate(), 365)
        }).insert(ignore_permissions=True)

        # Create a Session Lifecycle
        self.session = frappe.get_doc({
            "doctype": "Session Lifecycle",
            "session_title": f"Test Session - Air Navigation {test_id}",
            "course": self.course.name,
            "start_date": add_days(getdate(), 10),
            "end_date": add_days(getdate(), 15),
            "status": "PLANNED",
            "instructor": self.instructor.name,
            "location": self.classroom.name
        }).insert(ignore_permissions=True)

        # Create a Training Request (using student user)
        self.training_request = frappe.get_doc({
            "doctype": "Training Request",
            "learner": self.student.name,
            "course": self.course.name,
            "requested_start_date": add_days(getdate(), 10),
            "workflow_state": "Draft"
        }).insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data"""
        for dt_name in ["LMS Certificate", "LMS Enrollment", "Examiner Result",
                        "Examination Session", "Session Lifecycle", "Training Request",
                        "Instructor", "Classroom", "LMS Course"]:
            docs = frappe.get_all(dt_name, filters={"name": ["like", "TEST-%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
        # Also clean up any with test-course-air-navigation or INST-TEST
        for dt_name in ["LMS Course"]:
            docs = frappe.get_all(dt_name, filters={"course_code": ["like", "TEST-%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()

    def test_full_lms_lifecycle(self):
        """Test complete lifecycle from Training Request to Certificate Issued"""

        # Step 1: Submit Training Request (Learner submits)
        self.training_request = apply_workflow(self.training_request, "Submit")
        self.assertEqual(self.training_request.status, "Submitted")

        # HOT Approves the Training Request
        self.training_request = apply_workflow(self.training_request, "Approve")
        self.assertEqual(self.training_request.status, "Approved")

        # Create LMS Enrollment
        enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": self.student.full_name,
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)
        self.enrollment = enrollment

        # Step 2: Move Session Lifecycle: PLANNED -> READY FOR DELIVERY
        self.session.status = "READY FOR DELIVERY"
        self.session.instructor_availability_confirmed = 1
        self.session.instructor_compliance_checked = 1
        self.session.classroom_booked = 1
        self.session.equipment_check_completed = 1
        self.session.course_materials_version_confirmed = 1
        self.session.lms_shell_confirmed = 1
        self.session.ipad_status_confirmed = 1
        self.session.connectivity_test_passed = 1
        self.session.save(ignore_permissions=True)
        self.assertEqual(self.session.status, "READY FOR DELIVERY")

        # Step 3: Move Session Lifecycle: READY FOR DELIVERY -> IN PROGRESS
        self.session.status = "IN PROGRESS"
        self.session.go_no_go_decision = "GO"
        self.session.tc_practical_readiness_signed = 1
        self.session.dlts_digital_readiness_signed = 1
        self.session.save(ignore_permissions=True)
        self.assertEqual(self.session.status, "IN PROGRESS")

        # Add attendance records for Phase 3 gate
        start_date = getdate(self.session.start_date)
        for i in range(6):
            day = add_days(start_date, i)
            self.session.append("daily_attendance", {
                "date": day,
                "learner": self.student.name,
                "am_status": "Present",
                "pm_status": "Present",
                "marked_by": frappe.session.user,
                "marked_at": now_datetime()
            })

        # Step 4: Create Examination Session and move through workflow
        exam_session = frappe.get_doc({
            "doctype": "Examination Session",
            "session": self.session.name,
            "session_title": self.session.session_title,
            "course": self.session.course,
            "examination_date": self.session.start_date,
            "start_date": self.session.start_date,
            "end_date": self.session.end_date
        }).insert(ignore_permissions=True)
        self.exam_session = exam_session

        # Move Examination Session through workflow: Planned -> Scheduled -> In Progress -> Completed -> Reviewed
        exam_session = apply_workflow(exam_session, "Schedule")
        self.assertEqual(exam_session.status, "Scheduled")

        exam_session = apply_workflow(exam_session, "Start")
        self.assertEqual(exam_session.status, "In Progress")

        exam_session = apply_workflow(exam_session, "Complete")
        self.assertEqual(exam_session.status, "Completed")

        exam_session = apply_workflow(exam_session, "Review")
        self.assertEqual(exam_session.status, "Reviewed")

        # Create Examiner Result with PASS and move through workflow
        examiner_result = frappe.get_doc({
            "doctype": "Examiner Result",
            "examination_session": exam_session.name,
            "learner": self.student.name,
            "score": 85,
            "examiner_decision": "PASS"
        }).insert(ignore_permissions=True)

        # Move Examiner Result through workflow: Draft -> Submitted -> Verified -> Approved
        examiner_result = apply_workflow(examiner_result, "Submit")
        self.assertEqual(examiner_result.status, "Submitted")

        examiner_result = apply_workflow(examiner_result, "Verify")
        self.assertEqual(examiner_result.status, "Verified")

        examiner_result = apply_workflow(examiner_result, "Approve")
        self.assertEqual(examiner_result.status, "Approved")

        # Step 5: Move Session Lifecycle to ASSESSMENT COMPLETE
        self.session.status = "ASSESSMENT COMPLETE"
        self.session.lms_shell_created = 1
        self.session.save(ignore_permissions=True)
        self.assertEqual(self.session.status, "ASSESSMENT COMPLETE")

        # Step 6: Move Session Lifecycle to CLOSED
        self.session.status = "CLOSED"
        self.session.qm_quality_check_approved = 1
        self.session.qm_approved_at = now_datetime()
        self.session.save(ignore_permissions=True)
        self.assertEqual(self.session.status, "CLOSED")

        # Generate certificates from exam session
        result = create_certificates_from_exam_session(exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        # Find the created certificate
        certificates = frappe.get_all("LMS Certificate",
            filters={"member": self.student.name, "course": self.course.name},
            fields=["name", "status", "certificate_number", "qm_approved_at", "qm_approved_by"])
        self.assertEqual(len(certificates), 1)
        cert = frappe.get_doc("LMS Certificate", certificates[0].name)
        self.assertEqual(cert.status, "Pending QM Approval")

        # Step 6: Move Certificate through workflow using proper transitions
        # QM Approval: Pending QM Approval -> QM Approved
        cert = apply_workflow(cert, "QM Approve")
        cert.reload()
        self.assertEqual(cert.status, "QM Approved")

        # Submit for HOT: QM Approved -> Pending HOT Approval
        cert = apply_workflow(cert, "Submit HOT")
        cert.reload()
        self.assertEqual(cert.status, "Pending HOT Approval")

        # HOT Approval: Pending HOT Approval -> Approved
        cert = apply_workflow(cert, "HOT Approve")
        cert.reload()
        self.assertEqual(cert.status, "Approved")

        # Distribution: Approved -> Distributed
        cert = apply_workflow(cert, "Distribute")
        cert.reload()
        self.assertEqual(cert.status, "Distributed")

        # Step 7: Verify LMS Enrollment updated
        enrollment = frappe.get_doc("LMS Enrollment", self.enrollment.name)
        self.assertTrue(enrollment.certificate_issued)
        self.assertIsNotNone(enrollment.certificate_expiry)

        # Step 8: Verify KPI Snapshot would be updated
        # (Run weekly snapshot to verify)
        from aatc.aatc.tasks import weekly_kpi_snapshot
        result = weekly_kpi_snapshot()
        self.assertEqual(result, "KPI snapshot captured")

        # Check latest KPI snapshot
        snapshots = frappe.get_all("KPI Snapshot", order_by="creation desc", limit=1)
        self.assertEqual(len(snapshots), 1)
        latest = frappe.get_doc("KPI Snapshot", snapshots[0].name)
        self.assertIsNotNone(latest.snapshot_date)


if __name__ == "__main__":
    unittest.main()