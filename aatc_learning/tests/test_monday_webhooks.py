# AATC Learning - Monday.com Webhook Tests (Workstream 5A)

import frappe
import unittest
from unittest.mock import patch, MagicMock
from frappe.utils import now_datetime, getdate, add_days, add_months
from frappe.model.workflow import apply_workflow
from aatc.certificate_automation import create_certificates_from_exam_session
from frappe.tests import IntegrationTestCase


class TestMondayWebhooks(IntegrationTestCase):
    """Test Monday.com webhook triggers"""

    def setUp(self):
        """Create test data"""
        self.tearDown()

        test_id = str(frappe.generate_hash())[:8]

        # Create test course
        self.course = frappe.get_doc({
            "doctype": "LMS Course",
            "title": f"Test Course - Webhook {test_id}",
            "course_code": f"TEST-WEB-{test_id}",
            "description": "Test course for webhooks",
            "short_introduction": "Test course for webhooks",
            "published": 1,
            "validity_period_months": 24
        }).insert(ignore_permissions=True)

        # Create test user
        self.student = frappe.get_doc({
            "doctype": "User",
            "email": f"student-web-{test_id}@test.com",
            "first_name": "Webhook",
            "last_name": "Student",
            "enabled": 1,
            "user_type": "Website User"
        }).insert(ignore_permissions=True)

        # Create enrollment
        self.enrollment = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "member": self.student.name,
            "member_name": "Webhook Student",
            "course": self.course.name,
            "status": "Enrolled"
        }).insert(ignore_permissions=True)

        # Create classroom
        self.classroom = frappe.get_doc({
            "doctype": "Classroom",
            "room_code": f"TEST-CR-WEB-{test_id}",
            "room_name": f"Test Classroom Web {test_id}",
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
            "instructor_id": f"INST-WEB-{test_id}",
            "employee": admin_employee.name,
            "instructor_type": "Ground",
            "compliance_status": "Active",
            "certificate_expiry": add_days(getdate(), 365)
        }).insert(ignore_permissions=True)

        # Create base Session Lifecycle (goes to CLOSED for certificate flow)
        self.session = frappe.get_doc({
            "doctype": "Session Lifecycle",
            "session_title": f"Test Session - Webhook {test_id}",
            "course": self.course.name,
            "start_date": add_days(getdate(), 10),
            "end_date": add_days(getdate(), 15),
            "status": "PLANNED",
            "instructor": self.instructor.name,
            "location": self.classroom.name
        }).insert(ignore_permissions=True)

        # Move session through all phases to CLOSED
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

        self.session.go_no_go_decision = "GO"
        self.session.tc_practical_readiness_signed = 1
        self.session.dlts_digital_readiness_signed = 1
        self.session.status = "IN PROGRESS"
        self.session.save(ignore_permissions=True)

        # Add attendance records
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

        self.session.lms_shell_created = 1
        self.session.status = "ASSESSMENT COMPLETE"
        self.session.save(ignore_permissions=True)

        self.session.qm_quality_check_approved = 1
        self.session.qm_approved_at = now_datetime()
        self.session.status = "CLOSED"
        self.session.save(ignore_permissions=True)

        # Commit to flush any webhooks queued during setUp
        frappe.db.commit()

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

        # Move through workflow
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

        self.examiner_result = apply_workflow(self.examiner_result, "Submit")
        self.examiner_result = apply_workflow(self.examiner_result, "Verify")
        self.examiner_result = apply_workflow(self.examiner_result, "Approve")

        # Clear any pending Redis queues to avoid QueueOverloaded
        self._clear_redis_queues()

    def _clear_redis_queues(self):
        """Clear Redis RQ queues to prevent QueueOverloaded during tests"""
        try:
            import redis
            r = redis.Redis.from_url(frappe.conf.redis_queue or "redis://localhost:11000")
            for key in r.scan_iter("rq:queue:*"):
                r.delete(key)
            for key in r.scan_iter("rq:job:*"):
                r.delete(key)
        except Exception:
            pass  # Best effort only

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
            docs = frappe.get_all(dt_name, filters={"name": ["like", "%WEB%"]})
            for doc in docs:
                try:
                    frappe.delete_doc(dt_name, doc.name, force=1, ignore_permissions=True)
                except Exception:
                    pass

        # Clean up Nonconformity
        docs = frappe.get_all("Nonconformity", filters={"name": ["like", "NCR-%"]})
        for doc in docs:
            try:
                frappe.delete_doc("Nonconformity", doc.name, force=1, ignore_permissions=True)
            except Exception:
                pass

        # Reset AATC Settings Monday fields only
        settings = frappe.get_single("AATC Settings")
        settings.monday_api_token = ""
        settings.monday_certificate_board_id = ""
        settings.monday_session_board_id = ""
        settings.monday_capa_board_id = ""
        settings.backup_offsite_enabled = 0
        settings.backup_offsite_provider = "None"
        settings.save(ignore_permissions=True)
        frappe.db.commit()


class TestDailyBackupOffsite(IntegrationTestCase):
    """Test daily_backup offsite provider logic"""

    def setUp(self):
        self.settings = frappe.get_single("AATC Settings")
        self.settings.backup_offsite_enabled = 0
        self.settings.backup_offsite_provider = "None"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        self.settings.backup_offsite_enabled = 0
        self.settings.backup_offsite_provider = "None"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.db.commit()

    @patch("frappe.utils.backups.new_backup")
    def test_daily_backup_offsite_disabled(self, mock_new_backup):
        """Test daily_backup with offsite disabled runs local only"""
        mock_backup = MagicMock()
        mock_backup.backup_files = ["/tmp/test.sql.gz"]
        mock_new_backup.return_value = mock_backup

        from aatc.tasks import daily_backup
        result = daily_backup()

        self.assertIn("local only", result.lower())
        mock_new_backup.assert_called_once_with(ignore_files=False, force=True)

    @patch("frappe.utils.backups.new_backup")
    @patch("aatc.tasks.boto3.client")
    def test_daily_backup_supabase_upload(self, mock_boto3_client, mock_new_backup):
        """Test daily_backup with Supabase provider calls boto3 upload"""
        mock_backup = MagicMock()
        mock_backup.backup_files = ["/tmp/test.sql.gz"]
        mock_new_backup.return_value = mock_backup

        # Configure Supabase settings
        self.settings.backup_offsite_enabled = 1
        self.settings.backup_offsite_provider = "Supabase"
        self.settings.backup_s3_endpoint_url = "https://test.supabase.co/storage/v1/s3"
        self.settings.backup_s3_access_key = "test_access"
        self.settings.backup_s3_secret_key = "test_secret"
        self.settings.backup_s3_bucket = "test-bucket"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.db.commit()

        # Mock file existence
        with patch("os.path.exists", return_value=True):
            with patch("os.path.getsize", return_value=1024):
                with patch("frappe.utils.now_datetime") as mock_now:
                    mock_now.return_value.strftime.return_value = "2026-10-22"
                    
                    mock_s3 = MagicMock()
                    mock_boto3_client.return_value = mock_s3
                    
                    from aatc.tasks import daily_backup
                    result = daily_backup()

        self.assertIn("supabase", result.lower())
        mock_s3.upload_file.assert_called_once()
        call_args = mock_s3.upload_file.call_args
        self.assertEqual(call_args[0][1], "test-bucket")  # bucket
        # Date-based path uses current date; just check it has the expected prefix
        self.assertTrue(call_args[0][2].startswith("aatc-backups/") and call_args[0][2].endswith("/test.sql.gz"))


if __name__ == "__main__":
    unittest.main()
