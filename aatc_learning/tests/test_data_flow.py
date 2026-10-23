# AATC Learning - Examination→Enrollment→Certificate Data Flow Tests (Workstream 3C)

import frappe
import unittest
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime, getdate, add_days, add_months
from frappe.model.workflow import apply_workflow
from aatc.certificate_automation import create_certificates_from_exam_session, generate_certificate_number


class TestExaminationEnrollmentCertificateFlow(IntegrationTestCase):
    """Test data flow from Examination Session to Enrollment to Certificate (Workstream 3C)"""

    def setUp(self):
        """Create test data"""
        self.tearDown()

        test_id = str(frappe.generate_hash())[:8]

        # Create test course
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course - Air Navigation {test_id}",
            "course_code": f"TEST-ANV-{test_id}",
            "description": "Test course for data flow",
            "short_introduction": "Test course for data flow",
            "published": 1,
            "validity_period_months": 24
        }).insert(ignore_permissions=True)

        # Create test user
        self.student = frappe.get_doc({
            "doctype": "User",
            "email": f"student-flow-{test_id}@test.com",
            "first_name": "Test",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create LMS Enrollment
        self.enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": "Test Student",
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Create classroom
        self.classroom = frappe.get_doc({
            "doctype": "Classroom",
            "room_code": f"TEST-CR-{test_id}",
            "room_name": f"Test Classroom {test_id}",
            "capacity": 20,
            "location": "Test Building",
            "inspection_status": "Inspected",
            "last_inspected_at": now_datetime()
        }).insert(ignore_permissions=True)

        # Create instructor
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
            "instructor_id": f"INST-FLOW-{test_id}",
            "employee": admin_employee.name,
            "instructor_type": "Ground",
            "compliance_status": "Active",
            "certificate_expiry": add_days(getdate(), 365)
        }).insert(ignore_permissions=True)

        # Create Session Lifecycle
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

        # Move session through all phases with required gate fields
        # Phase 1: PLANNED -> READY FOR DELIVERY
        self.session.instructor_availability_confirmed = 1
        self.session.instructor_compliance_checked = 1
        self.session.classroom_booked = 1
        self.session.equipment_check_completed = 1
        self.session.course_materials_version_confirmed = 1
        self.session.lms_shell_confirmed = 1
        self.session.ipad_status_confirmed = 1
        self.session.connectivity_test_passed = 1
        self.session.status = "READY FOR DELIVERY"
        self.session.save(ignore_permissions=True)

        # Phase 2: READY FOR DELIVERY -> IN PROGRESS
        self.session.go_no_go_decision = "GO"
        self.session.tc_practical_readiness_signed = 1
        self.session.dlts_digital_readiness_signed = 1
        self.session.status = "IN PROGRESS"
        self.session.save(ignore_permissions=True)

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

        # Phase 3: IN PROGRESS -> ASSESSMENT COMPLETE
        self.session.lms_shell_created = 1
        self.session.status = "ASSESSMENT COMPLETE"
        self.session.save(ignore_permissions=True)

        # Phase 4: ASSESSMENT COMPLETE -> CLOSED
        self.session.qm_quality_check_approved = 1
        self.session.qm_approved_at = now_datetime()
        self.session.status = "CLOSED"
        self.session.save(ignore_permissions=True)

        # Create Examination Session
        self.exam_session = frappe.get_doc({
            "doctype": "Examination Session",
            "session": self.session.name,
            "session_title": self.session.session_title,
            "course": self.session.course,
            "examination_date": self.session.start_date,
            "start_date": self.session.start_date,
            "end_date": self.session.end_date
        }).insert(ignore_permissions=True)

        # Move Examination Session through workflow
        self.exam_session = apply_workflow(self.exam_session, "Schedule")
        self.exam_session = apply_workflow(self.exam_session, "Start")
        self.exam_session = apply_workflow(self.exam_session, "Complete")
        self.exam_session = apply_workflow(self.exam_session, "Review")

        # Create Examiner Result with PASS
        self.examiner_result = frappe.get_doc({
            "doctype": "Examiner Result",
            "examination_session": self.exam_session.name,
            "learner": self.student.name,
            "score": 85,
            "examiner_decision": "PASS"
        }).insert(ignore_permissions=True)

        # Move Examiner Result through workflow
        self.examiner_result = apply_workflow(self.examiner_result, "Submit")
        self.examiner_result = apply_workflow(self.examiner_result, "Verify")
        self.examiner_result = apply_workflow(self.examiner_result, "Approve")

    def tearDown(self):
        """Clean up test data"""
        for dt_name in ["LMS Certificate", "Examiner Result", "Examination Session",
                        "Session Lifecycle", "Instructor", "Classroom", "LMS Course",
                        "LMS Enrollment", "User"]:
            docs = frappe.get_all(dt_name, filters={"name": ["like", "TEST-%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
            # Also clean up by flow test patterns
            docs = frappe.get_all(dt_name, filters={"name": ["like", "%FLOW%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()

    def test_examination_session_to_certificate_creation(self):
        """Test that Examination Session Reviewed status triggers certificate creation"""
        # Session is already CLOSED from setUp

        # Generate certificates from exam session
        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        # Verify certificate was created
        certificates = frappe.get_all("LMS Certificate",
            filters={"member": self.student.name, "course": self.course.name},
            fields=["name", "status", "examiner_result"])
        self.assertEqual(len(certificates), 1)

        cert = frappe.get_doc("LMS Certificate", certificates[0].name)
        self.assertEqual(cert.status, "Pending QM Approval")
        self.assertEqual(cert.examiner_result, self.examiner_result.name)

    def test_certificate_links_to_examiner_result(self):
        """Test that certificate references the Examiner Result"""
        # Session is already CLOSED from setUp

        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        certificates = frappe.get_all("LMS Certificate",
            filters={"member": self.student.name, "course": self.course.name},
            fields=["name", "examiner_result"])

        cert = frappe.get_doc("LMS Certificate", certificates[0].name)
        self.assertEqual(cert.examiner_result, self.examiner_result.name)
        self.assertEqual(cert.member, self.student.name)
        self.assertEqual(cert.course, self.course.name)

    def test_enrollment_updated_on_certificate_creation(self):
        """Test that LMS Enrollment is updated when certificate is created"""
        # Session is already CLOSED from setUp

        # Check enrollment before certificate creation
        enrollment_before = frappe.get_doc("LMS Enrollment", self.enrollment.name)
        self.assertFalse(enrollment_before.certificate_issued)
        self.assertIsNone(enrollment_before.certificate_expiry)

        # Generate certificates
        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        # Check enrollment after certificate creation
        enrollment_after = frappe.get_doc("LMS Enrollment", self.enrollment.name)
        self.assertTrue(enrollment_after.certificate_issued)
        self.assertIsNotNone(enrollment_after.certificate_expiry)
        self.assertEqual(enrollment_after.certificate_expiry,
                        add_months(getdate(), self.course.validity_period_months))

    def test_course_validity_period_applied_to_certificate(self):
        """Test that course validity_period_months is applied to certificate expiry"""
        # Session is already CLOSED from setUp

        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        certificates = frappe.get_all("LMS Certificate",
            filters={"member": self.student.name, "course": self.course.name},
            fields=["name", "issue_date", "expiry_date"])

        cert = frappe.get_doc("LMS Certificate", certificates[0].name)
        expected_expiry = add_months(cert.issue_date, self.course.validity_period_months)
        self.assertEqual(cert.expiry_date, expected_expiry)

    def test_multiple_students_in_exam_session(self):
        """Test certificate creation for multiple students in same exam session"""
        # Create second student
        test_id = str(frappe.generate_hash())[:8]
        student2 = frappe.get_doc({
            "doctype": "User",
            "email": f"student2-flow-{test_id}@test.com",
            "first_name": "Test2",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create enrollment for second student
        enrollment2 = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": student2.name,
            "member_name": "Test2 Student",
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Create Examiner Result for second student with PASS
        examiner_result2 = frappe.get_doc({
            "doctype": "Examiner Result",
            "examination_session": self.exam_session.name,
            "learner": student2.name,
            "score": 90,
            "examiner_decision": "PASS"
        }).insert(ignore_permissions=True)

        # Move through workflow
        examiner_result2 = apply_workflow(examiner_result2, "Submit")
        examiner_result2 = apply_workflow(examiner_result2, "Verify")
        examiner_result2 = apply_workflow(examiner_result2, "Approve")

        # Session is already CLOSED from setUp

        # Generate certificates
        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 2)

        # Verify both certificates created
        certificates = frappe.get_all("LMS Certificate",
            filters={"course": self.course.name},
            fields=["name", "member"])
        self.assertEqual(len(certificates), 2)

        member_emails = [c.member for c in certificates]
        self.assertIn(self.student.name, member_emails)
        self.assertIn(student2.name, member_emails)

    def test_fail_result_does_not_create_certificate(self):
        """Test that FAIL examiner decision does not create certificate"""
        # Create student with FAIL result
        test_id = str(frappe.generate_hash())[:8]
        student_fail = frappe.get_doc({
            "doctype": "User",
            "email": f"student-fail-{test_id}@test.com",
            "first_name": "TestFail",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        enrollment_fail = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": student_fail.name,
            "member_name": "TestFail Student",
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        examiner_result_fail = frappe.get_doc({
            "doctype": "Examiner Result",
            "examination_session": self.exam_session.name,
            "learner": student_fail.name,
            "score": 60,
            "examiner_decision": "FAIL"
        }).insert(ignore_permissions=True)

        examiner_result_fail = apply_workflow(examiner_result_fail, "Submit")
        examiner_result_fail = apply_workflow(examiner_result_fail, "Verify")
        examiner_result_fail = apply_workflow(examiner_result_fail, "Approve")

        # Session is already CLOSED from setUp

        # Generate certificates - should only create 1 (for the PASS student)
        result = create_certificates_from_exam_session(self.exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        # Verify no certificate for FAIL student
        fail_certs = frappe.get_all("LMS Certificate",
            filters={"member": student_fail.name, "course": self.course.name})
        self.assertEqual(len(fail_certs), 0)


if __name__ == "__main__":
    unittest.main()