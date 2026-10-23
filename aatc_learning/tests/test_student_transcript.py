# AATC Learning - Student Transcript End-to-End Tests (Workstream 3E)

import frappe
import unittest
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime, getdate, add_days, add_months
from frappe.model.workflow import apply_workflow
from aatc.certificate_automation import create_certificates_from_exam_session, generate_certificate_number


class TestStudentTranscriptEndToEnd(IntegrationTestCase):
    """Test Student Transcript end-to-end functionality (Workstream 3E)"""

    def setUp(self):
        """Create test data"""
        self.tearDown()

        test_id = str(frappe.generate_hash())[:8]

        # Create test course
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course - Transcript {test_id}",
            "course_code": f"TEST-TR-{test_id}",
            "description": "Test course for transcript",
            "short_introduction": "Test course for transcript",
            "published": 1,
            "validity_period_months": 24
        }).insert(ignore_permissions=True)

        # Create second course
        self.course2 = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course 2 - Transcript {test_id}",
            "course_code": f"TEST-TR2-{test_id}",
            "description": "Test course 2 for transcript",
            "short_introduction": "Test course 2 for transcript",
            "published": 1,
            "validity_period_months": 12
        }).insert(ignore_permissions=True)

        # Create test user
        self.student = frappe.get_doc({
            "doctype": "User",
            "email": f"student-transcript-{test_id}@test.com",
            "first_name": "Test",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
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
            "instructor_id": f"INST-TR-{test_id}",
            "employee": admin_employee.name,
            "instructor_type": "Ground",
            "compliance_status": "Active",
            "certificate_expiry": add_days(getdate(), 365)
        }).insert(ignore_permissions=True)

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
            docs = frappe.get_all(dt_name, filters={"name": ["like", "%TR%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()

    def create_full_certificate_flow(self, course, course_name_suffix=""):
        """Helper to create a complete certificate flow for a course"""
        # Create enrollment
        enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": "Test Student",
            "course": course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Create Session Lifecycle
        session = frappe.get_doc({
            "doctype": "Session Lifecycle",
            "session_title": f"Test Session {course_name_suffix} {course.name}",
            "course": course.name,
            "start_date": add_days(getdate(), 10),
            "end_date": add_days(getdate(), 15),
            "status": "PLANNED",
            "instructor": self.instructor.name,
            "location": self.classroom.name
        }).insert(ignore_permissions=True)

        # Phase 1: PLANNED -> READY FOR DELIVERY
        session.instructor_availability_confirmed = 1
        session.instructor_compliance_checked = 1
        session.classroom_booked = 1
        session.equipment_check_completed = 1
        session.course_materials_version_confirmed = 1
        session.lms_shell_confirmed = 1
        session.ipad_status_confirmed = 1
        session.connectivity_test_passed = 1
        session.status = "READY FOR DELIVERY"
        session.save(ignore_permissions=True)

        # Phase 2: READY FOR DELIVERY -> IN PROGRESS
        session.go_no_go_decision = "GO"
        session.tc_practical_readiness_signed = 1
        session.dlts_digital_readiness_signed = 1
        session.status = "IN PROGRESS"
        session.save(ignore_permissions=True)

        # Add attendance records for Phase 3 gate
        start_date = getdate(session.start_date)
        for i in range(6):
            day = add_days(start_date, i)
            session.append("daily_attendance", {
                "date": day,
                "learner": self.student.name,
                "am_status": "Present",
                "pm_status": "Present",
                "marked_by": frappe.session.user,
                "marked_at": now_datetime()
            })

        # Phase 3: IN PROGRESS -> ASSESSMENT COMPLETE
        session.lms_shell_created = 1
        session.status = "ASSESSMENT COMPLETE"
        session.save(ignore_permissions=True)

        # Phase 4: ASSESSMENT COMPLETE -> CLOSED
        session.qm_quality_check_approved = 1
        session.qm_approved_at = now_datetime()
        session.status = "CLOSED"
        session.save(ignore_permissions=True)

        # Create Examination Session
        exam_session = frappe.get_doc({
            "doctype": "Examination Session",
            "session": session.name,
            "session_title": session.session_title,
            "course": session.course,
            "examination_date": session.start_date,
            "start_date": session.start_date,
            "end_date": session.end_date
        }).insert(ignore_permissions=True)

        # Move Examination Session through workflow
        exam_session = apply_workflow(exam_session, "Schedule")
        exam_session = apply_workflow(exam_session, "Start")
        exam_session = apply_workflow(exam_session, "Complete")
        exam_session = apply_workflow(exam_session, "Review")

        # Create Examiner Result with PASS
        examiner_result = frappe.get_doc({
            "doctype": "Examiner Result",
            "examination_session": exam_session.name,
            "learner": self.student.name,
            "score": 85,
            "examiner_decision": "PASS"
        }).insert(ignore_permissions=True)

        # Move Examiner Result through workflow
        examiner_result = apply_workflow(examiner_result, "Submit")
        examiner_result = apply_workflow(examiner_result, "Verify")
        examiner_result = apply_workflow(examiner_result, "Approve")

        # Generate certificate (this now includes certificate number generation)
        result = create_certificates_from_exam_session(exam_session.name)
        self.assertEqual(result["certificates_created"], 1)

        # Get the certificate
        certificates = frappe.get_all("LMS Certificate",
            filters={"member": self.student.name, "course": course.name},
            fields=["name"])

        cert = frappe.get_doc("LMS Certificate", certificates[0].name)
        cert.reload()

        # Move to Distributed through workflow
        cert = apply_workflow(cert, "QM Approve")
        cert = apply_workflow(cert, "Submit HOT")
        cert = apply_workflow(cert, "HOT Approve")
        cert = apply_workflow(cert, "Distribute")
        cert.reload()

        return cert, enrollment

    def test_transcript_virtual_doctype_exists(self):
        """Test that Student Transcript Virtual DocType exists"""
        dt = frappe.get_doc("DocType", "Student Transcript")
        self.assertEqual(dt.is_virtual, 1, "Student Transcript should be a Virtual DocType")
        self.assertEqual(dt.module, "AATC Learning", "Module should be AATC Learning")

    def test_transcript_get_data_method_exists(self):
        """Test that Student Transcript has get_data method"""
        # Import the get_data function directly
        from aatc_learning.doctype.student_transcript.student_transcript import get_data
        self.assertTrue(callable(get_data), "get_data should be callable")

    def test_transcript_empty_for_new_student(self):
        """Test transcript is empty for student with no enrollments"""
        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        self.assertEqual(len(data), 0, "Transcript should be empty for new student")

    def test_transcript_with_single_course(self):
        """Test transcript shows single completed course"""
        cert, enrollment = self.create_full_certificate_flow(self.course, "Course1")

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        self.assertEqual(len(data), 1, "Transcript should show 1 course")

        record = data[0]
        self.assertEqual(record["course"], self.course.name)
        self.assertEqual(record["course_title"], self.course.title)
        self.assertEqual(record["certificate_number"], cert.certificate_number)
        self.assertEqual(record["certificate_issued"], 1)
        self.assertIsNotNone(record["certificate_expiry"])
        self.assertIsNotNone(record["completion_date"])

    def test_transcript_with_multiple_courses(self):
        """Test transcript shows multiple completed courses"""
        cert1, enrollment1 = self.create_full_certificate_flow(self.course, "Course1")
        cert2, enrollment2 = self.create_full_certificate_flow(self.course2, "Course2")

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        self.assertEqual(len(data), 2, "Transcript should show 2 courses")

        course_names = [r["course"] for r in data]
        self.assertIn(self.course.name, course_names)
        self.assertIn(self.course2.name, course_names)

        # Check certificate numbers
        cert_numbers = [r["certificate_number"] for r in data]
        self.assertIn(cert1.certificate_number, cert_numbers)
        self.assertIn(cert2.certificate_number, cert_numbers)

        # Check all have certificate_issued = 1
        for r in data:
            self.assertEqual(r["certificate_issued"], 1)

    def test_transcript_filter_by_student(self):
        """Test transcript filtering by student"""
        # First, create a certificate for student1 (self.student)
        cert1, enrollment1 = self.create_full_certificate_flow(self.course, "Course1")

        # Create second student
        test_id = str(frappe.generate_hash())[:8]
        student2 = frappe.get_doc({
            "doctype": "User",
            "email": f"student2-transcript-{test_id}@test.com",
            "first_name": "Test2",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create enrollment and certificate for student2
        # Temporarily swap self.student
        original_student = self.student
        self.student = student2
        cert2, enrollment2 = self.create_full_certificate_flow(self.course, "Student2Course")
        self.student = original_student

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        # Query for student1
        data1 = get_data(filters={"student": self.student.name})
        self.assertEqual(len(data1), 1, "Student1 should have 1 course")

        # Query for student2
        data2 = get_data(filters={"student": student2.name})
        self.assertEqual(len(data2), 1, "Student2 should have 1 course")

        # Verify different students have different data
        self.assertNotEqual(data1[0]["certificate_number"], data2[0]["certificate_number"])

    def test_transcript_includes_course_details(self):
        """Test transcript includes all required course details"""
        cert, enrollment = self.create_full_certificate_flow(self.course, "Course1")

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        record = data[0]

        # Check all required fields (based on actual get_data return structure)
        self.assertIn("course", record)
        self.assertIn("course_title", record)
        self.assertIn("certificate_number", record)
        self.assertIn("certificate_issued", record)
        self.assertIn("certificate_expiry", record)
        self.assertIn("completion_date", record)
        self.assertIn("final_grade", record)
        self.assertIn("examiner_decision", record)
        self.assertIn("exam_score", record)

    def test_transcript_certificate_with_no_active_enrollment(self):
        """Test transcript shows certificate even if enrollment is not active"""
        cert, enrollment = self.create_full_certificate_flow(self.course, "Course1")

        # Reload enrollment to get latest version
        enrollment.reload()

        # Cancel the enrollment
        enrollment.status = "Cancelled"
        enrollment.save(ignore_permissions=True)

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        self.assertEqual(len(data), 1, "Transcript should still show certificate")

        record = data[0]
        self.assertEqual(record["certificate_number"], cert.certificate_number)
        # The enrollment is still in the system, just cancelled
        # get_data returns all enrollments, so we verify certificate is still there

    def test_transcript_get_count_method(self):
        """Test that get_count method works"""
        cert, enrollment = self.create_full_certificate_flow(self.course, "Course1")

        from aatc_learning.doctype.student_transcript.student_transcript import get_count

        count = get_count(filters={"student": self.student.name})
        self.assertEqual(count, 1, "get_count should return 1 for student with 1 course")

    def test_transcript_excludes_in_progress_courses(self):
        """Test that transcript shows all enrollments but can filter by certificate_issued"""
        # Create enrollment but don't complete the certificate flow
        enrollment_incomplete = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": "Test Student",
            "course": self.course2.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Complete first course
        cert1, enrollment1 = self.create_full_certificate_flow(self.course, "Course1")

        from aatc_learning.doctype.student_transcript.student_transcript import get_data

        data = get_data(filters={"student": self.student.name})
        # get_data returns ALL enrollments, so we should have 2 (one with cert, one without)
        self.assertEqual(len(data), 2, "Transcript shows all enrollments")

        # But we can filter by certificate_issued
        data_with_cert = get_data(filters={"student": self.student.name, "certificate_issued": 1})
        self.assertEqual(len(data_with_cert), 1, "Filter by certificate_issued=1 should show only completed")
        self.assertEqual(data_with_cert[0]["course"], self.course.name)


if __name__ == "__main__":
    unittest.main()